# Testes de plano com o provider AWS simulado: não usam credenciais, não criam
# nada e não custam nada. Verificam se a configuração gerada bate com os
# critérios de aceite do guia (seções 14 e 17).
#
#   terraform init -backend=false
#   terraform test

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
    override_during = plan

    defaults = {
      address = "insper-eats-sp-postgres.example.sa-east-1.rds.amazonaws.com"
      port    = 5432
      master_user_secret = [{
        secret_arn = "arn:aws:secretsmanager:sa-east-1:123456789012:secret:rds!db-00000000"
      }]
    }
  }

  mock_resource "aws_lb" {
    override_during = plan

    defaults = {
      arn        = "arn:aws:elasticloadbalancing:sa-east-1:123456789012:loadbalancer/app/insper-eats-sp-alb/0123456789abcdef"
      dns_name   = "insper-eats-sp-alb-123456789.sa-east-1.elb.amazonaws.com"
      arn_suffix = "app/insper-eats-sp-alb/0123456789abcdef"
    }
  }
}

variables {
  # Nada de docker, AWS CLI ou task db-init durante os testes.
  build_images = false
  run_db_init  = false
}

run "rede_em_tres_camadas" {
  command = plan

  assert {
    condition     = aws_vpc.main.cidr_block == "10.20.0.0/16"
    error_message = "A VPC deve usar 10.20.0.0/16."
  }

  assert {
    condition     = length(aws_subnet.public) == 2 && length(aws_subnet.app) == 2 && length(aws_subnet.data) == 2
    error_message = "São esperadas seis sub-redes: duas públicas, duas de aplicação e duas de dados."
  }

  assert {
    condition     = aws_subnet.app[0].availability_zone != aws_subnet.app[1].availability_zone
    error_message = "As sub-redes de aplicação devem ficar em AZs diferentes."
  }

  assert {
    condition     = alltrue([for subnet in concat(aws_subnet.public, aws_subnet.app, aws_subnet.data) : !subnet.map_public_ip_on_launch])
    error_message = "Nenhuma sub-rede deve atribuir IP público automaticamente."
  }

  assert {
    condition     = length(aws_nat_gateway.main) == 2
    error_message = "O padrão é um NAT Gateway por AZ."
  }
}

run "nat_unico_quando_solicitado" {
  command = plan

  variables {
    single_nat_gateway = true
  }

  assert {
    condition     = length(aws_nat_gateway.main) == 1 && length(aws_route.app_nat) == 2
    error_message = "Com single_nat_gateway, as duas tabelas de aplicação devem usar o mesmo NAT."
  }
}

run "banco_privado_e_criptografado" {
  command = plan

  assert {
    condition     = aws_db_instance.postgres.publicly_accessible == false
    error_message = "O RDS não pode ser público."
  }

  assert {
    condition     = aws_db_instance.postgres.multi_az && aws_db_instance.postgres.storage_encrypted
    error_message = "O RDS deve ser Multi-AZ e criptografado."
  }

  assert {
    condition     = aws_db_instance.postgres.engine == "postgres" && aws_db_instance.postgres.engine_version == "17"
    error_message = "O RDS deve ser PostgreSQL 17."
  }

  assert {
    condition     = aws_db_instance.postgres.manage_master_user_password
    error_message = "A senha do administrador deve ser gerenciada pelo RDS no Secrets Manager."
  }

  assert {
    condition     = aws_db_instance.postgres.instance_class == "db.t4g.small" && aws_db_instance.postgres.allocated_storage == 20 && aws_db_instance.postgres.storage_type == "gp3"
    error_message = "Classe e armazenamento do RDS diferem do ambiente validado."
  }
}

