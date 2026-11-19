# Alertas por SNS, alarmes operacionais, métricas extraídas dos logs e
# dashboard. Os log groups dos serviços ficam no módulo ecs-service; o do
# db-init, em db_init.tf.

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

  # Alarmes por target group do ALB: targets saudáveis e respostas 5xx.
  target_alarms = {
    api      = aws_lb_target_group.api.arn_suffix
    frontend = aws_lb_target_group.frontend.arn_suffix
  }

  # Métricas extraídas dos logs (falhas da aplicação e métrica de negócio).
  app_metrics_namespace = "InsperEats/${local.name}"

  app_error_metrics = {
    api    = "ErrosApi"
    worker = "ErrosWorker"
    chat   = "ErrosChat"
  }

  orders_confirmed_metric = "PedidosConfirmados"

  # Um filtro por formato de log. Cada linha de log é um evento, então o
  # traceback que acompanha um erro não é contado de novo.
  #   api:    Uvicorn padrão, "ERROR:    Exception in ASGI application".
  #   worker: logging.basicConfig, "ERROR:insper-eats-worker:Falha ...".
  #   chat:   a aplicação loga JSON com o campo "level" e registra as falhas
  #           de dependência (API de pedidos, IA) como WARNING com
  #           "..._dependency_failure" na mensagem; o Uvicorn do chat loga
  #           texto, como o da API. Os dois filtros somam na mesma métrica.
  app_error_filters = {
    api = {
      service = "api"
      pattern = "?\"ERROR:\" ?\"CRITICAL:\""
    }
    worker = {
      service = "worker"
      pattern = "?\"ERROR:\" ?\"CRITICAL:\""
    }
    chat = {
      service = "chat"
      pattern = "{ ($.level = \"ERROR\") || ($.level = \"CRITICAL\") || ($.message = \"*dependency_failure*\") }"
    }
    chat-uvicorn = {
      service = "chat"
      pattern = "?\"ERROR:\" ?\"CRITICAL:\""
    }
  }

  # Referenciar o output do módulo faz o filtro esperar o log group existir.
  app_log_group_names = {
    api    = module.api.log_group.name
    worker = module.worker.log_group.name
    chat   = module.chat.log_group.name
  }
}

# --- Métricas extraídas dos logs -------------------------------------------

resource "aws_cloudwatch_log_metric_filter" "app_errors" {
  for_each = local.app_error_filters

  name           = "${local.name}-${each.key}-erros"
  log_group_name = local.app_log_group_names[each.value.service]
  pattern        = each.value.pattern

  metric_transformation {
    namespace     = local.app_metrics_namespace
    name          = local.app_error_metrics[each.value.service]
    value         = "1"
    default_value = "0"
    unit          = "Count"
  }
}

