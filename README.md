# Insper Eats

Plataforma de comércio conversacional do projeto de Computação em Nuvem.
Pessoa 1: API de pedidos, worker, SQS e AWS. Pessoa 2: chat com Gemini e frontend.

## Rodar a aplicação inteira

Com Docker Desktop aberto, na raiz deste repositório:

```powershell
.\insper-eats\scripts\start-local.ps1
```

Abra **http://localhost:8080**. O comando constrói e inicia banco, API, chat e frontend.
Ele preserva o volume PostgreSQL do compose existente. Não inicia worker nem acessa SQS.
São necessários `insper-eats/.env` com os dados do banco e `chat-service/.env` com a chave Gemini.
O arquivo `.env.docker` é gerado localmente e ignorado pelo Git. Nunca o envie ao repositório.

Para experimentar os serviços reais sem chamar a IA:

```powershell
.\insper-eats\scripts\start-local.ps1 -Commands
```

Nesse modo, use os comandos descritos no README do chat. A confirmação continua criando
pedidos reais no banco local. Para usar o Gemini, execute novamente sem `-Commands`.

Portas locais: frontend 8080, API 8002, chat 8003, banco 5433. Dentro do Docker, o chat
usa `http://api:8000` e o frontend usa `http://chat:8001`. Não use localhost entre containers.
Os terminais antigos nas portas 8000/8001/5173 podem continuar, mas use uma única interface
e o mesmo hostname durante o teste para manter a sessão do navegador.

## Testes

```powershell
cd .\insper-eats\chat-service
.\.venv\Scripts\python.exe tests/run_postgres.py
```

Os testes de serviço usam schemas temporários no PostgreSQL e simulam IA/API de pedidos.
Para validar os containers com API e banco reais, em ambiente separado:

```powershell
.\insper-eats\scripts\verify-stack.ps1
```

Execute esse último comando na raiz do repositório. Ele usa a porta 18080 e um banco
descartável, não os dados do seu ambiente normal. Relatório: `insper-eats/work/verification.json`.
O projeto Docker de verificação chama-se `insper-eats-verification`.

## Documentação

- [Entrega, decisões e próximos passos](insper-eats/docs/ENTREGA_PESSOA_2.md)
- [Implantação e contrato com a Pessoa 1](insper-eats/docs/IMPLANTACAO.md)
- [Chat Service e ferramentas da IA](insper-eats/chat-service/README.md)
- [Frontend](insper-eats/frontend/README.md)

## Sessões e histórico anterior

O chat agora usa sessão anônima com cookie HttpOnly, CSRF e autorização por conversa.
"Meus pedidos" reúne compras das conversas da mesma sessão do navegador. Não é um login
institucional e não conecta automaticamente dispositivos diferentes.

Conversas anteriores à proteção continuam no banco, mas não são atribuídas a um visitante
apenas porque ele conhece o UUID. Consulte a recuperação administrativa na documentação de implantação.

Nenhum recurso AWS foi criado por estes comandos. Publicação em Ohio, integração com
worker/SQS e reconstrução com Terraform em São Paulo continuam com a Pessoa 1.
