# ---------------------------------------------------------------------------
# Conta, região e nomes
# ---------------------------------------------------------------------------

variable "region" {
  description = "Região AWS de destino. Ohio (us-east-2) é o ambiente manual já validado; o padrão aqui é São Paulo."
  type        = string
  default     = "sa-east-1"
}

variable "aws_profile" {
  description = "Perfil da AWS CLI/SSO usado pelo provider e pelos scripts. null usa as credenciais do ambiente (AWS_PROFILE, variáveis de ambiente etc.)."
  type        = string
  default     = null
}

variable "allowed_account_ids" {
  description = "Trava de segurança opcional: o apply só roda nestas contas AWS."
  type        = list(string)
  default     = []
}

variable "project" {
  description = "Nome do projeto, usado como prefixo dos recursos."
  type        = string
  default     = "insper-eats"
}

variable "environment" {
  description = "Sufixo do ambiente. Os papéis IAM são globais na conta, então o sufixo evita colisão com os recursos manuais de Ohio."
  type        = string
  default     = "sp"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,8}$", var.environment))
    error_message = "Use de 1 a 8 caracteres minúsculos, dígitos ou hífen."
  }
}

# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------

variable "vpc_cidr" {
  description = "CIDR da VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDRs das duas sub-redes públicas (ALB e NAT), uma por AZ."
  type        = list(string)
  default     = ["10.20.1.0/24", "10.20.2.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Informe exatamente dois CIDRs (duas AZs)."
  }
}

variable "app_subnet_cidrs" {
  description = "CIDRs das duas sub-redes privadas de aplicação (tasks e instâncias ECS)."
  type        = list(string)
  default     = ["10.20.11.0/24", "10.20.12.0/24"]

  validation {
    condition     = length(var.app_subnet_cidrs) == 2
    error_message = "Informe exatamente dois CIDRs (duas AZs)."
  }
}

variable "data_subnet_cidrs" {
  description = "CIDRs das duas sub-redes privadas de dados (RDS)."
  type        = list(string)
  default     = ["10.20.21.0/24", "10.20.22.0/24"]

  validation {
    condition     = length(var.data_subnet_cidrs) == 2
    error_message = "Informe exatamente dois CIDRs (duas AZs)."
  }
}

variable "single_nat_gateway" {
  description = "true cria um único NAT Gateway (mais barato, sem alta disponibilidade de saída). O ambiente validado usa um por AZ."
  type        = bool
  default     = false
}

variable "enable_sqs_vpc_endpoint" {
  description = "Cria o endpoint de interface do SQS nas sub-redes de aplicação, como no ambiente validado."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Entrada HTTP
# ---------------------------------------------------------------------------

variable "api_allowed_cidrs" {
  description = "CIDRs autorizados a acessar a API de pedidos pelo listener :8000 do ALB (testes e administração). Vazio mantém a API sem rota pública: /produtos não tem autenticação."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for cidr in var.api_allowed_cidrs : can(cidrhost(cidr, 0))])
    error_message = "Cada item deve ser um CIDR IPv4 válido, por exemplo 203.0.113.10/32."
  }
}

variable "acm_certificate_arn" {
  description = "ARN de um certificado ACM na mesma região. Quando informado, cria o listener HTTPS:443 e redireciona HTTP para HTTPS."
  type        = string
  default     = null
}

variable "app_domain" {
  description = "Domínio público da aplicação (obrigatório junto com acm_certificate_arn). O registro DNS apontando para o ALB é criado fora deste Terraform."
  type        = string
  default     = null

  validation {
    condition     = (var.acm_certificate_arn == null) == (var.app_domain == null)
    error_message = "Informe acm_certificate_arn e app_domain juntos, ou nenhum dos dois."
  }
}

# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------

variable "db_instance_class" {
  description = "Classe da instância RDS."
  type        = string
  default     = "db.t4g.small"
}

variable "db_allocated_storage" {
  description = "Armazenamento gp3 do RDS, em GiB."
  type        = number
  default     = 20
}

variable "db_engine_version" {
  description = "Versão do PostgreSQL. \"17\" acompanha a versão menor mais recente."
  type        = string
  default     = "17"
}

variable "db_multi_az" {
  description = "Multi-AZ do RDS. false reduz o custo em ambientes de teste curtos."
  type        = bool
  default     = true
}

variable "db_master_username" {
  description = "Usuário administrador do RDS. A senha é gerenciada pelo RDS no Secrets Manager."
  type        = string
  default     = "insper_admin"
}

variable "db_backup_retention_days" {
  description = "Dias de retenção dos backups automáticos."
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Proteção contra exclusão do RDS. Ative em ambientes que não serão destruídos."
  type        = bool
  default     = false
}

variable "db_skip_final_snapshot" {
  description = "true destrói o RDS sem snapshot final (ambiente de disciplina). false gera o snapshot <nome>-postgres-final."
  type        = bool
  default     = true
}

variable "credentials_version" {
  description = "Aumente em 1 para girar as senhas de aplicação do banco e o token interno da API. Dispara o db-init e um novo deployment dos serviços."
  type        = number
  default     = 1
}

