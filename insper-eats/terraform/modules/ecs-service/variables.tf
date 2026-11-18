variable "name" {
  description = "Nome base do serviço, por exemplo insper-eats-sp-api. Vira a família da task definition e o prefixo dos papéis IAM."
  type        = string
}

variable "region" {
  description = "Região AWS (driver de logs)."
  type        = string
}

variable "cluster_arn" {
  description = "ARN do cluster ECS."
  type        = string
}

variable "cluster_name" {
  description = "Nome do cluster ECS (Application Auto Scaling)."
  type        = string
}

variable "launch_type" {
  description = "EC2 ou FARGATE."
  type        = string

  validation {
    condition     = contains(["EC2", "FARGATE"], var.launch_type)
    error_message = "Use EC2 ou FARGATE."
  }
}

variable "capacity_provider" {
  description = "Capacity provider usado pelo serviço."
  type        = string
}

variable "image" {
  description = "URI completa da imagem, com tag."
  type        = string
}

variable "container_name" {
  description = "Nome do contêiner na task definition."
  type        = string
}

variable "command" {
  description = "Comando que substitui o CMD da imagem. null mantém o da imagem."
  type        = list(string)
  default     = null
}

variable "container_port" {
  description = "Porta exposta pelo contêiner. null para serviços sem HTTP."
  type        = number
  default     = null
}

variable "cpu" {
  description = "CPU units da task."
  type        = number
}

variable "memory" {
  description = "Memória da task, em MiB."
  type        = number
}

variable "environment" {
  description = "Variáveis de ambiente não sensíveis."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Variável de ambiente => ARN (valueFrom) do secret no Secrets Manager."
  type        = map(string)
  default     = {}
}

variable "secret_arns" {
  description = "ARNs dos secrets que a execution role pode ler."
  type        = list(string)
  default     = []
}

variable "task_role_policy_json" {
  description = "Política inline da task role (permissões da aplicação). Usada quando enable_task_role_policy = true."
  type        = string
  default     = null
}

variable "enable_task_role_policy" {
  description = "Anexa task_role_policy_json à task role."
  type        = bool
  default     = false
}

variable "health_check_command" {
  description = "Health check do contêiner, no formato da task definition (CMD ou CMD-SHELL). null não define."
  type        = list(string)
  default     = null
}

variable "stop_timeout" {
  description = "Segundos entre SIGTERM e SIGKILL ao parar o contêiner (máximo 120)."
  type        = number
  default     = 30
}

variable "log_group_name" {
  description = "Log group do CloudWatch."
  type        = string
}

variable "log_retention_days" {
  description = "Retenção do log group, em dias."
  type        = number
  default     = 30
}

variable "subnet_ids" {
  description = "Sub-redes privadas das tasks."
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security groups das tasks."
  type        = list(string)
}

variable "min_count" {
  description = "Mínimo de tasks (também o desired_count inicial)."
  type        = number
}

variable "max_count" {
  description = "Máximo de tasks."
  type        = number
}

variable "cpu_target" {
  description = "Alvo de CPU média (%) para target tracking. null não cria a política (o chamador define outra)."
  type        = number
  default     = null
}

variable "enable_load_balancer" {
  description = "Registra as tasks em target_group_arn."
  type        = bool
  default     = false
}

variable "target_group_arn" {
  description = "Target group do ALB."
  type        = string
  default     = null
}

variable "health_check_grace_period" {
  description = "Segundos em que o ECS ignora health checks do ALB após iniciar a task."
  type        = number
  default     = 60
}

variable "enable_service_discovery" {
  description = "Registra as tasks em service_registry_arn (Cloud Map)."
  type        = bool
  default     = false
}

variable "service_registry_arn" {
  description = "ARN do serviço do Cloud Map."
  type        = string
  default     = null
}

variable "wait_for_steady_state" {
  description = "O apply aguarda o serviço estabilizar."
  type        = bool
  default     = true
}
