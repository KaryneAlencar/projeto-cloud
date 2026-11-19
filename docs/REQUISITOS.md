# Requisitos do enunciado e onde cada um é atendido

Mapa entre os requisitos do projeto final e o código deste repositório. Cada
linha aponta o arquivo e, quando ajuda, o recurso Terraform. Os nomes usam o
prefixo padrão `insper-eats-sp` (região `sa-east-1`).

**Situação.** O Terraform passou em validação estática, nos testes com provider
simulado (`terraform/tests/`) e no ensaio local em Docker. Ele ainda não foi
aplicado em `sa-east-1`: não há evidência de execução nessa região. As
evidências em `docs/evidencias/ohio/` são do ambiente manual anterior e não
comprovam o que está descrito aqui. O que este documento afirma é o que o
código declara.

## Tabela de requisitos

| # | Requisito | Como é atendido | Onde está |
| --- | --- | --- | --- |
| 1 | ECS sobre EC2; Fargate não é a capacidade principal | Os quatro serviços (api, worker, chat, frontend) usam `launch_type = "EC2"` e o mesmo Capacity Provider, apoiado num Auto Scaling Group. A única task em Fargate é a `db-init`, que roda uma vez por apply que precise dela e termina. | `terraform/ecs_services.tf` (módulos `api`, `worker`, `chat`, `frontend`); `terraform/ecs_cluster.tf` (`aws_ecs_capacity_provider.ec2`, `aws_ecs_cluster_capacity_providers.main`); `terraform/db_init.tf` |
| 2 | Imagens no ECR da própria região | Quatro repositórios criados na região de `var.region`. O build e o push são feitos pela máquina que roda o apply, para o registro regional; nenhuma imagem é copiada de outra região. Tags imutáveis, derivadas do hash dos arquivos de cada build. | `terraform/ecr.tf` (`aws_ecr_repository.this`, `terraform_data.image`); `terraform/scripts/build-push.sh` |
| 3 | ASG + Capacity Provider; capacidade mínima, desejada e máxima; ciclo de inclusão, drenagem, substituição e remoção | ASG com mínimo 0 e máximo 10 (`ecs_asg_max_size`). A capacidade desejada pertence ao Capacity Provider (`managed_scaling`, alvo 100%, passos de 1 a 2 instâncias, warm-up de 300 s); o Terraform ignora `desired_capacity`. Inclusão: a instância entra no cluster pelo `user_data` (`ECS_CLUSTER`). Drenagem: `managed_draining = "ENABLED"`. Substituição: `health_check_type = "EC2"`. Remoção: `managed_termination_protection = "ENABLED"` com `protect_from_scale_in`, de modo que só sai instância sem task. | `terraform/ecs_cluster.tf` (`aws_launch_template.ecs`, `aws_autoscaling_group.ecs`, `aws_ecs_capacity_provider.ec2`) |
| 4 | Dois níveis de elasticidade | Nível de tasks: Application Auto Scaling em cada serviço, de 2 a 4 tasks. Nível de instâncias: o Capacity Provider ajusta o ASG quando uma task não acha lugar. | `terraform/modules/ecs-service/main.tf` (`aws_appautoscaling_target.this`, `aws_appautoscaling_policy.cpu`); `terraform/ecs_services.tf` (`aws_appautoscaling_policy.worker_backlog`); `terraform/ecs_cluster.tf` |
| 5 | VPC própria em 2 ou mais AZs, com sub-redes públicas e privadas, rotas e security groups | VPC `10.20.0.0/16` em duas AZs, com seis sub-redes: públicas (ALB e NAT), de aplicação (instâncias e tasks) e de dados (RDS). A camada pública sai pelo Internet Gateway; a de aplicação, pelo NAT da própria zona; a de dados só tem a rota local. Nove security groups, um por papel, com regras que referenciam outros grupos. | `terraform/network.tf`; `terraform/security.tf`; `terraform/locals.tf` (`local.azs`) |
| 6 | Acesso externo pelo ALB; instâncias privadas | ALB público nas sub-redes públicas. Instâncias e tasks ficam nas sub-redes de aplicação, sem IP público (`assign_public_ip = false`, `map_public_ip_on_launch = false`). O security group das instâncias não tem regra de entrada. A API de pedidos só é alcançável de fora pelo listener `:8000`, restrito a `api_allowed_cidrs` (vazio por padrão). | `terraform/alb.tf`; `terraform/security.tf` (`aws_security_group.ecs_instances`, `aws_vpc_security_group_ingress_rule.alb_api`); `terraform/modules/ecs-service/main.tf` (`network_configuration`) |
| 7 | Health checks; o ECS substitui tasks e o ASG substitui instâncias | Três pontos. Contêiner: `healthCheck` nas quatro task definitions (HTTP em api, chat e frontend; arquivo de heartbeat no worker, que falha após 120 s sem toque). Target group: `/health` na API e `/healthz` no frontend. Instância: verificação EC2 do ASG. O ECS repõe a task que falha no health check ou é encerrada; o ASG repõe a instância não saudável. | `terraform/ecs_services.tf` (`local.python_health_check`, `local.worker_health_check`); `terraform/modules/ecs-service/main.tf` (`healthCheck`); `terraform/alb.tf` (`health_check`); `terraform/ecs_cluster.tf` (`health_check_type`); `backend/worker.py` (`HEARTBEAT_FILE`) |
| 8 | Dados essenciais em serviço persistente | Catálogo, pedidos, itens, estoque e outbox ficam no RDS PostgreSQL (Multi-AZ, criptografado, privado, backups de 7 dias). Conversas, sessões, seleção de compra e tentativas de confirmação do chat ficam num banco separado da mesma instância. Mensagens em trânsito ficam no SQS. Nenhuma task guarda dado em disco local; o heartbeat do worker em `/tmp` é só sinal de vida. | `terraform/database.tf` (`aws_db_instance.postgres`); `terraform/files/db_init.py`; `backend/models.py`; `chat-service/app/models.py`; `terraform/messaging.tf` |
| 9 | Dois ou mais serviços com responsabilidades e perfis de escala distintos, justificados | Quatro serviços. API: síncrona, escala por CPU (alvo `api_cpu_target`, 60%). Worker: assíncrono, sem porta, escala pelo backlog da fila (mensagens visíveis por task, alvo 5), porque a CPU dele não reflete a fila parada. Chat: espera a IA por até 120 s, escala por CPU (60%) e tem `stop_timeout` de 170 s para terminar respostas em andamento. Frontend: Nginx estático e proxy, escala por CPU (60%). Chat, frontend e API usam o mesmo tipo de política (CPU); o perfil realmente diferente é o do worker. | `terraform/ecs_services.tf`; `terraform/variables.tf` (`api_cpu_target`, `worker_backlog_target`) |
| 10 | Comunicação assíncrona com repetição, duplicidade, mensagens não processáveis e DLQ | Padrão outbox: a API grava pedido e evento na mesma transação; o worker publica no SQS e consome. Repetição: o worker só apaga a mensagem depois de processar; sem `delete_message` ela reaparece após 60 s (`visibility_timeout_seconds`). Duplicidade: chave de idempotência com hash do conteúdo na API e verificação de status no worker (pedido já confirmado é ignorado). Não processáveis: tipo inválido, ID inválido, pedido inexistente ou status inesperado geram erro e a mensagem não é apagada. DLQ: após 5 recebimentos (`maxReceiveCount`), com retenção de 14 dias e alarme. | `backend/pedidos.py` (`criar_pedido`); `backend/worker.py` (`publicar_pendentes`, `processar_mensagem`); `terraform/messaging.tf` (`aws_sqs_queue.orders`, `aws_sqs_queue.orders_dlq`); `terraform/observability.tf` (`aws_cloudwatch_metric_alarm.dlq_messages`) |
| 11 | Reservas e limites de CPU e memória coerentes, com explicação | Cada task: 256 CPU units e 512 MiB no nível da task (limite rígido) e `memoryReservation` de 384 MiB no contêiner (reserva). Os valores são variáveis, com validação de que a reserva não passa do limite. A conta e a justificativa estão na seção "Dimensionamento e posicionamento". | `terraform/variables.tf` (`task_cpu`, `task_memory`, `task_memory_reservation`); `terraform/modules/ecs-service/main.tf` (`aws_ecs_task_definition.this`, `local.container`) |
| 12 | Segredos no Secrets Manager | Quatro secrets de aplicação (`database-url`, `chat-database-url`, `orders-internal-token`, `gemini-api-key`) mais o do administrador do RDS, criado e girado pelo próprio RDS. Senhas e token são gerados por recursos efêmeros e gravados por argumentos write-only: não aparecem no plan, no state nem nos outputs. As task definitions guardam só o ARN (`secrets`/`valueFrom`). | `terraform/secrets.tf`; `terraform/database.tf` (`manage_master_user_password`); `terraform/ecs_services.tf` (blocos `secrets`); `terraform/variables.tf` (`gemini_api_key`, efêmera) |
| 13 | IAM Roles distintas, com menor privilégio | Dez papéis. Um para as instâncias (política gerenciada do agente ECS e SSM). Por serviço, uma execution role (política gerenciada de execução mais leitura apenas dos secrets daquele serviço; a do frontend não lê secret nenhum) e uma task role. Só a task role do worker tem permissões: quatro ações do SQS na fila de pedidos. A `db-init` tem execution role própria e é a única que lê a credencial de administrador do banco. As instâncias exigem IMDSv2 e têm `ECS_AWSVPC_BLOCK_IMDS=true`: uma task não alcança as credenciais do papel da instância. | `terraform/modules/ecs-service/main.tf` (`aws_iam_role.execution`, `aws_iam_role_policy.execution_secrets`, `aws_iam_role.task`); `terraform/ecs_services.tf` (`task_role_policy_json` do worker); `terraform/db_init.tf` (`aws_iam_role.db_init_execution`); `terraform/ecs_cluster.tf` (`aws_iam_role.ecs_instance`, `metadata_options`, `user_data`) |
| 14 | Logs no CloudWatch; métricas e alarmes para saúde das tasks, utilização do cluster, capacidade do ASG, respostas do load balancer, profundidade de filas e falhas da aplicação | Driver `awslogs` nas cinco task definitions, com log groups de retenção definida. 16 alarmes, todos com ação no tópico SNS ao disparar e ao normalizar: saúde das tasks (`*-tasks-low` x4, `*-targets-unhealthy` x2), utilização do cluster (`cluster-capacity-high`), capacidade do ASG (`asg-at-max`), respostas do balanceador (`*-target-5xx` x2, `alb-5xx`), filas (`orders-queue-age`, `dlq-messages`) e falhas da aplicação (`*-app-errors` x3, sobre métricas extraídas dos logs). Dashboard com 14 widgets, incluindo a métrica de negócio `PedidosConfirmados`, extraída do log do worker. Diagnóstico de cada alarme em [RUNBOOK.md](RUNBOOK.md). | `terraform/observability.tf`; `terraform/outputs.tf` (`alarm_names`); `terraform/modules/ecs-service/main.tf` (`logConfiguration`, `aws_cloudwatch_log_group.this`) |
| 15 | Disponível durante a troca de task; recupera após perda de instância | Mínimo de 2 tasks por serviço. Deploy com `deployment_minimum_healthy_percent = 100` e `deployment_maximum_percent = 200`: a task nova fica saudável antes de a antiga sair; o circuit breaker desfaz um deploy que não estabiliza. `deregistration_delay` de 30 s (API) e 160 s (frontend), e `stop_timeout` de 170 s no chat. `distinctInstance` e spread por AZ: as réplicas de um serviço ficam em instâncias e zonas diferentes, então perder uma instância tira no máximo uma réplica de cada um de dois serviços. A API responde 503 com `Retry-After` quando o banco está indisponível, e o worker encerra limpo no SIGTERM. Comportamento declarado no código e ainda não medido em `sa-east-1`; os testes estão no "Nível 4" de `terraform/README.md`. | `terraform/modules/ecs-service/main.tf` (`aws_ecs_service.this`); `terraform/alb.tf`; `terraform/ecs_services.tf` (`stop_timeout`); `backend/main.py` (`banco_indisponivel`); `backend/worker.py` (`solicitar_encerramento`) |
| 16 | Vendedor de IA com funções reais que consultam e registram | Ver "Requisito 16: o que a IA faz e o que ela não faz", abaixo. | `chat-service/app/ai.py` (`TOOLS`, `execute_tool`); `chat-service/app/purchases.py`; `chat-service/app/checkout.py`; `chat-service/app/gemini.py` |
| 17 | Terraform cobre tudo, organizado, parametrizado, com state remoto; criação e destruição reproduzíveis | Toda a infraestrutura está em `terraform/`, um arquivo por camada e um módulo reutilizado pelos quatro serviços. Parâmetros em `variables.tf`, todos com padrão. State num bucket S3 versionado, criptografado e com lock nativo, criado por `bootstrap/`. `./deploy.sh` cria o bucket, gera `backend.hcl` e aplica; `./destroy.sh` remove o ambiente e, em seguida, o bucket do state. O build das imagens e a task `db-init` são disparados pelo próprio apply (`local-exec`). Ficam fora do Terraform, por natureza: obter a chave do Gemini e confirmar o e-mail do SNS. | `terraform/*.tf`; `terraform/modules/ecs-service/`; `terraform/bootstrap/`; `terraform/versions.tf` (`backend "s3"`); `terraform/deploy.sh`; `terraform/destroy.sh`; `terraform/tests/` |
| 18 | Portabilidade regional, sem dependência de Ohio | Ver "Portabilidade regional", abaixo. | `terraform/variables.tf` (`region`, `environment`); `terraform/locals.tf`; `terraform/ecs_cluster.tf` (`data.aws_ssm_parameter.ecs_ami`) |

