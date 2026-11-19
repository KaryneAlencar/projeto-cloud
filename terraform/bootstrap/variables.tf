variable "region" {
  description = "Região do bucket de state. Use a mesma do ambiente."
  type        = string
  default     = "sa-east-1"
}

variable "aws_profile" {
  description = "Perfil da AWS CLI/SSO. null usa as credenciais do ambiente."
  type        = string
  default     = null
}

variable "project" {
  description = "Nome do projeto, prefixo do bucket."
  type        = string
  default     = "insper-eats"
}

variable "environment" {
  description = "Sufixo do ambiente, usado na chave do state."
  type        = string
  default     = "sp"
}

variable "force_destroy" {
  description = "Permite destruir o bucket mesmo com states dentro. Ative só para desmontar tudo ao final."
  type        = bool
  default     = false
}
