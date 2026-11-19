# Repositórios ECR e publicação das imagens.
#
# A tag de cada imagem é um hash dos arquivos que entram no build. Código igual
# gera a mesma tag (nada é reconstruído); código alterado gera uma tag nova, o
# que cria uma nova revisão da task definition e um deployment do serviço.

locals {
  images = {
    api = {
      context    = "${path.module}/../backend"
      dockerfile = "Dockerfile.api"
      sources    = ["main.py", "database.py", "models.py", "pedidos.py", "requirements.txt", "Dockerfile.api"]
    }
    worker = {
      context    = "${path.module}/../backend"
      dockerfile = "Dockerfile.worker"
      sources    = ["worker.py", "database.py", "models.py", "requirements.txt", "Dockerfile.worker"]
    }
    chat = {
      context    = "${path.module}/../chat-service"
      dockerfile = "Dockerfile"
      sources    = ["app/**/*.py", "scripts/**/*.py", "requirements.txt", "Dockerfile", ".dockerignore"]
    }
    frontend = {
      context    = "${path.module}/../frontend"
      dockerfile = "Dockerfile"
      sources = [
        "src/**", "public/**", "nginx/**", "index.html", "package.json", "package-lock.json",
        "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts", "Dockerfile", ".dockerignore",
      ]
    }
  }

  image_source_hashes = {
    for name, image in local.images : name => sha256(join("\n", [
      for file in sort(distinct(flatten([for pattern in image.sources : fileset(image.context, pattern)]))) :
      "${file}:${filesha256("${image.context}/${file}")}"
    ]))
  }

  image_tags = {
    for name in keys(local.images) : name => var.build_images ? substr(local.image_source_hashes[name], 0, 12) : var.image_tag
  }

  image_uris = {
    for name in keys(local.images) : name => "${aws_ecr_repository.this[name].repository_url}:${local.image_tags[name]}"
  }
}

resource "aws_ecr_repository" "this" {
  for_each = local.images

  name                 = "${local.name}-${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = var.ecr_force_delete

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Mantem as 10 imagens mais recentes"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# docker build + push pela máquina que roda o apply. O script não refaz nada
# quando a tag já existe no repositório.
resource "terraform_data" "image" {
  for_each = var.build_images ? local.images : {}

  triggers_replace = {
    repository = aws_ecr_repository.this[each.key].repository_url
    tag        = local.image_tags[each.key]
  }

  provisioner "local-exec" {
    interpreter = ["bash", "-c"]
    command     = "\"$SCRIPT\""

    environment = merge(local.script_env, {
      SCRIPT          = "${path.module}/scripts/build-push.sh"
      REPOSITORY_NAME = aws_ecr_repository.this[each.key].name
      REPOSITORY_URL  = aws_ecr_repository.this[each.key].repository_url
      IMAGE_TAG       = local.image_tags[each.key]
      BUILD_CONTEXT   = each.value.context
      DOCKERFILE      = each.value.dockerfile
    })
  }
}
