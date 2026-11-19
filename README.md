# Insper Eats

Plataforma de comércio conversacional do projeto de Computação em Nuvem.
Pessoa 1: API de pedidos, worker, SQS e AWS. Pessoa 2: chat com Gemini e frontend.

## Estrutura

| Pasta | Conteúdo |
| --- | --- |
| `backend/` | API de pedidos (FastAPI) e worker SQS |
| `chat-service/` | Chat Service (FastAPI + Gemini) |
| `frontend/` | Interface React servida por Nginx |
| `terraform/` | Infraestrutura AWS completa (São Paulo por padrão) |
| `scripts/` | Execução e verificação locais |
| `docs/` | Entrega, implantação e roteiro do vídeo |

## Rodar a aplicação inteira

Com o Docker em execução, na raiz deste repositório (PowerShell; no Linux/macOS, `pwsh`):

```powershell
.\scripts\start-local.ps1
```

Abra **http://localhost:8080**. O comando constrói e inicia banco, API, chat e frontend.
Ele preserva o volume PostgreSQL do compose existente. Não inicia worker nem acessa SQS.
São necessários `.env` na raiz, com `POSTGRES_USER`, `POSTGRES_PASSWORD` e `POSTGRES_DB`,
e `chat-service/.env` com a chave Gemini.
O arquivo `.env.docker` é gerado localmente e ignorado pelo Git. Nunca o envie ao repositório.

A API só aceita `/pedidos` com o cabeçalho `X-Internal-Token`. No compose local, API e chat
recebem o mesmo `ORDERS_INTERNAL_TOKEN` (um valor padrão só para desenvolvimento; defina a
variável no `.env` da raiz para trocar).

Para experimentar os serviços reais sem chamar a IA:

```powershell
.\scripts\start-local.ps1 -Commands
```

Nesse modo, use os comandos descritos no README do chat. A confirmação continua criando
pedidos reais no banco local. Para usar o Gemini, execute novamente sem `-Commands`.

Portas locais: frontend 8080, API 8002, chat 8003, banco 5433. Dentro do Docker, o chat
usa `http://api:8000` e o frontend usa `http://chat:8001`. Não use localhost entre containers.
Os terminais antigos nas portas 8000/8001/5173 podem continuar, mas use uma única interface
e o mesmo hostname durante o teste para manter a sessão do navegador.

## Testes

```powershell
cd .\chat-service
.\.venv\Scripts\python.exe tests/run_postgres.py
```

Os testes de serviço usam schemas temporários no PostgreSQL e simulam IA/API de pedidos.
Para validar os containers com API e banco reais, em ambiente separado:

```powershell
.\scripts\verify-stack.ps1
```

Execute esse último comando na raiz do repositório. Ele usa a porta 18080 e um banco
descartável, não os dados do seu ambiente normal. Relatório: `work/verification.json`.
O projeto Docker de verificação chama-se `insper-eats-verification`.

Para um ensaio local com worker e fila (ElasticMQ no lugar do SQS), veja o "Nível 1" em
[terraform/README.md](terraform/README.md).

## AWS

A infraestrutura (VPC, RDS, SQS, ECS, ALB, alarmes e dashboard) é criada pelo Terraform em
`terraform/`, com `./deploy.sh`. Pré-requisitos, testes e custos estão em
[terraform/README.md](terraform/README.md). Os comandos locais acima não criam recursos AWS.

## Documentação

- [Infraestrutura AWS com Terraform](terraform/README.md)
- [Implantação e contrato entre os serviços](docs/IMPLANTACAO.md)
- [Entrega da Pessoa 2 (registro de 05/11/2026)](docs/ENTREGA_PESSOA_2.md)
- [Roteiro do vídeo de entrega](docs/VIDEO_ENTREGA.md)
- [Chat Service e ferramentas da IA](chat-service/README.md)
- [Frontend](frontend/README.md)

## Sessões e histórico anterior

O chat agora usa sessão anônima com cookie HttpOnly, CSRF e autorização por conversa.
"Meus pedidos" reúne compras das conversas da mesma sessão do navegador. Não é um login
institucional e não conecta automaticamente dispositivos diferentes.

Conversas anteriores à proteção continuam no banco, mas não são atribuídas a um visitante
apenas porque ele conhece o UUID. Consulte a recuperação administrativa na documentação de implantação.