# Métrica de negócio: pedidos confirmados pelo worker. A linha de mensagem
# duplicada ("Pedido N ja confirmado...") fica de fora.
resource "aws_cloudwatch_log_metric_filter" "orders_confirmed" {
  name           = "${local.name}-pedidos-confirmados"
  log_group_name = local.app_log_group_names["worker"]
  pattern        = "\"INFO:insper-eats-worker:Pedido\" \"confirmado\" -\"ja confirmado\""

  metric_transformation {
    namespace     = local.app_metrics_namespace
    name          = local.orders_confirmed_metric
    value         = "1"
    default_value = "0"
    unit          = "Count"
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

# Utilização do cluster: reserva acima de 100% significa tasks pedindo mais
# instâncias do que o ASG tem. Durante um scale-out normal isso dura poucos
# minutos (warm-up de 300 s); 10 minutos seguidos indicam tasks sem lugar.
resource "aws_cloudwatch_metric_alarm" "cluster_capacity" {
  alarm_name        = "${local.name}-cluster-capacity-high"
  alarm_description = "Reserva do Capacity Provider acima de 100% por 10 minutos (tasks sem lugar)"

  namespace   = "AWS/ECS/ManagedScaling"
  metric_name = "CapacityProviderReservation"
  statistic   = "Average"
  period      = 60

  dimensions = {
    ClusterName          = aws_ecs_cluster.main.name
    CapacityProviderName = aws_ecs_capacity_provider.ec2.name
  }

  comparison_operator = "GreaterThanThreshold"
  threshold           = 100
  evaluation_periods  = 10
  datapoints_to_alarm = 10
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Capacidade do ASG: no teto, o Capacity Provider não consegue mais escalar.
# Depende de enabled_metrics no Auto Scaling Group (ecs_cluster.tf).
resource "aws_cloudwatch_metric_alarm" "asg_at_max" {
  alarm_name        = "${local.name}-asg-at-max"
  alarm_description = "Auto Scaling Group no maximo de ${var.ecs_asg_max_size} instancias"

  namespace   = "AWS/AutoScaling"
  metric_name = "GroupInServiceInstances"
  statistic   = "Maximum"
  period      = 60

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.ecs.name
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.ecs_asg_max_size
  evaluation_periods  = 3
  datapoints_to_alarm = 3
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Respostas do ALB: 5 ou mais respostas 5xx dos targets em um minuto, em 2 de
# 3 minutos. Um erro isolado não dispara. Sem requisições não há dado, e isso
# não é falha.
resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  for_each = local.target_alarms

  alarm_name        = "${local.name}-${each.key}-target-5xx"
  alarm_description = "Targets de ${each.key} devolveram 5 ou mais respostas 5xx por minuto"

  namespace   = "AWS/ApplicationELB"
  metric_name = "HTTPCode_Target_5XX_Count"
  statistic   = "Sum"
  period      = 60

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = each.value
  }

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Profundidade da fila: a mensagem mais antiga espera há mais de 5 minutos,
# ou seja, o worker não está dando conta (ou parou de consumir).
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  alarm_name        = "${local.name}-orders-queue-age"
  alarm_description = "Mensagem mais antiga da fila de pedidos com mais de 300 s"

  namespace   = "AWS/SQS"
  metric_name = "ApproximateAgeOfOldestMessage"
  statistic   = "Maximum"
  period      = 60

  dimensions = {
    QueueName = aws_sqs_queue.orders.name
  }

  comparison_operator = "GreaterThanThreshold"
  threshold           = 300
  evaluation_periods  = 3
  datapoints_to_alarm = 2
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# Falhas da aplicação: 5 ou mais linhas de erro em 5 minutos, por serviço.
resource "aws_cloudwatch_metric_alarm" "app_errors" {
  for_each = local.app_error_metrics

  alarm_name        = "${local.name}-${each.key}-app-errors"
  alarm_description = "5 ou mais erros nos logs de ${each.key} em 5 minutos"

  namespace   = local.app_metrics_namespace
  metric_name = each.value
  statistic   = "Sum"
  period      = 300

  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 5
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.app_errors]
}

# --- Dashboard -------------------------------------------------------------

# Os 13 widgets de backend/observability/cloudwatch-dashboard.json, com os
# nomes e ARNs deste ambiente e as séries do chat e do frontend, mais um com a
# métrica de negócio (pedidos confirmados): 14 widgets.

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
    {
      title = "Negocio - Pedidos confirmados pelo worker"
      stat  = "Sum"
      metrics = [
        [local.app_metrics_namespace, aws_cloudwatch_log_metric_filter.orders_confirmed.metric_transformation[0].name, { label = "Pedidos confirmados" }],
      ]
    },
  ]

  dashboard_alarm_arns = concat(
    [for alarm in aws_cloudwatch_metric_alarm.targets_unhealthy : alarm.arn],
    [for alarm in aws_cloudwatch_metric_alarm.tasks_low : alarm.arn],
    [aws_cloudwatch_metric_alarm.dlq_messages.arn],
    [aws_cloudwatch_metric_alarm.cluster_capacity.arn],
    [aws_cloudwatch_metric_alarm.asg_at_max.arn],
    [for alarm in aws_cloudwatch_metric_alarm.target_5xx : alarm.arn],
    [aws_cloudwatch_metric_alarm.queue_age.arn],
    [for alarm in aws_cloudwatch_metric_alarm.app_errors : alarm.arn],
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