run "security_groups_segmentados" {
  command = plan

  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_http.cidr_ipv4 == "0.0.0.0/0" && aws_vpc_security_group_ingress_rule.alb_http.from_port == 80
    error_message = "O ALB deve aceitar HTTP 80 público."
  }

  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.alb_api) == 0
    error_message = "Por padrão, o listener da API não deve ter nenhum CIDR liberado."
  }

  assert {
    condition     = length(aws_vpc_security_group_ingress_rule.alb_https) == 0
    error_message = "Sem certificado, não deve existir entrada 443."
  }

  assert {
    condition     = toset(keys(aws_vpc_security_group_ingress_rule.rds_from_clients)) == toset(["api", "worker", "chat", "db_init"])
    error_message = "Só API, worker, chat e db-init podem falar com o RDS."
  }

  assert {
    condition     = alltrue([for rule in aws_vpc_security_group_ingress_rule.rds_from_clients : rule.cidr_ipv4 == null && rule.from_port == 5432])
    error_message = "A entrada do RDS deve ser por security group, na porta 5432."
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.api_from_alb.cidr_ipv4 == null && aws_vpc_security_group_ingress_rule.api_from_chat.cidr_ipv4 == null
    error_message = "A API só deve receber tráfego do ALB e do chat."
  }
}

run "api_liberada_apenas_para_cidrs_informados" {
  command = plan

  variables {
    api_allowed_cidrs = ["203.0.113.10/32"]
  }

  assert {
    condition     = aws_vpc_security_group_ingress_rule.alb_api["203.0.113.10/32"].from_port == 8000
    error_message = "O CIDR informado deve liberar apenas a porta 8000 do ALB."
  }
}

run "filas_com_dlq" {
  command = plan

  assert {
    condition     = aws_sqs_queue.orders.name == "insper-eats-sp-orders" && aws_sqs_queue.orders_dlq.name == "insper-eats-sp-orders-dlq"
    error_message = "Nomes das filas fora do padrão."
  }

  assert {
    condition     = aws_sqs_queue.orders.fifo_queue == false
    error_message = "A fila de pedidos deve ser Standard."
  }

  assert {
    condition     = aws_sqs_queue.orders.visibility_timeout_seconds == 60
    error_message = "O visibility timeout deve ser 60 s, como no worker."
  }
}

run "cluster_e_capacity_provider" {
  command = plan

  assert {
    condition     = one(aws_ecs_cluster.main.setting).value == "enabled"
    error_message = "Container Insights deve estar habilitado."
  }

  assert {
    condition     = aws_autoscaling_group.ecs.min_size == 0 && aws_autoscaling_group.ecs.max_size == 10 && aws_autoscaling_group.ecs.protect_from_scale_in
    error_message = "O ASG deve ir de 0 a 10 instâncias, com proteção de scale-in."
  }

  assert {
    condition     = aws_launch_template.ecs.instance_type == "t3.medium" && aws_launch_template.ecs.metadata_options[0].http_tokens == "required"
    error_message = "Instâncias t3.medium com IMDSv2 obrigatório."
  }

  assert {
    condition = (
      aws_ecs_capacity_provider.ec2.auto_scaling_group_provider[0].managed_termination_protection == "ENABLED" &&
      aws_ecs_capacity_provider.ec2.auto_scaling_group_provider[0].managed_draining == "ENABLED" &&
      aws_ecs_capacity_provider.ec2.auto_scaling_group_provider[0].managed_scaling[0].target_capacity == 100 &&
      aws_ecs_capacity_provider.ec2.auto_scaling_group_provider[0].managed_scaling[0].maximum_scaling_step_size == 4 &&
      aws_ecs_capacity_provider.ec2.auto_scaling_group_provider[0].managed_scaling[0].instance_warmup_period == 300
    )
    error_message = "Managed scaling, termination protection e draining devem seguir o ambiente validado."
  }
}