## Requisito 16: o que a IA faz e o que ela não faz

O chat envia ao Gemini (`gemini-3.8-flash` por padrão) seis funções, declaradas
em `TOOLS` e executadas em `execute_tool`, ambas em `chat-service/app/ai.py`:

| Função | Efeito real |
| --- | --- |
| `listar_produtos` | Lê catálogo, preços e estoque da API de pedidos (`GET /produtos`), que lê o PostgreSQL. |
| `consultar_pedido` | Lê o status de um pedido na API (`GET /pedidos/{id}`), restrito aos pedidos da sessão do navegador. |
| `listar_meus_pedidos` | Lista os pedidos das conversas da mesma sessão, com status atualizado pela API. |
| `preparar_compra` | Valida itens e estoque contra o catálogo real e grava a seleção (itens, total, cliente, local de entrega e uma chave de idempotência) na conversa. |
| `atualizar_entrega` | Grava nome e local de entrega na seleção. |
| `cancelar_selecao` | Apaga a seleção ainda não confirmada. |

As três primeiras consultam; as três últimas registram. A gravação é
persistente: a seleção é a coluna `compra` da tabela `chat_conversa`, no banco
do chat no RDS, e é confirmada na mesma transação da mensagem
(`send_message` em `chat-service/app/main.py`). Ela sobrevive à troca da task e
é o que o resumo de compra na tela mostra.

