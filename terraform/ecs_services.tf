# Os quatro serviços da aplicação.
#
# Todos rodam em instâncias EC2 pelo mesmo Capacity Provider; nenhum usa
# Fargate. Uma t3.medium só comporta duas tasks awsvpc (3 ENIs) e o módulo
# impõe distinctInstance por serviço: com 4 serviços de 2 tasks são 4
# instâncias em repouso, e até 8 com todos em 4 tasks; o máximo do ASG é 10
# para sobrar vaga a um deployment no pico (ver ecs_asg_max_size).

# --- Descoberta de serviços (Cloud Map) ------------------------------------

resource "aws_service_discovery_private_dns_namespace" "internal" {
  name        = local.internal_domain
  description = "Enderecos internos do ${local.name}"
  vpc         = aws_vpc.main.id
}

resource "aws_service_discovery_service" "internal" {
  for_each = toset(["api", "chat"])

  name = each.key

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.internal.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }

  # O ECS mantém o registro de cada task conforme o health check do contêiner.
  health_check_custom_config {}

  # No destroy, remove o serviço mesmo que ainda haja uma task registrada.
  force_destroy = true

  lifecycle {
    # O provider relê o bloco vazio como diferente a cada plan e pede para
    # RECRIAR o serviço do Cloud Map. Isso apagou o registro DNS da API no
    # primeiro apply após o deploy (as tasks antigas não se registram no
    # serviço novo) e o chat ficou sem alcançar a API. O bloco não muda depois
    # de criado, então a diferença é ignorada.
    ignore_changes = [health_check_custom_config]
  }
}

locals {
  python_health_check = {
    for name, port in { api = 8000, chat = 8001 } : name => [
      "CMD", "python", "-c",
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${port}/health', timeout=3)",
    ]
  }

  # O worker não tem porta: o laço principal toca um arquivo de heartbeat ao
  # fim de cada ciclo (backend/worker.py). Um ciclo leva cerca de 10 s de long
  # polling mais o processamento; sem heartbeat por 120 s, a task é substituída.
  worker_health_check = [
    "CMD", "python", "-c",
    "import os, sys, time; sys.exit(0 if time.time() - os.path.getmtime('/tmp/worker-heartbeat') < 120 else 1)",
  ]

  # Muda quando as credenciais giram, para as tasks relerem os secrets.
  credentials_marker = "${var.credentials_version}.${var.gemini_api_key_version}"
}

# --- API de pedidos --------------------------------------------------------

module "api" {
  source = "./modules/ecs-service"

  name           = "${local.name}-api"
  container_name = "api"
  region         = var.region
  cluster_arn    = aws_ecs_cluster.main.arn
  cluster_name   = aws_ecs_cluster.main.name

  launch_type       = "EC2"
  capacity_provider = aws_ecs_capacity_provider.ec2.name

  image          = local.image_uris["api"]
  container_port = 8000
  cpu            = var.task_cpu
  memory         = var.task_memory

  memory_reservation = var.task_memory_reservation

  environment = {
    CREDENTIALS_VERSION = local.credentials_marker
  }

  secrets = {
    DATABASE_URL          = aws_secretsmanager_secret.database_url.arn
    ORDERS_INTERNAL_TOKEN = aws_secretsmanager_secret.orders_internal_token.arn
  }
  secret_arns = [
    aws_secretsmanager_secret.database_url.arn,
    aws_secretsmanager_secret.orders_internal_token.arn,
  ]

  health_check_command = local.python_health_check["api"]

  log_group_name     = local.log_groups["api"]
  log_retention_days = var.log_retention_days

  subnet_ids         = aws_subnet.app[*].id
  security_group_ids = [aws_security_group.api.id]

  min_count  = var.service_min_count
  max_count  = var.service_max_count
  cpu_target = var.api_cpu_target

  enable_load_balancer = true
  target_group_arn     = aws_lb_target_group.api.arn

  enable_service_discovery = true
  service_registry_arn     = aws_service_discovery_service.internal["api"].arn

