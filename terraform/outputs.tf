# Nenhum output carrega valor de segredo: só nomes, URLs e ARNs.

output "region" {
  description = "Região do ambiente."
  value       = var.region
}

output "name_prefix" {
  description = "Prefixo dos recursos."
  value       = local.name
}

output "app_url" {
  description = "Endereço público da aplicação (frontend)."
  value       = local.app_origin
}

output "alb_dns_name" {
  description = "DNS do ALB. Com HTTPS, aponte o registro de app_domain para ele."
  value       = aws_lb.main.dns_name
}

output "api_url" {
  description = "API de pedidos pelo listener :8000 do ALB. Só responde para api_allowed_cidrs."
  value       = "http://${aws_lb.main.dns_name}:8000"
}

output "api_reachable_from" {
  description = "CIDRs com acesso ao listener da API."
  value       = var.api_allowed_cidrs
}

output "vpc_id" {
  description = "ID da VPC."
  value       = aws_vpc.main.id
}

output "ecs_cluster_name" {
  description = "Nome do cluster ECS."
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_names" {
  description = "Nomes dos serviços ECS."
  value = {
    api      = module.api.service_name
    worker   = module.worker.service_name
    chat     = module.chat.service_name
    frontend = module.frontend.service_name
  }
}

output "autoscaling_group_name" {
  description = "Auto Scaling Group das instâncias ECS."
  value       = aws_autoscaling_group.ecs.name
}

output "capacity_provider_name" {
  description = "Capacity Provider EC2 do cluster."
  value       = aws_ecs_capacity_provider.ec2.name
}

output "target_group_arns" {
  description = "Target groups do ALB."
  value = {
    api      = aws_lb_target_group.api.arn
    frontend = aws_lb_target_group.frontend.arn
  }
}

output "ecr_repository_urls" {
  description = "Repositórios ECR."
  value       = { for name, repository in aws_ecr_repository.this : name => repository.repository_url }
}

output "image_tags" {
  description = "Tags das imagens em uso."
  value       = local.image_tags
}

output "rds_identifier" {
  description = "Identificador da instância RDS."
  value       = aws_db_instance.postgres.identifier
}

output "rds_endpoint" {
  description = "Endpoint privado do RDS (acessível só de dentro da VPC)."
  value       = aws_db_instance.postgres.address
}

output "sqs_queue_url" {
  description = "URL da fila de pedidos."
  value       = aws_sqs_queue.orders.url
}

output "sqs_dlq_url" {
  description = "URL da Dead Letter Queue."
  value       = aws_sqs_queue.orders_dlq.url
}

output "secret_names" {
  description = "Nomes dos secrets no Secrets Manager (os valores não são expostos)."
  value = {
    database_url          = aws_secretsmanager_secret.database_url.name
    chat_database_url     = aws_secretsmanager_secret.chat_database_url.name
    orders_internal_token = aws_secretsmanager_secret.orders_internal_token.name
    gemini_api_key        = aws_secretsmanager_secret.gemini_api_key.name
  }
}

output "sns_topic_arn" {
  description = "Tópico SNS dos alertas."
  value       = aws_sns_topic.alerts.arn
}

output "alarm_names" {
  description = "Alarmes do CloudWatch."
  value = concat(
    [for alarm in aws_cloudwatch_metric_alarm.targets_unhealthy : alarm.alarm_name],
    [for alarm in aws_cloudwatch_metric_alarm.tasks_low : alarm.alarm_name],
    [aws_cloudwatch_metric_alarm.dlq_messages.alarm_name],
    [aws_cloudwatch_metric_alarm.cluster_capacity.alarm_name],
    [aws_cloudwatch_metric_alarm.asg_at_max.alarm_name],
    [for alarm in aws_cloudwatch_metric_alarm.target_5xx : alarm.alarm_name],
    [aws_cloudwatch_metric_alarm.queue_age.alarm_name],
    [for alarm in aws_cloudwatch_metric_alarm.app_errors : alarm.alarm_name],
  )
}

output "log_group_names" {
  description = "Log groups dos serviços."
  value = merge(local.log_groups, {
    db_init = aws_cloudwatch_log_group.db_init.name
  })
}

output "dashboard_url" {
  description = "Dashboard do CloudWatch."
  value       = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