Não existe função de compra. O pedido (linha em `pedido`, itens, baixa de
estoque e evento de outbox) é criado pelo servidor em
`POST /chat/conversas/{id}/confirmar`, quando o cliente clica no botão
"Confirmar pedido" (`chat-service/app/checkout.py`, que chama `POST /pedidos` da
API com a chave de idempotência gravada pela ferramenta). Isso é uma escolha de
projeto, por segurança: um modelo de linguagem pode interpretar mal uma
mensagem, ser induzido por texto do próprio catálogo ou repetir uma chamada, e
uma compra não deve depender disso. As instruções do modelo dizem o mesmo
(`INSTRUCTIONS` em `ai.py`), mas a garantia não está nas instruções: está em a
lista de funções não conter nenhuma que crie pedido.

Leitura do enunciado. A exigência de que a IA use funções reais para consultar
e para registrar uma transação é atendida assim: a consulta é feita pelas três
funções de leitura, e o registro é a gravação persistente da seleção de compra
feita por `preparar_compra` e `atualizar_entrega`, que é o conteúdo exato do
pedido. A confirmação explícita no botão é a etapa final da mesma transação e
envia à API os dados que a ferramenta gravou, sem passar de novo pelo modelo.
Quem ler o enunciado como "a IA deve, sozinha, criar o pedido" não encontrará
isso aqui, e a diferença é deliberada.

