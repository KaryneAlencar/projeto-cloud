# Insper Eats: infraestrutura AWS com Terraform

Reproduz, com um `terraform apply`, o ambiente montado manualmente em Ohio
(descrito no guia `insper_eats_guia_aws_para_terraform.pdf`, que não faz parte
deste repositório) e acrescenta os dois serviços que
ainda não estavam na AWS (chat e frontend). O destino padrão é São Paulo
(`sa-east-1`), com o sufixo `sp` nos nomes. Nada aqui lê, importa ou altera os
recursos manuais de Ohio.

O código passou em validação estática, nos testes com provider simulado e no
ensaio local em Docker. Ainda não foi aplicado em `sa-east-1`: tempos e
resultados "esperados" abaixo são estimativas até a primeira execução.

Documentos relacionados: [requisitos do enunciado e onde cada um é
atendido](../docs/REQUISITOS.md) e [runbook dos alarmes](../docs/RUNBOOK.md).

## O que é criado

```
internet
   |
  ALB público ── :80 (ou :443) ──> frontend (Nginx, ECS em EC2)
   |                                   | /api/*
   |                                   v
   |                               chat (FastAPI, ECS em EC2) ──> Gemini
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
| Compute | Cluster ECS, Auto Scaling Group 0 a 10 de t3.medium, Capacity Provider com managed scaling, proteção e draining |
| Serviços | API, worker, chat e frontend, 2 a 4 tasks cada, todos em EC2 pelo mesmo Capacity Provider, com Application Auto Scaling |
| Entrada | ALB, target groups do tipo `ip`, HTTPS opcional |
| Observabilidade | Log groups com retenção, 16 alarmes, métricas extraídas dos logs, tópico SNS, dashboard de 14 widgets |
| Estado | Bucket S3 versionado e criptografado, com lock nativo (`bootstrap/`) |

São cerca de 150 recursos.

### Decisões que diferem de Ohio

- **Nomes com sufixo de ambiente** (`insper-eats-sp-...`). Papéis IAM são
  globais na conta: sem o sufixo, colidiriam com os de Ohio.
- **Chat e frontend também em EC2, com frota maior.** O enunciado exige ECS
  sobre EC2 e não aceita Fargate como capacidade principal, então os quatro
  serviços usam o mesmo Capacity Provider. Uma t3.medium tem 3 interfaces de
  rede, o que dá 2 tasks `awsvpc` por instância, e `distinctInstance` impede
  duas réplicas do mesmo serviço na mesma instância. Com 4 serviços de 2 tasks
  são 4 instâncias em repouso (em Ohio eram 2); com todos em 4 tasks, 8. O
  máximo do Auto Scaling Group passou de 4 para 10 (`ecs_asg_max_size`): as 2
  instâncias além das 8 são a folga para um rolling deployment com a frota no
  pico, quando a task nova precisa de vaga antes de a antiga sair. A conta
  completa está em `docs/REQUISITOS.md`. Só a task temporária `db-init` usa Fargate: roda uma vez, antes de existirem
  instâncias, e termina.
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
- Mais alarmes, 16 no total: aos de targets e de tasks somam-se os do chat e
  do frontend; reserva do Capacity Provider; ASG no máximo; respostas 5xx dos
  targets da API e do frontend; respostas 5xx geradas pelo próprio ALB; idade
  da mensagem mais antiga da fila; erros nos logs da API, do worker e do chat.
  O que cada um significa e como tratar está em `docs/RUNBOOK.md`.
- Um widget a mais no dashboard (14 no total): pedidos confirmados pelo
  worker, métrica extraída dos logs.
- **Health check no worker**, por arquivo de heartbeat (falha após 120 s sem
  toque), e reserva de memória (`memoryReservation`) nos quatro contêineres.
- **`stop_timeout` do chat em 170 s**, para terminar respostas em andamento
  (o Uvicorn do chat espera até 160 s). Em EC2 não há o teto de 120 s que o
  Fargate impõe.
- **Instâncias com IMDSv2 obrigatório e `ECS_AWSVPC_BLOCK_IMDS=true`**: as
  tasks não alcançam as credenciais do papel da instância.

## Pré-requisitos

| Ferramenta | Para quê |
| --- | --- |
| Terraform 1.11 ou mais novo | recursos efêmeros e argumentos write-only (senhas fora do state) |
| AWS CLI v2 | login, envio de imagens ao ECR, execução da task `db-init`, scripts de teste |
| Docker | build das quatro imagens durante o apply |
| Python 3 e bash | scripts em `scripts/` (no Windows, use WSL ou Git Bash) |

No Arch/Omarchy: `sudo pacman -S terraform aws-cli-v2`.

Cota de vCPU na região: as 4 instâncias t3.medium em repouso usam 8 vCPU, e o
máximo de 10 instâncias, 20. A cota é "Running On-Demand Standard (A, C, D, H,
I, M, R, T, Z) instances", código `L-1216C47A`. `deploy.sh` a consulta antes de
aplicar: abaixo de 8 interrompe; abaixo de 20 avisa que o scale-out completo
não cabe. Para conferir à mão:

```bash
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A \
  --query 'Quota.Value' --output text