variable "secret_recovery_window_days" {
  description = "Janela de recuperação dos secrets ao destruir. 0 apaga na hora e permite recriar o ambiente com os mesmos nomes."
  type        = number
  default     = 0
}

variable "seed_products" {
  description = "Catálogo inicial, inserido pela task db-init somente quando a tabela de produtos está vazia. Lista vazia não insere nada."
  type = list(object({
    nome    = string
    preco   = string
    estoque = number
  }))
  default = [
    { nome = "Brownie", preco = "8.00", estoque = 40 },
    { nome = "Pão de queijo", preco = "6.50", estoque = 60 },
    { nome = "Sanduíche natural", preco = "16.00", estoque = 30 },
    { nome = "Salada de frutas", preco = "12.00", estoque = 25 },
    { nome = "Café coado", preco = "5.00", estoque = 80 },
    { nome = "Suco de laranja", preco = "9.00", estoque = 40 },
  ]
}

variable "run_db_init" {
  description = "Executa a task db-init durante o apply (requer AWS CLI). Desative apenas se a inicialização for feita por outro meio."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Imagens
# ---------------------------------------------------------------------------

variable "build_images" {
  description = "Constrói e envia as imagens ao ECR durante o apply (requer Docker e AWS CLI). Com false, as tags de image_tag precisam existir nos repositórios."
  type        = bool
  default     = true
}

variable "image_tag" {
  description = "Tag usada quando build_images = false."
  type        = string
  default     = "v1"
}

variable "ecr_force_delete" {
  description = "Permite destruir repositórios ECR que ainda contêm imagens."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# ECS
# ---------------------------------------------------------------------------

variable "ecs_instance_type" {
  description = "Tipo das instâncias EC2 do cluster. t3.medium aceita só 2 tasks awsvpc por instância (3 ENIs)."
  type        = string
  default     = "t3.medium"
}

variable "ecs_asg_max_size" {
  description = "Máximo de instâncias EC2 no Auto Scaling Group."
  type        = number
  default     = 4
}

variable "service_min_count" {
  description = "Mínimo de tasks por serviço."
  type        = number
  default     = 2
}

variable "service_max_count" {
  description = "Máximo de tasks por serviço."
  type        = number
  default     = 4
}

variable "task_cpu" {
  description = "CPU units de cada task."
  type        = number
  default     = 256
}

variable "task_memory" {
  description = "Memória de cada task, em MiB."
  type        = number
  default     = 512
}

variable "task_memory_reservation" {
  description = "Reserva de memória (soft limit) do contêiner de cada task, em MiB. Deve ser menor ou igual a task_memory."
  type        = number
  default     = 384

  validation {
    condition     = var.task_memory_reservation > 0 && var.task_memory_reservation <= var.task_memory
    error_message = "task_memory_reservation deve ser maior que zero e menor ou igual a task_memory."
  }
}

variable "api_cpu_target" {
  description = "Alvo de CPU média (%) da API. Baixe temporariamente (ex.: 5) para demonstrar o scale-out, como no teste de Ohio."
  type        = number
  default     = 60
}

variable "worker_backlog_target" {
  description = "Mensagens visíveis por task do worker que disparam o scale-out."
  type        = number
  default     = 5
}

variable "worker_scaling_queue_name" {
  description = "Fila observada pela política do worker. null usa a fila principal; informe uma fila temporária para testar o scale-out sem poluir a fila real."
  type        = string
  default     = null
}

variable "wait_for_steady_state" {
  description = "O apply só termina quando os serviços ECS estabilizam. Falha em vez de reportar sucesso com tasks quebradas."
  type        = bool
  default     = true
}

# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

variable "ai_provider" {
  description = "gemini usa a IA real (exige a chave no secret gemini-api-key). commands usa o roteiro sem IA, útil para validar a implantação."
  type        = string
  default     = "gemini"

  validation {
    condition     = contains(["gemini", "commands"], var.ai_provider)
    error_message = "Use gemini ou commands."
  }
}

variable "gemini_api_key" {
  description = "Chave do Gemini, informada por TF_VAR_gemini_api_key. É efêmera: vai direto para o Secrets Manager e não é gravada no plan nem no state. null mantém um valor provisório."
  type        = string
  default     = null
  sensitive   = true
  ephemeral   = true
}

variable "gemini_api_key_version" {
  description = "Aumente em 1 para o Terraform regravar a chave do Gemini (troca de chave depois do primeiro apply)."
  type        = number
  default     = 1
}

variable "gemini_model" {
  description = "Modelo Gemini usado pelo chat."
  type        = string
  default     = "gemini-2.5-flash"
}

# ---------------------------------------------------------------------------
# Observabilidade
# ---------------------------------------------------------------------------

variable "alert_email" {
  description = "E-mail inscrito no tópico SNS de alertas. A AWS envia um link de confirmação. null não cria inscrição."
  type        = string
  default     = null
}

variable "log_retention_days" {
  description = "Retenção dos logs dos serviços no CloudWatch."
  type        = number
  default     = 30
}
