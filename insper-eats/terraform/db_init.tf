# Task temporária que prepara o PostgreSQL: usuários de aplicação, banco do
# chat, permissões e tabelas da API (ver files/db_init.py).
#
# É a única task que recebe a credencial de administrador do RDS, por uma
# execution role própria. Roda em Fargate para não depender das instâncias
# EC2, que só existem depois que os serviços pedem capacidade.

resource "aws_cloudwatch_log_group" "db_init" {
  name              = "/ecs/${local.name}/db-init"
  retention_in_days = 7
}

resource "aws_iam_role" "db_init_execution" {
  name = "${local.name}-db-init-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "db_init_execution" {
  role       = aws_iam_role.db_init_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "db_init_secrets" {
  name = "${local.name}-db-init-secrets"
  role = aws_iam_role.db_init_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "secretsmanager:GetSecretValue"
      Resource = [
        aws_db_instance.postgres.master_user_secret[0].secret_arn,
        aws_secretsmanager_secret.database_url.arn,
        aws_secretsmanager_secret.chat_database_url.arn,
      ]
    }]
  })
}

resource "aws_ecs_task_definition" "db_init" {
  family                   = "${local.name}-db-init"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.db_init_execution.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  # Reaproveita a imagem da API, que já traz Python, psycopg e os modelos.
  container_definitions = jsonencode([{
    name      = "db-init"
    image     = local.image_uris["api"]
    essential = true
    command   = ["python", "-c", file("${path.module}/files/db_init.py")]

    environment = [
      { name = "DB_HOST", value = aws_db_instance.postgres.address },
      { name = "DB_NAME", value = local.db_name },
      { name = "DB_PORT", value = tostring(aws_db_instance.postgres.port) },
      { name = "SEED_PRODUCTS", value = jsonencode(var.seed_products) },
    ]

    secrets = [
      { name = "CHAT_DATABASE_URL", valueFrom = aws_secretsmanager_secret.chat_database_url.arn },
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.database_url.arn },
      { name = "MASTER_PASSWORD", valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:password::" },
      { name = "MASTER_USERNAME", valueFrom = "${aws_db_instance.postgres.master_user_secret[0].secret_arn}:username::" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.db_init.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "db-init"
      }
    }
  }])
}

# Executa a task e espera o resultado. Repete quando o script, a imagem, o
# banco ou as credenciais mudam.
resource "terraform_data" "db_init" {
  count = var.run_db_init ? 1 : 0

  triggers_replace = {
    task_definition = aws_ecs_task_definition.db_init.arn
    database        = aws_db_instance.postgres.id
    credentials     = var.credentials_version
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "\"$SCRIPT\""

    environment = merge(local.script_env, {
      SCRIPT          = "${path.module}/scripts/run-db-init.sh"
      CLUSTER         = aws_ecs_cluster.main.name
      TASK_DEFINITION = aws_ecs_task_definition.db_init.arn
      SUBNETS         = join(",", aws_subnet.app[*].id)
      SECURITY_GROUP  = aws_security_group.db_init.id
      LOG_GROUP       = aws_cloudwatch_log_group.db_init.name
    })
  }

  depends_on = [
    terraform_data.image,
    aws_ecs_cluster_capacity_providers.main,
    aws_iam_role_policy_attachment.db_init_execution,
    aws_iam_role_policy.db_init_secrets,
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.chat_database_url,
    aws_route.app_nat,
    aws_route_table_association.app,
    aws_vpc_security_group_egress_rule.https_out,
    aws_vpc_security_group_egress_rule.to_rds,
    aws_vpc_security_group_ingress_rule.rds_from_clients,
  ]
}
