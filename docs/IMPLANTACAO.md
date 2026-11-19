# Entrega técnica para integração e implantação

## Componentes e imagens

| Componente | Construção | Porta interna | Saúde | Dependências |
| --- | --- | --- | --- | --- |
| Frontend | `docker build -t insper-eats-frontend ./frontend` | 8080 | GET /healthz | Chat Service |
| Chat | `docker build -t insper-eats-chat ./chat-service` | 8001, variável PORT | GET /health | PostgreSQL, API de pedidos, Gemini |
| API existente | Dockerfile.api da Pessoa 1 | 8000 | GET /health | PostgreSQL |
| Worker existente | Dockerfile.worker da Pessoa 1 | sem HTTP | arquivo `/tmp/worker-heartbeat`, tocado a cada volta do laço; falha após 120 s sem toque | PostgreSQL e SQS |

Os comandos de construção partem da raiz do repositório. As imagens da Pessoa 2 executam
sem usuário root, excluem arquivos .env e não incorporam chaves. O frontend usa build
estático servido pelo Nginx; não usa `npm run dev` em produção. O chat usa dois processos
Uvicorn por padrão. WEB_CONCURRENCY permite ajustar essa quantidade ao dimensionamento ECS.
Não há login nem senha padrão de usuário na aplicação.

## Execução local conjunta

`scripts/start-local.ps1` aplica compose.yaml + compose.app.yaml e gera .env.docker a
partir das credenciais locais existentes, com escape adequado para a URL PostgreSQL.
No Linux/macOS, `scripts/start-local.sh` faz o mesmo sem .env.docker: usa APP_DATABASE_URL
do .env da raiz e cadastra um catálogo inicial quando `/produtos` está vazio.
O arquivo base e os Dockerfiles da Pessoa 1 permanecem intactos.

Banco e API iniciam antes do chat, com verificações de saúde. O frontend só inicia depois
de o chat ficar saudável. Os volumes PostgreSQL são preservados. Alterar POSTGRES_PASSWORD
no .env não muda a senha de um banco que já foi inicializado: mantenha as credenciais atuais.

Para escolher portas:

```powershell
.\scripts\start-local.ps1 -FrontendPort 8080 -ApiPort 8002 -ChatPort 8003
```

```bash
FRONTEND_PORT=8080 API_PORT=8002 CHAT_PORT=8003 ./scripts/start-local.sh
```

Para consultar logs, na raiz do repositório:

```powershell
docker compose --env-file .env --env-file .env.docker -f compose.yaml -f compose.app.yaml logs --tail 80 chat
```

Para parar sem apagar dados:

```powershell
docker compose --env-file .env --env-file .env.docker -f compose.yaml -f compose.app.yaml stop
```

Com o `start-local.sh`, os mesmos comandos dispensam os dois `--env-file`.
Não execute `down -v` no ambiente normal: isso remove os volumes do banco.

## Variáveis para o ECS

| Variável | Onde | Valor/objetivo |
| --- | --- | --- |
| CHAT_DATABASE_URL | chat, segredo | URL PostgreSQL persistente, com driver postgresql+psycopg |
| GEMINI_API_KEY | chat, segredo | Chave do projeto do Google AI Studio |
| AI_PROVIDER | chat | gemini em operação; commands somente para roteiro de desenvolvimento |
| GEMINI_MODEL | chat | Modelo principal; padrão gemini-flash-lite-latest |
| GEMINI_FALLBACK_MODELS | chat | Modelos reserva, em ordem, usados quando o principal está indisponível (503, 429, timeout) |
| AI_FALLBACK_COMMANDS | chat | true: com todos os modelos fora, responde pelo roteiro básico com aviso, em vez de erro |
| AI_TIMEOUT | chat | Orçamento total de IA, até 120 segundos |
| ORDERS_API_URL | chat | Endereço interno da API de pedidos |
| ORDERS_API_TIMEOUT | chat | Prazo independente da API, padrão 5 segundos |
| ORDERS_INTERNAL_TOKEN | chat e API, segredo | Token compartilhado enviado em X-Internal-Token; sem ele /pedidos responde 503 |
| DATABASE_URL | API e worker, segredo | URL PostgreSQL do banco de pedidos, com driver postgresql+psycopg |
| DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT | API e worker | Pool de conexões; padrão 10, 5 e 5 segundos. No ECS o worker usa 2 e 1 |
| SQS_QUEUE_NAME | worker | Nome da fila de pedidos |
| AWS_REGION | worker | Região do SQS; o código não fixa região |
| COOKIE_SECURE | chat | true no endereço HTTPS publicado; false somente no HTTP local |
| SESSION_DAYS | chat | Validade da sessão anônima, padrão 30 dias |
| APP_ORIGINS | chat | Origem pública exata, com esquema e porta se houver, separada por vírgulas |
| PORT | chat | Porta de escuta, padrão 8001 |
| WEB_CONCURRENCY | chat | Processos por container, padrão 2 |
| CHAT_UPSTREAM | frontend/Nginx | URL interna do chat, exemplo http://chat:8001 |
| VITE_CHAT_MODE | build frontend | api |
| VITE_CHAT_API_URL | build frontend | /api para usar o mesmo domínio |

