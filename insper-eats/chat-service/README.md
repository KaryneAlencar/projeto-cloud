# Chat Service — Pessoa 2

FastAPI na porta 8001. Consome por HTTP a API da Pessoa 1 (porta 8000) e
persiste conversas, mensagens e preparação de compra em tabelas próprias no PostgreSQL.
Não importa o backend existente, não altera suas tabelas e não cria pedidos nesta etapa.
O diálogo atual usa comandos explícitos; ainda não há IA generativa.

## Executar no PowerShell

Na pasta `insper-eats/chat-service`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Execute os comandos de criação/cópia somente no primeiro preparo. Se o ambiente e o
`.env` já existirem, basta ativar o ambiente. Edite o `.env` com a conexão do banco local.
Nunca versione esse arquivo. O arquivo do chat é independente de `insper-eats/.env`:

```dotenv
CHAT_DATABASE_URL=postgresql+psycopg://USUARIO:SENHA@127.0.0.1:5433/NOME_DO_BANCO
ORDERS_API_URL=http://127.0.0.1:8000
ORDERS_API_TIMEOUT=5
```

Pode usar a mesma instância PostgreSQL local: o chat cria somente `chat_conversa`,
`chat_mensagem` e `chat_requisicao`. Para isolamento adicional, use um banco e usuário
próprios e conceda somente acesso a esse banco. A configuração exige PostgreSQL.
As tabelas são criadas na inicialização; alterações futuras de schema precisarão de migrações.

Com Docker Desktop aberto, suba o banco na pasta `insper-eats` com `docker compose up -d db`.
Depois, na pasta `chat-service`, execute:

```powershell
python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8001 --reload
```

Documentação interativa: http://127.0.0.1:8001/docs
Saúde do chat/banco: http://127.0.0.1:8001/health
A saúde verifica o banco sem depender da API de pedidos. Uma falha desta retorna
503 na consulta, sem descartar nem duplicar as mensagens da tentativa.

Mantenha a API da Pessoa 1 executando em outro terminal na porta 8000.
Sua base de produtos e pedidos continua sendo administrada exclusivamente por essa API.
O chat não cadastra produtos nem inventa resultados se o catálogo estiver vazio.

## Conectar a interface

Crie/edite `frontend/.env.local`:

```dotenv
VITE_CHAT_MODE=api
VITE_CHAT_API_URL=/api
```

Reinicie o Vite (`npm run dev` na pasta frontend). O proxy existente encaminha `/api`
para o chat na porta 8001. Teste “Ver o cardápio”: os dados serão reais.
Não habilitamos automaticamente o modo integrado para não interromper a demonstração.
Não precisa de chaves de IA ou credenciais AWS nesta etapa.

## Endpoints e roteiro sem IA

| Método | Caminho | Função |
| --- | --- | --- |
| GET | /health | Estado do chat e banco |
| GET | /chat/produtos | Catálogo real, via API de pedidos |
| GET | /chat/pedidos/{id} | Pedido real, via API de pedidos |
| POST | /chat/conversas | Cria conversa e saudação persistida |
| GET | /chat/conversas/{id} | Histórico e seleção persistidos |
| POST | /chat/conversas/{id}/mensagens | Recebe conteudo e mensagem_id (UUID) |
| POST | /chat/conversas/{id}/confirmar | Retorna 501: criação comercial pendente |

Os endpoints de conversa retornam o contrato descrito em `frontend/README.md`,
com `confirmacao_habilitada: false`. Mensagens incluem `criado_em` em ISO 8601.
O identificador da conversa é UUID. Os valores monetários da resposta de conversa
são números; o cálculo da estimativa usa Decimal no servidor. A estimativa não reserva
estoque nem substitui o preço definitivo da API de pedidos.

Comandos aceitos nesta base provisória:

- `Ver o cardápio`: consulta catálogo, preço e estoque reais.
- `Quero 2 brownies`: prepara um único produto pelo nome real (plural simples).
- `Selecionar 1:2, 2:1`: seleciona pelo ID e quantidade; substitui a seleção anterior.
- `Meu nome é Ana` e `Entrega: sala 512, prédio 2`: completam a preparação.
- `Pedido 4`: consulta o pedido real 4.
- `cancelar`: limpa a seleção e sua chave.

Uma alteração da seleção/dados gera nova versão (`compra.id`) e chave de idempotência,
persistidas atomicamente com as mensagens. Uma retentativa da mesma mensagem conserva
o resultado e a chave. `mensagem_id` repetido com conteúdo diferente retorna 409.
Cada conversa é bloqueada no PostgreSQL durante o processamento para serializar
mensagens concorrentes. As tabelas de catálogo, estoque e pedidos não são acessadas.
O estado pode ser recuperado após reinício e entre processos, sem depender de memória.

## Testes

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Sem `CHAT_TEST_DATABASE_URL`, os testes PostgreSQL serão explicitamente ignorados;
somente testes do cliente HTTP serão executados. Para integração completa, configure
essa variável com uma URL PostgreSQL local de teste (mesmo formato de CHAT_DATABASE_URL).
Para usar a conexão do `.env` local nos testes, execute `python tests/run_postgres.py`.
Esse comando usa CHAT_TEST_DATABASE_URL quando definida, ou CHAT_DATABASE_URL do `.env`.

Os testes criam e removem somente um schema aleatório `chat_test_*` por caso e simulam
as respostas da API de pedidos, mantendo os dados existentes intactos. É necessário
privilégio para criar schema. Não use banco de produção para testes.

Cobertura: persistência após nova instância do serviço, chave persistida, duplicidade
concorrente, isolamento de conversas, rollback/retentativa após falha HTTP, estoque
insuficiente, cancelamento, consultas de catálogo/pedido e respostas HTTP inválidas.

## Próxima etapa

Adicionar agente de IA com ferramentas reais e confirmação comercial idempotente.
O endpoint de confirmação ainda não chama `POST /pedidos`: a chave já está persistida
para essa implementação posterior. Não confundir preparação de compra com compra criada.
A API ainda não possui autenticação; mantenha o serviço local até definir identidade
e autorização por conversa/pedido antes de expor o projeto na AWS.
