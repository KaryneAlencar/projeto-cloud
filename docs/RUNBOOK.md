# Runbook: alarmes e procedimentos de operação

O que cada alarme do CloudWatch significa, como diagnosticar e como encerrar.
Os alarmes são criados em `terraform/observability.tf` e listados no output
`alarm_names`. Todos notificam o tópico SNS `insper-eats-sp-alertas` ao disparar
e ao voltar a OK.

**Situação.** O ambiente ainda não foi aplicado em `sa-east-1`. Os comandos
abaixo foram escritos a partir do código e dos nomes que o Terraform declara;
nenhum foi executado contra esse ambiente. Revise na primeira ocorrência real.

## Preparação

AWS CLI v2, com credenciais da conta do ambiente. Os nomes são os padrões
(`project = "insper-eats"`, `environment = "sp"`); se mudou as variáveis, troque
o prefixo.

```bash
export AWS_PROFILE=insper-eats AWS_REGION=sa-east-1
P=insper-eats-sp
CLUSTER=$P-cluster
ASG=$P-ecs-asg

servicos() { aws ecs describe-services --cluster "$CLUSTER" \
  --services $P-api-service $P-worker-service $P-chat-service $P-frontend-service \
  --query 'services[].[serviceName,desiredCount,runningCount,pendingCount]' --output table; }

eventos() { aws ecs describe-services --cluster "$CLUSTER" --services "$P-$1-service" \
  --query 'services[0].events[:10].[createdAt,message]' --output text; }

paradas() {   # motivo das últimas tasks encerradas de um serviço
  local tasks
  tasks=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$P-$1-service" \
    --desired-status STOPPED --query 'taskArns' --output text)
  [ -n "$tasks" ] && [ "$tasks" != "None" ] || { echo "nenhuma task encerrada recente"; return; }
  aws ecs describe-tasks --cluster "$CLUSTER" --tasks $tasks \
    --query 'tasks[].[stoppedAt,stopCode,stoppedReason,containers[0].exitCode,containers[0].reason]' \
    --output text
}

instancias() { aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].Instances[].[InstanceId,AvailabilityZone,LifecycleState,HealthStatus]' \
  --output table; }

# CloudWatch Logs Insights pela CLI: insights '<consulta>' <grupo> [<grupo>...]
# Janela: última hora (date -d é do GNU date; no macOS use date -v-1H +%s).
insights() {
  local consulta="$1" id; shift
  id=$(aws logs start-query --log-group-names "$@" \
    --start-time "$(date -d '1 hour ago' +%s)" --end-time "$(date +%s)" \
    --query-string "$consulta" --query queryId --output text)
  sleep 5
  aws logs get-query-results --query-id "$id" \
    --query "results[*][?field!='@ptr'].value" --output text
}
```

`servicos`, `eventos api`, `paradas worker` e `instancias` são usados em quase
todas as seções. Se `insights` voltar vazio, a consulta pode não ter terminado:
repita `aws logs get-query-results --query-id <id>` e confira o campo `status`.

Grupos de log: `/ecs/insper-eats-sp/api`, `/worker`, `/chat`, `/frontend` e
`/db-init`. Para acompanhar ao vivo:

```bash
aws logs tail /ecs/$P/worker --since 15m --follow
```

Formato dos logs, que define como filtrar:

| Serviço | Formato | Linha de erro |
| --- | --- | --- |
| api | texto (`logging.basicConfig` e Uvicorn) | `ERROR:` no início; traceback nas linhas seguintes |
| worker | texto (`logging.basicConfig`) | `ERROR:insper-eats-worker:Falha ...` |
| chat | JSON com `timestamp`, `level`, `logger`, `request_id`, `message`; o Uvicorn do chat loga texto | `level` `ERROR`/`CRITICAL`, ou `message` contendo `dependency_failure` (registrado como WARNING) |
| frontend | log de acesso e de erro do Nginx | linhas `[error]` |

## Primeiro passo, para qualquer alarme

```bash
aws cloudwatch describe-alarms --alarm-name-prefix "$P-" --state-value ALARM \
  --query 'MetricAlarms[].[AlarmName,StateUpdatedTimestamp,StateReason]' --output table
servicos
instancias
```

Vários alarmes juntos costumam ter uma causa só. Combinações comuns:

| Alarmes simultâneos | Causa provável |
| --- | --- |
| `*-tasks-low` de dois serviços e `*-targets-unhealthy` | perda de uma instância EC2 (cada uma hospeda 2 tasks, de serviços diferentes) |
| `orders-queue-age` e, logo depois, `dlq-messages` | mensagem que o worker não consegue processar: 5 tentativas de 60 s levam cerca de 5 minutos |
| `chat-app-errors` e `frontend-target-5xx` | dependência do chat fora: Gemini ou API de pedidos |
| `worker-app-errors`, `chat-app-errors` e `frontend-target-5xx` | banco indisponível ou em failover |
| `cluster-capacity-high` e `asg-at-max` | frota no teto com tasks sem lugar |

Histórico de um alarme:

```bash
aws cloudwatch describe-alarm-history --alarm-name $P-dlq-messages \
  --history-item-type StateUpdate --max-items 10 \
  --query 'AlarmHistoryItems[].[Timestamp,HistorySummary]' --output text
```

## Índice dos 16 alarmes

| Alarme | Seção |
| --- | --- |
| `insper-eats-sp-api-targets-unhealthy` | [targets-unhealthy](#targets-unhealthy) |
| `insper-eats-sp-frontend-targets-unhealthy` | [targets-unhealthy](#targets-unhealthy) |
| `insper-eats-sp-api-tasks-low` | [tasks-low](#tasks-low) |
| `insper-eats-sp-worker-tasks-low` | [tasks-low](#tasks-low) |
| `insper-eats-sp-chat-tasks-low` | [tasks-low](#tasks-low) |
| `insper-eats-sp-frontend-tasks-low` | [tasks-low](#tasks-low) |
| `insper-eats-sp-dlq-messages` | [dlq-messages](#dlq-messages) |
| `insper-eats-sp-cluster-capacity-high` | [cluster-capacity-high](#cluster-capacity-high) |
| `insper-eats-sp-asg-at-max` | [asg-at-max](#asg-at-max) |
| `insper-eats-sp-api-target-5xx` | [target-5xx](#target-5xx) |
| `insper-eats-sp-frontend-target-5xx` | [target-5xx](#target-5xx) |
| `insper-eats-sp-alb-5xx` | [alb-5xx](#alb-5xx) |
| `insper-eats-sp-orders-queue-age` | [orders-queue-age](#orders-queue-age) |
| `insper-eats-sp-api-app-errors` | [app-errors](#app-errors) |
| `insper-eats-sp-worker-app-errors` | [app-errors](#app-errors) |
| `insper-eats-sp-chat-app-errors` | [app-errors](#app-errors) |

## targets-unhealthy

`insper-eats-sp-api-targets-unhealthy` e `insper-eats-sp-frontend-targets-unhealthy`.

**O que significa.** O target group do ALB teve menos de 2 targets saudáveis
(`HealthyHostCount` mínimo abaixo de `service_min_count`) em 2 de 3 minutos.
Ausência de dado conta como violação. Com 1 target o serviço ainda atende, sem
redundância; com 0, o ALB responde 503 e `alb-5xx` dispara junto. O health
check é `GET /health` na API e `GET /healthz` no frontend, a cada 15 s, com 3
falhas para marcar como não saudável.

**Como diagnosticar.**

```bash
TG=$(aws elbv2 describe-target-groups --names $P-api-tg \
  --query 'TargetGroups[0].TargetGroupArn' --output text)     # ou $P-frontend-tg
aws elbv2 describe-target-health --target-group-arn "$TG" \
  --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State,TargetHealth.Reason,TargetHealth.Description]' \
  --output table
eventos api          # ou: eventos frontend
paradas api
```

- `Target.Timeout` ou `Target.FailedHealthChecks`: a task está no ar e não
  responde. Veja o log do serviço (`aws logs tail /ecs/$P/api --since 15m`).
  O `/health` da API não consulta o banco; se ele falha, o processo travou ou
  não subiu.
- Menos de 2 targets registrados: o problema é de tasks; siga em
  [tasks-low](#tasks-low).
- `draining` durante um deploy é normal (30 s na API, 160 s no frontend).
- Frontend não saudável logo depois de um deploy do chat: o `/healthz` do Nginx
  não depende do chat, então a causa está no próprio frontend.

**Como encerrar.** O alarme volta a OK quando há 2 targets saudáveis por 2
minutos. O ECS repõe sozinho a task reprovada no health check. Se as tasks
novas também falham, o circuit breaker desfaz o deployment; corrija o código ou
a configuração e aplique de novo. Para forçar a troca das tasks de um serviço:

```bash
aws ecs update-service --cluster "$CLUSTER" --service $P-api-service --force-new-deployment \
  --query 'service.deployments[0].rolloutState' --output text
aws ecs wait services-stable --cluster "$CLUSTER" --services $P-api-service
```

## tasks-low

`insper-eats-sp-api-tasks-low`, `-worker-tasks-low`, `-chat-tasks-low` e
`-frontend-tasks-low`.

**O que significa.** O serviço teve menos de 2 tasks em execução
(`RunningTaskCount` do Container Insights, média abaixo de `service_min_count`)
em 2 de 3 minutos. Ausência de dado conta como violação: o alarme também
dispara se o Container Insights parar de publicar.

**Como diagnosticar.**

```bash
servicos
eventos worker       # mensagens do agendador: falta de capacidade, health check, deploy
paradas worker       # stopCode e motivo das tasks encerradas
```

Leitura do motivo:

| O que aparece | Causa | Ação |
| --- | --- | --- |
| `Task failed container health checks` | health check do contêiner reprovado | ver o log do serviço. No worker, é o laço principal parado há mais de 120 s (arquivo `/tmp/worker-heartbeat` sem toque) |
| `OutOfMemoryError` ou código de saída 137 | passou dos 512 MiB da task | aumentar `task_memory` e aplicar; investigar o consumo |
| `ResourceInitializationError` com Secrets Manager | secret ausente, sem permissão ou sem rota de saída | conferir o secret e o NAT da zona |
| `CannotPullContainerError` | imagem ausente no ECR ou sem rota | conferir a tag em `terraform output image_tags` e o repositório |
| evento `unable to place a task` | sem instância com vaga | ver [cluster-capacity-high](#cluster-capacity-high) |
| várias tasks de serviços diferentes paradas no mesmo minuto | instância perdida | `instancias`; o ASG repõe sozinho |
| código de saída 1 logo na partida | erro de configuração (variável ou secret inválido) | log do serviço, primeiras linhas |

Para ver se a instância por baixo está saudável e quantas tasks cada uma tem:

```bash
aws ecs describe-container-instances --cluster "$CLUSTER" \
  --container-instances $(aws ecs list-container-instances --cluster "$CLUSTER" \
      --query 'containerInstanceArns' --output text) \
  --query 'containerInstances[].[ec2InstanceId,status,runningTasksCount,pendingTasksCount,agentConnected]' \
  --output table
```

**Como encerrar.** Volta a OK quando o serviço tem 2 tasks por 2 minutos. O ECS
repõe as tasks sozinho; a ação manual só é necessária quando a reposição falha
(tabela acima). Se a causa for uma instância com o agente desconectado
(`agentConnected` falso), substitua-a: ver
[Substituição manual de instância](#substituição-manual-de-instância).

## dlq-messages

`insper-eats-sp-dlq-messages`.

**O que significa.** Há pelo menos uma mensagem na fila
`insper-eats-sp-orders-dlq`. O worker recebeu essa mensagem 5 vezes sem
conseguir processá-la (`maxReceiveCount` em `terraform/messaging.tf`). O pedido
correspondente, se existir, continua com status `recebido`. A DLQ guarda a
mensagem por 14 dias.

**Como diagnosticar.**

```bash
FILA=$(aws sqs get-queue-url --queue-name $P-orders --query QueueUrl --output text)
DLQ=$(aws sqs get-queue-url --queue-name $P-orders-dlq --query QueueUrl --output text)

aws sqs get-queue-attributes --queue-url "$DLQ" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible

# Lê sem apagar. As mensagens ficam invisíveis por 30 s e voltam à DLQ.
aws sqs receive-message --queue-url "$DLQ" --max-number-of-messages 10 \
  --visibility-timeout 30 --attribute-names All \
  --query 'Messages[].[MessageId,Body,Attributes.ApproximateReceiveCount,Attributes.SentTimestamp]' \
  --output text
```

O corpo esperado é `{"tipo": "pedido.criado", "pedido_id": N, "evento_id": M}`.
O motivo da recusa está no log do worker, no traceback que segue cada
`Falha ao processar mensagem`:

```bash
insights 'fields @timestamp, @message
| filter @message like /Falha ao processar mensagem|ValueError|Error/
| sort @timestamp desc
| limit 50' /ecs/$P/worker
```

| Motivo no log (`backend/worker.py`) | Natureza | O que fazer |
| --- | --- | --- |
| `Tipo de evento inválido`, `ID de pedido inválido` | mensagem malformada (não veio da outbox) | apagar; reenviar não resolve |
| `Pedido não encontrado` | o pedido não existe nesse banco | apagar, depois de entender a origem |
| `Status inesperado` | o pedido não está em `recebido` nem `confirmado` | corrigir o dado antes de reenviar |
| erro de conexão ou de banco (`OperationalError`) | falha transitória que durou mais de 5 tentativas | reenviar depois que o banco voltar |

**Como encerrar.** O alarme volta a OK quando a DLQ fica vazia.

Reenvio (redrive) para a fila de origem, depois de corrigir a causa. Sem
`--destination-arn`, as mensagens voltam para a fila de onde vieram:

```bash
DLQ_ARN=$(aws sqs get-queue-attributes --queue-url "$DLQ" --attribute-names QueueArn \
  --query Attributes.QueueArn --output text)
aws sqs start-message-move-task --source-arn "$DLQ_ARN"
aws sqs list-message-move-tasks --source-arn "$DLQ_ARN" \
  --query 'Results[].[Status,ApproximateNumberOfMessagesMoved,ApproximateNumberOfMessagesToMove,FailureReason]' \
  --output text
```

O reenvio é seguro quanto a duplicidade: o worker ignora o pedido que já está
`confirmado`. Uma mensagem que continua inválida volta à DLQ em cerca de 5
minutos e o alarme dispara de novo.

Descarte de uma mensagem que não deve ser reprocessada (use o `ReceiptHandle`
de um `receive-message` recente):

```bash
RH=$(aws sqs receive-message --queue-url "$DLQ" --query 'Messages[0].ReceiptHandle' --output text)
aws sqs delete-message --queue-url "$DLQ" --receipt-handle "$RH"
```

`aws sqs purge-queue --queue-url "$DLQ"` apaga tudo de uma vez. Só use depois
de ler as mensagens: cada uma pode ser um pedido sem confirmação.

## cluster-capacity-high

`insper-eats-sp-cluster-capacity-high`.

**O que significa.** A métrica `CapacityProviderReservation` ficou acima de
100% por 10 minutos seguidos: as tasks pedem mais instâncias do que o Auto
Scaling Group tem. Alguns minutos acima de 100% são normais num scale-out (a
instância leva o warm-up de 300 s para contar); 10 minutos indicam que a
instância não chega ou não entra no cluster. Há tasks em `PENDING`.

**Como diagnosticar.**

```bash
servicos                                   # coluna pendingCount
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names "$ASG" \
  --query 'AutoScalingGroups[0].[MinSize,DesiredCapacity,MaxSize,length(Instances)]' --output text
aws autoscaling describe-scaling-activities --auto-scaling-group-name "$ASG" --max-items 10 \
  --query 'Activities[].[StartTime,StatusCode,Description,StatusMessage]' --output text
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A \
  --query 'Quota.Value' --output text      # vCPU On-Demand: 8 em repouso, 20 no máximo
```

- Atividade com `Failed` e mensagem de `VcpuLimitExceeded`: a cota de vCPU
  acabou. Peça aumento em Service Quotas.
- `InsufficientInstanceCapacity`: a zona não tem t3.medium no momento. O ASG
  tenta de novo; se persistir, troque `ecs_instance_type`.
- Desejado igual ao máximo: a frota está no teto; ver [asg-at-max](#asg-at-max).
- Instâncias `InService` no ASG que não aparecem no cluster: o agente ECS não
  registrou. Confira a saída pelo NAT da zona e o log da instância
  (`aws ssm start-session --target <id>`, que exige o plugin do Session
  Manager, e depois `sudo journalctl -u ecs`).

Lembre do limite de interfaces de rede: uma t3.medium aceita 2 tasks, e duas
réplicas do mesmo serviço não dividem instância. Uma instância com CPU e
memória livres pode estar cheia.

**Como encerrar.** Volta a OK quando a reserva fica em 100% ou menos, isto é,
quando todas as tasks têm lugar. Resolva a causa (cota, capacidade da zona,
teto do ASG) e confirme com `servicos` que `pendingCount` zerou.

## asg-at-max

`insper-eats-sp-asg-at-max`.

**O que significa.** O Auto Scaling Group está com `ecs_asg_max_size`
instâncias em serviço (10, por padrão) há 3 minutos. O Capacity Provider não
consegue mais escalar: a próxima task sem lugar fica em `PENDING`. Por si só
não há indisponibilidade. O teto de 10 corresponde a 8 instâncias para os
quatro serviços em 4 tasks, mais 2 de folga para um deploy.

**Como diagnosticar.**

```bash
servicos
instancias
aws ecs describe-container-instances --cluster "$CLUSTER" \
  --container-instances $(aws ecs list-container-instances --cluster "$CLUSTER" \
      --query 'containerInstanceArns' --output text) \
  --query 'containerInstances[].[ec2InstanceId,runningTasksCount,pendingTasksCount]' --output table
```

Três situações:

1. **Carga real**: os serviços estão em 4 tasks e há um deploy em andamento. É
   o uso previsto da folga. Acompanhe e confirme que a frota encolhe depois.
2. **Frota espalhada depois de um pico**: os serviços já voltaram a 2 ou 3
   tasks, mas há instâncias com 1 task só. É um limite conhecido do desenho: o
   Capacity Provider só remove instância vazia e o ECS não reconsolida tasks
   em execução.
3. **Demanda acima do previsto**: serviços no máximo, sem deploy, e
   `cluster-capacity-high` também disparado.

**Como encerrar.** Volta a OK quando há menos instâncias em serviço que o
máximo.

Situação 2, consolidação manual. Drene uma instância que tenha 1 task; o ECS
sobe a substituta em outra instância com vaga e, vazia, a instância drenada é
removida pelo Capacity Provider. Repita, uma por vez, esperando o serviço
estabilizar:

```bash
INSTANCIA=i-0123456789abcdef0
CI=$(aws ecs list-container-instances --cluster "$CLUSTER" \
  --filter "ec2InstanceId == $INSTANCIA" --query 'containerInstanceArns[0]' --output text)
aws ecs update-container-instances-state --cluster "$CLUSTER" \
  --container-instances "$CI" --status DRAINING \
  --query 'containerInstances[0].status' --output text
servicos            # espere running == desired antes da próxima
```

Se a substituta não achar vaga (todas as outras instâncias cheias ou já com
uma task do mesmo serviço), o ECS pede uma instância nova e nada se ganha:
devolva a instância com `--status ACTIVE`.

Situação 3: aumente `ecs_asg_max_size` (confira antes a cota de vCPU, 2 por
instância) e aplique, ou reduza a demanda. Aumentar `service_max_count` sem
aumentar o teto do ASG piora o quadro.

## target-5xx

`insper-eats-sp-api-target-5xx` e `insper-eats-sp-frontend-target-5xx`.

**O que significa.** Os targets devolveram 5 ou mais respostas 5xx por minuto
ao ALB, em 2 de 3 minutos (`HTTPCode_Target_5XX_Count`). A aplicação respondeu,
com erro.

Atenção ao que cada um mede:

- `frontend-target-5xx` cobre todo o tráfego de clientes, inclusive
  `/api/*`, que o Nginx encaminha ao chat. Um 502, 503 ou 504 do chat (ou do
  Nginx, quando o chat não responde) aparece aqui.
- `api-target-5xx` cobre só o que entra pelo listener `:8000` do ALB (testes e
  administração). O chat chama a API pelo endereço interno do Cloud Map, sem
  passar pelo ALB: falhas da API no fluxo de compra aparecem como
  `orders_dependency_failure` no log do chat e em `chat-app-errors`.

**Como diagnosticar.**

```bash
# Frontend: quais caminhos estão devolvendo 5xx (log de acesso do Nginx).
insights 'fields @timestamp, @message
| filter @message like /" 5\d\d /
| sort @timestamp desc
| limit 50' /ecs/$P/frontend

# Chat: respostas 5xx e a falha de dependência que as causou.
insights 'fields @timestamp, request_id, level, message
| filter message like /status=5\d\d/ or message like /dependency_failure/
| sort @timestamp desc
| limit 50' /ecs/$P/chat

# API: erros e tracebacks.
aws logs tail /ecs/$P/api --since 15m --filter-pattern '?"ERROR:" ?"CRITICAL:" ?Traceback'
```

Causas mais prováveis:

| Sintoma | Causa | Seção |
| --- | --- | --- |
| chat com `ai_dependency_failure` | Gemini indisponível, sem cota ou com chave/modelo inválido | [Gemini indisponível](#gemini-indisponível) |
| chat com `orders_dependency_failure status=503` | API fora ou sem resposta em 5 s | `eventos api`, `paradas api` |
| API respondendo 503 com `Retry-After` | banco indisponível ou pool esgotado | [Banco indisponível](#banco-indisponível) |
| `/pedidos` respondendo 503 "Autenticacao interna nao configurada" | API sem `ORDERS_INTERNAL_TOKEN` | conferir o secret `insper-eats-sp/orders-internal-token` e a task definition |
| 504 depois de 150 s em `/api/*` | chat não respondeu no prazo do Nginx | log do chat no mesmo `request_id` |

**Como encerrar.** Volta a OK quando a contagem fica abaixo de 5 por minuto.
Sem requisições não há dado, e isso não conta como falha. Se a causa foi um
deploy, o circuit breaker já deve ter voltado à versão anterior; confirme com
`eventos chat`.

## alb-5xx

`insper-eats-sp-alb-5xx`.

**O que significa.** O próprio ALB gerou 5 ou mais respostas 5xx por minuto, em
2 de 3 minutos (`HTTPCode_ELB_5XX_Count`). Nesses casos a métrica dos targets
fica em zero, porque a requisição não chegou a uma task ou não voltou dela:
503 sem target saudável, 502 com conexão recusada ou encerrada pelo target, 504
com target sem resposta dentro do `idle_timeout` de 180 s.

**Como diagnosticar.**

```bash
for tg in api frontend; do
  aws elbv2 describe-target-health --target-group-arn "$(aws elbv2 describe-target-groups \
      --names $P-$tg-tg --query 'TargetGroups[0].TargetGroupArn' --output text)" \
    --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State,TargetHealth.Reason]' --output text
done
servicos
eventos frontend
```

- Nenhum target `healthy`: é indisponibilidade total do serviço. Siga
  [targets-unhealthy](#targets-unhealthy) e [tasks-low](#tasks-low).
- Targets saudáveis e 502 esporádicos durante um deploy: task encerrada com
  conexão aberta. O frontend tem `deregistration_delay` de 160 s e o Nginx
  mantém o keep-alive por 190 s (mais que o ALB) para evitar isso; se
  acontecer, anote o horário e compare com `eventos frontend`.
- 504: uma resposta passou de 180 s. O chat limita a IA a 120 s e o Nginx
  espera 150 s, então o 504 do ALB indica um target travado, não uma resposta
  lenta comum.

O ALB não grava log de acesso (não está configurado em `terraform/alb.tf`); o
diagnóstico usa as métricas e os logs dos serviços.

**Como encerrar.** Volta a OK quando o ALB para de gerar erros próprios.
Normalmente isso acompanha a volta de `*-targets-unhealthy` a OK.

## orders-queue-age

`insper-eats-sp-orders-queue-age`.

**O que significa.** A mensagem mais antiga da fila `insper-eats-sp-orders`
espera há mais de 300 s (`ApproximateAgeOfOldestMessage`), em 2 de 3 minutos.
O worker não está dando conta ou parou de consumir. Os pedidos correspondentes
ficam em `recebido` na tela do cliente. Nada se perde: a fila retém as
mensagens por 4 dias.

**Como diagnosticar.**

```bash
FILA=$(aws sqs get-queue-url --queue-name $P-orders --query QueueUrl --output text)
aws sqs get-queue-attributes --queue-url "$FILA" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible
servicos                                   # worker: desired e running
aws logs tail /ecs/$P/worker --since 15m
```

| O que se vê | Causa | Ação |
| --- | --- | --- |
| poucas mensagens, sempre as mesmas, e `Falha ao processar mensagem` no log | mensagem não processável a caminho da DLQ | esperar; em cerca de 5 minutos ela vai para a DLQ e a idade volta ao normal. Tratar em [dlq-messages](#dlq-messages) |
| `Falha no Worker` repetido a cada 5 s | banco ou SQS inacessível para o worker | [Banco indisponível](#banco-indisponível); para o SQS, conferir o endpoint de VPC e o security group `-vpce-sg` |
| muitas mensagens visíveis e worker em 4 tasks | backlog maior que a capacidade | aguardar o escoamento; se for recorrente, aumentar `service_max_count` e `ecs_asg_max_size` |
| muitas mensagens e worker em 2 tasks | a política de backlog não escalou | conferir a política abaixo e [cluster-capacity-high](#cluster-capacity-high) |
| worker com 0 tasks em execução | tasks caindo | [tasks-low](#tasks-low) |
| log parado, tasks "em execução" | laço travado; o health check derruba a task após 120 s sem heartbeat | conferir `paradas worker` |

Política de escala do worker e últimas ações:

```bash
aws application-autoscaling describe-scaling-activities --service-namespace ecs \
  --resource-id service/$CLUSTER/$P-worker-service --max-items 5 \
  --query 'ScalingActivities[].[StartTime,StatusCode,Description]' --output text
```

Caso diferente, que este alarme não cobre: pedidos presos em `recebido` com a
fila vazia. O evento ainda está na outbox, sem publicar. Indício: a API registra
`pedido_criado` e o worker não registra `Evento N enviado ao SQS`.

```bash
insights 'filter @message like /pedido_criado|enviado ao SQS|confirmado/
| stats count() by bin(5m), @log' /ecs/$P/api /ecs/$P/worker
```

**Como encerrar.** Volta a OK quando a mensagem mais antiga tem menos de 300 s,
isto é, quando a fila escoa.

## app-errors

`insper-eats-sp-api-app-errors`, `-worker-app-errors` e `-chat-app-errors`.

**O que significa.** 5 ou mais linhas de erro no log do serviço em 5 minutos.
As métricas (`ErrosApi`, `ErrosWorker`, `ErrosChat`, namespace
`InsperEats/insper-eats-sp`) vêm de filtros de log:

| Alarme | O que conta |
| --- | --- |
| `api-app-errors` | linhas com `ERROR:` ou `CRITICAL:`: exceções não tratadas (resposta 500). O 503 de banco indisponível é tratado e não conta aqui |
| `worker-app-errors` | linhas com `ERROR:` ou `CRITICAL:`: `Falha ao processar mensagem` e `Falha no Worker` |
| `chat-app-errors` | `level` `ERROR`/`CRITICAL`, mensagens com `dependency_failure` (WARNING) e erros do Uvicorn do chat |

**Como diagnosticar.**

```bash
# API e worker (texto): erros agrupados por mensagem.
insights 'filter @message like /^(ERROR|CRITICAL):/
| stats count() as n by @message
| sort n desc
| limit 20' /ecs/$P/api

insights 'filter @message like /^(ERROR|CRITICAL):/
| stats count() as n by @message
| sort n desc
| limit 20' /ecs/$P/worker

# Chat (JSON): o que falhou, por tipo.
insights 'fields @timestamp, request_id, level, message
| filter level in ["ERROR", "CRITICAL"] or message like /dependency_failure/
| sort @timestamp desc
| limit 50' /ecs/$P/chat

# Chat: falhas da IA por código.
insights 'filter message like /ai_dependency_failure/
| parse message "code=* reason=*" as code, reason
| stats count() as n by code
| sort n desc' /ecs/$P/chat
```

O traceback de um erro da API ou do worker vem nas linhas seguintes do mesmo
stream:

```bash
aws logs tail /ecs/$P/api --since 15m --filter-pattern '?"ERROR:" ?Traceback ?Error'
```

Por serviço:

- **api**: exceção não tratada é defeito de código ou dado inesperado. Leia o
  traceback; se começou depois de um deploy, a correção é reverter.
- **worker**: `Falha ao processar mensagem` aponta para uma mensagem específica
  (ver [dlq-messages](#dlq-messages)); `Falha no Worker` a cada 5 s aponta para
  banco ou SQS fora.
- **chat**: `ai_dependency_failure` leva a
  [Gemini indisponível](#gemini-indisponível); `orders_dependency_failure`
  leva à API de pedidos (`eventos api`, log da API no mesmo horário).

**Como encerrar.** Volta a OK no primeiro período de 5 minutos com menos de 5
erros. Sem linhas de erro a métrica vale 0. Para reverter um deploy com
defeito, restaure o código anterior e aplique de novo: a tag da imagem é o hash
dos arquivos, então o código antigo volta a usar a imagem antiga, que ainda
está no ECR (o repositório mantém as 10 mais recentes).

## Seguir uma requisição pelos logs

O Nginx do frontend gera um identificador por requisição e o envia ao chat em
`X-Request-ID` (`frontend/nginx/default.conf.template`). O chat o normaliza
para o formato UUID com hifens, grava em todas as linhas de log daquela
requisição (campo `request_id`), devolve no cabeçalho `X-Request-ID` da
resposta e repassa à API de pedidos (`chat-service/app/orders.py`). A API
registra o identificador na linha `pedido_criado` (`backend/pedidos.py`).

Onde obter o identificador: no cabeçalho `X-Request-ID` da resposta, na aba
Rede do navegador, ou numa linha de log do chat.

```bash
RID=00000000-0000-0000-0000-000000000000
insights "fields @timestamp, @log, level, message, @message
| filter request_id = '$RID' or @message like '$RID'
| sort @timestamp asc
| limit 200" /ecs/$P/chat /ecs/$P/api
```

Limites dessa rastreabilidade:

- Na API, só a criação de pedido registra o identificador; consultas
  (`GET /produtos`, `GET /pedidos/{id}`) não aparecem.
- O log de acesso do Nginx usa o formato padrão, que não inclui o
  identificador. No grupo `/ecs/insper-eats-sp/frontend`, localize a requisição
  pelo horário e pelo caminho.
- O worker não recebe o identificador. Para continuar do pedido em diante, use
  o `pedido_id` da linha `pedido_criado`:

```bash
insights 'fields @timestamp, @log, @message
| filter @message like /[Pp]edido(_id=| )42\b/
| sort @timestamp asc' /ecs/$P/api /ecs/$P/worker
```

Pedidos de uma conversa, pelo log do chat (`conversation_id` aparece nas linhas
`chat_message`, `ai_round` e `ai_tool`):

```bash
insights 'fields @timestamp, request_id, message
| filter message like /conversation_id=COLE-O-UUID-AQUI/
| sort @timestamp asc' /ecs/$P/chat
```

## Substituição manual de instância

Quando usar: agente ECS desconectado, instância degradada, ou para aplicar uma
AMI nova (o launch template novo só vale para instâncias criadas depois).

Caminho curto. O ASG encerra a instância e lança outra; com `managed_draining`
ligado, o ECS drena as tasks antes do encerramento:

```bash
instancias
INSTANCIA=i-0123456789abcdef0
aws autoscaling set-instance-health --instance-id "$INSTANCIA" --health-status Unhealthy
```

Caminho cuidadoso, que só encerra a instância depois de as tasks estarem em
outro lugar:

```bash
CI=$(aws ecs list-container-instances --cluster "$CLUSTER" \
  --filter "ec2InstanceId == $INSTANCIA" --query 'containerInstanceArns[0]' --output text)
aws ecs update-container-instances-state --cluster "$CLUSTER" \
  --container-instances "$CI" --status DRAINING --query 'containerInstances[0].status' --output text

# Repita até runningTasksCount chegar a 0.
aws ecs describe-container-instances --cluster "$CLUSTER" --container-instances "$CI" \
  --query 'containerInstances[0].[status,runningTasksCount,pendingTasksCount]' --output text

aws autoscaling set-instance-health --instance-id "$INSTANCIA" --health-status Unhealthy
```

O que esperar: cada instância hospeda 2 tasks, de serviços diferentes. Como o
deploy exige 100% de tasks saudáveis, o ECS sobe as substitutas antes de parar
as antigas; se não houver vaga, o Capacity Provider lança uma instância e a
drenagem espera por ela (alguns minutos). O chat leva até 170 s para encerrar
(`stop_timeout`). No caminho curto os alarmes `*-tasks-low` e
`*-targets-unhealthy` podem disparar por alguns minutos.

Confirmação:

```bash
instancias
servicos
aws ecs wait services-stable --cluster "$CLUSTER" \
  --services $P-api-service $P-worker-service $P-chat-service $P-frontend-service
```

Uma instância por vez. Para trocar a frota inteira, repita esperando
`services-stable` entre uma e outra.

## Gemini indisponível

**Sintoma.** O chat responde ao cliente que o assistente está indisponível
(HTTP 503 em `POST /chat/conversas/{id}/mensagens`). `chat-app-errors` dispara,
e `frontend-target-5xx` também se o volume for alto. Pedidos já feitos, a
consulta de status e a confirmação pelo botão continuam funcionando: nenhum
deles chama a IA. O health check do chat não chama o Gemini, então as tasks
continuam saudáveis.

**Diagnóstico.** O código da falha está no log do chat, na linha
`ai_dependency_failure code=... reason=...`:

```bash
insights 'filter message like /ai_dependency_failure|gemini_retry/
| parse message "code=* reason=*" as code, reason
| stats count() as n, latest(@timestamp) as ultimo by code
| sort n desc' /ecs/$P/chat
```

| Código | Causa | Ação |
| --- | --- | --- |
| `gemini_http_500`, `_502`, `_503`, `_504` | provedor instável ou fora; o chat já repetiu a chamada antes de desistir (linhas `gemini_retry`) | aguardar; se durar, trocar o modelo ou usar o modo de comandos |
| `gemini_timeout`, `gemini_transport_error` | sem resposta no prazo, ou falha de rede até o provedor | o mesmo; conferir também a saída pelo NAT |
| `gemini_http_429` | cota ou limite de taxa | conferir a cota no Google AI Studio; trocar de modelo pode ajudar |
| `gemini_http_401`, `gemini_http_403` | chave inválida, revogada ou sem acesso | gravar outra chave |
| `gemini_http_404` | o modelo de `gemini_model` não existe para essa chave | trocar `gemini_model` |
| outro `gemini_http_4xx` | requisição recusada; inclui o caso do secret ainda com o valor provisório, que não é uma chave | conferir chave e modelo |
| `gemini_not_configured` | chave ou modelo vazios na task | gravar a chave; conferir `GEMINI_MODEL` |

Se o código for de transporte e outros serviços também falharem para fora,
confira o NAT: o chat alcança o Gemini pela internet, pela saída da zona.

**Ações.** Todas são aplicadas por `./deploy.sh`, em `terraform/`, com a chave
exportada. A alteração muda a task definition do chat e dispara um rolling
deployment, sem indisponibilidade.

Trocar o modelo:

```bash
export TF_VAR_gemini_api_key="..."          # a mesma chave em uso
TF_VAR_gemini_model=<outro-modelo-disponível-na-conta> ./deploy.sh
```

Para tornar a troca permanente, ponha `gemini_model = "..."` em
`terraform.tfvars`. Valores do arquivo têm precedência sobre `TF_VAR_*`: se o
arquivo já define a variável, edite o arquivo.

Trocar a chave. `deploy.sh` deriva a versão do secret da própria chave, então
uma chave diferente é regravada sem outro passo:

```bash
read -rs TF_VAR_gemini_api_key && export TF_VAR_gemini_api_key
./deploy.sh
```

Alternativa sem Terraform: `./scripts/set-gemini-key.sh`, que grava o secret e
reinicia o chat.

Contingência sem IA. O chat passa a responder por comandos fixos
(`chat-service/app/dialogue.py`); o cliente ainda consulta o cardápio, monta a
seleção e confirma pelo botão, mas não há conversa em linguagem natural:

```bash
TF_VAR_ai_provider=commands ./deploy.sh
```

Para voltar, rode `./deploy.sh` de novo com a chave exportada e sem a variável
(ou com `ai_provider = "gemini"` no `terraform.tfvars`).

O `deploy.sh` guarda a versão da chave em `terraform/gemini.auto.tfvars`
(ignorado pelo Git). Enquanto esse arquivo existir, um `terraform apply` direto
não regrava o secret. Se ele for apagado, o próximo apply sem a chave no
ambiente volta a versão para o padrão e grava o valor provisório: rode
`./deploy.sh` com `TF_VAR_gemini_api_key` exportada para restaurar.

**Encerramento.** `chat-app-errors` volta a OK no primeiro período de 5 minutos
com menos de 5 falhas. Confirme com uma mensagem real pelo navegador:
`GET /health` do chat informa `ia_configurada`, que só indica a presença de
chave e modelo, não que o Gemini está respondendo.

## Banco indisponível

Não há alarme específico do RDS. Um banco fora ou em failover aparece como
`worker-app-errors` (`Falha no Worker`), `chat-app-errors`,
`frontend-target-5xx`, `orders-queue-age` e, se durar, `chat-tasks-low`: o
health check do contêiner do chat consulta o banco (`GET /health` responde 503
sem ele), então o ECS passa a substituir as tasks do chat. O `/health` da API
não consulta o banco, e os targets do ALB continuam saudáveis.

```bash
aws rds describe-db-instances --db-instance-identifier $P-postgres \
  --query 'DBInstances[0].[DBInstanceStatus,MultiAZ,AvailabilityZone,SecondaryAvailabilityZone]' \
  --output text
aws rds describe-events --source-type db-instance --source-identifier $P-postgres \
  --duration 120 --query 'Events[].[Date,Message]' --output text
```

Durante a indisponibilidade a API responde 503 com `Retry-After: 5`
(`backend/main.py`), o chat trata a resposta como resultado incerto e a
confirmação pode ser repetida com a mesma chave de idempotência, e o worker
continua tentando a cada 5 s sem ser reiniciado (o heartbeat é tocado mesmo com
o banco fora). Um failover Multi-AZ costuma levar de 1 a 2 minutos; depois
dele os serviços se reconectam sozinhos. Se o status não voltar a `available`,
o caminho é restaurar o banco para um instante dos últimos 7 dias numa nova
instância; esse procedimento não foi ensaiado.

O dashboard `insper-eats-sp-observabilidade` tem os widgets de CPU e de
conexões do RDS. Conexões no limite, com 503 da API e banco `available`, indicam
pool esgotado: confira se algum serviço escalou além do previsto.

## Alertas que não chegam

```bash
TOPICO=$(aws sns list-topics --query "Topics[?ends_with(TopicArn, ':$P-alertas')].TopicArn" --output text)
aws sns list-subscriptions-by-topic --topic-arn "$TOPICO" \
  --query 'Subscriptions[].[Protocol,Endpoint,SubscriptionArn]' --output text
aws sns publish --topic-arn "$TOPICO" --subject "Teste Insper Eats" --message "Teste de alerta"
```

`PendingConfirmation` na última coluna: o link enviado pela AWS ao e-mail de
`alert_email` não foi confirmado. Sem `alert_email`, o tópico existe e não tem
inscrição: os alarmes mudam de estado no console e ninguém é avisado.