O modo `ai_provider = "commands"` responde por comandos fixos, sem IA. Serve
para testes automáticos e como contingência (ver [RUNBOOK.md](RUNBOOK.md)); não
atende a este requisito e não deve ser usado na demonstração.

## Dimensionamento e posicionamento

### A conta

| Item | Valor | Origem |
| --- | --- | --- |
| Tipo de instância | t3.medium: 2 vCPU (2048 CPU units) e 4 GiB | `ecs_instance_type` |
| CPU por task | 256 CPU units (1/4 de vCPU) | `task_cpu` |
| Memória por task (limite) | 512 MiB | `task_memory` |
| Memória por contêiner (reserva) | 384 MiB | `task_memory_reservation` |
| Interfaces de rede por t3.medium | 3; uma é da instância, restam 2 para tasks | limite do tipo de instância |
| Tasks `awsvpc` por instância | 2 | consequência da linha acima |
| Serviços | 4, cada um de 2 a 4 tasks | `service_min_count`, `service_max_count` |

Limite e reserva de memória. O valor de 512 MiB no nível da task é o teto: o
contêiner que passar disso é encerrado. Os 384 MiB de `memoryReservation` são a
reserva do contêiner. A diferença de 128 MiB é margem para picos (uma resposta
longa da IA, um lote de mensagens) sem que o processo morra. Os processos são
Python com FastAPI ou um laço de consumo, e Nginx; nenhum mantém cache grande
em memória. Esses valores não foram calibrados por medição em `sa-east-1`: são
os do ambiente manual, mantidos.

