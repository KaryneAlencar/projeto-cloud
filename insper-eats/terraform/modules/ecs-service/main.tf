# Serviço ECS completo: log group, papéis IAM, task definition, serviço e
# Application Auto Scaling. Usado pelos quatro serviços da aplicação.

locals {
  is_ec2 = var.launch_type == "EC2"

  # Só entram na definição os campos realmente usados.
  container = merge(
    {
      name        = var.container_name
      image       = var.image
      essential   = true
      stopTimeout = var.stop_timeout

      environment = [for name in sort(keys(var.environment)) : { name = name, value = var.environment[name] }]
      secrets     = [for name in sort(keys(var.secrets)) : { name = name, valueFrom = var.secrets[name] }]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = var.container_name
        }
      }
    },
    var.command == null ? {} : { command = var.command },
    var.container_port == null ? {} : {
      portMappings = [{ containerPort = var.container_port, hostPort = var.container_port, protocol = "tcp" }]
    },
    var.health_check_command == null ? {} : {
      healthCheck = {
        command     = var.health_check_command
        interval    = 15
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    },
  )
}

resource "aws_cloudwatch_log_group" "this" {
  name              = var.log_group_name
  retention_in_days = var.log_retention_days
}

# --- IAM -------------------------------------------------------------------

# Execution role: usada pelo ECS para puxar a imagem, gravar logs e injetar os
# secrets. Só enxerga os secrets deste serviço.
resource "aws_iam_role" "execution" {
  name = "${var.name}-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  count = length(var.secret_arns) > 0 ? 1 : 0

  name = "read-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "secretsmanager:GetSecretValue"
      Resource = var.secret_arns
    }]
  })
}

# Task role: identidade do código da aplicação. Vazia, salvo política explícita.
resource "aws_iam_role" "task" {
  name = "${var.name}-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task" {
  count = var.enable_task_role_policy ? 1 : 0

  name   = "application"
  role   = aws_iam_role.task.id
  policy = var.task_role_policy_json
}

# --- Task definition e serviço ---------------------------------------------

resource "aws_ecs_task_definition" "this" {
  family                   = var.name
  network_mode             = "awsvpc"
  requires_compatibilities = [var.launch_type]
  cpu                      = var.cpu
  memory                   = var.memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([local.container])

  dynamic "runtime_platform" {
    for_each = local.is_ec2 ? [] : [1]

    content {
      operating_system_family = "LINUX"
      cpu_architecture        = "X86_64"
    }
  }
}

resource "aws_ecs_service" "this" {
  name            = "${var.name}-service"
  cluster         = var.cluster_arn
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.min_count

  capacity_provider_strategy {
    capacity_provider = var.capacity_provider
    weight            = 1
    base              = 0
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = var.subnet_ids
    security_groups  = var.security_group_ids
    assign_public_ip = false
  }

  # Em EC2: espalha por AZ, depois concentra por memória. Com distinctInstance,
  # duas réplicas do mesmo serviço nunca dividem a mesma instância.
  dynamic "ordered_placement_strategy" {
    for_each = local.is_ec2 ? [
      { type = "spread", field = "attribute:ecs.availability-zone" },
      { type = "binpack", field = "memory" },
    ] : []

    content {
      type  = ordered_placement_strategy.value.type
      field = ordered_placement_strategy.value.field
    }
  }

  dynamic "placement_constraints" {
    for_each = local.is_ec2 ? [1] : []

    content {
      type = "distinctInstance"
    }
  }

  dynamic "load_balancer" {
    for_each = var.enable_load_balancer ? [1] : []

    content {
      target_group_arn = var.target_group_arn
      container_name   = var.container_name
      container_port   = var.container_port
    }
  }

  health_check_grace_period_seconds = var.enable_load_balancer ? var.health_check_grace_period : null

  dynamic "service_registries" {
    for_each = var.enable_service_discovery ? [1] : []

    content {
      registry_arn = var.service_registry_arn
    }
  }

  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"
  wait_for_steady_state   = var.wait_for_steady_state

  lifecycle {
    # O Application Auto Scaling altera desired_count em produção.
    ignore_changes = [desired_count]
  }

  depends_on = [
    aws_iam_role_policy_attachment.execution,
    aws_iam_role_policy.execution_secrets,
    aws_iam_role_policy.task,
  ]
}

# --- Application Auto Scaling ----------------------------------------------

resource "aws_appautoscaling_target" "this" {
  service_namespace  = "ecs"
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.min_count
  max_capacity       = var.max_count
}

resource "aws_appautoscaling_policy" "cpu" {
  count = var.cpu_target == null ? 0 : 1

  name               = "${var.name}-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.this.service_namespace
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension

  target_tracking_scaling_policy_configuration {
    target_value       = var.cpu_target
    scale_out_cooldown = 60
    scale_in_cooldown  = 180

    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
