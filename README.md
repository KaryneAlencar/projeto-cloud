# Insper Eats

Pedido de lanche no campus por conversa com um vendedor de IA. O cliente pergunta
o que tem para comer, monta o pedido falando e confirma com um clique. A
plataforma roda na AWS em ECS sobre EC2, e um único `./deploy.sh` cria toda a
infraestrutura em São Paulo (`sa-east-1`) com Terraform, sem passos no console.

Projeto final de Computação em Nuvem, Insper.

> **Apresentação:** [vídeo](https://youtu.be/iK5mZbTSrtM)

## Sumário

1. [O produto](#o-produto)
2. [Situação da entrega](#situação-da-entrega)
3. [Como rodar](#como-rodar)
4. [Arquitetura](#arquitetura)
5. [Como cada parte funciona](#como-cada-parte-funciona)
6. [Decisões e compromissos](#decisões-e-compromissos)
7. [Falhas, riscos e recuperação](#falhas-riscos-e-recuperação)
8. [Limites conhecidos](#limites-conhecidos)
9. [Onde cada requisito está no código](#onde-cada-requisito-está-no-código)
10. [Estrutura do repositório e documentação](#estrutura-do-repositório-e-documentação)
11. [Equipe](#equipe)

## O produto

**Problema.** O intervalo entre aulas é curto e boa parte dele vai para a fila
da cantina. O aluno não sabe o que ainda tem, espera para pedir e espera de
novo para retirar.

**Público-alvo.** Alunos, professores e funcionários do campus. Depois, outros
campi e empresas com cantina própria.

**Proposta de valor.** "Menos fila, mais intervalo." O cliente escreve como
falaria com o atendente ("tem algo doce até 10 reais?"), recebe a resposta com
preço e disponibilidade reais, informa onde está e confirma. O pedido chega à
cantina com o estoque já baixado.

**Diferenciais.**

- A conversa usa o catálogo e o estoque do banco no momento da pergunta. A IA
  não inventa produto nem preço.
- A IA monta o pedido, mas não compra. Quem cria o pedido é o botão "Confirmar
  pedido". Um mal-entendido do modelo não vira cobrança.
- Dois clientes não compram o último brownie. O banco trava a linha do produto
  e um deles recebe "estoque insuficiente".

**Modelo de receita (proposta).** Comissão por pedido paga pela cantina
parceira, taxa de entrega opcional para o cliente e licença da plataforma para
outros campi. Cada campus novo é um ambiente criado pelo mesmo Terraform,
mudando a variável `environment` (e `region`, se for o caso).

## Situação da entrega

| Verificação | Como reproduzir | Resultado |
| --- | --- | --- |
| Formatação e validação do Terraform | `terraform fmt -check -recursive && terraform validate` | passa |
| 16 cenários com o provider AWS simulado: rede, security groups, RDS privado, filas, placement, escala, alarmes, ausência de segredos em texto claro | `terraform test` | 16 passed |
| Ensaio local das mesmas imagens, do mesmo `db-init` e das mesmas variáveis das task definitions, com PostgreSQL e ElasticMQ no lugar de RDS e SQS | [Nível 1](terraform/README.md#nível-1-ensaio-local-em-docker-cerca-de-3-minutos-sem-aws) | 10 ok |
| Testes do chat com PostgreSQL real e IA simulada | `chat-service/tests/run_postgres.py` | passam |
| Ambiente manual anterior, em Ohio: failover de task, failover de EC2 e carga | [docs/evidencias](docs/evidencias/README.md) | registrado em 06/11/2026 |
| `./deploy.sh` em `sa-east-1` seguido de `scripts/verify_deploy.py` (19 verificações) | [Nível 3](terraform/README.md#nível-3-verificação-do-ambiente-implantado) | **pendente** |

## Como rodar

### Deploy AWS

Pré-requisitos na máquina: Terraform 1.11 ou mais novo, AWS CLI v2, Docker em
execução, Python 3 e bash (no Windows, WSL ou Git Bash). Na conta: credenciais
de administrador e cota de pelo menos 8 vCPU On-Demand na região (código
`L-1216C47A`; 20 para o scale-out completo).

```bash
cd terraform
aws sso login --profile insper-eats
export AWS_PROFILE=insper-eats
read -rs TF_VAR_gemini_api_key && export TF_VAR_gemini_api_key   # chave do Gemini; não aparece na tela
./deploy.sh
```

O `deploy.sh` não faz perguntas. Em ordem, ele:

1. confere ferramentas, Docker e credenciais, e mostra a conta AWS;
2. cria o bucket S3 do state remoto (`bootstrap/`) e gera `backend.hcl`;
3. confere a cota de vCPU (abaixo de 8 interrompe, abaixo de 20 avisa);
4. roda `terraform apply`, que constrói e envia as 4 imagens ao ECR, cria a
   rede, o banco, o cluster e os serviços, prepara o banco com a task
   `db-init` e só termina quando os 4 serviços estão estáveis.

A primeira execução leva de 30 a 40 minutos, a maior parte no RDS Multi-AZ. No
fim, o script imprime a URL da aplicação. Rodar de novo é seguro: só aplica o
que mudou.

```bash
python3 scripts/verify_deploy.py   # 19 verificações na AWS e na aplicação, relatório em evidencias/
terraform output                   # URLs, nomes e ARNs para navegar no console
./destroy.sh                       # remove o ambiente e o bucket do state
```

Sem `TF_VAR_gemini_api_key`, o chat sobe em modo de comandos, sem IA. Para
chamar a API de pedidos de fora (porta 8000 do ALB), copie
`terraform.tfvars.example` para `terraform.tfvars` e coloque seu IP em
`api_allowed_cidrs`. Ficam fora do Terraform só duas coisas: obter a chave no
Google AI Studio e, se usar `alert_email`, confirmar a inscrição do SNS.

O ambiente ligado custa por hora (2 NAT Gateways, RDS Multi-AZ, ALB e 4
instâncias t3.medium). Suba, use e destrua. Detalhes de custo, variáveis e
operação: [terraform/README.md](terraform/README.md).

### Na máquina local, com Docker

```bash
./scripts/start-local.sh          # Windows: .\scripts\start-local.ps1
```

Abra http://localhost:8080. O script cria `.env` e `chat-service/.env` a partir
dos exemplos quando faltam, sobe PostgreSQL, API, chat e frontend e cadastra um
catálogo inicial. A chave do Gemini vai em `chat-service/.env`. Para testar sem
IA, use `./scripts/start-local.sh --commands`. Esse modo local não sobe worker
nem fila: os pedidos ficam em "recebido".

<details>
<summary>Portas, verificação isolada e detalhes</summary>

Portas no host: frontend 8080, API 8002, chat 8003, PostgreSQL 5433. Entre
containers, o chat chama `http://api:8000` e o frontend chama
`http://chat:8001`.

A API só aceita `/pedidos` com o cabeçalho `X-Internal-Token`. No compose local,
API e chat recebem o mesmo `ORDERS_INTERNAL_TOKEN`, com um valor padrão só para
desenvolvimento.

Para validar as imagens com banco descartável, na porta 18080, sem tocar nos
seus dados:

```bash
./scripts/verify-stack.sh         # Windows: .\scripts\verify-stack.ps1
docker compose -p insper-eats-verification -f compose.verify.yaml down -v   # limpeza
```

Para ensaiar com worker e fila (ElasticMQ no lugar do SQS), veja o "Nível 1" em
[terraform/README.md](terraform/README.md). Sessão, CSRF e recuperação de
conversas antigas estão em [docs/IMPLANTACAO.md](docs/IMPLANTACAO.md).

</details>

### Testes

| Nível | O que prova | Comando, a partir de `terraform/` |
| --- | --- | --- |
| 0 | O código Terraform é válido e o plano atende aos critérios | `terraform init -backend=false && terraform test` |
| 1 | As imagens sobem, o `db-init` cria usuários e tabelas e o pedido vai do frontend até a confirmação pelo worker | `docker compose -f tests/local/compose.yaml up -d --build --wait` e `verify_deploy.py --skip-aws` |
| 2 | Permissões, cota e nomes antes de gastar | `terraform plan` (cerca de 150 recursos) |
| 3 | O ambiente implantado funciona | `python3 scripts/verify_deploy.py` |
| 4 | Falhas e carga: DLQ, troca de task, troca de EC2, scale-out da API e do worker | comandos no [Nível 4](terraform/README.md#nível-4-comportamento-sob-falha-e-carga) |

Testes do chat: `cd chat-service && .venv/bin/python tests/run_postgres.py`.

## Arquitetura

```mermaid
flowchart TB
  user(["Cliente no navegador"])
  gemini(["API do Google Gemini"])
  dev(["Máquina que roda ./deploy.sh"])

  subgraph aws["AWS sa-east-1"]
    subgraph vpc["VPC 10.20.0.0/16, duas zonas de disponibilidade"]
      subgraph pub["Sub-redes públicas 10.20.1.0/24 e 10.20.2.0/24"]
        alb["Application Load Balancer<br/>:80 frontend, :8000 API só para IPs liberados"]
        nat["NAT Gateway, um por zona"]
      end
      subgraph app["Sub-redes privadas de aplicação 10.20.11.0/24 e 10.20.12.0/24"]
        subgraph ecs["Cluster ECS sobre EC2<br/>Auto Scaling Group de 0 a 10 t3.medium, gerido pelo Capacity Provider"]
          fe["frontend<br/>Nginx + React<br/>2 a 4 tasks"]
          chat["chat<br/>FastAPI + Gemini<br/>2 a 4 tasks"]
          api["API de pedidos<br/>FastAPI<br/>2 a 4 tasks"]
          worker["worker<br/>consumidor SQS<br/>2 a 4 tasks"]
        end
        vpce["Endpoint de VPC do SQS"]
      end
      subgraph data["Sub-redes privadas de dados 10.20.21.0/24 e 10.20.22.0/24"]
        rds[("RDS PostgreSQL 17 Multi-AZ<br/>bancos insper_eats e insper_eats_chat")]
      end
    end
    sqs[["SQS insper-eats-sp-orders"]]
    dlq[["DLQ insper-eats-sp-orders-dlq"]]
    ecr["ECR<br/>4 repositórios"]
    sm["Secrets Manager<br/>4 secrets + senha admin do RDS"]
    cw["CloudWatch<br/>logs, 16 alarmes, dashboard"]
    sns["SNS<br/>alertas"]
  end

  user -->|"HTTP :80"| alb
  alb -->|":8080"| fe
  fe -->|"/api/* para :8001<br/>chat.insper-eats-sp.internal"| chat
  chat -->|":8000 + X-Internal-Token<br/>api.insper-eats-sp.internal"| api
  chat -->|"HTTPS pelo NAT"| gemini
  chat -->|"5432 TLS"| rds
  api -->|"5432 TLS"| rds
  worker -->|"5432 TLS"| rds
  worker -->|"HTTPS"| vpce
  vpce --> sqs
  sqs -->|"após 5 recebimentos"| dlq
  dev -->|"docker push"| ecr
  ecr -.->|"imagens"| ecs
  sm -.->|"secrets na partida da task"| ecs
  ecs -.->|"logs e métricas"| cw
  cw -.->|"alarmes"| sns
```

### Caminho de um pedido

A parte síncrona termina quando o cliente vê o número do pedido. A parte
assíncrona confirma o pedido depois, sem o cliente esperar.

1. O navegador chama o ALB na porta 80. O ALB entrega ao Nginx do frontend, que
   serve a interface React.
2. O Nginx encaminha `/api/*` ao chat, que ele acha pelo DNS privado do Cloud
   Map (`chat.insper-eats-sp.internal`). Ele resolve o nome de novo a cada 10 s,
   então uma task nova do chat entra no rodízio sem reiniciar o frontend.
3. O chat manda a conversa ao Gemini, que pede para chamar funções. O chat
   executa cada função contra a API de pedidos
   (`api.insper-eats-sp.internal:8000`, com `X-Internal-Token`) e grava a
   seleção de compra no banco do chat.
4. O cliente clica em "Confirmar pedido". O chat envia `POST /pedidos` com uma
   chave de idempotência. A API, numa única transação no RDS, trava as linhas
   dos produtos, baixa o estoque, grava pedido e itens e grava o evento
   `pedido.criado` na tabela de outbox. O pedido nasce como "recebido".
5. O worker lê o outbox e publica o evento no SQS, pelo endpoint de VPC. Em
   seguida consome a fila, muda o pedido para "confirmado" e só então apaga a
   mensagem.
6. O painel "Meus pedidos" consulta o status a cada 10 s e mostra a mudança.
7. Uma mensagem que falha 5 vezes vai para a DLQ e dispara o alarme
   `dlq-messages`.

Fora do caminho do pedido: o ECR guarda as imagens, o Secrets Manager entrega
as credenciais às tasks na partida, o CloudWatch recebe logs e métricas e o SNS
avisa quando um alarme muda de estado.

### Serviços

| Serviço | Faz | Porta | Recebe de | Health check | Escala por |
| --- | --- | --- | --- | --- | --- |
| frontend | Nginx com a interface React e proxy de `/api` para o chat | 8080 | ALB | `/healthz` | CPU, alvo 60% |
| chat | Conversa, chamada ao Gemini, sessão do navegador e confirmação | 8001 | frontend | `/health` | CPU, alvo 60% |
| api | Catálogo, estoque e pedidos (FastAPI) | 8000 | chat; ALB :8000 só para IPs liberados | `/health` | CPU, alvo 60% |
| worker | Publica o outbox no SQS e confirma pedidos | nenhuma | fila | arquivo de heartbeat, 120 s | mensagens na fila por task, alvo 5 |
| db-init | Cria usuários, bancos, tabelas e catálogo inicial; roda uma vez por apply e termina | nenhuma | Terraform | não se aplica | não escala (Fargate) |

## Como cada parte funciona

### Rede e comunicação

Arquivos: [`network.tf`](terraform/network.tf), [`security.tf`](terraform/security.tf), [`alb.tf`](terraform/alb.tf).

| Camada | Sub-redes | Saída para a internet | O que fica ali |
| --- | --- | --- | --- |
| Pública | 10.20.1.0/24 e 10.20.2.0/24 | Internet Gateway | ALB e os 2 NAT Gateways |
| Aplicação | 10.20.11.0/24 e 10.20.12.0/24 | NAT da própria zona | instâncias EC2 e tasks |
| Dados | 10.20.21.0/24 e 10.20.22.0/24 | nenhuma, só a rota local | RDS |

Cada sub-rede de aplicação tem a própria tabela de rotas e sai pelo NAT da sua
zona. Se uma zona cai, a outra continua com saída. Nenhuma instância ou task tem
IP público.

Os 9 security groups referenciam uns aos outros em vez de faixas de IP. O único
caminho aberto é este:

```
internet :80/:443 -> ALB -> :8080 frontend -> :8001 chat -> :8000 API -> :5432 RDS
                                                   worker -> :5432 RDS
                    ALB :8000 (só api_allowed_cidrs) -> :8000 API
```

O RDS aceita a porta 5432 só de API, worker, chat e `db-init`:

```hcl
resource "aws_vpc_security_group_ingress_rule" "rds_from_clients" {
  for_each = local.database_clients   # api, worker, chat, db_init

  security_group_id            = aws_security_group.rds.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
```

O security group das instâncias não tem regra de entrada. As tasks saem para a
internet só por HTTPS (443), para ECR, CloudWatch, Secrets Manager e Gemini.

Outros pontos de rede:

- **ALB.** A porta 80 entrega o frontend (com certificado ACM, 443 e
  redirecionamento de 80). A API fica num listener separado, na 8000, fechado
  por padrão porque `/produtos` não tem autenticação. Target groups do tipo
  `ip`, porque cada task tem a própria interface de rede (`awsvpc`). O
  `idle_timeout` é de 180 s, porque uma resposta da IA pode levar até 150 s.
- **Endpoints de VPC.** O endpoint gateway do S3 (sem custo) traz as camadas
  das imagens do ECR sem passar pelo NAT. O endpoint de interface do SQS mantém
  o tráfego do worker dentro da VPC.
- **DNS interno.** O Cloud Map registra cada task da API e do chat em
  `api.insper-eats-sp.internal` e `chat.insper-eats-sp.internal`, com TTL de
  10 s. O ECS tira do DNS a task que falha no health check.

### Containers e elasticidade

Arquivos: [`ecs_cluster.tf`](terraform/ecs_cluster.tf), [`ecs_services.tf`](terraform/ecs_services.tf), [`modules/ecs-service/`](terraform/modules/ecs-service/main.tf), [`ecr.tf`](terraform/ecr.tf).

**Imagens.** O próprio `terraform apply` constrói as 4 imagens e as envia ao
ECR da região de destino. A tag é um hash dos arquivos que entram no build.
Código igual gera a mesma tag e nada é reconstruído. Código alterado gera tag
nova, uma revisão da task definition e um rolling deployment. Os repositórios
têm tags imutáveis e varredura de vulnerabilidades no push. As imagens do chat
e do frontend rodam sem root e não contêm `.env`.

**Cluster, ASG e Capacity Provider.** O Auto Scaling Group começa com 0
instâncias e vai até 10. Quem decide quantas existem é o Capacity Provider, a
partir das tasks que precisam de lugar. O Terraform ignora `desired_capacity`
para não brigar com ele.

```hcl
managed_scaling {
  status                    = "ENABLED"
  target_capacity           = 100   # instância só existe se tiver task
  minimum_scaling_step_size = 1
  maximum_scaling_step_size = 4     # o primeiro apply sobe as 4 de uma vez
  instance_warmup_period    = 300
}
```

Com `managed_termination_protection` e `protect_from_scale_in`, o ASG só
remove instância sem task. Com `managed_draining`, o ECS tira as tasks de uma
instância antes de ela sair. A instância entra no cluster pelo `user_data`
(`ECS_CLUSTER=...`) e usa a AMI otimizada para ECS da região, lida de um
parâmetro público do SSM.

**Dois níveis de escala.**

| Nível | Quem decide | Regra |
| --- | --- | --- |
| Tasks | Application Auto Scaling | API, chat e frontend: CPU média a 60%. Worker: mensagens visíveis na fila divididas pelas tasks em execução, alvo 5. Todos entre 2 e 4 tasks. |
| Instâncias | Capacity Provider | Uma task sem lugar faz o ASG crescer. Uma instância sem task é removida. |

O worker escala pela fila, e não por CPU, porque um worker parado esperando a
fila e um worker afogado em mensagens gastam quase a mesma CPU.

**Quantas instâncias e por quê.** Em modo `awsvpc` cada task ocupa uma
interface de rede. A t3.medium tem 3, e uma é da própria instância: cabem 2
tasks por máquina. A restrição `distinctInstance` impede duas réplicas do mesmo
serviço na mesma instância, e o `spread` por zona divide as réplicas entre as
duas AZs.

| Situação | Tasks | Instâncias |
| --- | --- | --- |
| Repouso, 4 serviços com 2 tasks | 8 | 4, duas por zona |
| Pico, 4 serviços com 4 tasks | 16 | 8 |
| Máximo do ASG | até 20 vagas | 10 |

As 2 instâncias além das 8 são folga para um deploy no pico: com
`deployment_maximum_percent = 200`, a task nova sobe antes de a antiga sair e
precisa de vaga.

**Reserva e limite por task.** 256 CPU units (1/4 de vCPU) e 512 MiB de limite
rígido na task; 384 MiB de reserva (`memoryReservation`) no contêiner. Os 128
MiB de diferença absorvem picos, como uma resposta longa da IA, sem matar o
processo. Com 2 tasks, uma instância fica com cerca de 25% de CPU e memória
reservadas. Quem limita é o número de interfaces de rede (ver
[Limites conhecidos](#limites-conhecidos)).

**Health checks em três pontos.**

| Onde | Como | Quem age |
| --- | --- | --- |
| Contêiner | HTTP em `/health` (API, chat) e `/healthz` (frontend); no worker, arquivo `/tmp/worker-heartbeat` tocado a cada volta do laço, falha após 120 s sem toque | ECS substitui a task |
| Target group | `/health` (API) e `/healthz` (frontend), a cada 15 s | ALB para de mandar tráfego |
| Instância | verificação EC2 do ASG | ASG substitui a instância |

**Deploy sem queda.** `deployment_minimum_healthy_percent = 100`: a versão
antiga só sai quando a nova está saudável. O circuit breaker desfaz um deploy
que não estabiliza. O ALB espera 30 s (API) e 160 s (frontend) antes de tirar
um target. O chat tem `stop_timeout` de 170 s para terminar respostas em
andamento, e o worker trata SIGTERM terminando a volta atual antes de sair.

### Dados e mensageria

Arquivos: [`database.tf`](terraform/database.tf), [`messaging.tf`](terraform/messaging.tf), [`files/db_init.py`](terraform/files/db_init.py), [`backend/pedidos.py`](backend/pedidos.py), [`backend/worker.py`](backend/worker.py).

**Persistência.** RDS PostgreSQL 17, `db.t4g.small`, Multi-AZ, privado,
criptografado, com backups automáticos de 7 dias. Há dois bancos na mesma
instância, cada um com usuário próprio que só conecta no seu:

| Banco | Usuário | Tabelas |
| --- | --- | --- |
| `insper_eats` | `insper_app` (API e worker) | `produto`, `pedido`, `itempedido`, `eventooutbox` |
| `insper_eats_chat` | `insper_chat` (chat) | conversas, mensagens, sessões, seleção de compra, tentativas de confirmação |

Nenhuma task guarda estado em disco. Trocar ou perder uma task não perde
conversa nem pedido. A task `db-init` roda uma vez em Fargate, antes de existir
qualquer instância EC2. É a única que lê a senha de administrador. Ela cria os
usuários e as tabelas e insere o catálogo inicial se a tabela estiver vazia.

**Síncrono e assíncrono.** Chat, API e RDS formam o caminho síncrono: o cliente
espera a resposta. Outbox, SQS e worker formam o caminho assíncrono.

**Por que outbox.** A API grava o pedido e o evento `pedido.criado` na mesma
transação. Se a API publicasse direto no SQS, um erro entre o commit e a
publicação perderia o evento. Com o outbox, o worker publica o que estiver
pendente (`SELECT ... FOR UPDATE SKIP LOCKED`, para dois workers não pegarem o
mesmo evento).

**Retentativas, duplicidade e DLQ.**

```hcl
resource "aws_sqs_queue" "orders" {
  visibility_timeout_seconds = 60
  receive_wait_time_seconds  = 10   # long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = 5
  })
}
```

- O worker só chama `delete_message` depois de processar. Se falhar, a
  mensagem volta a ficar visível em 60 s e é tentada de novo.
- SQS Standard entrega pelo menos uma vez. A duplicidade é tratada em dois
  lugares. Na API, a chave de idempotência mais um hash do conteúdo: repetir o
  mesmo pedido devolve o pedido existente sem baixar estoque de novo, e a mesma
  chave com outro conteúdo recebe 409. No worker, um pedido já "confirmado" é
  ignorado.
- Mensagem de tipo desconhecido, ID inválido ou pedido inexistente gera erro e
  não é apagada. Na quinta tentativa vai para a DLQ, que guarda por 14 dias e
  tem alarme.
- As duas filas recusam conexões sem TLS por política de recurso.

**Concorrência no estoque.** A API trava as linhas dos produtos com
`SELECT ... FOR UPDATE`, sempre em ordem de ID para não haver deadlock. Se dois
clientes pedem o último item, um recebe 201 e o outro 409.

**Banco indisponível.** Durante um failover do RDS, a API responde 503 com
`Retry-After: 5` em vez de 500. A seleção fica congelada como "confirmando", e o
botão "Repetir confirmação" reenvia o mesmo conteúdo com a mesma chave de
idempotência.

### Vendedor de IA

Arquivos: [`chat-service/app/ai.py`](chat-service/app/ai.py), [`checkout.py`](chat-service/app/checkout.py), [`gemini.py`](chat-service/app/gemini.py). Detalhes: [chat-service/README.md](chat-service/README.md).

O chat usa a API do Gemini com function calling. O modelo recebe seis funções;
cada uma executa uma operação real:

| Função | Tipo | Efeito |
| --- | --- | --- |
| `listar_produtos` | consulta | `GET /produtos` na API: catálogo, preço e estoque do RDS |
| `consultar_pedido` | consulta | `GET /pedidos/{id}`, só para pedidos da sessão do navegador |
| `listar_meus_pedidos` | consulta | pedidos de todas as conversas da sessão, com status atual |
| `preparar_compra` | grava | valida itens e estoque contra o catálogo e grava a seleção no banco do chat |
| `atualizar_entrega` | grava | grava nome e local de entrega na seleção |
| `cancelar_selecao` | grava | apaga a seleção ainda não confirmada |

Não existe função de compra, e isso é proposital. Um modelo de linguagem pode
entender mal uma mensagem, ser induzido por texto do catálogo ou repetir uma
chamada. O pedido é criado pelo servidor quando o cliente clica em "Confirmar
pedido", com os dados exatos que `preparar_compra` gravou. Antes de chamar a API,
o chat grava a tentativa no banco; se a resposta não chega, o botão "Repetir
confirmação" reenvia o mesmo conteúdo com a mesma chave, e a API não baixa o
estoque duas vezes.

Se o modelo principal (`gemini-flash-lite-latest`) falha com 429, 5xx ou
timeout, o chat tenta os modelos reserva, dentro de um prazo total de 120 s. Se
todos falham, responde pelo roteiro sem IA com um aviso explícito. O modo
`ai_provider = "commands"` existe para testes automáticos e contingência; não é
usado na demonstração.

### Segurança

**Papéis IAM.** Dez papéis, cada um com o mínimo necessário:

| Papel | Quantos | Pode |
| --- | --- | --- |
| Instância EC2 | 1 | agente ECS e SSM (políticas gerenciadas) |
| Execution role, por serviço | 4 | baixar imagem, gravar log e ler só os secrets do próprio serviço; a do frontend não lê nenhum |
| Task role, por serviço | 4 | nada, exceto a do worker: `GetQueueUrl`, `SendMessage`, `ReceiveMessage` e `DeleteMessage` na fila de pedidos |
| Execution role do `db-init` | 1 | a única que lê a senha de administrador do RDS |

A execution role é usada pelo ECS antes de o contêiner existir. A task role é a
identidade do código em execução. As instâncias exigem IMDSv2 e têm
`ECS_AWSVPC_BLOCK_IMDS=true`, então uma task não alcança as credenciais do papel
da instância.

**Segredos.** Quatro secrets de aplicação (`database-url`,
`chat-database-url`, `orders-internal-token`, `gemini-api-key`) e a senha de
administrador do RDS, criada e girada pelo próprio RDS. As senhas e o token
vêm de recursos efêmeros e são gravados por argumentos write-only. Não aparecem
no plan, no state nem nos outputs:

```hcl
ephemeral "random_password" "db_app" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id                = aws_secretsmanager_secret.database_url.id
  secret_string_wo         = "postgresql+psycopg://...:${ephemeral.random_password.db_app.result}@...?sslmode=require"
  secret_string_wo_version = var.credentials_version
}
```

A task definition guarda só o ARN do secret. Para girar senhas e token, aumente
`credentials_version` e aplique.

**Na aplicação.** A API exige `X-Internal-Token` em `/pedidos`; só o chat tem o
token. O navegador recebe uma sessão anônima em cookie HttpOnly, as mutações
exigem token CSRF e cabeçalho `Origin` conhecido, e uma conversa só é lida pela
sessão que a criou. Não há login.

**Criptografia.** Em repouso: RDS, volumes EBS, SQS, bucket do state. Em
trânsito: `sslmode=require` no banco, TLS obrigatório no SQS e no S3. Entre
navegador e ALB, só com certificado (`acm_certificate_arn` e `app_domain`).

### Observabilidade

Arquivo: [`observability.tf`](terraform/observability.tf). Procedimento por alarme: [docs/RUNBOOK.md](docs/RUNBOOK.md).

**Logs.** Os 4 serviços e o `db-init` enviam logs ao CloudWatch pelo driver
`awslogs`, em `/ecs/insper-eats-sp/<serviço>`, com retenção de 30 dias. O
Nginx gera um `X-Request-ID` por requisição; o chat registra e repassa à API,
que grava o mesmo ID na linha `pedido_criado`. Uma compra pode ser seguida nos
três serviços. Os logs não guardam texto de conversa, cookies nem credenciais.

**Alarmes.** 16, todos notificando o tópico SNS `insper-eats-sp-alertas` ao
disparar e ao voltar a OK:

| O que vigia | Alarmes |
| --- | --- |
| Saúde das tasks | `<serviço>-tasks-low` (4), `api-targets-unhealthy`, `frontend-targets-unhealthy` |
| Cluster e ASG | `cluster-capacity-high`, `asg-at-max` |
| Respostas do balanceador | `api-target-5xx`, `frontend-target-5xx`, `alb-5xx` |
| Fila | `orders-queue-age`, `dlq-messages` |
| Falhas da aplicação | `api-app-errors`, `worker-app-errors`, `chat-app-errors`, sobre métricas extraídas dos logs |

**Dashboard.** `insper-eats-sp-observabilidade`, com 14 widgets: ECS, ALB,
ASG, SQS, RDS, erros da aplicação e a métrica de negócio
`PedidosConfirmados`, contada a partir do log do worker. O cluster tem
Container Insights ligado.

### Terraform

Arquivos: [`terraform/`](terraform/). Guia completo: [terraform/README.md](terraform/README.md).

**Organização.** Um arquivo por camada (`network.tf`, `security.tf`,
`database.tf`, `secrets.tf`, `messaging.tf`, `ecr.tf`, `ecs_cluster.tf`,
`alb.tf`, `db_init.tf`, `ecs_services.tf`, `observability.tf`). O módulo
`modules/ecs-service` cria, para cada serviço, log group, os dois papéis IAM,
task definition, serviço e auto scaling. Os 4 serviços são 4 chamadas desse
módulo com parâmetros diferentes. São cerca de 150 recursos.

**State remoto.** O backend é um bucket S3 versionado, criptografado, sem
acesso público e com lock nativo (`use_lockfile`), que impede dois applies ao
mesmo tempo. O bucket precisa existir antes do `terraform init`, por isso é
criado por um Terraform separado em `bootstrap/`. O `deploy.sh` encadeia os
dois.

**Parâmetros.** Todas as variáveis de [`variables.tf`](terraform/variables.tf)
têm padrão; `terraform.tfvars` é opcional. As mais usadas:

| Variável | Padrão | Para quê |
| --- | --- | --- |
| `region` | `sa-east-1` | região de destino |
| `environment` | `sp` | sufixo de todos os nomes |
| `api_allowed_cidrs` | `[]` | IPs que alcançam a API na porta 8000 |
| `ecs_instance_type`, `ecs_asg_max_size` | `t3.medium`, `10` | frota EC2 |
| `service_min_count`, `service_max_count` | `2`, `4` | tasks por serviço |
| `api_cpu_target`, `worker_backlog_target` | `60`, `5` | alvos de escala |
| `db_multi_az`, `single_nat_gateway` | `true`, `false` | trocar disponibilidade por custo em testes |
| `acm_certificate_arn`, `app_domain` | `null` | HTTPS |
| `alert_email` | `null` | e-mail inscrito no SNS |

**Reconstrução em São Paulo, sem dependência de Ohio.** O ambiente manual
anterior ficava em Ohio (`us-east-2`). O código não lê nem referencia nada de
lá, e tudo o que depende de região é resolvido na região de destino:

- as zonas vêm de `data "aws_availability_zones"`;
- a AMI vem do parâmetro público `/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id`;
- as imagens são construídas e enviadas ao ECR da região;
- endpoints de VPC, logs e dashboard usam `var.region`;
- o bucket do state leva conta e região no nome.

O sufixo `environment` entra em todos os nomes. Papéis IAM são globais na
conta, e é o sufixo que evita colisão com outro ambiente. Para subir em outra
região, num clone limpo:

```bash
TF_VAR_region=us-east-1 TF_VAR_environment=dr ./deploy.sh
```

**Ordem do apply.** O Terraform monta o grafo de dependências e cria em
paralelo o que é independente:

| Fase | O que é criado | Depende de |
| --- | --- | --- |
| 1 | VPC, sub-redes, NAT, rotas, security groups, ECR, SQS, papéis IAM | nada |
| 2 | build e push das 4 imagens | repositórios ECR |
| 3 | RDS (10 a 20 min) e os secrets com as URLs de conexão | endpoint do banco |
| 4 | cluster, launch template, ASG em zero, Capacity Provider, ALB, Cloud Map | rede |
| 5 | task `db-init` em Fargate | banco, secrets, imagem e NAT |
| 6 | os 4 serviços; o Capacity Provider sobe 4 instâncias | banco preparado |
| 7 | auto scaling, alarmes e dashboard | serviços |

O apply espera os serviços ficarem estáveis (`wait_for_steady_state`). Se uma
task não sobe, ele falha em vez de reportar sucesso.

## Decisões e compromissos

| Decisão | Ganho | Custo |
| --- | --- | --- |
| Os 4 serviços em EC2, pelo mesmo Capacity Provider | atende a exigência de ECS sobre EC2; um só modelo de capacidade; security group por task | 4 instâncias em repouso e até 10; cerca de 75% de CPU e memória de cada uma sem uso |
| NAT Gateway por zona | a saída sobrevive à perda de uma zona | dois NAT ligados o tempo todo |
| RDS Multi-AZ | failover automático do banco | o dobro do custo da instância |
| ASG começando em zero, gerido pelo Capacity Provider | paga só pelas instâncias que têm task | primeira subida e deploys levam minutos |
| `distinctInstance` | perder uma EC2 tira no máximo uma réplica de cada serviço | todo deploy precisa de instância extra temporária |
| API fora da porta 80, restrita por IP | `/produtos`, sem autenticação, não fica exposto | testes precisam liberar o IP |
| A IA não tem função de compra | um erro do modelo não cria pedido | o cliente precisa clicar para confirmar |
| Outbox em vez de publicar direto no SQS | nenhum evento se perde entre commit e publicação | uma tabela a mais e alguns segundos de atraso na confirmação |
| HTTP por padrão | funciona sem domínio próprio | tráfego em claro até configurar certificado e domínio |

## Falhas, riscos e recuperação

Procedimentos detalhados: [docs/RUNBOOK.md](docs/RUNBOOK.md).

| Falha | Impacto para o cliente | Como se detecta | Recuperação | Tipo |
| --- | --- | --- | --- | --- |
| Task interrompida | nenhum; a outra réplica atende | `*-tasks-low`, eventos do serviço | o ECS cria outra em cerca de 1 minuto | automática |
| Perda de uma EC2 | até dois serviços ficam com uma réplica por alguns minutos | alarmes de tasks e de targets | o ASG substitui a instância e o ECS recoloca as tasks | automática |
| Deploy com defeito | nenhum; a versão antiga segue no ar | eventos do serviço | o circuit breaker desfaz o deploy | automática |
| Zona indisponível | capacidade menor; conexões ao banco caem por 1 a 2 minutos | alarmes de targets, eventos do RDS | o ALB usa a outra zona, o RDS promove a réplica e o ASG repõe instâncias na zona restante | automática |
| Mensagem que sempre falha | um pedido fica em "recebido" | `orders-queue-age`, `dlq-messages`, log do worker | corrigir a causa e mover de volta da DLQ (`aws sqs start-message-move-task`) | detecção automática, correção manual |
| Gemini fora do ar | o chat responde pelo roteiro sem IA; pedidos e confirmação seguem | `chat-app-errors`, `ai_dependency_failure` no log | trocar de modelo ou usar `ai_provider = "commands"` | manual |
| Dado apagado ou corrompido | perda de pedidos até a restauração | relato ou inconsistência; não há alarme | restaurar o RDS para um instante dos últimos 7 dias, numa instância nova | manual, não ensaiada |
| Região indisponível | plataforma inteira fora do ar | fora da AWS; os alarmes ficam na mesma região | recriar a infraestrutura em outra região pelo Terraform | proposta |

**O que já existe e o que é proposta.** Hoje, num desastre regional, o
Terraform recria a infraestrutura vazia em outra região em cerca de 30 minutos
(`TF_VAR_region=... ./deploy.sh`). Os dados não vão junto: backups do RDS,
imagens e o próprio state ficam em São Paulo. Sem a região de volta, a
plataforma recomeça com o catálogo inicial e sem pedidos.

Melhorias, em ordem de prioridade para uma startup real:

1. Copiar os backups do RDS para outra região.
2. Replicar o bucket do state e as imagens do ECR.
3. Ensaiar a restauração do banco e medir RTO e RPO.
4. HTTPS com domínio próprio e failover de DNS no Route 53.
5. Migrações versionadas de schema e autenticação na API.

**Quando a plataforma falha, quais são os riscos e como recuperar?** Dentro de
uma região, a plataforma tem alta disponibilidade: perda de task, de instância,
de zona e failover do banco se resolvem sozinhos, em minutos e sem perder
dados. Ela não tem recuperação de desastres completa. Contra a perda da região
ou a corrupção de dados, o que existe é recriar a infraestrutura por código e
restaurar manualmente backups de até 7 dias, que ficam na mesma região. Alta
disponibilidade mantém o serviço no ar quando um componente falha.
Recuperação de desastres devolve serviço e dados depois que tudo falhou, com
tempo e perda máximos definidos e ensaiados, e isso ainda é proposta.

## Limites conhecidos

- **O gargalo da frota é a interface de rede.** A t3.medium aceita 2 tasks
  `awsvpc` e a família t3 não tem ENI trunking. Paga-se por CPU e memória que
  não podem ser usadas. As saídas seriam um tipo com trunking (m5, c5) ou o modo
  `bridge`, que perde o security group por task.
- **A frota não encolhe sozinha depois de um pico.** O Capacity Provider só
  remove instância vazia, e o ECS não reagrupa tasks em execução. A
  consolidação é manual ([RUNBOOK, asg-at-max](docs/RUNBOOK.md#asg-at-max)).
- **Sem HTTPS por padrão.** Sem domínio e certificado, o cookie de sessão não é
  `Secure`.
- **Schema por `create_all`**, sem migrações versionadas.
- **`/produtos` sem autenticação.** Por isso a porta 8000 fica fechada por
  padrão.
- **Reservas de CPU e memória não foram medidas em `sa-east-1`.** São os valores
  do ambiente manual em Ohio, onde a CPU da API não passou de 30% sob carga.

## Onde cada requisito está no código

Mapa completo, com o recurso Terraform de cada linha: [docs/REQUISITOS.md](docs/REQUISITOS.md).

| Requisito | Onde |
| --- | --- |
| ECS sobre EC2, Fargate não é a capacidade principal | `terraform/ecs_services.tf`, `terraform/ecs_cluster.tf` |
| Imagens no ECR da região | `terraform/ecr.tf`, `terraform/scripts/build-push.sh` |
| ASG + Capacity Provider, dois níveis de escala | `terraform/ecs_cluster.tf`, `terraform/modules/ecs-service/main.tf` |
| VPC em 2 AZs, sub-redes públicas e privadas, ALB | `terraform/network.tf`, `terraform/security.tf`, `terraform/alb.tf` |
| Health checks e substituição de tasks e instâncias | `terraform/ecs_services.tf`, `terraform/alb.tf`, `backend/worker.py` |
| Persistência gerenciada | `terraform/database.tf`, `terraform/files/db_init.py` |
| Mensageria com retentativa, duplicidade e DLQ | `terraform/messaging.tf`, `backend/pedidos.py`, `backend/worker.py` |
| Segredos e IAM de menor privilégio | `terraform/secrets.tf`, `terraform/modules/ecs-service/main.tf`, `terraform/db_init.tf` |
| Logs, métricas e alarmes | `terraform/observability.tf` |
| Vendedor de IA com funções reais | `chat-service/app/ai.py`, `chat-service/app/checkout.py` |
| Terraform completo, com state remoto e portável entre regiões | `terraform/`, `terraform/bootstrap/`, `terraform/deploy.sh` |

## Estrutura do repositório e documentação

```
backend/          API de pedidos (FastAPI) e worker SQS
chat-service/     chat com Gemini, sessão e confirmação de compra
frontend/         interface React servida por Nginx
terraform/        infraestrutura AWS completa, deploy.sh e destroy.sh
scripts/          execução e verificação locais
docs/             requisitos, runbook, implantação, roteiro do vídeo, evidências
```

| Documento | Responde |
| --- | --- |
| [terraform/README.md](terraform/README.md) | como implantar, testar em 5 níveis, operar, custo e destruição |
| [docs/REQUISITOS.md](docs/REQUISITOS.md) | onde cada requisito do enunciado está, com o dimensionamento da frota |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | o que cada um dos 16 alarmes significa e como agir |
| [docs/IMPLANTACAO.md](docs/IMPLANTACAO.md) | contrato entre os serviços, variáveis, sessão e CSRF |
| [docs/VIDEO_ENTREGA.md](docs/VIDEO_ENTREGA.md) | roteiro do vídeo, etapa por etapa |
| [docs/evidencias/README.md](docs/evidencias/README.md) | testes de failover e carga do ambiente manual em Ohio |
| [chat-service/README.md](chat-service/README.md) | ferramentas da IA, confirmação segura, endpoints |
| [frontend/README.md](frontend/README.md) | interface, modo demonstração, contrato com o chat |