Ocupação por instância. Com 2 tasks, uma instância usa 512 de 2048 CPU units
(25%) e 1024 MiB dos cerca de 4 GiB (por volta de 25%; o agente ECS registra um
pouco menos que o nominal). O que enche a instância são as interfaces de rede.

Quantidade de instâncias:

| Situação | Tasks | Instâncias | vCPU |
| --- | --- | --- | --- |
| Repouso (4 serviços x 2 tasks) | 8 | 4 | 8 |
| Pico (4 serviços x 4 tasks) | 16 | 8 | 16 |
| Máximo do ASG (`ecs_asg_max_size`) | até 20 vagas | 10 | 20 |

Por que 10 e não 8. O deploy é rolling com 200%: a task nova sobe antes de a
antiga sair, e precisa de uma vaga numa instância que não tenha outra task do
mesmo serviço. Com a frota no pico, as 8 instâncias estão cheias. As 2
instâncias a mais dão 4 vagas, no máximo 2 para o mesmo serviço
(`distinctInstance`), e o deployment avança em lotes conforme as tasks antigas
saem. Com máximo 8, um deploy no pico ficaria parado até a carga cair.

Cota de vCPU. A conta precisa de 8 vCPU On-Demand em repouso e de 20 para o
máximo, na cota "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z)
instances" (código `L-1216C47A`). `terraform/deploy.sh` consulta a cota antes
de aplicar: abaixo de 8 ele interrompe; entre 8 e 19 ele avisa que o scale-out
completo não cabe.

### Posicionamento

Definido em `aws_ecs_service.this`, em `terraform/modules/ecs-service/main.tf`:

- `distinctInstance`: duas réplicas do mesmo serviço nunca dividem a mesma
  instância. Perder uma instância tira no máximo uma réplica de cada serviço.
- `spread` por `attribute:ecs.availability-zone`: as réplicas se distribuem
  pelas duas zonas.
- `binpack` por memória, como segundo critério: dentro da zona, preenche as
  instâncias já em uso antes de pedir outra.

Em repouso, o resultado esperado são 4 instâncias, 2 por zona, cada uma com
tasks de dois serviços diferentes.

### Limites conhecidos do desenho

