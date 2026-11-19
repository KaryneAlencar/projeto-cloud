# Entrega técnica para integração e implantação

## Componentes e imagens

| Componente | Construção | Porta interna | Saúde | Dependências |
| --- | --- | --- | --- | --- |
| Frontend | `docker build -t insper-eats-frontend ./frontend` | 8080 | GET /healthz | Chat Service |
| Chat | `docker build -t insper-eats-chat ./chat-service` | 8001, variável PORT | GET /health | PostgreSQL, API de pedidos, Gemini |
| API existente | Dockerfile.api da Pessoa 1 | 8000 | GET /health | PostgreSQL |
| Worker existente | Dockerfile.worker da Pessoa 1 | sem HTTP | a definir pela Pessoa 1 | PostgreSQL e SQS |

Os comandos de construção partem da pasta insper-eats. As imagens da Pessoa 2 executam
sem usuário root, excluem arquivos .env e não incorporam chaves. O frontend usa build
estático servido pelo Nginx; não usa `npm run dev` em produção. O chat usa dois processos
Uvicorn por padrão. WEB_CONCURRENCY permite ajustar essa quantidade ao dimensionamento ECS.
Não há login nem senha padrão de usuário na aplicação.

## Execução local conjunta

`scripts/start-local.ps1` aplica compose.yaml + compose.app.yaml e gera .env.docker a
partir das credenciais locais existentes, com escape adequado para a URL PostgreSQL.
O arquivo base e os Dockerfiles da Pessoa 1 permanecem intactos.

Banco e API iniciam antes do chat, com verificações de saúde. O frontend só inicia depois
de o chat ficar saudável. Os volumes PostgreSQL são preservados. Alterar POSTGRES_PASSWORD
no .env não muda a senha de um banco que já foi inicializado: mantenha as credenciais atuais.

Para escolher portas:

```powershell
.\scripts\start-local.ps1 -FrontendPort 8080 -ApiPort 8002 -ChatPort 8003
```

Para consultar logs, na pasta insper-eats:

```powershell
docker compose --env-file .env --env-file .env.docker -f compose.yaml -f compose.app.yaml logs --tail 80 chat
```

Para parar sem apagar dados:

```powershell
docker compose --env-file .env --env-file .env.docker -f compose.yaml -f compose.app.yaml stop
```

Não execute `down -v` no ambiente normal: isso remove os volumes do banco.

## Variáveis para o ECS

| Variável | Onde | Valor/objetivo |
| --- | --- | --- |
| CHAT_DATABASE_URL | chat, segredo | URL PostgreSQL persistente, com driver postgresql+psycopg |
| GEMINI_API_KEY | chat, segredo | Chave do projeto do Google AI Studio |
| AI_PROVIDER | chat | gemini em operação; commands somente para roteiro de desenvolvimento |
| GEMINI_MODEL | chat | Modelo disponível na conta; exemplo gemini-2.5-flash |
| AI_TIMEOUT | chat | Orçamento total de IA, até 120 segundos |
| ORDERS_API_URL | chat | Endereço interno da API de pedidos |
| ORDERS_API_TIMEOUT | chat | Prazo independente da API, padrão 5 segundos |
| COOKIE_SECURE | chat | true no endereço HTTPS publicado; false somente no HTTP local |
| SESSION_DAYS | chat | Validade da sessão anônima, padrão 30 dias |
| APP_ORIGINS | chat | Origem pública exata, com esquema e porta se houver, separada por vírgulas |
| PORT | chat | Porta de escuta, padrão 8001 |
| WEB_CONCURRENCY | chat | Processos por container, padrão 2 |
| CHAT_UPSTREAM | frontend/Nginx | URL interna do chat, exemplo http://chat:8001 |
| VITE_CHAT_MODE | build frontend | api |
| VITE_CHAT_API_URL | build frontend | /api para usar o mesmo domínio |

No ECS, fornecer segredos por Secrets Manager/Parameter Store e permissões da task.
Variáveis VITE_* são públicas; nunca colocar chaves ou senhas nelas. O frontend deve
encaminhar o cookie e o cabeçalho X-CSRF-Token ao Chat Service. Não exponha o banco nem
a API de pedidos diretamente ao público; a API existente não implementa autorização de comprador.

## Rede, caminhos e tempos

O navegador chama `/api/chat/...`; o Nginx remove `/api/` e encaminha `/chat/...` ao chat.
O Nginx resolve o endereço de CHAT_UPSTREAM novamente usando o DNS do container,
permitindo substituição do serviço. DNS_RESOLVER pode sobrescrever esse servidor.
Na AWS, CHAT_UPSTREAM precisa apontar para um endereço interno realmente configurado
pela infraestrutura; o nome chat do Docker Compose não é criado automaticamente no ECS.
O backend de pedidos mantém `/produtos` e `/pedidos`, consumidos somente pelo chat.
Não encaminhe diretamente `/api/chat` sem remover o prefixo /api, pois o serviço não o registra.
O exemplo publica tudo por um único domínio para evitar configuração CORS e compartilhamento
de cookies entre origens. No ALB/proxies, configurar um prazo de inatividade compatível
com a espera de até 150 segundos. O timeout de 120 segundos da IA é para o ciclo inteiro.

Reservas/limites de CPU/memória e políticas de escalabilidade devem ser definidos pela
Pessoa 1 conforme a capacidade EC2 e medições de carga. O padrão de dois processos é
configurável e não equivale a uma recomendação de dimensionamento final para ECS.

## Persistência e inicialização

Tabelas exclusivas: chat_conversa, chat_mensagem, chat_requisicao, chat_confirmacao,
chat_sessao, chat_acesso_conversa. Catálogo, pedidos e estoque continuam sob responsabilidade
da API existente. A criação aditiva das tabelas é serializada com advisory lock PostgreSQL
para evitar corrida na inicialização de múltiplos workers. Não são alteradas colunas antigas.
Para evoluções futuras do schema, adotar migrações versionadas antes de mudar colunas.

Preferir banco/usuário exclusivos do chat no RDS. Com banco compartilhado localmente,
o código não importa os modelos do backend nem escreve em suas tabelas diretamente.
Configurar backup e restauração no serviço persistente com a Pessoa 1.

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
A Pessoa 1 pode enviá-los ao CloudWatch pelo driver de logs das tasks.

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
