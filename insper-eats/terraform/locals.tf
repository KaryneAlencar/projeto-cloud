data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  name = "${var.project}-${var.environment}"

  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # As AZs vêm da região de destino: os nomes de Ohio não existem em São Paulo.
  azs = slice(data.aws_availability_zones.available.names, 0, 2)

  https_enabled = var.acm_certificate_arn != null

  # Origem pública exata, usada pelo chat para validar o cabeçalho Origin.
  app_origin = local.https_enabled ? "https://${var.app_domain}" : "http://${lower(aws_lb.main.dns_name)}"

  db_name      = "insper_eats"
  db_app_user  = "insper_app"
  chat_db_name = "insper_eats_chat"
  chat_db_user = "insper_chat"

  # Endereços internos (Cloud Map). O Nginx do frontend resolve o chat por DNS
  # a cada 10 s, então a troca de tasks não exige reiniciar o frontend.
  internal_domain = "${local.name}.internal"
  api_internal    = "http://api.${local.internal_domain}:8000"
  chat_internal   = "http://chat.${local.internal_domain}:8001"

  log_groups = {
    api      = "/ecs/${local.name}/api"
    worker   = "/ecs/${local.name}/worker"
    chat     = "/ecs/${local.name}/chat"
    frontend = "/ecs/${local.name}/frontend"
  }

  # Variáveis repassadas aos scripts chamados por local-exec.
  script_env = merge(
    { AWS_REGION = var.region, AWS_DEFAULT_REGION = var.region },
    var.aws_profile == null ? {} : { AWS_PROFILE = var.aws_profile },
  )
}
