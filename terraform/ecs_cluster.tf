# Cluster ECS sobre EC2 com Capacity Provider. O Auto Scaling Group começa em
# zero: quem decide quantas instâncias existem é o Capacity Provider, a partir
# das tasks que precisam de lugar.

resource "aws_ecs_cluster" "main" {
  name = "${local.name}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  depends_on = [aws_cloudwatch_log_group.container_insights]
}

# O Container Insights cria este log group sozinho, sem retenção definida e
# fora do Terraform. Criá-lo antes o mantém sob gestão e o remove no destroy.
resource "aws_cloudwatch_log_group" "container_insights" {
  name              = "/aws/ecs/containerinsights/${local.name}-cluster/performance"
  retention_in_days = var.log_retention_days
}

# --- Instâncias ------------------------------------------------------------

data "aws_ssm_parameter" "ecs_ami" {
  name = "/aws/service/ecs/optimized-ami/amazon-linux-2023/recommended/image_id"
}

resource "aws_iam_role" "ecs_instance" {
  name = "${local.name}-ecs-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_instance" {
  for_each = {
    ecs = "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role"
    ssm = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }

  role       = aws_iam_role.ecs_instance.name
  policy_arn = each.value
}

resource "aws_iam_instance_profile" "ecs_instance" {
  name = "${local.name}-ecs-instance-profile"
  role = aws_iam_role.ecs_instance.name
}

resource "aws_launch_template" "ecs" {
  name                   = "${local.name}-ecs-launch-template"
  image_id               = nonsensitive(data.aws_ssm_parameter.ecs_ami.value)
  instance_type          = var.ecs_instance_type
  vpc_security_group_ids = [aws_security_group.ecs_instances.id]
  update_default_version = true

  iam_instance_profile {
    arn = aws_iam_instance_profile.ecs_instance.arn
  }

  # Ingressa a instância no cluster.
  user_data = base64encode(<<-EOT
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.main.name}" >> /etc/ecs/ecs.config
    # Tasks awsvpc não alcançam o IMDS: sem isso, um contêiner comprometido
    # obteria as credenciais do papel da instância. Cada task usa só a sua
    # task role, entregue pelo endpoint de credenciais do ECS.
    echo "ECS_AWSVPC_BLOCK_IMDS=true" >> /etc/ecs/ecs.config
  EOT
  )

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  monitoring {
    enabled = true
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 30
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.tags, { Name = "${local.name}-ecs-instance" })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = merge(local.tags, { Name = "${local.name}-ecs-instance" })
  }
}

resource "aws_autoscaling_group" "ecs" {
  name                = "${local.name}-ecs-asg"
  vpc_zone_identifier = aws_subnet.app[*].id
  min_size            = 0
  max_size            = var.ecs_asg_max_size

  health_check_type = "EC2"

  # Publica as métricas do grupo no CloudWatch (AWS/AutoScaling); o alarme de
  # capacidade em observability.tf depende delas.
  enabled_metrics = ["GroupDesiredCapacity", "GroupInServiceInstances"]

  # Exigido pela managed termination protection do Capacity Provider.
  protect_from_scale_in = true

  # No destroy, encerra as instâncias mesmo protegidas contra scale-in.
  force_delete = true

  launch_template {
    id      = aws_launch_template.ecs.id
    version = aws_launch_template.ecs.latest_version
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }

  lifecycle {
    # desired_capacity pertence ao Capacity Provider; forçá-lo aqui desfaz o
    # escalonamento gerenciado.
    ignore_changes = [desired_capacity]
  }

  depends_on = [aws_route.app_nat]
}

# --- Capacity Provider -----------------------------------------------------

resource "aws_ecs_capacity_provider" "ec2" {
  name = "${local.name}-ecs-capacity-provider"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.ecs.arn
    managed_termination_protection = "ENABLED"
    managed_draining               = "ENABLED"

    managed_scaling {
      status                    = "ENABLED"
      target_capacity           = 100
      minimum_scaling_step_size = 1
      # 4 por rodada: o primeiro apply sai de 0 para as 4 instâncias de repouso
      # de uma vez, em vez de duas rodadas de alarme + boot.
      maximum_scaling_step_size = 4
      instance_warmup_period    = 300
    }
  }
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = [aws_ecs_capacity_provider.ec2.name, "FARGATE"]

  default_capacity_provider_strategy {
    capacity_provider = aws_ecs_capacity_provider.ec2.name
    weight            = 1
    base              = 0
  }
}
