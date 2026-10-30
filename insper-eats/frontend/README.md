# Insper Eats — Frontend (Pessoa 2)

Interface React + TypeScript + Vite. Não altera backend, worker, estoque ou AWS.

## Executar

Na pasta frontend:

```powershell
npm install
npm run dev
```

O terminal mostra o endereço local (normalmente http://localhost:5173).
O modo padrão é demonstração: não precisa de banco, API, AWS ou credenciais.

## Testar a demonstração

1. Clique em Ver o cardápio.
2. Envie Quero 2 brownies (também aceita cookies e pão de queijo; 1 a 20 unidades por produto).
3. Envie Meu nome é Ana.
4. Envie Entrega: sala 512, prédio 2.
5. Confira o resumo e clique em Simular confirmação.
6. Atualize a página: o histórico e o resumo devem reaparecer.
7. Envie cancelar para limpar a seleção, ou use Nova conversa.

O simulador é um roteiro determinístico, não uma IA. Uma nova seleção substitui a anterior.
Dados e conversas de demonstração ficam no localStorage deste navegador. Uma confirmação
simulada nunca chama a API de pedidos. Não use dados pessoais reais na demonstração.

## Conectar o futuro Chat Service

Copie .env.example para .env.local e configure:

```dotenv
VITE_CHAT_MODE=api
VITE_CHAT_API_URL=/api
```

Reinicie o Vite. O proxy local encaminha /api para http://127.0.0.1:8001,
removendo o prefixo /api. A API de pedidos existente continua na porta 8000.
O modo integrado não está disponível enquanto o Chat Service não for implementado.
Não há fallback silencioso para demonstração em caso de falha da API.

Em produção, configure o ALB/reverse proxy para encaminhar /api ao Chat Service
ou defina VITE_CHAT_API_URL com a URL dele e configure CORS nesse serviço.
As variáveis VITE_* são públicas e incorporadas no build. Nunca coloque chaves de IA,
AWS ou senhas nelas. A interface se comunica exclusivamente com o Chat Service.

## Contrato proposto (a implementar no Chat Service)

Todos os endpoints abaixo retornam a conversa completa no formato descrito a seguir:

| Método | Caminho | Corpo |
| --- | --- | --- |
| POST | /chat/conversas | {} |
| GET | /chat/conversas/{id} | Sem corpo |
| POST | /chat/conversas/{id}/mensagens | {"conteudo":"Quero 2 brownies","mensagem_id":"uuid"} |
| POST | /chat/conversas/{id}/confirmar | {"compra_id":"uuid-da-selecao"} |

```json
{
  "id": "uuid-conversa",
  "mensagens": [
    {"id":"uuid-mensagem","papel":"assistente","conteudo":"Confira seu resumo."}
  ],
  "compra": {
    "id":"uuid-da-selecao",
    "cliente":"Ana",
    "local_entrega":"Sala 512, prédio 2",
    "itens":[{"nome":"Brownie","quantidade":2,"preco_unitario":8}],
    "total":16,
    "status":"preparando"
  }
}
```

compra pode ser null. papel aceita usuario ou assistente. Valores monetários na resposta
são números em reais; o servidor deve calcular e validar com precisão decimal.
Após registrar o pedido, compra.status é confirmado, com pedido_id (string) e
pedido_status contendo o status real da API de pedidos. Confirmado aqui significa que
a compra foi registrada; pedido_status distingue recebido de confirmado pelo worker.

Responsabilidades do Chat Service na próxima etapa:

- Persistir mensagens e estado da compra no PostgreSQL, sem depender de memória local.
- Consultar o catálogo real pela API existente e fornecer preços/estoque reais.
- Usar IA generativa para interpretar a conversa e ferramentas para consultar/criar pedidos.
- Deduplicar mensagem_id de maneira persistente. Uma repetição retorna o mesmo resultado.
- Gerar nova compra.id a cada mudança da seleção e rejeitar confirmação de uma versão antiga.
- Validar confirmação, nome, entrega, estoque e totais no servidor.
- Associar compra.id a uma chave_idempotencia persistente; reutilizá-la em retentativas.
- Criar o pedido exclusivamente em POST /pedidos, após confirmação explícita.
- Preservar transações contra confirmações concorrentes, incluindo abas/dispositivos distintos.
- Retornar JSON com códigos HTTP adequados para erros e registrar logs correlacionáveis.

A trava de envio da interface evita cliques simultâneos nesta aba; não substitui a
idempotência no servidor. A mesma tentativa de mensagem conserva mensagem_id enquanto
o conteúdo não muda. Timeout: 30 segundos. Em falha, o texto digitado permanece disponível.
O navegador guarda apenas o identificador da conversa no modo integrado; o servidor
precisa fornecer o histórico. Não há autenticação implementada nesta etapa.

## Verificação

```powershell
npm run build
```

Gera dist/. Para conferir a versão compilada: npm run preview.
O proxy do Vite é de desenvolvimento; a implantação precisa do roteamento descrito acima.
