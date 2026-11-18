# Alertas por SNS, alarmes operacionais e dashboard. Os log groups dos serviços
# ficam no módulo ecs-service; o do db-init, em db_init.tf.

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alertas"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == null ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# --- Alarmes ---------------------------------------------------------------

locals {
  # Alarmes "menos de 2 tasks em execução", um por serviço.
  task_count_alarms = {
    api    = module.api.service_name
    worker = module.worker.service_name
    chat   = module.chat.service_name
  }

  # Alarmes "menos de 2 targets saudáveis no ALB".
  target_alarms = {
    api      = aws_lb_target_group.api.arn_suffix
    frontend = aws_lb_target_group.frontend.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "targets_unhealthy" {
  for_each = local.target_alarms

  alarm_name        = "${local.name}-${each.key}-targets-unhealthy"
  alarm_description = "Menos de ${var.service_min_count} targets saudaveis de ${each.key} no ALB"

  namespace   = "AWS/ApplicationELB"
  metric_name = "HealthyHostCount"
  statistic   = "Minimum"
  period      = 60

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = each.value
  }

  comparison_operator = "LessThanThreshold"
  threshold           = var.service_min_count
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "tasks_low" {
  for_each = local.task_count_alarms

  alarm_name        = "${local.name}-${each.key}-tasks-low"
  alarm_description = "Menos de ${var.service_min_count} tasks de ${each.key} em execucao"

  namespace   = "ECS/ContainerInsights"
  metric_name = "RunningTaskCount"
  statistic   = "Average"
  period      = 60

  # Escritas direto com o nome do serviço (erro corrigido em Ohio).
  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = each.value
  }

  comparison_operator = "LessThanThreshold"
  threshold           = var.service_min_count
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  treat_missing_data  = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name        = "${local.name}-dlq-messages"
  alarm_description = "Ha mensagens na DLQ de pedidos"

  namespace   = "AWS/SQS"
  metric_name = "ApproximateNumberOfMessagesVisible"
  statistic   = "Maximum"
  period      = 60

  dimensions = {
    QueueName = aws_sqs_queue.orders_dlq.name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# --- Dashboard -------------------------------------------------------------

# Mesmos 13 widgets de backend/observability/cloudwatch-dashboard.json, com os
# nomes e ARNs deste ambiente e as séries do chat e do frontend.

locals {
  ecs_services = {
    API      = module.api.service_name
    Worker   = module.worker.service_name
    Chat     = module.chat.service_name
    Frontend = module.frontend.service_name
  }

  alb_api_dimensions = ["LoadBalancer", aws_lb.main.arn_suffix, "TargetGroup", aws_lb_target_group.api.arn_suffix]
  alb_web_dimensions = ["LoadBalancer", aws_lb.main.arn_suffix, "TargetGroup", aws_lb_target_group.frontend.arn_suffix]

  dashboard_metric_widgets = [
    {
      title = "ECS - Tasks em execucao"
      stat  = "Average"
      metrics = [for label, service in local.ecs_services :
        ["ECS/ContainerInsights", "RunningTaskCount", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", service, { label = label }]
      ]
    },
    {
      title = "ECS - Utilizacao de CPU (%)"
      stat  = "Average"
      metrics = [for label, service in local.ecs_services :
        ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", service, { label = "CPU ${label}" }]
      ]
    },
    {
      title = "ECS - Utilizacao de memoria (%)"
      stat  = "Average"
      metrics = [for label, service in local.ecs_services :
        ["AWS/ECS", "MemoryUtilization", "ClusterName", aws_ecs_cluster.main.name, "ServiceName", service, { label = "Memoria ${label}" }]
      ]
    },
    {
      title = "SQS - Mensagens disponiveis"
      stat  = "Maximum"
      metrics = [
        ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.orders.name, { label = "Fila principal" }],
        ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", aws_sqs_queue.orders_dlq.name, { label = "DLQ" }],
      ]
    },
    {
      title = "ALB - Targets saudaveis"
      stat  = "Minimum"
      metrics = [
        concat(["AWS/ApplicationELB", "HealthyHostCount"], local.alb_api_dimensions, [{ label = "API" }]),
        concat(["AWS/ApplicationELB", "HealthyHostCount"], local.alb_web_dimensions, [{ label = "Frontend" }]),
      ]
    },
    {
      title = "ALB - Tempo de resposta"
      stat  = "Average"
      metrics = [
        concat(["AWS/ApplicationELB", "TargetResponseTime"], local.alb_api_dimensions, [{ label = "API (segundos)" }]),
        concat(["AWS/ApplicationELB", "TargetResponseTime"], local.alb_web_dimensions, [{ label = "Frontend (segundos)" }]),
      ]
    },
    {
      title = "ALB - Requisicoes recebidas"
      stat  = "Sum"
      metrics = [
        concat(["AWS/ApplicationELB", "RequestCount"], local.alb_api_dimensions, [{ label = "API" }]),
        concat(["AWS/ApplicationELB", "RequestCount"], local.alb_web_dimensions, [{ label = "Frontend" }]),
      ]
    },
    {
      title = "ALB - Erros HTTP 5xx"
      stat  = "Sum"
      metrics = [
        concat(["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count"], local.alb_api_dimensions, [{ label = "API" }]),
        concat(["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count"], local.alb_web_dimensions, [{ label = "Frontend" }]),
      ]
    },
    {
      title = "ECS - Reserva do Capacity Provider (%)"
      stat  = "Average"
      metrics = [
        ["AWS/ECS/ManagedScaling", "CapacityProviderReservation", "ClusterName", aws_ecs_cluster.main.name, "CapacityProviderName", aws_ecs_capacity_provider.ec2.name, { label = "Reserva EC2" }],
      ]
    },
    {
      title = "RDS - Utilizacao de CPU (%)"
      stat  = "Average"
      metrics = [
        ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.postgres.identifier, { label = "CPU PostgreSQL" }],
      ]
    },
    {
      title = "RDS - Conexoes com PostgreSQL"
      stat  = "Average"
      metrics = [
        ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.postgres.identifier, { label = "Conexoes" }],
      ]
    },
    {
      title = "SQS - Idade da mensagem mais antiga"
      stat  = "Maximum"
      metrics = [
        ["AWS/SQS", "ApproximateAgeOfOldestMessage", "QueueName", aws_sqs_queue.orders.name, { label = "Idade (segundos)" }],
      ]
    },
  ]

  dashboard_alarm_arns = concat(
    [for alarm in aws_cloudwatch_metric_alarm.targets_unhealthy : alarm.arn],
    [for alarm in aws_cloudwatch_metric_alarm.tasks_low : alarm.arn],
    [aws_cloudwatch_metric_alarm.dlq_messages.arn],
  )
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-observabilidade"

  dashboard_body = jsonencode({
    start          = "-PT6H"
    periodOverride = "inherit"

    widgets = concat(
      [{
        type   = "alarm"
        x      = 0
        y      = 0
        width  = 24
        height = 4
        properties = {
          title  = "Insper Eats - Alarmes Operacionais"
          sortBy = "stateUpdatedTimestamp"
          alarms = local.dashboard_alarm_arns
        }
      }],
      # Duas colunas de 12, a partir da linha 4.
      [for index, widget in local.dashboard_metric_widgets : {
        type   = "metric"
        x      = (index % 2) * 12
        y      = 4 + floor(index / 2) * 6
        width  = 12
        height = 6
        properties = {
          title   = widget.title
          region  = var.region
          view    = "timeSeries"
          period  = 60
          stat    = widget.stat
          metrics = widget.metrics
        }
      }],
    )
  })
}