No ECS, o Terraform entrega os segredos pelo Secrets Manager: a task definition guarda
só o ARN, e a execution role de cada serviço lê apenas os secrets dele
(`terraform/secrets.tf`, `terraform/ecs_services.tf`). O valor de ORDERS_INTERNAL_TOKEN é
gerado pelo Terraform e entregue igual à API e ao chat.
Variáveis VITE_* são públicas; nunca colocar chaves ou senhas nelas. O frontend deve
encaminhar o cookie e o cabeçalho X-CSRF-Token ao Chat Service. Não exponha o banco nem
a API de pedidos diretamente ao público; a API existente não implementa autorização de comprador.

## Rede, caminhos e tempos

O navegador chama `/api/chat/...`; o Nginx remove `/api/` e encaminha `/chat/...` ao chat.
O Nginx resolve o endereço de CHAT_UPSTREAM novamente usando o DNS do container,
permitindo substituição do serviço. DNS_RESOLVER pode sobrescrever esse servidor.
Na AWS, CHAT_UPSTREAM precisa apontar para um endereço interno realmente configurado
pela infraestrutura; o nome chat do Docker Compose não é criado automaticamente no ECS.
O Terraform cria esses endereços no Cloud Map: `http://chat.insper-eats-sp.internal:8001`
para o frontend e `http://api.insper-eats-sp.internal:8000` em ORDERS_API_URL
(`terraform/locals.tf`).
O backend de pedidos mantém `/produtos` e `/pedidos`, consumidos somente pelo chat.
Não encaminhe diretamente `/api/chat` sem remover o prefixo /api, pois o serviço não o registra.
O exemplo publica tudo por um único domínio para evitar configuração CORS e compartilhamento
de cookies entre origens. No ALB/proxies, configurar um prazo de inatividade compatível
com a espera de até 150 segundos. O timeout de 120 segundos da IA é para o ciclo inteiro.

Reservas, limites e políticas de escalabilidade estão definidos no Terraform
(`terraform/variables.tf` e `terraform/ecs_services.tf`): cada task tem 256 CPU units,
limite de 512 MiB e reserva de 384 MiB; cada serviço vai de 2 a 4 tasks, por CPU a 60%
(API, chat e frontend) ou por backlog da fila (worker). A conta e os limites conhecidos
estão em [REQUISITOS.md](REQUISITOS.md). Esses valores ainda não foram calibrados por
medição de carga em `sa-east-1`. O chat roda com `WEB_CONCURRENCY=2` e `stop_timeout`
de 170 segundos, para concluir respostas em andamento na troca de task.

## Persistência e inicialização

Tabelas exclusivas: chat_conversa, chat_mensagem, chat_requisicao, chat_confirmacao,
chat_sessao, chat_acesso_conversa. Catálogo, pedidos e estoque continuam sob responsabilidade
da API existente. A criação aditiva das tabelas é serializada com advisory lock PostgreSQL
para evitar corrida na inicialização de múltiplos workers. Não são alteradas colunas antigas.
Para evoluções futuras do schema, adotar migrações versionadas antes de mudar colunas.

Preferir banco/usuário exclusivos do chat no RDS. Com banco compartilhado localmente,
o código não importa os modelos do backend nem escreve em suas tabelas diretamente.
No Terraform, o chat tem banco e usuário próprios (`insper_eats_chat` / `insper_chat`),
criados pela task db-init, e o RDS mantém backups automáticos de 7 dias
(`terraform/database.tf`). A restauração não foi ensaiada.

