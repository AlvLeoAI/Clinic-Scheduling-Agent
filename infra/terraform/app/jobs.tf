# Daily chat retention purge and the parameters the deploy workflow reads.

data "aws_iam_policy_document" "scheduler_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-purge-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_trust.json
}

locals {
  purge_family_arn = "arn:aws:ecs:${local.region}:${local.account_id}:task-definition/clinic-purge"
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "RunPurge"
    actions   = ["ecs:RunTask"]
    resources = [local.purge_family_arn, "${local.purge_family_arn}:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.main.arn]
    }
  }

  statement {
    sid       = "TagOnRun"
    actions   = ["ecs:TagResource"]
    resources = ["arn:aws:ecs:${local.region}:${local.account_id}:task/${local.name}/*"]
    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RunTask"]
    }
  }

  statement {
    sid       = "PassExecutionRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution["runtime"].arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "run-purge"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "purge" {
  #checkov:skip=CKV_AWS_297:The schedule holds no sensitive input; the AWS-owned key is enough.
  name                         = "clinic-purge-chat"
  description                  = "python -m scripts.purge_chat --apply"
  schedule_expression          = var.purge_schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.scheduler.arn

    # Family without a revision: runs the latest revision, which the deploy workflow
    # registers with the current image.
    ecs_parameters {
      task_definition_arn = local.purge_family_arn
      launch_type         = "FARGATE"
      platform_version    = "LATEST"
      propagate_tags      = "TASK_DEFINITION"

      network_configuration {
        subnets          = aws_subnet.public[*].id
        security_groups  = [aws_security_group.jobs.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 0
    }
  }

  depends_on = [aws_ecs_task_definition.task]
}

# Read by .github/workflows/deploy.yml (ssm:GetParameter on this name only).
resource "aws_ssm_parameter" "deploy" {
  #checkov:skip=CKV2_AWS_34:Holds resource names and IDs only, no secrets.
  name = "/clinic-scheduling-agent/deploy"
  type = "String"
  value = jsonencode({
    cluster        = aws_ecs_cluster.main.name
    services       = { api = aws_ecs_service.api.name, ui = aws_ecs_service.ui.name }
    families       = { for key, task in aws_ecs_task_definition.task : key => task.family }
    subnets        = aws_subnet.public[*].id
    migrate_sg     = aws_security_group.jobs.id
    migrate_logs   = aws_cloudwatch_log_group.task["migrate"].name
    smoke_sg       = aws_security_group.smoke.id
    smoke_logs     = aws_cloudwatch_log_group.task["smoke"].name
    repository_api = "${local.registry}/clinic-scheduling-api"
    repository_ui  = "${local.registry}/clinic-scheduling-ui"
    url            = "https://${aws_cloudfront_distribution.ui.domain_name}"
  })
}