run "servicos_ecs" {
  command = plan

  assert {
    condition = alltrue([
      for service in [module.api.service, module.worker.service, module.chat.service, module.frontend.service] :
      service.desired_count == 2 && service.deployment_maximum_percent == 200 && service.deployment_minimum_healthy_percent == 100
    ])
    error_message = "Todos os serviços devem iniciar com 2 tasks e deployment 200/100."
  }

  assert {
    condition = alltrue([
      for service in [module.api.service, module.worker.service, module.chat.service, module.frontend.service] :
      one(service.placement_constraints).type == "distinctInstance" &&
      [for strategy in service.ordered_placement_strategy : "${strategy.type}:${strategy.field}"] == ["spread:attribute:ecs.availability-zone", "binpack:memory"]
    ])
    error_message = "Os quatro serviços: spread por AZ, binpack por memória e distinctInstance."
  }

  assert {
    condition = alltrue([
      for service in [module.api.service, module.worker.service, module.chat.service, module.frontend.service] :
      one(service.capacity_provider_strategy).capacity_provider == "insper-eats-sp-ecs-capacity-provider"
    ])
    error_message = "Os quatro serviços devem usar o Capacity Provider EC2."
  }

  assert {
    condition = alltrue([
      for service in [module.api, module.worker, module.chat, module.frontend] :
      !contains([for strategy in service.service.capacity_provider_strategy : strategy.capacity_provider], "FARGATE") &&
      length(service.requires_compatibilities) == 1 && contains(service.requires_compatibilities, "EC2")
    ])
    error_message = "Nenhum serviço pode usar Fargate: o enunciado exige ECS sobre EC2."
  }

  assert {
    condition     = alltrue([for service in [module.api.service, module.worker.service, module.chat.service, module.frontend.service] : one(service.network_configuration).assign_public_ip == false])
    error_message = "Nenhuma task pode ter IP público."
  }

  assert {
    condition     = one(module.api.service.load_balancer).container_port == 8000 && one(module.frontend.service.load_balancer).container_port == 8080
    error_message = "API (8000) e frontend (8080) devem estar registrados no ALB."
  }

  assert {
    condition     = length(module.worker.service.load_balancer) == 0 && length(module.chat.service.load_balancer) == 0
    error_message = "Worker e chat não devem ter target group."
  }

  assert {
    condition     = module.worker.container.healthCheck.command[0] == "CMD" && strcontains(module.worker.container.healthCheck.command[3], "/tmp/worker-heartbeat")
    error_message = "O worker deve ter health check pelo arquivo de heartbeat."
  }
}

run "task_definitions_sem_segredos_em_texto" {
  command = plan

  assert {
    condition     = module.api.container.secrets[*].name == ["DATABASE_URL", "ORDERS_INTERNAL_TOKEN"]
    error_message = "A API deve receber DATABASE_URL e ORDERS_INTERNAL_TOKEN como secrets."
  }

  assert {
    condition     = module.chat.container.secrets[*].name == ["CHAT_DATABASE_URL", "GEMINI_API_KEY", "ORDERS_INTERNAL_TOKEN"]
    error_message = "O chat deve receber banco, chave Gemini e token interno como secrets."
  }

  assert {
    condition = alltrue(flatten([
      for container in [module.api.container, module.worker.container, module.chat.container, module.frontend.container] : [
        for variable in container.environment : !can(regex("(?i)(password|senha|token|api_key|database_url)", variable.name))
      ]
    ]))
    error_message = "Variáveis sensíveis não podem ir em environment; use secrets."
  }

  assert {
    condition     = { for variable in module.worker.container.environment : variable.name => variable.value }["SQS_QUEUE_NAME"] == "insper-eats-sp-orders"
    error_message = "O worker deve apontar para a fila deste ambiente."
  }

  assert {
    condition     = { for variable in module.worker.container.environment : variable.name => variable.value }["AWS_REGION"] == "sa-east-1"
    error_message = "O worker deve usar a região do ambiente (o padrão do código é us-east-2)."
  }

  assert {
    condition     = { for variable in module.chat.container.environment : variable.name => variable.value }["ORDERS_API_URL"] == "http://api.insper-eats-sp.internal:8000"
    error_message = "O chat deve chamar a API pelo endereço interno."
  }

  assert {
    condition     = { for variable in module.chat.container.environment : variable.name => variable.value }["APP_ORIGINS"] == "http://insper-eats-sp-alb-123456789.sa-east-1.elb.amazonaws.com"
    error_message = "APP_ORIGINS deve ser a origem pública exata do ALB."
  }

  assert {
    condition     = { for variable in module.chat.container.environment : variable.name => variable.value }["COOKIE_SECURE"] == "false"
    error_message = "Sem HTTPS, COOKIE_SECURE deve ser false."
  }

  assert {
    condition     = { for variable in module.frontend.container.environment : variable.name => variable.value }["CHAT_UPSTREAM"] == "http://chat.insper-eats-sp.internal:8001"
    error_message = "O Nginx deve encaminhar /api para o endereço interno do chat."
  }

  assert {
    condition     = module.api.container.cpu_units == 256 && module.api.container.memory_mib == 512
    error_message = "As tasks devem usar 256 CPU units e 512 MiB."
  }

  assert {
    condition = alltrue([
      for container in [module.api.container, module.worker.container, module.chat.container, module.frontend.container] :
      container.memoryReservation == 384
    ])
    error_message = "Os quatro contêineres devem reservar 384 MiB (memoryReservation)."
  }
}