  wait_for_steady_state = var.wait_for_steady_state

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_route.app_nat,
    aws_route_table_association.app,
    terraform_data.image,
    terraform_data.db_init,
    aws_lb_listener.api,
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.orders_internal_token,
  ]
}

# --- Worker ----------------------------------------------------------------

module "worker" {
  source = "./modules/ecs-service"

  name           = "${local.name}-worker"
  container_name = "worker"
  region         = var.region
  cluster_arn    = aws_ecs_cluster.main.arn
  cluster_name   = aws_ecs_cluster.main.name

  launch_type       = "EC2"
  capacity_provider = aws_ecs_capacity_provider.ec2.name

  image  = local.image_uris["worker"]
  cpu    = var.task_cpu
  memory = var.task_memory

  memory_reservation = var.task_memory_reservation

  environment = {
    AWS_REGION          = var.region
    SQS_QUEUE_NAME      = aws_sqs_queue.orders.name
    CREDENTIALS_VERSION = local.credentials_marker
    # O worker usa uma conexão por vez; pool pequeno poupa conexões do RDS.
    DB_POOL_SIZE    = "2"
    DB_MAX_OVERFLOW = "1"
  }

  secrets     = { DATABASE_URL = aws_secretsmanager_secret.database_url.arn }
  secret_arns = [aws_secretsmanager_secret.database_url.arn]

  enable_task_role_policy = true
  task_role_policy_json = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid    = "OrdersQueue"
      Effect = "Allow"
      Action = [
        # Só as quatro chamadas que backend/worker.py faz.
        "sqs:GetQueueUrl",
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
      ]
      Resource = aws_sqs_queue.orders.arn
    }]
  })

  health_check_command = local.worker_health_check

  log_group_name     = local.log_groups["worker"]
  log_retention_days = var.log_retention_days

  subnet_ids         = aws_subnet.app[*].id
  security_group_ids = [aws_security_group.worker.id]

  min_count = var.service_min_count
  max_count = var.service_max_count

  wait_for_steady_state = var.wait_for_steady_state

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_route.app_nat,
    aws_route_table_association.app,
    terraform_data.image,
    terraform_data.db_init,
    aws_secretsmanager_secret_version.database_url,
    aws_sqs_queue_policy.tls_only,
    aws_vpc_endpoint.sqs,
  ]
}

# Backlog por task: mensagens visíveis na fila dividido pelas tasks em execução.
resource "aws_appautoscaling_policy" "worker_backlog" {
  name               = "${local.name}-worker-sqs-scaling"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = module.worker.autoscaling.service_namespace
  resource_id        = module.worker.autoscaling.resource_id
  scalable_dimension = module.worker.autoscaling.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = var.worker_backlog_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 180

    customized_metric_specification {
      metrics {
        id          = "m1"
        label       = "Mensagens visiveis na fila"
        return_data = false

        metric_stat {
          stat = "Sum"

          metric {
            namespace   = "AWS/SQS"
            metric_name = "ApproximateNumberOfMessagesVisible"

            dimensions {
              name  = "QueueName"
              value = coalesce(var.worker_scaling_queue_name, aws_sqs_queue.orders.name)
            }
          }
        }
      }

      metrics {
        id          = "m2"
        label       = "Tasks do worker em execucao"
        return_data = false

        metric_stat {
          stat = "Average"

          metric {
            namespace   = "ECS/ContainerInsights"
            metric_name = "RunningTaskCount"

            dimensions {
              name  = "ClusterName"
              value = aws_ecs_cluster.main.name
            }

            dimensions {
              name  = "ServiceName"
              value = module.worker.service_name
            }
          }
        }
      }

      metrics {
        id          = "e1"
        label       = "Backlog por task"
        expression  = "m1 / m2"
        return_data = true
      }
    }
  }
}

# --- Chat Service ----------------------------------------------------------

module "chat" {
  source = "./modules/ecs-service"

