"""Consulta real opcional ao Gemini pelo chat, sem confirmar compras."""
import argparse
import http.cookiejar
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8001')
    args = parser.parse_args()
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
    csrf = ''

    def post(path, body=None):
        request = Request(args.base.rstrip('/') + path, method='POST',
                          data=json.dumps(body or {}).encode(),
                          headers={'Content-Type': 'application/json', 'X-CSRF-Token': csrf})
        try:
            with opener.open(request, timeout=150) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.load(exc)

    try:
        status, value = post('/chat/sessao')
        if status != 200:
            raise RuntimeError('Não foi possível iniciar a sessão de verificação.')
        csrf = value['csrf_token']
        status, conversation = post('/chat/conversas')
        if status != 201:
            raise RuntimeError('Não foi possível iniciar a conversa de verificação.')
        status, value = post(f"/chat/conversas/{conversation['id']}/mensagens", {
            'conteudo': 'Consulte o catálogo e mostre somente duas opções com seus preços. Não prepare nem confirme compras.',
            'mensagem_id': str(uuid4()),
        })
        if status != 200:
            print(json.dumps({'result': 'provider_or_dependency_failure', 'http_status': status, 'code': value.get('code'), 'detail': value.get('detail')}, ensure_ascii=False))
            return 1
        print(json.dumps({'result': 'passed', 'conversation_id': conversation['id'], 'response': value['mensagens'][-1]['conteudo'], 'purchase_prepared': value['compra'] is not None}, ensure_ascii=False))
        return 0
    except (OSError, URLError, RuntimeError):
        print('O Chat Service não respondeu à verificação. Confira os serviços locais.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