run "escalonamento" {
  command = plan

  assert {
    condition = alltrue([
      for target in [module.api.autoscaling, module.worker.autoscaling, module.chat.autoscaling, module.frontend.autoscaling] :
      target.min_capacity == 2 && target.max_capacity == 4
    ])
    error_message = "Todos os serviços devem escalar entre 2 e 4 tasks."
  }

  assert {
    condition     = module.api.cpu_policy.target_value == 60 && module.api.cpu_policy.scale_out_cooldown == 60 && module.api.cpu_policy.scale_in_cooldown == 180
    error_message = "API: CPU alvo 60%, cooldowns 60 s / 180 s."
  }

  assert {
    condition     = aws_appautoscaling_policy.worker_backlog.target_tracking_scaling_policy_configuration[0].target_value == 5
    error_message = "Worker: alvo de 5 mensagens por task."
  }

  assert {
    condition = [
      for metric in aws_appautoscaling_policy.worker_backlog.target_tracking_scaling_policy_configuration[0].customized_metric_specification[0].metrics :
      metric.id if metric.return_data
    ] == ["e1"]
    error_message = "A política do worker deve retornar apenas a expressão m1 / m2."
  }
}

run "entrada_http" {
  command = plan

  assert {
    condition     = aws_lb.main.internal == false && aws_lb.main.idle_timeout == 180
    error_message = "ALB público com idle timeout de 180 s."
  }

  assert {
    condition     = aws_lb_target_group.api.target_type == "ip" && aws_lb_target_group.api.port == 8000 && aws_lb_target_group.api.health_check[0].path == "/health"
    error_message = "Target group da API: tipo ip, porta 8000, health check /health."
  }

  assert {
    condition     = aws_lb_listener.http.default_action[0].type == "forward" && length(aws_lb_listener.https) == 0
    error_message = "Sem certificado, o listener 80 encaminha direto para o frontend."
  }
}

run "https_quando_ha_certificado" {
  command = plan

  variables {
    acm_certificate_arn = "arn:aws:acm:sa-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    app_domain          = "eats.example.com"
  }

  assert {
    condition     = aws_lb_listener.http.default_action[0].type == "redirect" && aws_lb_listener.https[0].port == 443
    error_message = "Com certificado: 80 redireciona e 443 atende."
  }

  assert {
    condition     = { for variable in module.chat.container.environment : variable.name => variable.value }["COOKIE_SECURE"] == "true"
    error_message = "Com HTTPS, COOKIE_SECURE deve ser true."
  }

  assert {
    condition     = output.app_url == "https://eats.example.com"
    error_message = "app_url deve ser o domínio HTTPS."
  }
}

