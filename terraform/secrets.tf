# Segredos de aplicação.
#
# As senhas são geradas por recursos efêmeros e enviadas ao Secrets Manager por
# argumentos write-only: não aparecem no plan, no state nem nos outputs. O
# Terraform só reenvia o valor quando credentials_version muda; a task db-init
# lê os mesmos secrets e aplica as senhas aos usuários do PostgreSQL.

ephemeral "random_password" "db_app" {
  length  = 40
  special = false
}

ephemeral "random_password" "db_chat" {
  length  = 40
  special = false
}

ephemeral "random_password" "orders_token" {
  length  = 48
  special = false
}

locals {
  db_endpoint = "${aws_db_instance.postgres.address}:${aws_db_instance.postgres.port}"
}

# --- DATABASE_URL da API e do worker ---------------------------------------

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${local.name}/database-url"
  description             = "DATABASE_URL do usuario ${local.db_app_user} (API e worker)"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id                = aws_secretsmanager_secret.database_url.id
  secret_string_wo         = "postgresql+psycopg://${local.db_app_user}:${ephemeral.random_password.db_app.result}@${local.db_endpoint}/${local.db_name}?sslmode=require"
  secret_string_wo_version = var.credentials_version

  lifecycle {
    # Banco recriado tem outro endpoint: a URL precisa ser regravada.
    replace_triggered_by = [aws_db_instance.postgres.id]
  }
}

# --- CHAT_DATABASE_URL -----------------------------------------------------

resource "aws_secretsmanager_secret" "chat_database_url" {
  name                    = "${local.name}/chat-database-url"
  description             = "CHAT_DATABASE_URL do usuario ${local.chat_db_user} (Chat Service)"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "chat_database_url" {
  secret_id                = aws_secretsmanager_secret.chat_database_url.id
  secret_string_wo         = "postgresql+psycopg://${local.chat_db_user}:${ephemeral.random_password.db_chat.result}@${local.db_endpoint}/${local.chat_db_name}?sslmode=require"
  secret_string_wo_version = var.credentials_version

  lifecycle {
    replace_triggered_by = [aws_db_instance.postgres.id]
  }
}

# --- Token interno entre chat e API de pedidos -----------------------------

# backend/pedidos.py exige o cabeçalho X-Internal-Token em /pedidos e responde
# 503 enquanto ORDERS_INTERNAL_TOKEN não estiver configurado.
resource "aws_secretsmanager_secret" "orders_internal_token" {
  name                    = "${local.name}/orders-internal-token"
  description             = "Token compartilhado entre o Chat Service e a API de pedidos"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "orders_internal_token" {
  secret_id                = aws_secretsmanager_secret.orders_internal_token.id
  secret_string_wo         = ephemeral.random_password.orders_token.result
  secret_string_wo_version = var.credentials_version
}

# --- Chave do Gemini -------------------------------------------------------

# A chave chega pela variável efêmera gemini_api_key (TF_VAR_gemini_api_key) e
# é enviada por argumento write-only: não fica no plan nem no state. Sem a
# variável, o secret recebe um valor provisório para as tasks conseguirem
# iniciar; nesse caso use ai_provider = "commands" ou grave a chave depois com
# scripts/set-gemini-key.sh.
resource "aws_secretsmanager_secret" "gemini_api_key" {
  name                    = "${local.name}/gemini-api-key"
  description             = "GEMINI_API_KEY do Chat Service"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "gemini_api_key" {
  secret_id                = aws_secretsmanager_secret.gemini_api_key.id
  secret_string_wo         = coalesce(var.gemini_api_key, "chave-nao-configurada")
  secret_string_wo_version = var.gemini_api_key_version
}