## Sessão, CSRF e autorização

POST /chat/sessao cria/recupera cookie HttpOnly, SameSite=Lax e devolve csrf_token.
Mutações seguintes exigem X-CSRF-Token. Origens informadas pelo navegador são verificadas
contra APP_ORIGINS. GETs também exigem sessão. O token de sessão é armazenado como hash
no PostgreSQL, sem depender de memória de uma task ou arquivo local. Sessão expirada ou
encerrada deixa de acessar as conversas antigas. POST /chat/sessao/encerrar revoga a sessão.

Uma conversa só pode ser lida, alterada ou confirmada por sua sessão proprietária.
Consultar um pedido por número também verifica o vínculo com a sessão, inclusive pela IA.
GET /chat/pedidos lista pedidos de todas as conversas da sessão. O identificador de conversa
ou a session_reference não funcionam como credencial. O acesso de outra sessão retorna 404.

Esta é identificação anônima do navegador. Para login institucional, recuperação autônoma
de conta e histórico entre dispositivos, ainda será necessário integrar um provedor de identidade.

## Recuperar uma conversa anterior à proteção

Os dados antigos são preservados. A recuperação é administrativa e local; não há endpoint
público para alguém tomar posse de uma conversa pelo UUID.

1. Abra a interface no navegador que deve ser o proprietário.
2. No console do navegador, execute este trecho para obter a referência pública da sessão:

```javascript
fetch('/api/chat/sessao', {method: 'POST'})
  .then(response => response.json())
  .then(session => console.log(session.session_reference))
```

3. Na pasta chat-service, use o Python local:

```powershell
.\.venv\Scripts\python.exe scripts/claim_legacy.py --conversation UUID_DA_CONVERSA --session-reference REFERENCIA_DA_SESSAO
```

O UUID anterior é mantido em localStorage, na chave `insper-eats:conversation:/api:previous`,
quando a interface não consegue reabrir a conversa antiga. Para restaurar essa conversa
na interface após a vinculação, ajuste a chave `insper-eats:conversation:/api` para o UUID
recuperado e atualize a página. Seus pedidos aparecerão na lista da sessão após a vinculação.
O script recusa conversas que já tenham proprietário e não transfere sessões.
No Docker, o mesmo script está em /app/scripts/claim_legacy.py e usa as variáveis da task.

## Observabilidade

Os logs da aplicação são JSON com timestamp, level, logger, request_id e message.
Cada resposta inclui X-Request-ID; UUID válido enviado pelo cliente é preservado.
Os eventos incluem tempos HTTP, rodadas de IA, retentativas e erros do provedor. Não
registram corpo de mensagem, cookies, CSRF, chave ou URL de banco com credenciais.
No ECS, os logs dos quatro serviços vão para o CloudWatch pelo driver `awslogs`, nos
grupos `/ecs/insper-eats-sp/<serviço>`, com retenção de 30 dias
(`terraform/modules/ecs-service/main.tf`). O Nginx do frontend gera o X-Request-ID de
cada requisição; o chat o registra e o repassa à API de pedidos, que o grava na linha
`pedido_criado`. Filtros de métrica sobre esses logs alimentam os alarmes de falhas da
aplicação (`terraform/observability.tf`); as consultas para seguir um request_id estão
em [RUNBOOK.md](RUNBOOK.md).

Health checks não fazem chamada paga à IA. `ia_configurada=true` significa apenas
presença da chave/modelo, não comprova validade, quota ou disponibilidade do Google.

## Roteiro de demonstração conjunta

1. Consultar catálogo real pelo chat e preparar uma compra.
2. Confirmar pelo botão e mostrar pedido/estoque na API.
3. Repetir a confirmação e comprovar que o estoque não foi debitado outra vez.
4. Rodar worker/SQS da Pessoa 1 e ver status mudar na interface em aproximadamente 10 segundos.
5. Reiniciar task do chat e recuperar conversa com o mesmo cookie.
6. Demonstrar que outro navegador não acessa a conversa/pedido.
7. Demonstrar escalonamento/substituição ECS/EC2, persistência e alarmes com a Pessoa 1.
8. Repetir a implantação em São Paulo por Terraform, com imagens e parâmetros regionais próprios.

O worker/SQS real e os testes de infraestrutura não fazem parte do compose de verificação.