run "certificado_sem_dominio_e_recusado" {
  command = plan

  variables {
    acm_certificate_arn = "arn:aws:acm:sa-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  }

  expect_failures = [var.app_domain]
}

run "observabilidade" {
  command = plan

  assert {
    condition = toset(output.alarm_names) == toset([
      "insper-eats-sp-api-targets-unhealthy",
      "insper-eats-sp-frontend-targets-unhealthy",
      "insper-eats-sp-api-tasks-low",
      "insper-eats-sp-worker-tasks-low",
      "insper-eats-sp-chat-tasks-low",
      "insper-eats-sp-frontend-tasks-low",
      "insper-eats-sp-alb-5xx",
      "insper-eats-sp-dlq-messages",
      "insper-eats-sp-cluster-capacity-high",
      "insper-eats-sp-asg-at-max",
      "insper-eats-sp-api-target-5xx",
      "insper-eats-sp-frontend-target-5xx",
      "insper-eats-sp-orders-queue-age",
      "insper-eats-sp-api-app-errors",
      "insper-eats-sp-worker-app-errors",
      "insper-eats-sp-chat-app-errors",
    ])
    error_message = "Conjunto de alarmes diferente do esperado."
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.cluster_capacity.metric_name == "CapacityProviderReservation" &&
      aws_cloudwatch_metric_alarm.cluster_capacity.threshold == 100 &&
      aws_cloudwatch_metric_alarm.cluster_capacity.dimensions["CapacityProviderName"] == "insper-eats-sp-ecs-capacity-provider"
    )
    error_message = "Alarme do cluster: reserva do Capacity Provider acima de 100%."
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.asg_at_max.threshold == 10 &&
      aws_cloudwatch_metric_alarm.asg_at_max.dimensions["AutoScalingGroupName"] == "insper-eats-sp-ecs-asg" &&
      contains(aws_autoscaling_group.ecs.enabled_metrics, "GroupInServiceInstances")
    )
    error_message = "Alarme do ASG: instâncias em serviço no máximo, com as métricas do grupo habilitadas."
  }

  assert {
    condition = alltrue([
      for alarm in aws_cloudwatch_metric_alarm.target_5xx :
      alarm.metric_name == "HTTPCode_Target_5XX_Count" && alarm.statistic == "Sum" && alarm.treat_missing_data == "notBreaching"
    ])
    error_message = "Alarmes de 5xx: soma por target group, sem dado não é falha."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.queue_age.threshold == 300 && aws_cloudwatch_metric_alarm.queue_age.dimensions["QueueName"] == "insper-eats-sp-orders"
    error_message = "Alarme da fila: mensagem mais antiga com mais de 300 s na fila principal."
  }

  assert {
    condition = alltrue([
      for service, alarm in aws_cloudwatch_metric_alarm.app_errors :
      alarm.namespace == "InsperEats/insper-eats-sp" && contains([
        for filter in aws_cloudwatch_log_metric_filter.app_errors : filter.metric_transformation[0].name
      ], alarm.metric_name)
    ])
    error_message = "Cada alarme de falhas da aplicação deve ler uma métrica gerada por um filtro de log."
  }

  assert {
    condition     = aws_cloudwatch_log_metric_filter.app_errors["worker"].log_group_name == "/ecs/insper-eats-sp/worker" && aws_cloudwatch_log_metric_filter.orders_confirmed.metric_transformation[0].name == "PedidosConfirmados"
    error_message = "Os filtros do worker devem ler o log group do worker e publicar PedidosConfirmados."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.tasks_low["api"].dimensions["ServiceName"] == "insper-eats-sp-api-service"
    error_message = "A dimensão ServiceName deve ser o nome literal do serviço."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.dlq_messages.threshold == 1 && aws_cloudwatch_metric_alarm.dlq_messages.comparison_operator == "GreaterThanOrEqualToThreshold"
    error_message = "Alarme da DLQ: >= 1 mensagem."
  }

  assert {
    condition     = aws_cloudwatch_log_group.db_init.retention_in_days == 7 && module.api.log_group.retention_in_days == 30
    error_message = "Retenção: 30 dias nos serviços, 7 no db-init."
  }

  assert {
    condition     = length(aws_sns_topic_subscription.email) == 0
    error_message = "Sem alert_email, não deve existir inscrição."
  }
}

run "nomes_nao_colidem_com_ohio" {
  command = plan

  assert {
    condition     = aws_ecs_cluster.main.name == "insper-eats-sp-cluster" && aws_iam_role.ecs_instance.name == "insper-eats-sp-ecs-instance-role"
    error_message = "Os nomes devem carregar o sufixo do ambiente."
  }

  assert {
    condition     = output.region == "sa-east-1"
    error_message = "A região padrão deve ser São Paulo."
  }
}
