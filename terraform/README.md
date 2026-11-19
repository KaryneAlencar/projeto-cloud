# Insper Eats: infraestrutura AWS com Terraform

Reproduz, com um `terraform apply`, o ambiente montado manualmente em Ohio
(descrito no guia `insper_eats_guia_aws_para_terraform.pdf`, que não faz parte
deste repositório) e acrescenta os dois serviços que
ainda não estavam na AWS (chat e frontend). O destino padrão é São Paulo
(`sa-east-1`), com o sufixo `sp` nos nomes. Nada aqui lê, importa ou altera os
recursos manuais de Ohio.

## O que é criado

```
internet
   |
  ALB público ── :80 (ou :443) ──> frontend (Nginx, Fargate)
   |                                   | /api/*
   |                                   v
   |                               chat (FastAPI, Fargate) ──> Gemini
   |                                   | X-Internal-Token
   └── :8000 (só api_allowed_cidrs) ─> API de pedidos (ECS em EC2) ──┐
                                                                     v
                              worker (ECS em EC2) <── SQS + DLQ     RDS PostgreSQL 17
                                     └───────────────────────────────┘
```

| Camada | Recursos |
| --- | --- |
| Rede | VPC 10.20.0.0/16, 2 AZs, 6 sub-redes (pública, aplicação, dados), IGW, NAT por AZ, endpoints S3 e SQS |
| Segurança | 9 security groups encadeados por referência; papéis IAM separados por serviço |
| Dados | RDS PostgreSQL 17 Multi-AZ, privado e criptografado; senha do administrador gerenciada pelo RDS |
| Mensageria | SQS Standard com DLQ (5 recebimentos), TLS obrigatório |
| Compute | Cluster ECS, Auto Scaling Group 0 a 4 de t3.medium, Capacity Provider com managed scaling, proteção e draining |
| Serviços | API, worker, chat e frontend, 2 a 4 tasks cada, com Application Auto Scaling |
| Entrada | ALB, target groups do tipo `ip`, HTTPS opcional |
| Observabilidade | Log groups com retenção, 14 alarmes, métricas extraídas dos logs, tópico SNS, dashboard de 14 widgets |
| Estado | Bucket S3 versionado e criptografado, com lock nativo (`bootstrap/`) |

São cerca de 150 recursos.

### Decisões que diferem de Ohio

- **Nomes com sufixo de ambiente** (`insper-eats-sp-...`). Papéis IAM são
  globais na conta: sem o sufixo, colidiriam com os de Ohio.
- **Chat e frontend em Fargate.** Uma t3.medium tem 3 interfaces de rede, o
  que dá 2 tasks `awsvpc` por instância, e essas vagas já são da API e do
  worker. Em Fargate, os serviços novos não disputam vagas nem mudam o
  comportamento de escala das instâncias. API e worker continuam em EC2, como
  foi validado.
- **A porta 80 entrega o frontend; a API fica na porta 8000 do ALB**, aberta
  só para os CIDRs de `api_allowed_cidrs` (vazio por padrão). Em Ohio a API
  estava na porta 80, pública. `/produtos` não tem autenticação, e
  `docs/IMPLANTACAO.md` pede que a API não seja exposta.
- **Health check da API em `/health`** (em Ohio era `/docs`).
- **Endereços internos por Cloud Map**: `api.insper-eats-sp.internal` e
  `chat.insper-eats-sp.internal`.
- **Banco e usuário exclusivos do chat** (`insper_eats_chat` / `insper_chat`),
  como `docs/IMPLANTACAO.md` recomenda. Cada usuário só conecta no próprio banco.
- **Token interno da API**: `backend/pedidos.py` exige `X-Internal-Token` em
  `/pedidos`. O Terraform gera o valor e o entrega à API e ao chat como secret.
- **Rollback automático** no circuit breaker dos deployments (em Ohio estava
  desligado).
- Dez alarmes a mais (14 no total): targets do frontend e tasks do chat;
  reserva do Capacity Provider; ASG no máximo; respostas 5xx da API e do
  frontend; idade da mensagem mais antiga da fila; erros nos logs da API, do
  worker e do chat.
- Um widget a mais no dashboard (14 no total): pedidos confirmados pelo
  worker, métrica extraída dos logs.
