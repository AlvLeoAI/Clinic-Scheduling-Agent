locals {
  registry = "${local.account_id}.dkr.ecr.${local.region}.amazonaws.com"
  images = {
    api = "${local.registry}/clinic-scheduling-api:${var.image_tag}"
    ui  = "${local.registry}/clinic-scheduling-ui:${var.image_tag}"
  }
  log_groups = toset(["api", "ui", "migrate", "purge", "smoke"])

  # Same probes as the Dockerfiles (ECS ignores Dockerfile HEALTHCHECK), every 30 s.
  probe = "import urllib.request; urllib.request.urlopen('http://127.0.0.1:%d%s', timeout=3)"
  api_health = {
    command     = ["CMD", "python", "-c", format(local.probe, 8000, "/api/v1/health/live")]
    interval    = 30
    timeout     = 5
    retries     = 3
    startPeriod = 15
  }
  ui_health = {
    command     = ["CMD", "python", "-c", format(local.probe, 8501, "/_stcore/health")]
    interval    = 30
    timeout     = 5
    retries     = 3
    startPeriod = 20
  }

  app_password = [{ name = "DATABASE_PASSWORD", valueFrom = aws_secretsmanager_secret.app_password.arn }]
}

resource "aws_ecs_cluster" "main" {
  #checkov:skip=CKV_AWS_65:Container Insights is billed per metric; not needed for a demo.
  name = local.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_cloudwatch_log_group" "task" {
  #checkov:skip=CKV_AWS_158:Default CloudWatch encryption; a CMK costs $1/month.
  #checkov:skip=CKV_AWS_338:Synthetic demo data; seven days is enough.
  for_each          = local.log_groups
  name              = "/${local.name}/${each.key}"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------------------
# Execution roles: pull images, write logs, read only the secrets each task needs.
# No task roles: the containers call no AWS API.

data "aws_iam_policy_document" "ecs_tasks_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

locals {
  execution_roles = {
    runtime = { logs = ["api", "purge"], secrets = [aws_secretsmanager_secret.app_password.arn] }
    ui      = { logs = ["ui"], secrets = [] }
    smoke   = { logs = ["smoke"], secrets = [] } # HTTP only: no database credentials
    migrate = {
      logs = ["migrate"]
      secrets = [
        aws_db_instance.main.master_user_secret[0].secret_arn,
        aws_secretsmanager_secret.app_password.arn,
      ]
    }
  }
}

resource "aws_iam_role" "execution" {
  for_each           = local.execution_roles
  name               = "${local.name}-${each.key}-execution"
  path               = "/clinic-scheduling-agent/ecs/" # the deploy role may pass only these
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_trust.json
}

data "aws_iam_policy_document" "execution" {
  for_each = local.execution_roles

  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid     = "EcrPull"
    actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [
      "arn:aws:ecr:${local.region}:${local.account_id}:repository/clinic-scheduling-api",
      "arn:aws:ecr:${local.region}:${local.account_id}:repository/clinic-scheduling-ui",
    ]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for group in each.value.logs : "${aws_cloudwatch_log_group.task[group].arn}:log-stream:*"]
  }

  dynamic "statement" {
    for_each = length(each.value.secrets) > 0 ? [1] : []
    content {
      sid       = "Secrets"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = each.value.secrets
    }
  }
}

resource "aws_iam_role_policy" "execution" {
  for_each = local.execution_roles
  name     = "execution"
  role     = aws_iam_role.execution[each.key].id
  policy   = data.aws_iam_policy_document.execution[each.key].json
}

# ---------------------------------------------------------------------------
# Task definitions. Terraform registers the first revision of each family; the deploy
# workflow registers later ones with new image tags (services ignore task_definition).

