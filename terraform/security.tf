# Um Security Group por papel. As regras referenciam outros grupos, nunca
# faixas de IP internas, então só o caminho previsto fica aberto:
#
#   internet -> ALB -> frontend -> chat -> API -> RDS
#                  \-> API (:8000, só api_allowed_cidrs)      worker -> RDS, SQS

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb-sg"
  description = "ALB publico"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-alb-sg" }
}

resource "aws_security_group" "frontend" {
  name        = "${local.name}-frontend-sg"
  description = "Tasks do frontend (Nginx)"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-frontend-sg" }
}

resource "aws_security_group" "chat" {
  name        = "${local.name}-chat-sg"
  description = "Tasks do Chat Service"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-chat-sg" }
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api-sg"
  description = "Tasks da API de pedidos"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-api-sg" }
}

resource "aws_security_group" "worker" {
  name        = "${local.name}-worker-sg"
  description = "Tasks do worker, sem entrada"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-worker-sg" }
}

resource "aws_security_group" "db_init" {
  name        = "${local.name}-db-init-sg"
  description = "Task temporaria de inicializacao do banco"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-db-init-sg" }
}

resource "aws_security_group" "rds" {
  name        = "${local.name}-rds-sg"
  description = "RDS PostgreSQL, sem saida"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-rds-sg" }
}

resource "aws_security_group" "ecs_instances" {
  name        = "${local.name}-ecs-instances-sg"
  description = "Instancias EC2 do cluster ECS, sem entrada"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-ecs-instances-sg" }
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${local.name}-vpce-sg"
  description = "Endpoints de interface da VPC"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-vpce-sg" }
}

# --- ALB -------------------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP publico"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_ingress_rule" "alb_https" {
  count = local.https_enabled ? 1 : 0

  security_group_id = aws_security_group.alb.id
  description       = "HTTPS publico"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_ingress_rule" "alb_api" {
  for_each = toset(var.api_allowed_cidrs)

  security_group_id = aws_security_group.alb.id
  description       = "API de pedidos para testes e administracao"
  cidr_ipv4         = each.value
  ip_protocol       = "tcp"
  from_port         = 8000
  to_port           = 8000
}

resource "aws_vpc_security_group_egress_rule" "alb_to_frontend" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Frontend"
  referenced_security_group_id = aws_security_group.frontend.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  description                  = "API de pedidos"
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# --- Frontend --------------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "frontend_from_alb" {
  security_group_id            = aws_security_group.frontend.id
  description                  = "ALB"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}

resource "aws_vpc_security_group_egress_rule" "frontend_to_chat" {
  security_group_id            = aws_security_group.frontend.id
  description                  = "Chat Service"
  referenced_security_group_id = aws_security_group.chat.id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}

# --- Chat ------------------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "chat_from_frontend" {
  security_group_id            = aws_security_group.chat.id
  description                  = "Frontend"
  referenced_security_group_id = aws_security_group.frontend.id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}

resource "aws_vpc_security_group_egress_rule" "chat_to_api" {
  security_group_id            = aws_security_group.chat.id
  description                  = "API de pedidos"
  referenced_security_group_id = aws_security_group.api.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# --- API -------------------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  description                  = "ALB"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_ingress_rule" "api_from_chat" {
  security_group_id            = aws_security_group.api.id
  description                  = "Chat Service"
  referenced_security_group_id = aws_security_group.chat.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

# --- Regras comuns às tasks ------------------------------------------------

locals {
  # HTTPS de saída: ECR, CloudWatch Logs, Secrets Manager, SQS e Gemini.
  https_egress_groups = {
    frontend = aws_security_group.frontend.id
    chat     = aws_security_group.chat.id
    api      = aws_security_group.api.id
    worker   = aws_security_group.worker.id
    db_init  = aws_security_group.db_init.id
  }

  # Quem pode abrir conexão com o PostgreSQL.
  database_clients = {
    api     = aws_security_group.api.id
    worker  = aws_security_group.worker.id
    chat    = aws_security_group.chat.id
    db_init = aws_security_group.db_init.id
  }
}

resource "aws_vpc_security_group_egress_rule" "https_out" {
  for_each = local.https_egress_groups

  security_group_id = each.value
  description       = "HTTPS para servicos AWS e APIs externas"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

resource "aws_vpc_security_group_egress_rule" "to_rds" {
  for_each = local.database_clients

  security_group_id            = each.value
  description                  = "PostgreSQL"
  referenced_security_group_id = aws_security_group.rds.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# --- RDS -------------------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "rds_from_clients" {
  for_each = local.database_clients

  security_group_id            = aws_security_group.rds.id
  description                  = "PostgreSQL a partir de ${each.key}"
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

# --- Instâncias ECS --------------------------------------------------------

# O agente ECS só inicia conexões de saída, todas por HTTPS (ECS, ECR, SSM e
# repositórios de pacotes). As tasks usam awsvpc e têm seus próprios grupos,
# então nada precisa entrar nas instâncias.
resource "aws_vpc_security_group_egress_rule" "ecs_instances_out" {
  security_group_id = aws_security_group.ecs_instances.id
  description       = "HTTPS do agente ECS, SSM e atualizacoes"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

# --- VPC endpoints ---------------------------------------------------------

resource "aws_vpc_security_group_ingress_rule" "vpce_from_worker" {
  security_group_id            = aws_security_group.vpc_endpoints.id
  description                  = "Worker para o SQS"
  referenced_security_group_id = aws_security_group.worker.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