- **Health check no worker**, por arquivo de heartbeat, e reserva de memória
  (`memoryReservation`) nos quatro contêineres.

## Pré-requisitos

| Ferramenta | Para quê |
| --- | --- |
| Terraform 1.11 ou mais novo | recursos efêmeros e argumentos write-only (senhas fora do state) |
| AWS CLI v2 | login, envio de imagens ao ECR, execução da task `db-init`, scripts de teste |
| Docker | build das quatro imagens durante o apply |
| Python 3 e bash | scripts em `scripts/` (no Windows, use WSL ou Git Bash) |

No Arch/Omarchy: `sudo pacman -S terraform aws-cli-v2`.

Credenciais com permissão de administrador na conta:

```bash
aws configure sso                 # uma vez; crie o perfil insper-eats
aws sso login --profile insper-eats
export AWS_PROFILE=insper-eats AWS_REGION=sa-east-1
aws sts get-caller-identity       # confirme a conta antes de continuar
```

## Estrutura

```
terraform/
  versions.tf  variables.tf  locals.tf  outputs.tf
  network.tf        VPC, sub-redes, NAT, rotas, endpoints
  security.tf       security groups e regras
  database.tf       RDS
  secrets.tf        secrets de aplicação (valores fora do state)
  messaging.tf      SQS e DLQ
  ecr.tf            repositórios e build/push das imagens
  ecs_cluster.tf    cluster, launch template, ASG, Capacity Provider
  alb.tf            ALB, target groups, listeners
  db_init.tf        task que prepara o banco
  ecs_services.tf   Cloud Map e os quatro serviços
  observability.tf  SNS, alarmes, dashboard
  modules/ecs-service/   serviço ECS completo (IAM, task, serviço, auto scaling)
  bootstrap/             bucket do state remoto
  files/db_init.py       script executado pela task db-init
  deploy.sh              implantação completa em um comando
  scripts/               build-push.sh, run-db-init.sh, set-gemini-key.sh,
                         verify_deploy.py, load_api.py
  tests/                 testes com provider simulado e ensaio local em Docker
```

## Implantação

Um comando, sem perguntas, a partir de `terraform/`:

```bash
export TF_VAR_gemini_api_key="..."   # chave do Gemini; não vai para o plan nem para o state
./deploy.sh
```

`deploy.sh` confere as ferramentas e as credenciais, cria o bucket do state
remoto (`bootstrap/`), gera `backend.hcl` e roda `terraform apply`. O apply
constrói e envia as quatro imagens, cria a infraestrutura, roda a task
`db-init` (usuários, tabelas e catálogo inicial) e só termina quando os quatro
serviços estão estáveis. Leva de 25 a 35 minutos; o RDS Multi-AZ é a maior
parte. Se uma task não sobe, o apply falha em vez de reportar sucesso.

`terraform.tfvars` é opcional. Para ajustar valores, copie
`terraform.tfvars.example` e edite; o mais útil é `api_allowed_cidrs`, com o seu
IP (`curl -s https://checkip.amazonaws.com`), para alcançar a API em `:8000`.

Os mesmos passos, um a um:

```bash
cd bootstrap && terraform init && terraform apply
terraform output -raw backend_config > ../backend.hcl && cd ..
terraform init -backend-config=backend.hcl
terraform plan -out tfplan
terraform apply tfplan
```

Sem `TF_VAR_gemini_api_key`, o chat só funciona com `ai_provider = "commands"`.
Para gravar ou trocar a chave depois, defina a variável e aplique com
`-var gemini_api_key_version=2`, ou use `./scripts/set-gemini-key.sh`.

## Como testar

Os níveis vão do mais barato ao mais completo. Os dois primeiros não usam AWS.

### Nível 0: validação estática e testes simulados (segundos, sem credenciais)

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
terraform test
```

`terraform test` roda 16 cenários com o provider AWS simulado: 15 conferem o
plano contra os critérios do guia (rede, security groups, RDS privado, filas,
placement, escalonamento, alarmes, ausência de segredos em texto claro) e 1
aplica e destrói o grafo inteiro em memória. Esperado: `16 passed, 0 failed`.

Depois de `init -backend=false`, rode `terraform init -backend-config=backend.hcl`
de novo antes de usar o state remoto.

### Nível 1: ensaio local em Docker (cerca de 3 minutos, sem AWS)

Sobe as mesmas quatro imagens, o mesmo `files/db_init.py` e as mesmas variáveis
de ambiente das task definitions, com PostgreSQL no lugar do RDS e ElasticMQ no
lugar do SQS:

```bash
docker compose -f tests/local/compose.yaml up -d --build --wait
ORDERS_INTERNAL_TOKEN=token-local-only python3 scripts/verify_deploy.py \
  --skip-aws --app-url http://127.0.0.1:18081 --api-url http://127.0.0.1:18001
