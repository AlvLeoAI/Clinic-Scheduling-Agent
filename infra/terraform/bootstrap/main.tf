data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = "us-east-2"
  repository = "AlvLeoAI/Clinic-Scheduling-Agent"

  # Names shared with infra/terraform/app; the deploy role is scoped to them.
  cluster         = "clinic-scheduling-agent"
  services        = ["clinic-api", "clinic-ui"]
  migrate_family  = "clinic-migrate"
  ecs_role_path   = "/clinic-scheduling-agent/ecs/"
  deploy_param    = "/clinic-scheduling-agent/deploy"
  migrate_logs    = "/clinic-scheduling-agent/migrate"
  image_repos     = ["clinic-scheduling-api", "clinic-scheduling-ui"]
  ecs_arn_prefix  = "arn:aws:ecs:${local.region}:${local.account_id}"
  logs_arn_prefix = "arn:aws:logs:${local.region}:${local.account_id}"
}

# ---------------------------------------------------------------------------
# Terraform state bucket (S3-native locking, no DynamoDB table).

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_144:Single-region sandbox; versioning protects state, replication is not worth its cost.
  #checkov:skip=CKV_AWS_145:SSE-S3 is enough for state that holds no secrets (passwords are write-only or RDS-managed).
  #checkov:skip=CKV_AWS_18:No server access logging, to avoid a second bucket in a single-operator sandbox; the deploy role has no state access, so only the SSO admin role reads it (by IAM grants, not the bucket policy). CloudTrail management events cover configuration changes, not object reads: enable S3 data events or server access logs before any shared or long-running use.
  #checkov:skip=CKV2_AWS_62:No consumer for event notifications.
  bucket = "clinic-scheduling-agent-tfstate-${local.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

data "aws_iam_policy_document" "state_tls_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket = aws_s3_bucket.state.id
  policy = data.aws_iam_policy_document.state_tls_only.json
}

# ---------------------------------------------------------------------------
# Image repositories. Kept here so images survive an app destroy and CI can push
# before the app stack exists.

resource "aws_ecr_repository" "image" {
  #checkov:skip=CKV_AWS_136:AES256 at rest is enough for public-source demo images; a CMK costs $1/month.
  for_each             = toset(local.image_repos)
  name                 = each.value
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "image" {
  for_each   = aws_ecr_repository.image
  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after a day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep the last 10 tagged images"
        selection = {
          tagStatus      = "tagged"
          tagPatternList = ["*"]
          countType      = "imageCountMoreThan"
          countNumber    = 10
        }
        action = { type = "expire" }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC and the deploy role.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only jobs that run in the aws-sandbox environment. Its deployment-branch rule
    # (main only) and required reviewer are set in the repository settings.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${local.repository}:environment:aws-sandbox"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "clinic-scheduling-agent-deploy"
  description          = "GitHub Actions deploy workflow: push images, run migrations, update services."
  assume_role_policy   = data.aws_iam_policy_document.deploy_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "deploy" {
  statement {
    sid       = "EcrLogin"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = [for repo in aws_ecr_repository.image : repo.arn]
  }

  # Neither action supports resource-level permissions.
  statement {
    sid       = "TaskDefinitions"
    actions   = ["ecs:DescribeTaskDefinition", "ecs:RegisterTaskDefinition"]
    resources = ["*"]
  }

  statement {
    sid     = "TagOnCreate"
    actions = ["ecs:TagResource"]
    resources = [
      "${local.ecs_arn_prefix}:task-definition/*",
      "${local.ecs_arn_prefix}:task/${local.cluster}/*",
    ]
    condition {
      test     = "StringEquals"
      variable = "ecs:CreateAction"
      values   = ["RegisterTaskDefinition", "RunTask"]
    }
  }

  statement {
    sid       = "Services"
    actions   = ["ecs:DescribeServices", "ecs:UpdateService"]
    resources = [for name in local.services : "${local.ecs_arn_prefix}:service/${local.cluster}/${name}"]
  }

  statement {
    sid       = "RunMigrations"
    actions   = ["ecs:RunTask"]
    resources = ["${local.ecs_arn_prefix}:task-definition/${local.migrate_family}:*"]
    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = ["${local.ecs_arn_prefix}:cluster/${local.cluster}"]
    }
  }

  statement {
    sid       = "WatchMigrations"
    actions   = ["ecs:DescribeTasks"]
    resources = ["${local.ecs_arn_prefix}:task/${local.cluster}/*"]
  }

  statement {
    sid       = "MigrationLogs"
    actions   = ["logs:GetLogEvents"]
    resources = ["${local.logs_arn_prefix}:log-group:${local.migrate_logs}:log-stream:*"]
  }

  statement {
    sid       = "DeployParameters"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${local.region}:${local.account_id}:parameter${local.deploy_param}"]
  }

  statement {
    sid       = "PassTaskRoles"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${local.account_id}:role${local.ecs_role_path}*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "deploy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
