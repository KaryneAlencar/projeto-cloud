"""Teste HTTP ponta a ponta no projeto Docker descartável de verificação."""
import argparse
import concurrent.futures
import http.cookiejar
import json
import subprocess
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-p', 'insper-eats-verification', '-f', 'compose.verify.yaml']


def container_python(source):
    result = subprocess.run(COMPOSE + ['exec', '-T', 'api', 'python', '-c', source], cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Não foi possível acessar a API isolada de verificação.')
    return json.loads(result.stdout)


class Browser:
    def __init__(self, base):
        self.base = base.rstrip('/')
        self.opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.csrf = ''

    def call(self, method, path, body=None, csrf=True):
        headers = {'Origin': self.base, 'Content-Type': 'application/json'}
        if csrf and self.csrf:
            headers['X-CSRF-Token'] = self.csrf
        request = Request(self.base + path, method=method, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            response = self.opener.open(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                data = json.loads(raw)
            except ValueError:
                data = raw.decode()
            return response.status, data, response.headers

    def start(self):
        status, value, _ = self.call('POST', '/api/chat/sessao')
        assert status == 200, value
        self.csrf = value['csrf_token']

    def message(self, cid, content):
        status, value, _ = self.call('POST', f'/api/chat/conversas/{cid}/mensagens', {'conteudo': content, 'mensagem_id': str(uuid4())})
        assert status == 200, value
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:18080')
    parser.add_argument('--output', default='work/verification.json')
    args = parser.parse_args()
    if args.base.rstrip('/') not in {'http://127.0.0.1:18080', 'http://localhost:18080'}:
        raise SystemExit('A verificação só aceita o ambiente isolado na porta 18080.')
    checks = []
    browser, stranger = Browser(args.base), Browser(args.base)
    assert browser.call('GET', '/healthz')[0] == 200
    status, page, headers = browser.call('GET', '/')
    assert status == 200 and 'Insper Eats' in page
    assert 'Content-Security-Policy' in headers
    assert browser.call('GET', '/api/chat/pedidos')[0] == 401
    browser.start()
    stranger.start()
    assert browser.call('POST', '/api/chat/conversas', {}, csrf=False)[0] == 403
    checks.append('Frontend de produção, proxy, cookie e CSRF')

    product = container_python("import json,urllib.request; payload=json.dumps({'nome':'Brownie Verificacao','preco':'8.00','estoque':20}).encode(); req=urllib.request.Request('http://127.0.0.1:8000/produtos',data=payload,headers={'Content-Type':'application/json'}); print(urllib.request.urlopen(req).read().decode())")
    status, conversation, _ = browser.call('POST', '/api/chat/conversas', {})
    assert status == 201
    cid = conversation['id']
    assert stranger.call('GET', f'/api/chat/conversas/{cid}')[0] == 404
    result = browser.message(cid, 'Ver o cardápio')
    assert 'Brownie Verificacao' in result['mensagens'][-1]['conteudo']
    browser.message(cid, f"Selecionar {product['id']}:2")
    browser.message(cid, 'Meu nome é Ana')
    selection = browser.message(cid, 'Entrega: sala 512, prédio 2')['compra']
    assert selection['total'] == 16
    checks.append('Catálogo e preparação com API e PostgreSQL reais')

    payload = {'compra_id': selection['id']}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: browser.call('POST', f'/api/chat/conversas/{cid}/confirmar', payload), range(2)))
    assert all(result[0] == 200 for result in results)
    order_id = int(results[0][1]['compra']['pedido_id'])
    assert str(order_id) == results[1][1]['compra']['pedido_id']
    stock = container_python(f"import json,urllib.request; rows=json.load(urllib.request.urlopen('http://127.0.0.1:8000/produtos')); print(json.dumps(next(p['estoque'] for p in rows if p['id']=={int(product['id'])})))")
    assert stock == 18
    assert stranger.call('GET', f'/api/chat/pedidos/{order_id}')[0] == 404
    assert stranger.call('GET', '/api/chat/pedidos')[1]['pedidos'] == []
    checks.append('Compra concorrente sem duplicidade e estoque debitado uma vez')
    checks.append('Pedidos e conversas isolados entre navegadores')

    # Simula somente a atualização que o worker faria, dentro do banco descartável.
    update = subprocess.run(COMPOSE + ['exec', '-T', 'db', 'psql', '-U', 'verify', '-d', 'verify', '-c', f"UPDATE pedido SET status='confirmado' WHERE id={order_id}"], cwd=ROOT, capture_output=True)
    assert update.returncode == 0
    assert browser.call('GET', '/api/chat/pedidos')[1]['pedidos'][0]['status'] == 'confirmado'
    checks.append('Consulta do status atual após atualização simulada do worker')

    subprocess.run(COMPOSE + ['restart', 'chat'], cwd=ROOT, check=True, capture_output=True)
    ready = False
    for _ in range(40):
        try:
            status, restored, _ = browser.call('GET', f'/api/chat/conversas/{cid}')
            if status == 200:
                ready = True
                break
        except (OSError, URLError):
            pass
        time.sleep(1)
    assert ready, 'Chat não recuperou a conversa após reiniciar'
    assert restored['compra']['pedido_id'] == str(order_id)
    assert browser.call('GET', '/api/chat/pedidos')[1]['pedidos'][0]['status'] == 'confirmado'
    checks.append('Sessão, histórico e pedidos recuperados após reiniciar containers')
    report = {'result': 'passed', 'checks': checks, 'ai': 'commands (sem chamadas externas)', 'worker': 'atualização simulada; sem SQS', 'order_id_in_disposable_database': order_id}
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