docker compose -f tests/local/compose.yaml down -v
```

Esperado: `10 ok, 0 pulado(s), 0 falha(s)`. Isso prova que as imagens
constroem, que o `db-init` cria usuários e tabelas com as permissões certas e
que o pedido vai do frontend até a confirmação pelo worker.

### Nível 2: plano real (minutos, sem custo)

```bash
terraform plan -out tfplan
```

Esperado: cerca de 150 recursos a criar, nenhum a alterar ou destruir, em uma
conta sem o ambiente. Erros aqui são de permissão, cota ou nome já em uso, e
aparecem antes de qualquer gasto.

### Nível 3: verificação do ambiente implantado

```bash
python3 scripts/verify_deploy.py
```

O script lê `terraform output`, consulta a AWS (somente leitura) e exercita a
aplicação. Esperado: 19 verificações `ok`. Ele cria produtos e pedidos de teste
com nomes iniciados por "Teste Terraform" e grava um relatório JSON em
`evidencias/`.

| Verificação | Critério do guia (seção 17) |
| --- | --- |
| ECS: serviços estáveis, sem IP público | 2 réplicas saudáveis; tasks sem exposição pública |
| ECS: API e worker em duas AZs e instâncias distintas | réplicas em duas AZs |
| ALB: targets saudáveis | ALB com health check healthy |
| Capacity Provider e Auto Scaling Group | ASG e Capacity Provider ativos |
| RDS privado e criptografado | RDS sem exposição pública |
| Task definitions sem segredos em texto claro | segredos via Secrets Manager |
| CloudWatch: alarmes / Logs: grupos e retenção | alarmes, logs e retenção definidos |
| Frontend pelo ALB / Chat pelo proxy | HTTP 200 em endpoint de verificação |
| API: pedido idempotente / concorrência no estoque | aplicação consulta e grava pedidos; duplicidade não debita estoque |
| Worker: pedido confirmado pela fila | fila publica `pedido.criado`, worker confirma |
| Chat: compra ponta a ponta / status atualizado | fluxo de compra ponta a ponta |

Se os testes da API aparecerem como `pulado`, seu IP não está em
`api_allowed_cidrs`. Os testes do chat também dependem de
`ai_provider = "commands"`; com `gemini`, o teste de compra automática é
pulado e a compra deve ser feita à mão pelo navegador.

Confira ainda, à mão:

```bash
terraform output app_url           # abra no navegador e faça uma compra pelo chat
terraform output dashboard_url     # os 14 widgets devem mostrar dados em ~5 min
terraform plan -detailed-exitcode  # código 0 = nenhuma mudança pendente
nc -zv -w 5 "$(terraform output -raw rds_endpoint)" 5432   # deve falhar: o RDS é privado
```

### Nível 4: comportamento sob falha e carga

Os comandos usam os nomes padrão (`insper-eats-sp`).

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)
ASG=$(terraform output -raw autoscaling_group_name)
servicos() { aws ecs describe-services --cluster "$CLUSTER" \
  --services insper-eats-sp-api-service insper-eats-sp-worker-service \
  --query 'services[].[serviceName,desiredCount,runningCount]' --output table; }
instancias() { aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].Instances[].[InstanceId,AvailabilityZone,LifecycleState]' --output table; }
```

**DLQ** (cerca de 6 minutos). Envia uma mensagem de tipo inválido, espera as 5
tentativas e confere que ela chegou à DLQ. O alarme `dlq-messages` dispara e
volta a OK depois que o script remove a mensagem:

```bash
python3 scripts/verify_deploy.py --dlq
```

**Substituição de task.** O serviço deve voltar a 2/2 em cerca de 1 minuto:

