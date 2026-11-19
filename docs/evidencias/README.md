# Evidências

Arquivos gerados durante a etapa manual na AWS, em Ohio (`us-east-2`), em 06/11/2026.
Estão aqui como registro: descrevem o ambiente montado à mão, não o criado pelo Terraform
em `terraform/` (cujos relatórios o `verify_deploy.py` grava em `terraform/evidencias/`).
Os nomes originais foram preservados; o sufixo é a data e a hora local da geração.

## `ohio/`

| Item | O que é |
| --- | --- |
| `insper-eats-etapa43-20261106-074533/` | Auditoria automatizada, somente leitura, da infraestrutura (`resumo-etapa43.txt` e o mesmo conteúdo em `auditoria-etapa43.json`). 20 checagens: 19 OK e 1 ATENÇÃO (origem CloudFront → ALB em HTTP). O próprio relatório lista as ressalvas e avisa que não comprova carga nem failover. |
| `insper-eats-failover-20261106-082400.txt` | Interrupção de uma task do serviço web no ECS. O serviço voltou a 2/2 tasks e o ALB a 2/2 alvos saudáveis; 16 amostras HTTP pelo CloudFront, 0 falhas. |
| `insper-eats-ec2-failover-20261106-085452.txt` | Substituição de uma instância EC2 do Auto Scaling Group (marcada como Unhealthy). O ASG voltou a 4/4, os três serviços a 2/2 e o ALB web a 2/2; 22/22 amostras HTTP com sucesso. |
| `insper-eats-dashboard-backup-20261106-084256.json` | Cópia do corpo do dashboard do CloudWatch, com 13 widgets (alarmes, ECS, ALB, SQS, RDS). |
| `insper-eats-dashboard-backup-final-20261106-084951.json` | Versão seguinte do mesmo dashboard, com 15 widgets: acrescenta "Negocio - Pedidos confirmados" e "Aplicacao - Falhas em dependencias". |
| `evidencias-carga-20261106-090620/` | Teste de carga só com GET, em quatro fases (baseline, moderada, pico, recuperação). `resumo.txt`/`resumo.json` trazem os totais; `requisicoes.csv`, `health_checks.csv` e `ecs_amostras.csv` trazem as amostras. Pico: 8544/8544 HTTP 200, p95 0,51 s; uma falha na fase de recuperação (89/90); CPU máxima publicada 26,5%; `DesiredCount` da API permaneceu em 2. |
| `evidencias-carga-20261106-095429/` | Segunda execução do mesmo teste. Pico: 8582/8590 HTTP 200 (99,91%), p95 0,45 s; demais fases 100%; CPU máxima publicada 29,9%; `DesiredCount` da API permaneceu em 2. |
| `resultado-protecao-pedidos-20261106-110354.txt` | Registro da publicação das revisões que protegem `/pedidos` com token interno (web 4 → 5, API 2 → 3). `/api/health` e `/produtos` responderam 200 e `/pedidos/7` sem sessão respondeu 401. O arquivo marca como PENDENTE o teste de compra real pelo navegador. |

Nos dois testes de carga a CPU ficou abaixo do alvo de escalabilidade, então eles não
demonstram scale-out. Os arquivos contêm identificadores da conta AWS (número da conta,
ARNs e IDs de instância), mas nenhuma chave ou segredo: o segredo aparece somente por ARN.