```

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
  destroy.sh             remoção do ambiente e do bucket do state
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
remoto (`bootstrap/`; se o bucket já existe, ele é adotado), gera `backend.hcl`,
confere a cota de vCPU e roda `terraform apply`. O apply constrói e envia as
quatro imagens, cria a infraestrutura, roda a task `db-init` (usuários, tabelas
e catálogo inicial) e só termina quando os quatro serviços estão estáveis. A
estimativa é de 30 a 40 minutos na primeira vez; o RDS Multi-AZ é a maior
parte. Se uma task não sobe, o apply falha em vez de reportar sucesso. Repetir
o comando é seguro: só aplica o que mudou.

As credenciais vêm do ambiente (`AWS_PROFILE` ou variáveis `AWS_*`). Se usar
`aws_profile` em `terraform.tfvars`, exporte o mesmo perfil em `AWS_PROFILE`.

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

Chave do Gemini. O secret só é regravado quando `gemini_api_key_version` muda.
`deploy.sh` deriva essa versão da própria chave: a mesma chave não gera
mudança, e uma chave nova em `TF_VAR_gemini_api_key` é regravada no próximo
`./deploy.sh`, sem outro passo. Sem a variável, `deploy.sh` implanta o chat em
modo de comandos (`ai_provider = "commands"`, sem IA), a menos que
`terraform.tfvars` fixe outro valor; para ligar a IA, exporte a chave e rode
de novo. `./scripts/set-gemini-key.sh` grava a chave direto no Secrets Manager
e reinicia o chat, sem passar pelo Terraform.

O `deploy.sh` grava a versão derivada em `gemini.auto.tfvars` (ignorado pelo
Git), que o Terraform lê sozinho. Por isso um `terraform plan` ou `terraform
apply` direto, mesmo sem a chave no ambiente, enxerga a mesma versão e não toca
no secret. Variáveis avulsas podem ir por `-var` ou por ambiente, por exemplo
`TF_VAR_api_cpu_target=5 ./deploy.sh`.

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
| ECS: quatro serviços em duas AZs e instâncias distintas | réplicas em duas AZs |
| ALB: targets saudáveis | ALB com health check healthy |
| Capacity Provider e Auto Scaling Group (4 ou mais instâncias em serviço) | ASG e Capacity Provider ativos |
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

Os comandos usam os nomes padrão (`insper-eats-sp`). As mudanças de variável
são aplicadas por `./deploy.sh`, com `TF_VAR_gemini_api_key` exportada (ver
"Implantação").

```bash
CLUSTER=$(terraform output -raw ecs_cluster_name)
ASG=$(terraform output -raw autoscaling_group_name)
servicos() { aws ecs describe-services --cluster "$CLUSTER" \
  --services insper-eats-sp-api-service insper-eats-sp-worker-service \
             insper-eats-sp-chat-service insper-eats-sp-frontend-service \
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

**Substituição de EC2.** Cada instância hospeda 2 tasks, de serviços
diferentes. O ASG cria outra instância e os serviços voltam a 2/2 em alguns
minutos:

```bash
INSTANCIA=$(aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].Instances[0].InstanceId' --output text)
aws autoscaling set-instance-health --instance-id "$INSTANCIA" --health-status Unhealthy
instancias
```

**Scale-out da API por CPU.** A carga comum não chega a 60% de CPU (em Ohio
ficou em 9,5%), então o alvo é baixado temporariamente, como no teste original:

```bash
TF_VAR_api_cpu_target=5 ./deploy.sh
python3 scripts/load_api.py "$(terraform output -raw api_url)" --seconds 420 --threads 32
servicos        # API: desired 2 -> 4
instancias      # EC2: 4 -> 6 (cada task nova precisa de uma instância sem outra task da API)
./deploy.sh     # restaura 60%; a API volta a 2 tasks depois do cooldown
```

A frota pode não voltar a 4 instâncias sozinha: se as tasks que restarem
ficarem em instâncias diferentes, nenhuma fica vazia para o Capacity Provider
remover. Ver "Limites conhecidos" e a consolidação manual em
`docs/RUNBOOK.md` ("asg-at-max").

**Scale-out do worker por backlog.** Uma fila temporária evita poluir a real:

```bash
FILA=$(aws sqs create-queue --queue-name insper-eats-sp-scale-test --query QueueUrl --output text)
for i in $(seq 1 40); do aws sqs send-message --queue-url "$FILA" --message-body "carga $i" >/dev/null; done
TF_VAR_worker_scaling_queue_name=insper-eats-sp-scale-test ./deploy.sh
servicos        # worker: desired 2 -> 4
./deploy.sh     # volta a observar a fila real
aws sqs delete-queue --queue-url "$FILA"
```

**Alerta por e-mail.** Com `alert_email` definido e a inscrição confirmada:

```bash
aws sns publish --topic-arn "$(terraform output -raw sns_topic_arn)" \
  --subject "Teste Insper Eats" --message "Teste de alerta"
```

## Operação

- **Alarmes e incidentes.** `docs/RUNBOOK.md` traz, para cada um dos 16
  alarmes, o significado, o diagnóstico e o encerramento, além do reenvio da
  DLQ, da substituição manual de instância e do que fazer quando o Gemini está
  indisponível.
- **Atualizar o código.** `./deploy.sh` detecta arquivos alterados, gera uma
  imagem com nova tag e faz o rolling deployment. Com as 4 instâncias cheias,
  o deploy faz o ASG subir temporariamente.
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
4 instâncias t3.medium e 1 endpoint de interface; nenhuma task Fargate fica
ligada. A estimativa anterior, de US$ 0,50 a 0,60 por hora (cerca de US$ 13 a
15 por dia), foi feita para a composição antiga, com 2 instâncias t3.medium e 4
tasks Fargate. Ela não foi refeita: duas instâncias a mais no lugar de quatro
tasks Fargate pequenas devem deixar o total um pouco acima dessa faixa. Confira
na calculadora da AWS. Para testes curtos, `db_multi_az = false` e
`single_nat_gateway = true` reduzem o valor.

```bash
./destroy.sh
```

`./destroy.sh` remove o ambiente e, em seguida, o bucket do state, sem
perguntas. Com `--keep-state`, remove só o ambiente e mantém o bucket para o
próximo deploy. Vai embora tudo o que este Terraform criou, inclusive banco
(sem snapshot final, por padrão), imagens e secrets; depois dele,
`./deploy.sh` recria do zero. Em ambiente que deva permanecer, defina
`db_deletion_protection = true` e `db_skip_final_snapshot = false`.

## Limites conhecidos

- **O gargalo da frota é a interface de rede, não CPU nem memória.** Uma
  t3.medium tem 3 interfaces, o que dá 2 tasks `awsvpc`, e a família t3 não
  aceita ENI trunking. Cada instância roda com cerca de 25% de CPU e de
  memória reservadas e não aceita uma terceira task: paga-se por capacidade
  que não pode ser usada.
- **Depois de um pico ou de um deploy, o ASG tende a não encolher sozinho.** O
  Capacity Provider só remove instância sem task, e o ECS não reconsolida
  tasks em execução. A consolidação é manual (`docs/RUNBOOK.md`, "asg-at-max").
- **Aplicar fora do `deploy.sh` pode apagar a chave do Gemini** do secret (ver
  "Implantação").
- O ambiente ainda não foi aplicado em `sa-east-1`; não há evidência de
  execução nessa região.
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