```bash
TASK=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name insper-eats-sp-worker-service \
  --query 'taskArns[0]' --output text)
aws ecs stop-task --cluster "$CLUSTER" --task "$TASK" --reason "teste de resiliencia"
servicos
```

**Substituição de EC2.** O ASG cria outra instância e os serviços voltam a 2/2
em alguns minutos:

```bash
INSTANCIA=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text)
aws autoscaling set-instance-health --instance-id "$INSTANCIA" --health-status Unhealthy
instancias
```

**Scale-out da API por CPU.** A carga comum não chega a 60% de CPU (em Ohio
ficou em 9,5%), então o alvo é baixado temporariamente, como no teste original:

```bash
terraform apply -var api_cpu_target=5
python3 scripts/load_api.py "$(terraform output -raw api_url)" --seconds 420 --threads 32
servicos        # API: desired 2 -> 4
instancias      # EC2: 2 -> 4
terraform apply # restaura 60%; em 15 a 20 min tudo volta a 2
```

**Scale-out do worker por backlog.** Uma fila temporária evita poluir a real:

```bash
FILA=$(aws sqs create-queue --queue-name insper-eats-sp-scale-test --query QueueUrl --output text)
for i in $(seq 1 40); do aws sqs send-message --queue-url "$FILA" --message-body "carga $i" >/dev/null; done
terraform apply -var worker_scaling_queue_name=insper-eats-sp-scale-test
servicos        # worker: desired 2 -> 4
terraform apply # volta a observar a fila real
aws sqs delete-queue --queue-url "$FILA"
```

**Alerta por e-mail.** Com `alert_email` definido e a inscrição confirmada:

```bash
aws sns publish --topic-arn "$(terraform output -raw sns_topic_arn)" \
  --subject "Teste Insper Eats" --message "Teste de alerta"
```

## Operação

- **Atualizar o código.** `terraform apply` detecta arquivos alterados, gera
  uma imagem com nova tag e faz o rolling deployment.
- **Girar senhas do banco e o token interno.** Aumente `credentials_version` e
  aplique. Entre a troca da senha e o fim do deployment, tasks antigas podem
  falhar ao abrir novas conexões por alguns minutos.
- **HTTPS.** Emita um certificado no ACM da mesma região, informe
  `acm_certificate_arn` e `app_domain`, aplique e aponte o DNS do domínio para
  `alb_dns_name`. O chat passa a usar cookie `Secure`.
- **Logs.** `aws logs tail /ecs/insper-eats-sp/api --follow` (também `worker`,
  `chat`, `frontend` e `db-init`).
- **Imagens por pipeline.** Com `build_images = false`, o apply usa a tag de
  `image_tag`, que precisa existir nos quatro repositórios.

## Custo e destruição

Com os padrões, o ambiente mantém ligados 2 NAT Gateways, 1 ALB, 1 RDS Multi-AZ,
2 instâncias t3.medium, 4 tasks Fargate e 1 endpoint de interface. Pela tabela
de preços de São Paulo isso fica na ordem de US$ 0,50 a 0,60 por hora (cerca de
US$ 13 a 15 por dia); é uma estimativa, confira na calculadora da AWS. Para
testes curtos, `db_multi_az = false` e `single_nat_gateway = true` reduzem o valor.

```bash
terraform destroy
cd bootstrap && terraform apply -var force_destroy=true && terraform destroy
```

O destroy remove tudo o que este Terraform criou, inclusive banco (sem snapshot
final, por padrão), imagens e secrets. Em ambiente que deva permanecer, defina
`db_deletion_protection = true` e `db_skip_final_snapshot = false`.

## Limites conhecidos

- Sem domínio e certificado, o tráfego é HTTP, e o cookie de sessão do chat não
  é `Secure`.
- A API de pedidos continua sem autenticação em `/produtos`. Mantenha
  `api_allowed_cidrs` restrito ao seu IP e esvazie a lista fora dos testes.
- O schema é criado por `create_all`; não há migrações versionadas.
- O tópico SNS não é criptografado: alarmes do CloudWatch não conseguem
  publicar em tópicos com a chave gerenciada `alias/aws/sns`.
- A AMI do ECS vem de um parâmetro público da AWS. Quando sai uma AMI nova, o
  `plan` mostra uma nova versão do launch template; só instâncias criadas
  depois passam a usá-la.
