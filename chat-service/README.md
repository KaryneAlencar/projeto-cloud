# Chat Service — Pessoa 2

FastAPI na porta 8001. Conversas no PostgreSQL, IA Gemini e consultas/compras pela
API existente da Pessoa 1 na porta 8000. Não altera arquivos nem tabelas do backend.

## Configuração e execução

Na pasta `chat-service`, ative `.venv` e instale `requirements.txt`.
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
ORDERS_INTERNAL_TOKEN=MESMO_VALOR_DA_API
AI_PROVIDER=gemini
GEMINI_API_KEY=SUA_CHAVE_LOCAL
GEMINI_MODEL=gemini-flash-lite-latest
GEMINI_FALLBACK_MODELS=gemini-3.5-flash-lite,gemini-3.8-flash
AI_FALLBACK_COMMANDS=true
AI_TIMEOUT=120
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
```

`DB_POOL_SIZE` (padrão 5) e `DB_MAX_OVERFLOW` (padrão 10) definem o pool de conexões por
processo: no máximo 15 conexões simultâneas ao PostgreSQL com os padrões. Se o pool estiver
cheio por 5 segundos (`pool_timeout`), a requisição recebe 503 com mensagem genérica em vez
de ficar na fila. Dimensione `processos x (DB_POOL_SIZE + DB_MAX_OVERFLOW)` abaixo do
`max_connections` do banco, reservando uma conexão por processo para o /health.

Crie sua chave em https://aistudio.google.com/apikey e coloque-a somente no .env local.
O modelo é configurável e precisa estar disponível na conta do provedor.
`GEMINI_MODEL` (padrão `gemini-flash-lite-latest`) é o modelo principal e
`GEMINI_FALLBACK_MODELS` (padrão `gemini-3.5-flash-lite,gemini-3.8-flash`) lista as reservas,
separadas por vírgula e tentadas em ordem; vazio desliga as reservas. Veja
"Falhas temporárias do provedor" abaixo.
A faixa gratuita tem cotas por conta/projeto/modelo; chave criada não significa uso ilimitado.
Confira disponibilidade e cotas no Google AI Studio: https://ai.google.dev/gemini-api/docs/pricing
Conteúdo da faixa gratuita pode ser usado para melhorar produtos do Google; use dados fictícios
na demonstração e confira os termos do provedor antes de usar conversas com dados pessoais.
Sem chave/modelo, o serviço inicia e /health informa ia_configurada=false;
a mensagem enviada à IA retorna 503 com texto genérico ("O assistente está indisponível
no momento...") e um `code` (por exemplo gemini_not_configured, gemini_http_401,
gemini_http_404). A orientação de configuração (chave, modelo, cota) aparece somente no
log `ai_dependency_failure`, nunca no navegador. Não existe
fallback silencioso para respostas simuladas: quando todos os modelos estão indisponíveis,
a resposta vem do roteiro sem IA e começa com um aviso explícito (`AI_FALLBACK_COMMANDS`,
abaixo). Erros de chave/configuração continuam em 503. Reinicie após alterar o `.env`.
`AI_PROVIDER=commands` permite testar comandos explícitos sem chamada à IA,
mas as compras desse modo também são REAIS após clicar em Confirmar pedido.

Abra http://127.0.0.1:8001/docs e http://127.0.0.1:8001/health.
A saúde verifica o banco; não faz chamada paga à IA nem teste de disponibilidade do provedor.
O /health abre uma conexão própria, fora do pool (connect_timeout de 2 s), para responder
rápido mesmo quando o pool está ocupado com conversas em andamento.
Mantenha PostgreSQL e a API da Pessoa 1 em execução. Na raiz do repositório,
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
- consultar_pedido: consulta GET /pedidos/{id}, restrito aos pedidos da sessão.
- listar_meus_pedidos: lista os pedidos confirmados da sessão atual do navegador.
- preparar_compra: valida IDs e quantidades contra o catálogo, calcula estimativa com Decimal.
- atualizar_entrega: atualiza os dados fornecidos e cria nova versão da seleção.
- cancelar_selecao: limpa apenas uma seleção não confirmada.

O ciclo de ferramentas usa a API nativa Gemini generateContent com schemas de funções,
validação local por Pydantic, no máximo seis rodadas e prazo total configurável.
As respostas nativas e thoughtSignature são preservadas durante cada ciclo de ferramentas;
textos internos marcados como thought não são exibidos. Chave transmitida em cabeçalho,
nunca na URL. Erros de cota 429 não são repetidos no mesmo modelo (passam ao próximo). Histórico recente (até 30 mensagens), estado da
seleção e resultados das ferramentas são enviados ao provedor de IA. Não coloque segredos
nas conversas. Chaves não são enviadas ao frontend nem registradas em logs.
A conversa completa permanece no PostgreSQL. Se a IA falhar após preparar uma seleção,
nenhuma preparação parcial é persistida: em erro, a transação local é revertida; na
resposta pelo roteiro sem IA, a seleção volta ao que era no início da mensagem.
Falha da API de pedidos DENTRO de uma ferramenta (pedido inexistente, API indisponível)
não derruba a requisição: a IA recebe {"erro": ...} como resultado e explica ao usuário;
a mensagem e uma preparação feita no mesmo turno são mantidas.

Referência da implementação: https://ai.google.dev/api/generate-content
Ferramentas: https://ai.google.dev/gemini-api/docs/function-calling

AI_PROVIDER aceita somente gemini ou commands; outro valor impede a inicialização com
mensagem de configuração. Não há outro provedor; a reserva é entre modelos Gemini e, por
último, o roteiro sem IA. A propriedade ia_configurada do /health verifica apenas a presença
de chave/modelo do Gemini, sem chamada externa. O status não comprova validade da chave ou
saldo/cota. O /health também informa `modelo` (principal), `modelos_reserva` e
`reserva_sem_ia` (valor de AI_FALLBACK_COMMANDS); nunca a chave.

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

401/403 em POST /pedidos (ORDERS_INTERNAL_TOKEN ausente ou diferente) são recusas
anteriores a qualquer efeito: o chat registra `orders_auth_failure` em nível ERROR,
responde 502 ("Não foi possível registrar o pedido agora. Nada foi cobrado nem
reservado...") e devolve a seleção para preparando com o MESMO compra_id e a mesma
chave de idempotência. Não fica presa em confirmando; confirmar de novo reenvia o pedido.
Erros 5xx (inclusive o 503 da API sem token configurado) e timeouts seguem incertos.

A API existente calcula preços dentro da sua própria transação. A consulta prévia reduz
mudanças inesperadas, mas não fornece garantia transacional de preço entre a consulta
e POST /pedidos: um contrato de cotação vinculante exigiria evolução conjunta dessa API.
O status do worker pode evoluir; consulte o pedido para ver o status real atualizado.

## Persistência e endpoints

Tabelas exclusivas: chat_conversa, chat_mensagem, chat_requisicao, chat_confirmacao,
chat_sessao e chat_acesso_conversa. Tabelas novas são criadas automaticamente sob lock
PostgreSQL na inicialização; colunas das tabelas existentes não mudam.
Evoluções futuras de colunas precisarão de migrações.

| Método | Caminho | Função |
| --- | --- | --- |
| GET | /health | Saúde do chat/banco e configuração de IA |
| POST | /chat/sessao | Inicia a sessão (cookie HttpOnly) e retorna csrf_token |
| POST | /chat/sessao/encerrar | Revoga a sessão |
| GET | /chat/produtos | Catálogo real |
| GET | /chat/pedidos | Pedidos da sessão |
| GET | /chat/pedidos/{id} | Pedido real da sessão |
| POST | /chat/conversas | Criar conversa |
| GET | /chat/conversas/{id} | Recuperar histórico e seleção |
| GET | /chat/conversas/{id}/pedidos | Pedidos desta conversa |
| POST | /chat/conversas/{id}/mensagens | conteudo e mensagem_id UUID |
| POST | /chat/conversas/{id}/confirmar | Confirma versão da seleção |

O conteúdo da mensagem não aceita caracteres de controle (NUL etc.; quebra de linha e
tabulação são permitidas): a resposta é 422 antes de qualquer chamada à IA. Enquanto uma
mensagem da conversa ainda está sendo processada, outra mensagem para a mesma conversa
recebe 409 ("Ainda estou respondendo à mensagem anterior...") em vez de esperar o bloqueio;
basta reenviar com o mesmo mensagem_id. Falha de conexão/pool do banco responde 503 genérico.

O X-Request-ID recebido (UUID ou os 32 hexadecimais do `$request_id` do Nginx, normalizado
para UUID) é devolvido na resposta, gravado nos logs e repassado em todas as chamadas à
API de pedidos.

Mensagens duplicadas não são executadas novamente e retornam o estado ATUAL da conversa,
evita-se ressuscitar uma seleção antiga após confirmação. Mesmo ID com outro texto retorna
409. O contrato da interface usa status preparando, confirmando e confirmado. confirmado
significa compra registrada; pedido_status contém o status real retornado pelo backend.

No modo commands (e na reserva sem IA): 'Ver o cardápio', 'Quero 2 brownies',
'Selecionar 1:2, 2:1', 'Meu nome é Ana', 'Entrega: sala 512, prédio 2', 'Pedido 4' e 'cancelar'.
'Quero N produto' aceita quantidade por extenso de um a dez, artigos e plural ('quero um
brownie', 'quero dois cafés', 'quero 2 dos brownies') e parte do nome, desde que só um
produto do catálogo corresponda; em caso de ambiguidade nada é escolhido.
Nome e entrega só alteram uma seleção em preparando; pedido já registrado ou com
confirmação pendente não é alterado. 'Pedido N' inexistente na sessão responde em texto.

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

Todos os caminhos /chat exigem sessão, exceto POST /chat/sessao, que inicia o cookie
HttpOnly e retorna csrf_token. Mutações exigem X-CSRF-Token. Conversas e pedidos são
autorizados pela sessão proprietária. POST /chat/sessao/encerrar revoga a sessão.
É uma identidade anônima do navegador; login institucional ainda não está implementado.
Para HTTPS na AWS, configure COOKIE_SECURE=true e APP_ORIGINS com a origem pública.
Consulte ../docs/IMPLANTACAO.md para rede, segredos e recuperação do histórico antigo.

## Teste com prazo maior

AI_TIMEOUT=120 define o orçamento total do ciclo de ferramentas da IA, não 120 segundos por chamada.
Cada rodada recebe o tempo restante, limitado a 45 segundos por rodada. O frontend e o proxy local aguardam até 150 segundos.
As consultas da API de pedidos preservam seu limite independente ORDERS_API_TIMEOUT=5.
Reinicie o Chat Service e o Vite após alterar a configuração. Os logs ai_round registram
round, elapsed_seconds e budget_seconds para comparar o tempo das etapas sem mostrar conteúdo
da conversa nem credenciais. Na execução pelo Uvicorn, use --log-level info para visualizar esses tempos no terminal.

## Falhas temporárias do provedor e meus pedidos

Cada rodada percorre a cadeia de modelos (GEMINI_MODEL e depois GEMINI_FALLBACK_MODELS)
dentro do mesmo prazo da rodada (até 45 s). Troca de modelo: HTTP 500/502/503/504, 429,
404 (modelo inexistente), timeout e erro de transporte. Não troca: 401/403 (chave ou
permissão), 400 e bloqueio de conteúdo. Em 5xx há uma repetição no mesmo modelo após 1 s;
429, 404 e timeout passam direto ao próximo. Um modelo que não é o último da cadeia tem
no máximo 15 s (tentativa, pausa e repetição); o último recebe o tempo restante da rodada.
O tempo de rede e as pausas consomem o mesmo orçamento da IA. As retentativas reutilizam o
mesmo pedido de geração, sem reexecutar ferramentas nem criar compras.

O modelo que respondeu primeiro fica fixado até o fim do ciclo de ferramentas daquela
mensagem: a thoughtSignature devolvida por um modelo é validada na rodada seguinte e a
documentação só a garante para o próprio modelo. Só há troca no meio do ciclo se o modelo
fixado falhar; nesse caso as assinaturas das chamadas anteriores vão com o valor neutro
documentado (`skip_thought_signature_validator`), e uma recusa 400 desse histórico conta
como indisponibilidade. Referência: https://ai.google.dev/gemini-api/docs/thought-signatures
A mensagem seguinte começa de novo pelo modelo principal.

Logs, sem conteúdo de conversa: `ai_model_used model=... fallback=true/false` (INFO, quem
atendeu a rodada), `ai_model_failed model=... code=... next=...` (WARNING) e
`ai_fallback_commands conversation_id=... code=...` (WARNING).

Com `AI_FALLBACK_COMMANDS=true` (padrão), se todos os modelos estiverem indisponíveis ou o
prazo da IA acabar, a mensagem é respondida com HTTP 200 pelo roteiro do modo commands,
precedida de "O assistente de IA está indisponível agora; respondi pelo modo básico.".
Alterações de seleção feitas pela IA nessa mensagem antes da falha são desfeitas antes de o
roteiro rodar. Erros de chave, configuração, bloqueio e resposta inválida continuam em 503.
`AI_FALLBACK_COMMANDS=false` devolve 503 também na indisponibilidade.

A ferramenta listar_meus_pedidos e GET /chat/pedidos consultam compras confirmadas em
todas as conversas da sessão atual, recuperando status pela API de pedidos.
GET /chat/conversas/{id}/pedidos mantém a consulta restrita à conversa proprietária.
Seleções preparadas, tentativas incertas e pedidos de outra sessão não aparecem.
O endpoint de histórico pode ser consultado diretamente mesmo quando a IA está indisponível.
