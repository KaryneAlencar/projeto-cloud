# RDS PostgreSQL privado. A senha do administrador é criada e girada pelo
# próprio RDS no Secrets Manager; o Terraform nunca a vê.

resource "aws_db_subnet_group" "main" {
  name        = "${local.name}-db-subnet-group"
  description = "Sub-redes privadas de dados do ${local.name}"
  subnet_ids  = aws_subnet.data[*].id

  tags = { Name = "${local.name}-db-subnet-group" }
}

resource "aws_db_instance" "postgres" {
  identifier = "${local.name}-postgres"

  engine                     = "postgres"
  engine_version             = var.db_engine_version
  auto_minor_version_upgrade = true
  instance_class             = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name                     = local.db_name
  username                    = var.db_master_username
  manage_master_user_password = true

  multi_az               = var.db_multi_az
  publicly_accessible    = false
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  backup_retention_period = var.db_backup_retention_days
  copy_tags_to_snapshot   = true
  apply_immediately       = true

  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${local.name}-postgres-final"

  tags = { Name = "${local.name}-postgres" }
}