- **O gargalo é a interface de rede, não CPU nem memória.** Cada instância
  roda com cerca de 25% de CPU e de memória reservadas e não aceita uma
  terceira task. A família t3 não aceita ENI trunking, que elevaria esse
  limite. Paga-se por capacidade que não pode ser usada. As alternativas são
  um tipo de instância com trunking (por exemplo das famílias m5 ou c5) ou o
  modo de rede `bridge`, que dispensa uma interface por task mas perde o
  security group por task em que `security.tf` se apoia. Nenhuma foi adotada.
- **Depois de um pico ou de um deploy, a frota tende a não encolher sozinha.**
  O Capacity Provider só remove instância sem nenhuma task (proteção de
  scale-in), e o ECS não reconsolida tasks em execução. Quando os serviços
  voltam a 2 tasks, as que sobram podem estar espalhadas, uma por instância, e
  o ASG fica acima de 4. A correção é manual e está em
  [RUNBOOK.md](RUNBOOK.md), em "asg-at-max".
- **Deploy em repouso também pede instância extra.** Com as 4 instâncias
  cheias, qualquer rolling deployment faz o ASG subir temporariamente, e o
  primeiro lote espera o lançamento e o registro da instância nova (minutos).
- **Deploy de vários serviços ao mesmo tempo, no pico, avança devagar**: são 4
  vagas de folga para até 16 tasks a trocar.
- **Reservas e limites não foram medidos em `sa-east-1`.** O ambiente ainda não
  foi aplicado nessa região.

## Portabilidade regional

O ambiente manual ficava em Ohio (`us-east-2`). O Terraform não lê, importa nem
referencia nada de lá. O que depende de região é resolvido na região de
destino:

| Item | Como é resolvido | Onde está |
| --- | --- | --- |
| Região | `var.region`, padrão `sa-east-1`, usada pelo provider | `terraform/variables.tf`; `terraform/versions.tf` |
| Zonas de disponibilidade | data source `aws_availability_zones`; as duas primeiras disponíveis | `terraform/locals.tf` (`local.azs`) |
| AMI das instâncias | parâmetro público do SSM `/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id`, que tem um valor por região | `terraform/ecs_cluster.tf` (`data.aws_ssm_parameter.ecs_ami`) |
| Endpoints de VPC | `com.amazonaws.${var.region}.s3` e `.sqs` | `terraform/network.tf` |
| Região dos logs | `awslogs-region = var.region` nas task definitions; `region` nos widgets do dashboard | `terraform/modules/ecs-service/main.tf`; `terraform/db_init.tf`; `terraform/observability.tf` |
| Região do SQS no worker | variável `AWS_REGION` da task, vinda de `var.region`; o código não fixa região | `terraform/ecs_services.tf`; `backend/worker.py` |
| Imagens | repositórios ECR criados na região de destino; build local e push para o registro regional | `terraform/ecr.tf`; `terraform/scripts/build-push.sh` |
| State | bucket com conta e região no nome, criado por `bootstrap/` | `terraform/bootstrap/main.tf` |
| Certificado HTTPS (opcional) | ARN informado por variável; precisa ser da mesma região | `terraform/variables.tf` (`acm_certificate_arn`) |

Nenhum ARN, ID de conta, ID de recurso ou nome de zona de Ohio aparece nos
arquivos `.tf`, nos scripts de `terraform/` ou no código dos serviços. As
menções a Ohio que restam são comentários e descrições de variáveis. Os ARNs de
políticas gerenciadas (`arn:aws:iam::aws:policy/...`) são globais.

O sufixo `var.environment` (`sp`) entra em todos os nomes. Papéis IAM são
globais na conta: é o sufixo que evita colisão com os recursos manuais de Ohio
e que permite um segundo ambiente na mesma conta.

Para subir em outra região, num clone limpo do repositório (o state local de
`bootstrap/` aponta para o bucket da região anterior):

```bash
TF_VAR_region=us-east-1 TF_VAR_environment=dr ./deploy.sh
```

Esse comando nunca foi executado. Os dados não acompanham: backups do RDS,
imagens e state ficam na região de origem.
