#!/usr/bin/env python3
"""Verifica um ambiente Insper Eats já implantado.

Lê os endereços de `terraform output`, consulta a AWS pela CLI (somente
leitura) e exercita a aplicação por HTTP: frontend, API de pedidos e o fluxo
de compra pelo chat, até o worker confirmar o pedido pela fila SQS.

Uso típico, a partir de terraform/:

    python3 scripts/verify_deploy.py            # tudo
    python3 scripts/verify_deploy.py --dlq      # inclui o teste da DLQ (~6 min)

Só usa a biblioteca padrão do Python. Cria produtos e pedidos de teste, com
nomes iniciados por "Teste Terraform".
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen
from uuid import uuid4

TERRAFORM_DIR = Path(__file__).resolve().parents[1]
DLQ_POLL_SECONDS = 15
SENSITIVE_NAME = re.compile(r"(password|senha|token|api_key|database_url)", re.IGNORECASE)


class Skip(Exception):
    """A verificação não se aplica ou não pode rodar neste ambiente."""


class Report:
    def __init__(self):
        self.results = []

    def check(self, name, function):
        try:
            detail = function()
            status = "ok"
        except Skip as skip:
            status, detail = "pulado", str(skip)
        except AssertionError as failure:
            status, detail = "FALHOU", str(failure) or "condição não atendida"
        except Exception as error:  # rede, CLI, JSON inesperado
            status, detail = "FALHOU", f"{type(error).__name__}: {error}"
        self.results.append({"verificacao": name, "resultado": status, "detalhe": detail or ""})
        print(f"[{status:^6}] {name}" + (f" - {detail}" if detail else ""), flush=True)
        return status == "ok"

    @property
    def failed(self):
        return [r for r in self.results if r["resultado"] == "FALHOU"]


# --- utilidades -------------------------------------------------------------


def run_json(command, cwd=None):
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "comando falhou")
    return json.loads(result.stdout) if result.stdout.strip() else None


def request(method, url, body=None, headers=None, timeout=20, opener=None):
    """Devolve (status, corpo decodificado, cabeçalhos). Não levanta em 4xx/5xx."""
    request = Request(url, method=method, headers={"Content-Type": "application/json", **(headers or {})},
                      data=json.dumps(body).encode() if body is not None else None)
    try:
        response = (opener.open if opener else urlopen)(request, timeout=timeout)
    except HTTPError as error:
        response = error
    with response:
        raw = response.read()
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw.decode(errors="replace")
        return response.status, data, response.headers


def wait_for(description, function, timeout, interval=5):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = function()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"{description}: não aconteceu em {timeout}s")


def skipped(reason):
    def run():
        raise Skip(reason)
    return run


class Aws:
    def __init__(self, region, profile):
        self.base = ["aws", "--region", region, "--output", "json"]
        if profile:
            self.base += ["--profile", profile]

    def __call__(self, *args):
        return run_json(self.base + list(args))


class Browser:
    """Sessão de navegador contra o frontend: cookie de sessão e token CSRF."""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.csrf = ""

    def call(self, method, path, body=None, csrf=True, timeout=30):
        headers = {"Origin": self.base}
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        return request(method, self.base + path, body, headers, timeout, self.opener)[:2]

    def start(self):
        status, value = self.call("POST", "/api/chat/sessao")
        assert status == 200, f"POST /api/chat/sessao retornou {status}"
        self.csrf = value["csrf_token"]

    def message(self, conversation, content):
        status, value = self.call("POST", f"/api/chat/conversas/{conversation}/mensagens",
                                  {"conteudo": content, "mensagem_id": str(uuid4())})
        assert status == 200, f"mensagem '{content}' retornou {status}: {value}"
        return value


# --- verificações de infraestrutura (AWS CLI, somente leitura) --------------


def infrastructure_checks(report, aws, out):
    cluster = out["ecs_cluster_name"]
    services = out["ecs_service_names"]

    def services_stable():
        described = aws("ecs", "describe-services", "--cluster", cluster, "--services", *services.values())["services"]
        assert len(described) == len(services), "nem todos os serviços foram encontrados"
        lines = []
        for service in described:
            name, desired, running = service["serviceName"], service["desiredCount"], service["runningCount"]
            assert desired >= 2 and running == desired, f"{name}: {running}/{desired} tasks"
            assert len(service["deployments"]) == 1, f"{name}: deployment em andamento"
            public_ip = service["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"]
            assert public_ip == "DISABLED", f"{name}: tasks com IP público"
            lines.append(f"{name.rsplit('-', 2)[-2]} {running}/{desired}")
        return ", ".join(lines)

    def tasks_in_two_zones():
        zones = {}
        for key in ("api", "worker"):
            arns = aws("ecs", "list-tasks", "--cluster", cluster, "--service-name", services[key])["taskArns"]
            tasks = aws("ecs", "describe-tasks", "--cluster", cluster, "--tasks", *arns)["tasks"]
            zones[key] = sorted({task["availabilityZone"] for task in tasks})
            instances = [task.get("containerInstanceArn") for task in tasks]
            assert len(zones[key]) >= 2, f"{key}: tasks em uma única AZ ({zones[key]})"
            assert len(set(instances)) == len(instances), f"{key}: duas réplicas na mesma instância"
        return f"api {zones['api']}, worker {zones['worker']}"

    def targets_healthy():
        lines = []
        for key, arn in out["target_group_arns"].items():
            states = [t["TargetHealth"]["State"] for t in
                      aws("elbv2", "describe-target-health", "--target-group-arn", arn)["TargetHealthDescriptions"]]
            healthy = states.count("healthy")
            assert healthy >= 2 and healthy == len(states), f"{key}: {states}"
            lines.append(f"{key} {healthy} healthy")
        return ", ".join(lines)

    def capacity_provider():
        provider = aws("ecs", "describe-capacity-providers", "--capacity-providers",
                       out["capacity_provider_name"])["capacityProviders"][0]
        asg = provider["autoScalingGroupProvider"]
        assert provider["status"] == "ACTIVE", provider["status"]
        assert asg["managedScaling"]["status"] == "ENABLED" and asg["managedScaling"]["targetCapacity"] == 100
        assert asg["managedTerminationProtection"] == "ENABLED" and asg.get("managedDraining") == "ENABLED"
        group = aws("autoscaling", "describe-auto-scaling-groups", "--auto-scaling-group-names",
                    out["autoscaling_group_name"])["AutoScalingGroups"][0]
        in_service = [i for i in group["Instances"] if i["LifecycleState"] == "InService"]
        assert len(in_service) >= 2, f"{len(in_service)} instâncias InService"
        return f"{len(in_service)} EC2 InService (min {group['MinSize']}, max {group['MaxSize']})"

    def database_private():
        db = aws("rds", "describe-db-instances", "--db-instance-identifier", out["rds_identifier"])["DBInstances"][0]
        assert db["DBInstanceStatus"] == "available", db["DBInstanceStatus"]
        assert db["PubliclyAccessible"] is False, "RDS público"
        assert db["StorageEncrypted"] is True, "RDS sem criptografia"
        return f"PostgreSQL {db['EngineVersion']}, Multi-AZ={db['MultiAZ']}, privado, criptografado"

    def no_plaintext_secrets():
        for key, service in services.items():
            definition = aws("ecs", "describe-services", "--cluster", cluster, "--services", service)["services"][0]["taskDefinition"]
            containers = aws("ecs", "describe-task-definition", "--task-definition", definition)["taskDefinition"]["containerDefinitions"]
            for container in containers:
                exposed = [v["name"] for v in container.get("environment", []) if SENSITIVE_NAME.search(v["name"])]
                assert not exposed, f"{key}: variáveis sensíveis em texto claro: {exposed}"
        return "segredos só por Secrets Manager"

    def alarms():
        described = aws("cloudwatch", "describe-alarms", "--alarm-names", *out["alarm_names"])["MetricAlarms"]
        states = {alarm["AlarmName"].replace(out["name_prefix"] + "-", ""): alarm["StateValue"] for alarm in described}
        assert len(states) == len(out["alarm_names"]), "alarme ausente"
        in_alarm = [name for name, state in states.items() if state == "ALARM"]
        assert not in_alarm, f"em ALARM: {in_alarm}"
        pending = [name for name, state in states.items() if state != "OK"]
        return f"{len(states)} alarmes OK" if not pending else f"sem dados ainda (aguarde alguns minutos): {pending}"

    def dlq_empty():
        attributes = aws("sqs", "get-queue-attributes", "--queue-url", out["sqs_dlq_url"],
                         "--attribute-names", "ApproximateNumberOfMessages")["Attributes"]
        count = int(attributes["ApproximateNumberOfMessages"])
        assert count == 0, f"{count} mensagem(ns) na DLQ"
        return "vazia"

    def log_groups():
        lines = []
        for key, name in out["log_group_names"].items():
            groups = aws("logs", "describe-log-groups", "--log-group-name-prefix", name)["logGroups"]
            match = next((g for g in groups if g["logGroupName"] == name), None)
            assert match and match.get("retentionInDays"), f"{name}: ausente ou sem retenção"
            lines.append(f"{key} {match['retentionInDays']}d")
        return ", ".join(lines)

    report.check("ECS: serviços estáveis, sem IP público", services_stable)
    report.check("ECS: API e worker em duas AZs e instâncias distintas", tasks_in_two_zones)
    report.check("ALB: targets saudáveis", targets_healthy)
    report.check("Capacity Provider e Auto Scaling Group", capacity_provider)
    report.check("RDS privado e criptografado", database_private)
    report.check("Task definitions sem segredos em texto claro", no_plaintext_secrets)
    report.check("CloudWatch: alarmes", alarms)
    report.check("SQS: DLQ", dlq_empty)
    report.check("CloudWatch Logs: grupos e retenção", log_groups)


# --- verificações HTTP ------------------------------------------------------


def frontend_checks(report, app_url):
    def home():
        status, page, headers = request("GET", app_url + "/")
        assert status == 200 and "Insper Eats" in page, f"GET / retornou {status}"
        assert "Content-Security-Policy" in headers, "sem Content-Security-Policy"
        assert request("GET", app_url + "/healthz")[0] == 200, "/healthz não respondeu 200"
        return "página, CSP e /healthz"

    def chat_health():
        status, value, _ = request("GET", app_url + "/api/health")
        assert status == 200 and value.get("status") == "ok" and value.get("banco") == "ok", f"{status}: {value}"
        return f"banco ok, modo {value.get('modo')}, IA configurada={value.get('ia_configurada')}"

    report.check("Frontend pelo ALB", home)
    report.check("Chat pelo proxy /api (inclui conexão com o RDS)", chat_health)


def api_reachable(api_url):
    try:
        return request("GET", api_url + "/health", timeout=6)[0] == 200
    except (URLError, OSError):
        return False


def create_product(api_url, stock):
    status, product, _ = request("POST", api_url + "/produtos",
                              {"nome": f"Teste Terraform {uuid4().hex[:8]}", "preco": "8.00", "estoque": stock})
    assert status == 201, f"POST /produtos retornou {status}: {product}"
    return product


def stock_of(api_url, product_id):
    products = request("GET", api_url + "/produtos")[1]
    return next(p["estoque"] for p in products if p["id"] == product_id)


def order_body(product_id, client="Cliente Teste"):
    return {"cliente": client, "local_entrega": "Sala 512 - Predio 2", "chave_idempotencia": str(uuid4()),
            "itens": [{"produto_id": product_id, "quantidade": 1}]}


def api_checks(report, api_url, token):
    auth = {"X-Internal-Token": token}
    state = {}

    def health():
        assert request("GET", api_url + "/health")[0] == 200
        assert request("GET", api_url + "/docs")[0] == 200, "/docs não respondeu 200"
        return "/health e /docs 200"

    def requires_token():
        status = request("POST", api_url + "/pedidos", order_body(1))[0]
        assert status == 401, f"sem token retornou {status} (esperado 401)"
        return "401 sem X-Internal-Token"

    def idempotent_order():
        product = create_product(api_url, 5)
        body = order_body(product["id"])
        first = request("POST", api_url + "/pedidos", body, auth)
        assert first[0] == 201, f"primeiro POST retornou {first[0]}: {first[1]}"
        second = request("POST", api_url + "/pedidos", body, auth)
        assert second[0] == 200 and second[1]["id"] == first[1]["id"], f"repetição retornou {second[0]}"
        assert stock_of(api_url, product["id"]) == 4, "estoque debitado mais de uma vez"
        state["order_id"] = first[1]["id"]
        return f"pedido {first[1]['id']}: 201, depois 200 com o mesmo id; estoque 5 -> 4"

    def concurrent_stock():
        product = create_product(api_url, 1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted(pool.map(lambda name: request("POST", api_url + "/pedidos", order_body(product["id"], name), auth)[0],
                                    ["Cliente A", "Cliente B"]))
        assert codes == [201, 409], f"respostas {codes} (esperado um 201 e um 409)"
        assert stock_of(api_url, product["id"]) == 0, "estoque final diferente de 0"
        return "dois clientes, um 201 e um 409, estoque final 0"

    def worker_confirms():
        if "order_id" not in state:
            raise Skip("depende do pedido criado no teste de idempotência")
        started = time.monotonic()
        wait_for("confirmação pelo worker",
                 lambda: request("GET", f"{api_url}/pedidos/{state['order_id']}", headers=auth)[1].get("status") == "confirmado",
                 timeout=120, interval=3)
        return f"pedido {state['order_id']} confirmado em {time.monotonic() - started:.0f}s (outbox -> SQS -> worker -> RDS)"

    report.check("API: health e documentação", health)
    report.check("API: /pedidos exige o token interno", requires_token)
    report.check("API: pedido idempotente", idempotent_order)
    report.check("API: concorrência no estoque", concurrent_stock)
    report.check("Worker: pedido confirmado pela fila", worker_confirms)


def chat_checks(report, app_url, api_url, api_ok):
    browser, stranger = Browser(app_url), Browser(app_url)
    state = {}

    def session_and_csrf():
        assert browser.call("GET", "/api/chat/pedidos")[0] == 401, "listagem sem sessão deveria retornar 401"
        browser.start()
        stranger.start()
        assert browser.call("POST", "/api/chat/conversas", {}, csrf=False)[0] == 403, "sem CSRF deveria retornar 403"
        return "401 sem sessão, 403 sem CSRF"

    def purchase():
        mode = request("GET", app_url + "/api/health")[1].get("modo")
        if mode != "commands":
            raise Skip(f"o roteiro automático exige ai_provider = \"commands\" (atual: {mode})")
        if not api_ok:
            raise Skip("precisa da API em :8000 para criar o produto de teste (api_allowed_cidrs)")
        product = create_product(api_url, 20)
        status, conversation = browser.call("POST", "/api/chat/conversas", {})
        assert status == 201, f"criar conversa retornou {status}"
        cid = conversation["id"]
        assert stranger.call("GET", f"/api/chat/conversas/{cid}")[0] == 404, "outra sessão acessou a conversa"
        menu = browser.message(cid, "Ver o cardápio")
        assert product["nome"] in menu["mensagens"][-1]["conteudo"], "produto ausente do cardápio"
        browser.message(cid, f"Selecionar {product['id']}:2")
        browser.message(cid, "Meu nome é Ana")
        selection = browser.message(cid, "Entrega: sala 512, prédio 2")["compra"]
        assert float(selection["total"]) == 16, f"total {selection['total']} (esperado 16)"
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: browser.call("POST", f"/api/chat/conversas/{cid}/confirmar",
                                                            {"compra_id": selection["id"]}), range(2)))
        assert all(code == 200 for code, _ in results), f"confirmações retornaram {[code for code, _ in results]}"
        orders = {value["compra"]["pedido_id"] for _, value in results}
        assert len(orders) == 1, f"confirmação dupla gerou pedidos diferentes: {orders}"
        assert stock_of(api_url, product["id"]) == 18, "estoque debitado mais de uma vez"
        state["order_id"] = int(orders.pop())
        assert stranger.call("GET", f"/api/chat/pedidos/{state['order_id']}")[0] == 404, "outra sessão viu o pedido"
        assert stranger.call("GET", "/api/chat/pedidos")[1]["pedidos"] == [], "outra sessão listou pedidos alheios"
        return f"pedido {state['order_id']}: confirmação dupla sem duplicar, estoque 20 -> 18, isolado entre sessões"

    def status_in_panel():
        if "order_id" not in state:
            raise Skip("depende da compra pelo chat")
        wait_for("status confirmado no painel",
                 lambda: any(o.get("status") == "confirmado" for o in browser.call("GET", "/api/chat/pedidos")[1]["pedidos"]),
                 timeout=120, interval=3)
        return "painel de pedidos mostra 'confirmado' (frontend -> chat -> API -> SQS -> worker)"

    report.check("Chat: sessão, cookie e CSRF", session_and_csrf)
    report.check("Chat: compra ponta a ponta", purchase)
    report.check("Chat: status atualizado pelo worker", status_in_panel)


def dlq_check(report, aws, out):
    """Mensagem de tipo inválido: o worker falha 5 vezes e a fila a move para a DLQ."""

    def poison_message():
        marker = f"verify-{uuid4().hex[:8]}"
        aws("sqs", "send-message", "--queue-url", out["sqs_queue_url"], "--message-body",
            json.dumps({"tipo": "teste.invalido", "pedido_id": 1, "evento_id": marker}))
        print("        mensagem inválida enviada; aguardando 5 tentativas de 60 s...", flush=True)

        def in_dlq():
            messages = aws("sqs", "receive-message", "--queue-url", out["sqs_dlq_url"], "--max-number-of-messages", "10",
                           "--visibility-timeout", "5", "--wait-time-seconds", "10") or {}
            return next((m for m in messages.get("Messages", []) if marker in m["Body"]), None)

        message = wait_for("chegada na DLQ", in_dlq, timeout=540, interval=DLQ_POLL_SECONDS)
        aws("sqs", "delete-message", "--queue-url", out["sqs_dlq_url"], "--receipt-handle", message["ReceiptHandle"])
        return "mensagem chegou à DLQ após 5 recebimentos e foi removida"

    report.check("SQS: falha persistente vai para a DLQ", poison_message)


# --- execução ---------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-url", help="URL do frontend (padrão: terraform output app_url)")
    parser.add_argument("--api-url", help="URL da API de pedidos (padrão: terraform output api_url)")
    parser.add_argument("--profile", default=os.environ.get("AWS_PROFILE"), help="perfil da AWS CLI")
    parser.add_argument("--skip-aws", action="store_true", help="só testes HTTP, sem AWS CLI")
    parser.add_argument("--dlq", action="store_true", help="inclui o teste da DLQ (leva cerca de 6 minutos)")
    parser.add_argument("--output-dir", default=str(TERRAFORM_DIR / "evidencias"), help="pasta do relatório JSON")
    args = parser.parse_args()

    out = {}
    if not (args.skip_aws and args.app_url):
        raw = run_json(["terraform", "output", "-json"], cwd=TERRAFORM_DIR) or {}
        out = {key: value["value"] for key, value in raw.items()}
        if not out:
            sys.exit("Sem outputs do Terraform. Rode `terraform apply` antes, ou use --app-url com --skip-aws.")
    app_url = (args.app_url or out["app_url"]).rstrip("/")
    api_url = (args.api_url or out.get("api_url") or "").rstrip("/")
    aws = None if args.skip_aws else Aws(out["region"], args.profile)

    print(f"Aplicação: {app_url}\nAPI:       {api_url or '(não informada)'}\n", flush=True)
    report = Report()

    if aws:
        infrastructure_checks(report, aws, out)
    frontend_checks(report, app_url)

    api_ok = bool(api_url) and api_reachable(api_url)
    token = os.environ.get("ORDERS_INTERNAL_TOKEN")
    if api_ok and not token and aws:
        token = aws("secretsmanager", "get-secret-value", "--secret-id",
                    out["secret_names"]["orders_internal_token"])["SecretString"]
    if api_ok and token:
        api_checks(report, api_url, token)
    else:
        reason = ("defina ORDERS_INTERNAL_TOKEN" if api_ok else
                  "a porta 8000 do ALB não respondeu: inclua seu IP em api_allowed_cidrs e aplique de novo")
        report.check("API de pedidos e worker", skipped(reason))

    chat_checks(report, app_url, api_url, api_ok)

    if args.dlq:
        if aws:
            dlq_check(report, aws, out)
        else:
            report.check("SQS: falha persistente vai para a DLQ", skipped("exige AWS CLI"))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"verify-{stamp}.json"
    path.write_text(json.dumps({"quando_utc": stamp, "aplicacao": app_url, "resultados": report.results},
                               ensure_ascii=False, indent=2), encoding="utf-8")

    totals = {status: sum(r["resultado"] == status for r in report.results) for status in ("ok", "pulado", "FALHOU")}
    print(f"\n{totals['ok']} ok, {totals['pulado']} pulado(s), {totals['FALHOU']} falha(s). Relatório: {path}")
    sys.exit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
