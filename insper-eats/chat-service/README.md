# Chat Service — Pessoa 2

FastAPI na porta 8001. Conversas no PostgreSQL, IA Gemini e consultas/compras pela
API existente da Pessoa 1 na porta 8000. Não altera arquivos nem tabelas do backend.

## Configuração e execução

Na pasta `insper-eats/chat-service`, ative `.venv` e instale `requirements.txt`.
No primeiro preparo, crie o ambiente com `python -m venv .venv` e copie
`.env.example` para `.env`. Se já existirem, preserve a configuração local.

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app.main:create_app --factory --reload --host 127.0.0.1 --port 8001
```

Configure no `.env` exclusivo do chat (nunca no frontend):

```dotenv
CHAT_DATABASE_URL=postgresql+psycopg://USUARIO:SENHA@127.0.0.1:5433/NOME_DO_BANCO
ORDERS_API_URL=http://127.0.0.1:8000
ORDERS_API_TIMEOUT=5
AI_PROVIDER=gemini
GEMINI_API_KEY=SUA_CHAVE_LOCAL
GEMINI_MODEL=gemini-2.5-flash
AI_TIMEOUT=15
```

Crie sua chave em https://aistudio.google.com/apikey e coloque-a somente no .env local.
O modelo é configurável e precisa estar disponível na conta do provedor.
A faixa gratuita tem cotas por conta/projeto/modelo; chave criada não significa uso ilimitado.
Confira disponibilidade e cotas no Google AI Studio: https://ai.google.dev/gemini-api/docs/pricing
Conteúdo da faixa gratuita pode ser usado para melhorar produtos do Google; use dados fictícios
na demonstração e confira os termos do provedor antes de usar conversas com dados pessoais.
Sem chave/modelo, o serviço inicia e /health informa ia_configurada=false;
a mensagem enviada à IA retorna 503 com orientação para configurar. Não existe
fallback silencioso para respostas simuladas. Reinicie após alterar o `.env`.
`AI_PROVIDER=commands` permite testar comandos explícitos sem chamada à IA,
mas as compras desse modo também são REAIS após clicar em Confirmar pedido.

Abra http://127.0.0.1:8001/docs e http://127.0.0.1:8001/health.
A saúde verifica o banco; não faz chamada paga à IA nem teste de disponibilidade do provedor.
Mantenha PostgreSQL e a API da Pessoa 1 em execução. Na pasta `insper-eats`,
`docker compose up -d db` inicia o banco configurado no compose existente.

## Interface

Em `frontend/.env.local`:

```dotenv
VITE_CHAT_MODE=api
VITE_CHAT_API_URL=/api
```

Reinicie o Vite. O proxy local encaminha /api para a porta 8001.
Converse naturalmente: 'Quais produtos têm até R$ 20?', escolha itens, informe
nome/local e revise o resumo. O botão Confirmar pedido cria uma compra REAL.
Escrever 'sim' na conversa não cria compra. A IA não possui ferramenta de confirmação.
O frontend no modo demo continua separado, com compras apenas simuladas.

## Ferramentas da IA

- listar_produtos: consulta GET /produtos com preços e estoque reais.
- consultar_pedido: consulta GET /pedidos/{id}.
- preparar_compra: valida IDs e quantidades contra o catálogo, calcula estimativa com Decimal.
- atualizar_entrega: atualiza os dados fornecidos e cria nova versão da seleção.
- cancelar_selecao: limpa apenas uma seleção não confirmada.

O ciclo de ferramentas usa a API nativa Gemini generateContent com schemas de funções,
validação local por Pydantic, no máximo seis rodadas e prazo total configurável.
As respostas nativas e thoughtSignature são preservadas durante cada ciclo de ferramentas;
textos internos marcados como thought não são exibidos. Chave transmitida em cabeçalho,
nunca na URL. Erros de cota 429 são informados sem repetição automática. Histórico recente (até 30 mensagens), estado da
seleção e resultados das ferramentas são enviados ao provedor de IA. Não coloque segredos
nas conversas. Chaves não são enviadas ao frontend nem registradas em logs.
A conversa completa permanece no PostgreSQL. Se a IA falhar após preparar uma seleção,
a transação local é revertida: nenhuma preparação parcial é persistida.

Referência da implementação: https://ai.google.dev/api/generate-content
Ferramentas: https://ai.google.dev/gemini-api/docs/function-calling

OpenAI continua como alternativa opcional: defina AI_PROVIDER=openai, OPENAI_API_KEY e
OPENAI_MODEL. Não há fallback automático entre provedores. A propriedade ia_configurada
do /health verifica apenas a presença de chave/modelo do provedor selecionado, sem
chamada externa. O status não comprova validade da chave ou saldo/cota.

## Confirmação segura

POST /chat/conversas/{id}/confirmar recebe {"compra_id":"uuid-da-versao-exibida"}.
O servidor valida seleção, nome, entrega, versão e chave persistida. Antes da primeira
tentativa consulta estoque e preços atuais. Se o preço mudou, atualiza o resumo com nova
versão e retorna a conversa SEM comprar. O usuário precisa revisar e confirmar novamente.

Antes de enviar POST /pedidos, o chat grava um payload imutável em chat_confirmacao e
congela a seleção com status confirmando. Esse commit ocorre ANTES do efeito externo.
Se houver timeout, resposta inválida, erro 5xx ou queda do processo, a seleção permanece
congelada: não é permitido editar/cancelar a tentativa de resultado incerto. Use Repetir
confirmação para reenviar exatamente o mesmo payload e chave. A API existente aplica
sua idempotência, recuperando o pedido anterior sem novo débito de estoque.

Confirmações concorrentes são serializadas por bloqueio de linha PostgreSQL. Depois de
registrado, repetições retornam a conversa sem novo POST. Respostas definitivas 400/404/
409/422 da API recusam a tentativa e liberam uma nova versão para revisão. O número,
status, preços e total definitivo do pedido vêm da resposta real da API.

A API existente calcula preços dentro da sua própria transação. A consulta prévia reduz
mudanças inesperadas, mas não fornece garantia transacional de preço entre a consulta
e POST /pedidos: um contrato de cotação vinculante exigiria evolução conjunta dessa API.
O status do worker pode evoluir; consulte o pedido para ver o status real atualizado.

## Persistência e endpoints

Tabelas exclusivas: chat_conversa, chat_mensagem, chat_requisicao, chat_confirmacao.
A nova tabela é criada automaticamente na inicialização; as tabelas existentes não mudam.
Evoluções futuras de colunas precisarão de migrações.

| Método | Caminho | Função |
| --- | --- | --- |
| GET | /health | Saúde do chat/banco e configuração de IA |
| GET | /chat/produtos | Catálogo real |
| GET | /chat/pedidos/{id} | Pedido real |
| POST | /chat/conversas | Criar conversa |
| GET | /chat/conversas/{id} | Recuperar histórico e seleção |
| POST | /chat/conversas/{id}/mensagens | conteudo e mensagem_id UUID |
| POST | /chat/conversas/{id}/confirmar | Confirma versão da seleção |

Mensagens duplicadas não são executadas novamente e retornam o estado ATUAL da conversa,
evita-se ressuscitar uma seleção antiga após confirmação. Mesmo ID com outro texto retorna
409. O contrato da interface usa status preparando, confirmando e confirmado. confirmado
significa compra registrada; pedido_status contém o status real retornado pelo backend.

No modo commands: 'Ver o cardápio', 'Quero 2 brownies', 'Selecionar 1:2, 2:1',
'Meu nome é Ana', 'Entrega: sala 512, prédio 2', 'Pedido 4' e 'cancelar'.

## Testes

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python tests/run_postgres.py
```

O primeiro comando de testes ignora integração se CHAT_TEST_DATABASE_URL não existir.
run_postgres.py usa essa variável ou CHAT_DATABASE_URL do .env. Os testes criam/removem
schemas aleatórios chat_test_*; nunca usam dados comerciais reais. API de pedidos e IA
são simuladas; o PostgreSQL é real. Não há custo de IA nem pedidos reais nos testes.
Cobertura inclui concorrência, confirmação explícita, timeout após compra, recuperação
após reinício com payload idêntico, preço alterado, revisão de versão, rollback da IA,
ferramentas com catálogo, isolamento e duplicidade de mensagens.

O sistema ainda não possui autenticação por conversa/pedido. Mantenha o serviço local
até implementar identidade e autorização antes da exposição na AWS.
