output "service_name" {
  description = "Nome do serviço ECS."
  value       = aws_ecs_service.this.name
}

output "task_definition_arn" {
  description = "ARN da revisão atual da task definition."
  value       = aws_ecs_task_definition.this.arn
}

output "task_role_arn" {
  description = "ARN da task role."
  value       = aws_iam_role.task.arn
}

output "execution_role_arn" {
  description = "ARN da execution role."
  value       = aws_iam_role.execution.arn
}

output "autoscaling" {
  description = "Alvo do Application Auto Scaling, para políticas definidas fora do módulo."
  value       = aws_appautoscaling_target.this
}

# Os outputs abaixo existem para inspeção e para os testes em tests/.

output "service" {
  description = "Serviço ECS completo."
  value       = aws_ecs_service.this
}

output "container" {
  description = "Definição do contêiner, mais CPU e memória da task."
  value       = merge(local.container, { cpu_units = var.cpu, memory_mib = var.memory })
}

output "cpu_policy" {
  description = "Configuração do target tracking de CPU, ou null."
  value       = one([for policy in aws_appautoscaling_policy.cpu : policy.target_tracking_scaling_policy_configuration[0]])
}

output "log_group" {
  description = "Log group do serviço."
  value       = aws_cloudwatch_log_group.this
}