locals {
  container_defaults = {
    essential              = true
    readonlyRootFilesystem = true
    user                   = "10001"
  }

  logging = { for group in local.log_groups : group => {
    logDriver = "awslogs"
    options = {
      awslogs-group         = aws_cloudwatch_log_group.task[group].name
      awslogs-region        = local.region
      awslogs-stream-prefix = group
      mode                  = "non-blocking"
      max-buffer-size       = "4m"
    }
  } }

  task_definitions = {
    api = {
      family = "clinic-api", memory = 512, role = "runtime"
      container = {
        image        = local.images.api
        portMappings = [{ containerPort = 8000, protocol = "tcp" }]
        healthCheck  = local.api_health
        environment = [
          { name = "AGENT_PROVIDER", value = "demo" },
          { name = "API_DOCS_ENABLED", value = "false" },
          { name = "DATABASE_URL", value = local.runtime_url },
          { name = "FORWARDED_ALLOW_IPS", value = local.vpc_cidr },
        ]
        secrets = local.app_password
      }
    }
    ui = {
      family = "clinic-ui", memory = 512, role = "ui"
      container = {
        image        = local.images.ui
        portMappings = [{ containerPort = 8501, protocol = "tcp" }]
        healthCheck  = local.ui_health
        environment = [
          { name = "API_BASE_URL", value = "http://api.clinic.internal:8000" },
        ]
        secrets = []
      }
    }
    migrate = {
      family = "clinic-migrate", memory = 512, role = "migrate"
      container = {
        image   = local.images.api
        command = ["sh", "-c", "alembic upgrade head && python -m scripts.seed && python -m scripts.db_roles"]
        environment = [
          { name = "AGENT_PROVIDER", value = "disabled" },
          { name = "DATABASE_URL", value = local.owner_url },
          { name = "DATABASE_ALLOWED_HOSTS", value = aws_db_instance.main.address },
        ]
        secrets = [
          { name = "DATABASE_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
          { name = "CLINIC_APP_PASSWORD", valueFrom = aws_secretsmanager_secret.app_password.arn },
        ]
      }
    }
    purge = {
      family = "clinic-purge", memory = 512, role = "runtime"
      container = {
        image   = local.images.api
        command = ["python", "-m", "scripts.purge_chat", "--apply"]
        environment = [
          { name = "AGENT_PROVIDER", value = "disabled" },
          { name = "DATABASE_URL", value = local.runtime_url },
        ]
        secrets = local.app_password
      }
    }
    # Post-deploy booking smoke, run by the deploy workflow inside the VPC. It talks to
    # the API through Cloud Map only and holds no database credentials.
    smoke = {
      family = "clinic-smoke", memory = 512, role = "smoke"
      container = {
        image       = local.images.api
        command     = ["python", "-m", "scripts.smoke_deploy", "--api", "http://api.clinic.internal:8000"]
        environment = []
        secrets     = []
      }
    }
  }
}

resource "aws_ecs_task_definition" "task" {
  for_each                 = local.task_definitions
  family                   = each.value.family
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = each.value.memory
  execution_role_arn       = aws_iam_role.execution[each.value.role].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([merge(local.container_defaults, each.value.container, {
    name             = each.key
    logConfiguration = local.logging[each.key]
  })])
}

# ---------------------------------------------------------------------------
# Services. Tasks get a public IP for outbound HTTPS only; security groups admit no
# inbound traffic except ALB -> UI and UI or the smoke task -> API.

resource "aws_ecs_service" "api" {
  #checkov:skip=CKV_AWS_333:Public IP for egress instead of a NAT gateway (decision b); no inbound rule allows it.
  name                               = "clinic-api"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.task["api"].arn
  desired_count                      = 1
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  enable_execute_command             = false
  propagate_tags                     = "SERVICE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true
  }

  service_registries {
    registry_arn = aws_service_discovery_service.api.arn
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [task_definition]
  }
}

resource "aws_ecs_service" "ui" {
  #checkov:skip=CKV_AWS_333:Public IP for egress instead of a NAT gateway (decision b); only the ALB may connect.
  name                               = "clinic-ui"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.task["ui"].arn
  desired_count                      = 1 # Streamlit sessions live in process memory
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 30
  enable_execute_command             = false
  propagate_tags                     = "SERVICE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.ui.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ui.arn
    container_name   = "ui"
    container_port   = 8501
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [task_definition]
  }

  depends_on = [aws_lb_listener.http]
}