  name           = "${local.name}-chat"
  container_name = "chat"
  region         = var.region
  cluster_arn    = aws_ecs_cluster.main.arn
  cluster_name   = aws_ecs_cluster.main.name

  launch_type       = "EC2"
  capacity_provider = aws_ecs_capacity_provider.ec2.name

  image          = local.image_uris["chat"]
  container_port = 8001
  cpu            = var.task_cpu
  memory         = var.task_memory

  memory_reservation = var.task_memory_reservation

  # O chat encerra requisições em andamento por até 160 s (uvicorn
  # --timeout-graceful-shutdown). Em EC2 não há o teto de 120 s do Fargate.
  stop_timeout = 170

  environment = {
    PORT                   = "8001"
    WEB_CONCURRENCY        = "2"
    ORDERS_API_URL         = local.api_internal
    AI_PROVIDER            = var.ai_provider
    GEMINI_MODEL           = var.gemini_model
    GEMINI_FALLBACK_MODELS = join(",", var.gemini_fallback_models)
    AI_FALLBACK_COMMANDS   = tostring(var.ai_fallback_commands)
    APP_ORIGINS            = local.app_origin
    COOKIE_SECURE          = tostring(local.https_enabled)
    CREDENTIALS_VERSION    = local.credentials_marker
  }

  secrets = {
    CHAT_DATABASE_URL     = aws_secretsmanager_secret.chat_database_url.arn
    ORDERS_INTERNAL_TOKEN = aws_secretsmanager_secret.orders_internal_token.arn
    GEMINI_API_KEY        = aws_secretsmanager_secret.gemini_api_key.arn
  }
  secret_arns = [
    aws_secretsmanager_secret.chat_database_url.arn,
    aws_secretsmanager_secret.orders_internal_token.arn,
    aws_secretsmanager_secret.gemini_api_key.arn,
  ]

  health_check_command = local.python_health_check["chat"]

  log_group_name     = local.log_groups["chat"]
  log_retention_days = var.log_retention_days

  subnet_ids         = aws_subnet.app[*].id
  security_group_ids = [aws_security_group.chat.id]

  min_count  = var.service_min_count
  max_count  = var.service_max_count
  cpu_target = 60

  enable_service_discovery = true
  service_registry_arn     = aws_service_discovery_service.internal["chat"].arn

  wait_for_steady_state = var.wait_for_steady_state

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_route.app_nat,
    aws_route_table_association.app,
    terraform_data.image,
    terraform_data.db_init,
    aws_secretsmanager_secret_version.chat_database_url,
    aws_secretsmanager_secret_version.orders_internal_token,
    aws_secretsmanager_secret_version.gemini_api_key,
  ]
}

# --- Frontend --------------------------------------------------------------

module "frontend" {
  source = "./modules/ecs-service"

  name           = "${local.name}-frontend"
  container_name = "frontend"
  region         = var.region
  cluster_arn    = aws_ecs_cluster.main.arn
  cluster_name   = aws_ecs_cluster.main.name

  launch_type       = "EC2"
  capacity_provider = aws_ecs_capacity_provider.ec2.name

  image          = local.image_uris["frontend"]
  container_port = 8080
  cpu            = var.task_cpu
  memory         = var.task_memory

  memory_reservation = var.task_memory_reservation

  environment = {
    CHAT_UPSTREAM = local.chat_internal
  }

  health_check_command = ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1"]

  log_group_name     = local.log_groups["frontend"]
  log_retention_days = var.log_retention_days

  subnet_ids         = aws_subnet.app[*].id
  security_group_ids = [aws_security_group.frontend.id]

  min_count  = var.service_min_count
  max_count  = var.service_max_count
  cpu_target = 60

  enable_load_balancer = true
  target_group_arn     = aws_lb_target_group.frontend.arn

  wait_for_steady_state = var.wait_for_steady_state

  depends_on = [
    aws_ecs_cluster_capacity_providers.main,
    aws_route.app_nat,
    aws_route_table_association.app,
    terraform_data.image,
    aws_lb_listener.http,
    aws_lb_listener.https,
  ]
}
