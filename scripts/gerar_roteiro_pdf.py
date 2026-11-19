#!/usr/bin/env python3
"""Gera ROTEIRO_VIDEO_TERRAFORM.pdf na raiz do repositório.

O endereço do ALB muda a cada destroy/deploy, então o PDF é gerado a partir
do endereço atual:

    .venv/bin/python scripts/gerar_roteiro_pdf.py                 # lê terraform output
    .venv/bin/python scripts/gerar_roteiro_pdf.py --app-url http://...

Requer reportlab (pip install reportlab).
"""
import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
REGION = "sa-east-1"
PREFIX = "insper-eats-sp"
RED = colors.HexColor("#b3202a")
GREY = colors.HexColor("#555555")
LIGHT = colors.HexColor("#f4f1ee")
BLUE = "#1a4fa0"


def terraform_outputs():
    try:
        result = subprocess.run(["terraform", "output", "-json"], cwd=ROOT / "terraform",
                                text=True, capture_output=True, timeout=120)
        return {k: v["value"] for k, v in json.loads(result.stdout or "{}").items()}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {}


def build(app_url, account, output):
    console = f"https://{REGION}.console.aws.amazon.com"
    api_url = app_url.rstrip("/") + ":8000"
    bucket = f"insper-eats-tfstate-{account}-{REGION}"
    links = {
        "vpc": f"{console}/vpcconsole/home?region={REGION}#vpcs:",
        "subnets": f"{console}/vpcconsole/home?region={REGION}#subnets:",
        "nat": f"{console}/vpcconsole/home?region={REGION}#NatGateways:",
        "sg": f"{console}/vpcconsole/home?region={REGION}#SecurityGroups:",
        "ecr": f"{console}/ecr/private-registry/repositories?region={REGION}",
        "rds": f"{console}/rds/home?region={REGION}#database:id={PREFIX}-postgres;is-cluster=false",
        "secrets": f"{console}/secretsmanager/listsecrets?region={REGION}",
        "sqs": f"{console}/sqs/v3/home?region={REGION}#/queues",
        "cluster": f"{console}/ecs/v2/clusters/{PREFIX}-cluster/services?region={REGION}",
        "infra": f"{console}/ecs/v2/clusters/{PREFIX}-cluster/infrastructure?region={REGION}",
        "tasks": f"{console}/ecs/v2/clusters/{PREFIX}-cluster/tasks?region={REGION}",
        "ec2": f"{console}/ec2/home?region={REGION}#Instances:instanceState=running",
        "asg": f"{console}/ec2/home?region={REGION}#AutoScalingGroupDetails:id={PREFIX}-ecs-asg;view=details",
        "alb": f"{console}/ec2/home?region={REGION}#LoadBalancers:",
        "tg": f"{console}/ec2/home?region={REGION}#TargetGroups:",
        "dash": f"{console}/cloudwatch/home?region={REGION}#dashboards:name={PREFIX}-observabilidade",
        "alarms": f"{console}/cloudwatch/home?region={REGION}#alarmsV2:",
        "logs": f"{console}/cloudwatch/home?region={REGION}#logsV2:log-groups",
        "s3": f"{console}/s3/buckets/{bucket}?region={REGION}",
        "cloudmap": f"{console}/cloudmap/home/namespaces?region={REGION}",
        "ohio": "https://us-east-2.console.aws.amazon.com/vpcconsole/home?region=us-east-2#vpcs:",
    }

    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica", fontSize=10,
                          leading=14, alignment=TA_LEFT, spaceAfter=4)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=11.5, textColor=GREY)
    h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=24,
                        textColor=RED, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=17,
                        textColor=RED, spaceBefore=12, spaceAfter=5)
    label = ParagraphStyle("label", parent=body, fontName="Helvetica-Bold", fontSize=9,
                           textColor=GREY, spaceBefore=4, spaceAfter=1)
    bullet = ParagraphStyle("bullet", parent=body, leftIndent=12, bulletIndent=2, spaceAfter=2)
    cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=12, spaceAfter=0)
    code = ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8.3, leading=11,
                          backColor=LIGHT, borderPadding=(5, 6, 5, 6), leftIndent=6,
                          rightIndent=6, spaceBefore=4, spaceAfter=8)

    def a(text, url):
        return f'<a href="{url}" color="{BLUE}"><u>{text}</u></a>'

    story = []

    def section(title, minutes=None):
        suffix = f' <font size="9" color="#555555">({minutes})</font>' if minutes else ""
        story.append(Paragraph(title + suffix, h2))

    def say(*lines):
        story.append(Paragraph("O QUE FALAR", label))
        for line in lines:
            story.append(Paragraph(line, bullet, bulletText="•"))

    def show(*lines):
        story.append(Paragraph("O QUE MOSTRAR", label))
        for line in lines:
            story.append(Paragraph(line, bullet, bulletText="•"))

    def block(text):
        story.append(Preformatted(text.strip("\n"), code))

    def table(rows, widths):
        data = [[Paragraph(str(c), cell) for c in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfc8c0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 6))

    # --- Capa -----------------------------------------------------------------
    story.append(Paragraph("Insper Eats: roteiro do vídeo", h1))
    story.append(Paragraph("Etapa 2: infraestrutura com Terraform em São Paulo (sa-east-1)", body))
    story.append(Paragraph(
        f"Gerado em {date.today().strftime('%d/%m/%Y')}. Duração sugerida: 8 a 10 minutos. "
        f"Conta AWS {account}. Os links abrem o Console já em São Paulo.", small))
    story.append(Spacer(1, 6))
    table([
        ["Atalho", "Endereço"],
        ["Aplicação", a(app_url, app_url) + "<br/><font size='8' color='#555555'>Digite com http:// "
                      "(não há certificado; https não responde).</font>"],
        ["API de pedidos (documentação)", a(api_url + "/docs", api_url + "/docs") +
         "<br/><font size='8' color='#555555'>Só abre do IP liberado em api_allowed_cidrs.</font>"],
        ["Dashboard", a("CloudWatch: insper-eats-sp-observabilidade", links["dash"])],
        ["Cluster ECS", a("ECS: insper-eats-sp-cluster", links["cluster"])],
    ], [48 * mm, 122 * mm])
    story.append(Paragraph(
        "O endereço do ALB muda a cada destroy/deploy. Para atualizar este PDF: "
        "<font face='Courier' size='8.5'>.venv/bin/python scripts/gerar_roteiro_pdf.py</font>", small))

    section("Antes de gravar")
    for line in [
        "No terminal, na raiz do repositório: <font face='Courier' size='9'>source scripts/aws-env.sh</font> "
        "(a última linha deve mostrar \"ok conta AWS\"). Se a sessão expirou: "
        "<font face='Courier' size='9'>aws sso login --profile insper-eats</font>.",
        "No Console, confira o seletor de região no canto superior direito: <b>América do Sul (São Paulo)</b>. "
        "Em Ohio aparecem os recursos da etapa manual, não os do Terraform.",
        "Abra a aplicação com <b>http://</b> na frente e faça uma compra de teste, para o catálogo e o painel "
        "já estarem carregados.",
        "Deixe abertas, em abas: o editor com a pasta terraform/, o Console e a aplicação.",
    ]:
        story.append(Paragraph(line, bullet, bulletText="•"))

    # --- 1 --------------------------------------------------------------------
    section("1. Abertura", "30 s")
    say("Na etapa 1 montamos a infraestrutura à mão em Ohio. Nesta etapa reconstruímos tudo com Terraform "
        "em São Paulo, sem reaproveitar nenhum recurso de Ohio.",
        "Um comando cria o ambiente inteiro: rede, banco, fila, imagens, cluster ECS sobre EC2, "
        "load balancer e observabilidade. Outro comando destrói tudo.")
    show(a("VPCs de Ohio", links["ohio"]) + ": a rede manual (insper-eats-vpc-ohio) continua intacta.",
         a("VPCs de São Paulo", links["vpc"]) + ": a rede insper-eats-sp-vpc, criada pelo Terraform.")

    # --- 2 --------------------------------------------------------------------
    section("2. Como o código está organizado", "1 min 30 s")
    show("No editor, a pasta <b>terraform/</b>: um arquivo por camada (network.tf, security.tf, database.tf, "
         "secrets.tf, messaging.tf, ecr.tf, ecs_cluster.tf, alb.tf, ecs_services.tf, observability.tf).",
         "O módulo <b>modules/ecs-service/</b>, usado quatro vezes (api, worker, chat, frontend): task definition, "
         "papéis IAM, serviço e auto scaling.",
         "<b>variables.tf</b>: região, sufixo do ambiente, tamanhos e limites são parâmetros.")
    say("O código é parametrizado: a região é uma variável, e o sufixo \"sp\" entra em todos os nomes para não "
        "colidir com Ohio, já que papéis IAM são globais na conta.",
        "Nada é fixo de uma região: as zonas vêm de um data source, a AMI do ECS vem de um parâmetro público "
        "do SSM, e os endpoints são montados a partir da variável de região.",
        "O estado fica em backend remoto: um bucket S3 versionado e criptografado, com lock nativo.")
    show(a("Bucket do state no S3", links["s3"]) + ": o arquivo insper-eats/sp/terraform.tfstate.")

    # --- 3 --------------------------------------------------------------------
    section("3. O deploy em um comando", "1 min")
    block("""
source scripts/aws-env.sh
cd terraform
./deploy.sh          # cria tudo;  ./destroy.sh remove tudo
""")
    say("O deploy.sh confere ferramentas e credenciais, cria o bucket do state, confere a cota de vCPU e roda "
        "o terraform apply, sem perguntas.",
        "Durante o apply, o Terraform constrói as quatro imagens Docker e envia ao ECR de São Paulo. "
        "A tag de cada imagem é um hash do código: código igual não reconstrói nada.",
        "Uma task temporária prepara o banco (usuários, tabelas e catálogo inicial) e o apply só termina "
        "quando os quatro serviços estão estáveis.",
        "Os segredos são gerados pelo Terraform e gravados no Secrets Manager por argumentos write-only: "
        "não aparecem no plan nem no state.")
    show(a("ECR", links["ecr"]) + ": os quatro repositórios insper-eats-sp-*.",
         a("Secrets Manager", links["secrets"]) + ": database-url, chat-database-url, orders-internal-token, "
         "gemini-api-key (mostre só os nomes, não os valores).")

    # --- 4 --------------------------------------------------------------------
    section("4. O que foi criado, no Console", "3 min")
    table([
        ["Onde clicar", "O que apontar", "O que dizer"],
        [a("VPC", links["vpc"]) + ", " + a("sub-redes", links["subnets"]) + ", " + a("NAT", links["nat"]),
         "VPC 10.20.0.0/16, 6 sub-redes em 2 zonas, 2 NAT Gateways",
         "Três camadas: pública (ALB e NAT), aplicação (tasks e instâncias) e dados (RDS). "
         "Só o ALB é público."],
        [a("Security groups", links["sg"]),
         "9 grupos insper-eats-sp-*",
         "As regras referenciam outros grupos, não faixas de IP: internet, ALB, frontend, chat, API, banco. "
         "As instâncias não têm nenhuma regra de entrada."],
        [a("RDS", links["rds"]),
         "PostgreSQL 17, Multi-AZ, sem acesso público, criptografado",
         "Conversas, catálogo, estoque e pedidos ficam aqui; nenhuma task guarda dado local."],
        [a("SQS", links["sqs"]),
         "insper-eats-sp-orders e insper-eats-sp-orders-dlq",
         "Comunicação assíncrona: a API grava o pedido e um evento; o worker publica e consome a fila. "
         "Após 5 falhas a mensagem vai para a DLQ."],
        [a("ECS: serviços", links["cluster"]),
         "4 serviços, 2 tasks cada, todos no Capacity Provider EC2",
         "ECS sobre EC2, sem Fargate nos serviços. Cada serviço tem papel de execução e papel de "
         "aplicação próprios."],
        [a("ECS: infraestrutura", links["infra"]) + " e " + a("Auto Scaling Group", links["asg"]),
         "Capacity Provider com managed scaling; ASG de 0 a 10; 4 instâncias t3.medium",
         "Ninguém define o número de instâncias: o Capacity Provider pede ao ASG conforme as tasks precisam. "
         "Cada t3.medium comporta 2 tasks (limite de interfaces de rede)."],
        [a("EC2: instâncias", links["ec2"]),
         "4 instâncias em 2 zonas, sem IP público",
         "Réplicas do mesmo serviço nunca ficam na mesma instância (distinctInstance) e se espalham por zona."],
        [a("Load balancer", links["alb"]) + " e " + a("target groups", links["tg"]),
         "Listener 80 para o frontend; targets healthy",
         "O acesso externo passa só pelo ALB. O health check decide quem recebe tráfego."],
        [a("Cloud Map", links["cloudmap"]),
         "Namespace insper-eats-sp.internal",
         "O frontend acha o chat e o chat acha a API por nome interno, sem endereço fixo."],
    ], [42 * mm, 52 * mm, 76 * mm])

    # --- 5 --------------------------------------------------------------------
    section("5. A aplicação funcionando", "1 min 30 s")
    show("Abra " + a(app_url, app_url) + ".",
         "Peça o cardápio, escolha um item, informe nome e local de entrega.",
         "Confira o resumo e clique em <b>Confirmar pedido</b>.",
         "No painel <b>Meus pedidos</b>, o status passa de Recebido para Confirmado em cerca de 10 segundos.")
    say("O vendedor é uma IA generativa que usa funções reais: consulta o catálogo na API e grava a seleção "
        "no banco. O pedido é criado quando o cliente confirma.",
        "A mudança para Confirmado é o caminho assíncrono completo: API, fila SQS, worker e banco.")
    story.append(Paragraph(
        "Se o assistente responder que está indisponível, é o provedor de IA (Gemini) fora do ar ou lento. "
        "O restante do ambiente continua funcionando; comente isso e siga para o próximo bloco.", small))

    # --- 6 --------------------------------------------------------------------
    section("6. Verificação automática", "1 min")
    block("""
cd terraform
python3 scripts/verify_deploy.py
""")
    say("O script lê os outputs do Terraform, consulta a AWS em modo leitura e exercita a aplicação.",
        "Ele confere serviços estáveis e sem IP público, réplicas em duas zonas e instâncias distintas, "
        "targets saudáveis, banco privado e criptografado, ausência de segredos em texto claro, alarmes, "
        "pedido idempotente, concorrência no estoque e a confirmação pelo worker.")
    story.append(Paragraph(
        "Com a IA real ligada (ai_provider = gemini), as duas verificações de compra automática pelo chat "
        "aparecem como \"pulado\": elas usam o modo de comandos. A compra pelo navegador do bloco 5 cobre "
        "esse caminho.", small))

    # --- 7 --------------------------------------------------------------------
    section("7. Observabilidade", "1 min")
    show(a("Dashboard", links["dash"]) + ": 14 widgets (tasks, CPU, memória, fila, ALB, RDS, reserva do "
         "Capacity Provider e pedidos confirmados).",
         a("Alarmes", links["alarms"]) + ": 16 alarmes insper-eats-sp-*.",
         a("Log groups", links["logs"]) + ": /ecs/insper-eats-sp/api, worker, chat, frontend.")
    say("Os alarmes cobrem saúde das tasks, utilização do cluster, capacidade do Auto Scaling Group, respostas "
        "do load balancer, profundidade da fila e falhas da aplicação, todos ligados a um tópico SNS.",
        "\"Pedidos confirmados\" é uma métrica de negócio extraída dos logs do worker.",
        "Um mesmo identificador de requisição aparece no log do chat e no log da API na criação do pedido, "
        "o que permite seguir uma compra de ponta a ponta.")

    # --- 8 --------------------------------------------------------------------
    section("8. Resiliência e elasticidade", "2 min, escolha uma ou duas demonstrações")
    story.append(Paragraph("Prepare os atalhos uma vez:", body))
    block(f"""
cd terraform
CLUSTER=$(terraform output -raw ecs_cluster_name)
ASG=$(terraform output -raw autoscaling_group_name)
""")
    story.append(KeepTogether([
        Paragraph("<b>Substituição de task</b> (cerca de 1 minuto). O serviço volta a 2/2 sozinho.", body),
        Preformatted("""
TASK=$(aws ecs list-tasks --cluster "$CLUSTER" \\
  --service-name insper-eats-sp-worker-service --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster "$CLUSTER" --task "$TASK" --reason "teste de resiliencia"
""".strip("\n"), code),
    ]))
    show(a("Tasks do cluster", links["tasks"]) + ": a task parada e a nova entrando.")
    story.append(KeepTogether([
        Paragraph("<b>Perda de uma instância EC2</b> (alguns minutos). O ASG lança outra e as tasks voltam.", body),
        Preformatted("""
INSTANCIA=$(aws autoscaling describe-auto-scaling-groups \\
  --auto-scaling-group-names "$ASG" \\
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text)
aws autoscaling set-instance-health --instance-id "$INSTANCIA" --health-status Unhealthy
""".strip("\n"), code),
    ]))
    show(a("Auto Scaling Group", links["asg"]) + ", aba Atividade: a instância sendo substituída.",
         "A aplicação continua respondendo durante a troca, porque cada serviço tem réplica em outra instância.")
    story.append(KeepTogether([
        Paragraph("<b>Scale-out por carga</b> (opcional, 10 a 20 minutos no total; grave em separado). "
                  "O alvo de CPU da API é baixado temporariamente para a carga de teste disparar a escala.", body),
        Preformatted("""
TF_VAR_api_cpu_target=5 ./deploy.sh
python3 scripts/load_api.py "$(terraform output -raw api_url)" --seconds 420 --threads 32
./deploy.sh     # restaura o alvo de 60%
""".strip("\n"), code),
    ]))
    say("São dois níveis de elasticidade: o Application Auto Scaling muda o número de tasks, e quando uma "
        "task não acha lugar o Capacity Provider aumenta o número de instâncias.",
        "A API escala por CPU; o worker escala pelo backlog da fila dividido pelo número de tasks.")

    # --- 9 --------------------------------------------------------------------
    section("9. Limites conhecidos e encerramento", "45 s")
    say("O tráfego é HTTP porque não usamos domínio nem certificado; o código já cria o listener HTTPS quando "
        "recebe um certificado do ACM.",
        "O dimensionamento da frota é ditado pelo limite de interfaces de rede da t3.medium (2 tasks por "
        "instância), não por CPU ou memória; por isso são 4 instâncias em repouso.",
        "A task que prepara o banco roda em Fargate por ser temporária e anterior às instâncias; os quatro "
        "serviços rodam em EC2.",
        "Para desmontar tudo: ./destroy.sh. Para recriar do zero: ./deploy.sh.")
    block("""
cd terraform
./destroy.sh         # remove o ambiente e o bucket do state
""")
    story.append(Paragraph(
        "Rode o destroy depois de gravar: o ambiente gera custo enquanto estiver no ar.", small))

    # --- Perguntas --------------------------------------------------------------
    section("Perguntas prováveis")
    table([
        ["Pergunta", "Resposta curta"],
        ["O que garante que não depende de Ohio?",
         "Região, zonas, AMI e endpoints vêm de variável, data source ou parâmetro do SSM. As imagens são "
         "construídas e enviadas ao ECR de São Paulo. Os nomes têm sufixo próprio. Nenhum ARN ou ID de Ohio "
         "aparece no código."],
        ["Onde ficam os segredos?",
         "No Secrets Manager. Senhas e token interno são gerados por recursos efêmeros e gravados por "
         "argumentos write-only, fora do state. A senha de administrador do banco é gerida pelo próprio RDS."],
        ["Por que 4 instâncias para 8 tasks pequenas?",
         "Cada task em modo awsvpc usa uma interface de rede, e a t3.medium só tem 3. O limite é de rede, "
         "não de CPU. É um custo conhecido do desenho; um tipo com ENI trunking reduziria a frota."],
        ["Como o scale-in é seguro?",
         "O Capacity Provider usa managed termination protection e managed draining: só remove instância "
         "sem tasks, e drena antes."],
        ["E se uma mensagem falhar sempre?",
         "Ela não é apagada, volta à fila e, após 5 recebimentos, vai para a DLQ. Um alarme avisa."],
        ["A criação é reproduzível?",
         "Sim: ./deploy.sh numa conta limpa cria tudo, e ./destroy.sh remove tudo, sem passos manuais."],
    ], [52 * mm, 118 * mm])

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(GREY)
        canvas.drawString(20 * mm, 12 * mm, "Insper Eats: roteiro do vídeo, etapa Terraform")
        canvas.drawRightString(190 * mm, 12 * mm, f"Página {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(output), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title="Insper Eats: roteiro do vídeo (Terraform)", author="Insper Eats")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--app-url", help="endereço da aplicação (padrão: terraform output app_url)")
    parser.add_argument("--account", help="ID da conta AWS (padrão: tirado do bucket do state)")
    parser.add_argument("--output", default=str(ROOT / "ROTEIRO_VIDEO_TERRAFORM.pdf"))
    args = parser.parse_args()

    outputs = {} if args.app_url and args.account else terraform_outputs()
    app_url = args.app_url or outputs.get("app_url")
    if not app_url:
        raise SystemExit("Informe --app-url ou rode a partir de um ambiente implantado (terraform output).")
    account = args.account
    if not account:
        backend = ROOT / "terraform" / "backend.hcl"
        text = backend.read_text() if backend.exists() else ""
        account = next((part for part in text.replace('"', " ").replace("-", " ").split()
                        if part.isdigit() and len(part) == 12), "<conta>")
    build(app_url.rstrip("/"), account, Path(args.output))
    print(f"Gerado: {args.output}")


if __name__ == "__main__":
    main()
