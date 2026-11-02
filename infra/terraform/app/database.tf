locals {
  db_name = "clinic_scheduling_dev" # required by app/db/safety.py
  db_tls  = "sslmode=verify-full&sslrootcert=/etc/ssl/certs/rds-ca-bundle.pem"
  # Password-less URLs; DATABASE_PASSWORD is injected from Secrets Manager.
  owner_url   = "postgresql+psycopg://clinic_demo@${aws_db_instance.main.address}:5432/${local.db_name}?${local.db_tls}"
  runtime_url = "postgresql+psycopg://clinic_app@${aws_db_instance.main.address}:5432/${local.db_name}?${local.db_tls}"
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_parameter_group" "main" {
  #checkov:skip=CKV2_AWS_30:log_statement=all would log the clinic_app password set by scripts.db_roles.
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # scripts.db_roles sends the runtime password in ALTER ROLE; keep it out of logs.
  parameter {
    name  = "log_statement"
    value = "none"
  }
}

resource "aws_cloudwatch_log_group" "postgresql" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; a CMK costs $1/month.
  #checkov:skip=CKV_AWS_338:Synthetic demo data; seven days is enough.
  name              = "/aws/rds/instance/${local.name}/postgresql"
  retention_in_days = var.log_retention_days
}

resource "aws_db_instance" "main" {
  #checkov:skip=CKV_AWS_157:Single-AZ is a cost decision for a demo with synthetic data.
  #checkov:skip=CKV_AWS_293:Deletion protection off so terraform destroy tears the demo down.
  #checkov:skip=CKV_AWS_161:Password auth via Secrets Manager; IAM auth would need token refresh in the app.
  #checkov:skip=CKV_AWS_118:Enhanced monitoring adds cost and a role; not needed for a demo.
  #checkov:skip=CKV_AWS_353:Performance Insights not needed for a demo.
  #checkov:skip=CKV_AWS_354:Performance Insights is off.
  #checkov:skip=CKV2_AWS_60:No final snapshot is kept, so tag copying does not matter.
  identifier     = local.name
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name                     = local.db_name
  username                    = "clinic_demo" # migration owner; required by the guard
  manage_master_user_password = true          # RDS-managed secret; never in Terraform state

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  parameter_group_name   = aws_db_parameter_group.main.name
  publicly_accessible    = false
  multi_az               = false
  ca_cert_identifier     = "rds-ca-rsa2048-g1"

  backup_retention_period         = 1
  delete_automated_backups        = true
  skip_final_snapshot             = true
  deletion_protection             = false
  auto_minor_version_upgrade      = true
  apply_immediately               = true
  copy_tags_to_snapshot           = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  depends_on = [aws_cloudwatch_log_group.postgresql]
}

# Runtime password for clinic_app. Ephemeral and write-only: generated during apply and
# sent to Secrets Manager, never stored in Terraform state or plan files. A new value is
# written only when app_password_version changes.
ephemeral "random_password" "app" {
  length  = 40
  special = false
}

resource "aws_secretsmanager_secret" "app_password" {
  #checkov:skip=CKV_AWS_149:The AWS-managed key is enough for a synthetic-data demo.
  #checkov:skip=CKV2_AWS_57:Rotated by bumping app_password_version and redeploying; no rotation Lambda.
  name                    = "${local.name}/clinic-app-password"
  description             = "Password of the clinic_app runtime database role"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app_password" {
  secret_id                = aws_secretsmanager_secret.app_password.id
  secret_string_wo         = ephemeral.random_password.app.result
  secret_string_wo_version = var.app_password_version
}

# Private DNS for the API: api.clinic.internal resolves to the running API task.
resource "aws_service_discovery_private_dns_namespace" "internal" {
  name = "clinic.internal"
  vpc  = aws_vpc.main.id
}

resource "aws_service_discovery_service" "api" {
  name = "api"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.internal.id
    routing_policy = "MULTIVALUE"
    dns_records {
      type = "A"
      ttl  = 10
    }
  }
}
