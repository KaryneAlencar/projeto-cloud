# Entrega da Pessoa 2 — 05/11/2026

## Antes e depois

| Frente | Antes | Estado entregue |
| --- | --- | --- |
| Histórico de compras | Restrito à conversa | Painel e ferramenta de IA reúnem pedidos das conversas da sessão |
| Acompanhamento | Consulta manual | Status real consultado a cada 10 segundos com página visível |
| Acesso | Conhecer UUID permitia acessar conversa | Sessão anônima persistente, cookie HttpOnly, CSRF e autorização de conversas/pedidos |
| Execução | Terminais separados | Imagens de frontend/chat e composição local com saúde das dependências |
| Verificação | Testes com dependências simuladas | 43 testes e fluxo em containers com API/PostgreSQL reais isolados |
| Integração e entrega | Configuração distribuída | README raiz, scripts e contrato de implantação para a Pessoa 1 |

A confirmação explícita e a idempotência existentes foram mantidas e verificadas.
O backend, worker e compose.yaml originais da Pessoa 1 não foram alterados.

## Onde e por quê

- chat-service/app/security.py, models.py, main.py e config.py: persistir sessões e
  propriedade das conversas, validar CSRF/origem e impedir acesso de outra sessão.
- chat-service/app/order_history.py e ai.py: consultar somente pedidos pertencentes
  à sessão e reunir compras de suas diferentes conversas.
- chat-service/app/logging_setup.py: logs JSON com identificação de requisição para
  diagnóstico, sem conteúdo de mensagens nem credenciais.
- chat-service/scripts/claim_legacy.py: recuperar administrativamente conversas
  anteriores à proteção sem disponibilizar apropriação pública por UUID.
- frontend/src/chat.ts: iniciar sessão, encaminhar cookie/CSRF e consultar histórico.
- frontend/src/OrdersPanel.tsx, App.tsx e App.css: listar compras, atualizar status
  sem consultas sobrepostas e sincronizar o comprovante apresentado.
- Dockerfiles, .dockerignore e frontend/nginx/: imagens sem segredos, execução sem
  root, interface estática e proxy com resolução DNS renovável.
- compose.app.yaml e scripts/start-local.ps1: iniciar ambiente conjunto preservando
  configuração e volume existentes; portas padrão 8080/8002/8003.
- compose.verify.yaml, scripts/verify_stack.py e verify-stack.ps1: validar isoladamente
  sem usar banco comercial nem chamar Gemini/SQS.
- scripts/smoke_gemini.py: roteiro opcional de consulta real, sem confirmar compra.
- README.md e docs/IMPLANTACAO.md: instruções locais e parâmetros necessários na AWS.

## Evidências e limites

Os 43 testes passaram com PostgreSQL real em schemas temporários. A verificação dos
containers passou nos seis cenários: frontend/proxy/sessão/CSRF; catálogo e preparação;
confirmação concorrente com um único débito de estoque; isolamento entre sessões;
consulta de status atualizado; recuperação após reinício do chat. Resultado local em
work/verification.json, ignorado pelo Git. A interface também foi exercitada pelo
navegador: catálogo, seleção, nome/endereço, confirmação e pedido no painel.

O fluxo de containers usou AI_PROVIDER=commands. A alteração de status do worker foi
simulada no banco descartável. Isso não valida Gemini, SQS, IAM, ECS, RDS, escalabilidade
ou disponibilidade na AWS. A tentativa de smoke no serviço local normal encontrou o
serviço indisponível; não há comprovação de chamada real ao Gemini nesta entrega.

O ambiente isolado permanece na porta 18080 para inspeção, com dados de verificação.
Ele não deve ser usado como ambiente real. Pode ser parado, na pasta insper-eats, com:

```powershell
docker compose -p insper-eats-verification -f compose.verify.yaml stop
```

## Próximas ações

1. Executar scripts/start-local.ps1 e acessar http://127.0.0.1:8080 para testar o
   ambiente normal com a chave/modelo Gemini locais e catálogo existente.
2. Se desejar o histórico anterior, seguir a recuperação administrativa documentada.
   Os dados foram preservados; não são atribuídos automaticamente a um visitante.
3. Com a Pessoa 1, publicar imagens e configurar endereços internos, HTTPS, origens,
   segredos, permissões, banco persistente e logs conforme IMPLANTACAO.md.
4. Validar worker/SQS real e atualização de status, reinício/substituição de tasks,
   persistência e escalabilidade em Ohio; reproduzir infraestrutura em São Paulo
   com Terraform conforme a divisão do trabalho.
5. Revisar e fazer commit das alterações. Nenhum commit nem recurso AWS foi criado
   automaticamente nesta entrega.

Identidade é anônima por navegador, sem login institucional ou recuperação entre
dispositivos. Apagar o cookie ou expirar a sessão remove o acesso do visitante ao
histórico, preservando os dados. Login institucional requer uma integração adicional.
