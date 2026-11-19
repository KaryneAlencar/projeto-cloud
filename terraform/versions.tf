terraform {
  # 1.11+ por causa de recursos efêmeros e argumentos write-only: as senhas
  # geradas aqui nunca são gravadas no state.
  required_version = ">= 1.11.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Configuração parcial: bucket, key e região vêm de backend.hcl
  # (gerado por terraform/bootstrap). Ver README.
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  profile             = var.aws_profile
  allowed_account_ids = length(var.allowed_account_ids) > 0 ? var.allowed_account_ids : null

  default_tags {
    tags = local.tags
  }
}
