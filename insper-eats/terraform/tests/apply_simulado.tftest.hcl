# Apply com o provider AWS simulado: percorre o grafo inteiro de dependências,
# inclusive valores que só existem depois da criação (ARNs, DNS do ALB), sem
# credenciais e sem criar nada na AWS.

mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["sa-east-1a", "sa-east-1b", "sa-east-1c"]
    }
  }

  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "ami-0123456789abcdef0"
    }
  }

  mock_resource "aws_db_instance" {
    defaults = {
      address = "insper-eats-sp-postgres.example.sa-east-1.rds.amazonaws.com"
      port    = 5432
      master_user_secret = [{
        secret_arn = "arn:aws:secretsmanager:sa-east-1:123456789012:secret:rds!db-00000000"
      }]
    }
  }

  mock_resource "aws_lb" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:sa-east-1:123456789012:loadbalancer/app/insper-eats-sp-alb/0123456789abcdef"
      dns_name   = "insper-eats-sp-alb-123456789.sa-east-1.elb.amazonaws.com"
      arn_suffix = "app/insper-eats-sp-alb/0123456789abcdef"
    }
  }

  # O provider valida o formato dos ARNs recebidos; os valores aleatórios do
  # mock não passam, então cada tipo referenciado ganha um ARN bem formado.
  mock_resource "aws_lb_target_group" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:sa-east-1:123456789012:targetgroup/insper-eats-sp-tg/0123456789abcdef"
      arn_suffix = "targetgroup/insper-eats-sp-tg/0123456789abcdef"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/insper-eats-sp-mock"
    }
  }

  mock_resource "aws_iam_instance_profile" {
    defaults = {
      arn = "arn:aws:iam::123456789012:instance-profile/insper-eats-sp-mock"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:sa-east-1:123456789012:insper-eats-sp-alertas"
    }
  }

  mock_resource "aws_ecs_cluster" {
    defaults = {
      arn = "arn:aws:ecs:sa-east-1:123456789012:cluster/insper-eats-sp-cluster"
    }
  }

  mock_resource "aws_ecs_task_definition" {
    defaults = {
      arn = "arn:aws:ecs:sa-east-1:123456789012:task-definition/insper-eats-sp-mock:1"
    }
  }

  mock_resource "aws_autoscaling_group" {
    defaults = {
      arn = "arn:aws:autoscaling:sa-east-1:123456789012:autoScalingGroup:00000000-0000-0000-0000-000000000000:autoScalingGroupName/insper-eats-sp-ecs-asg"
    }
  }

  mock_resource "aws_launch_template" {
    defaults = {
      id             = "lt-0123456789abcdef0"
      latest_version = 1
    }
  }

  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:sa-east-1:123456789012:insper-eats-sp-mock"
      url = "https://sqs.sa-east-1.amazonaws.com/123456789012/insper-eats-sp-mock"
    }
  }

  mock_resource "aws_secretsmanager_secret" {
    defaults = {
      arn = "arn:aws:secretsmanager:sa-east-1:123456789012:secret:insper-eats-sp/mock-AbCdEf"
    }
  }

  mock_resource "aws_service_discovery_service" {
    defaults = {
      arn = "arn:aws:servicediscovery:sa-east-1:123456789012:service/srv-0123456789abcdef"
    }
  }

  mock_resource "aws_cloudwatch_metric_alarm" {
    defaults = {
      arn = "arn:aws:cloudwatch:sa-east-1:123456789012:alarm:insper-eats-sp-mock"
    }
  }
}

variables {
  build_images = false
  run_db_init  = false
}

run "apply_simulado_completo" {
  command = apply

  assert {
    condition     = length(jsondecode(aws_cloudwatch_dashboard.main.dashboard_body).widgets) == 13
    error_message = "O dashboard deve ter 13 widgets, como o validado em Ohio."
  }

  assert {
    condition     = length(jsondecode(aws_cloudwatch_dashboard.main.dashboard_body).widgets[0].properties.alarms) == 6
    error_message = "O widget de alarmes deve listar os seis alarmes."
  }

  assert {
    condition     = output.api_url == "http://insper-eats-sp-alb-123456789.sa-east-1.elb.amazonaws.com:8000"
    error_message = "api_url deve apontar para o listener 8000 do ALB."
  }

  assert {
    condition     = length(output.ecr_repository_urls) == 4 && length(output.secret_names) == 4
    error_message = "São esperados quatro repositórios ECR e quatro secrets."
  }
}
