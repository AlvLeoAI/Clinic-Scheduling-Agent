# Each security group starts with no rules (Terraform removes AWS's default allow-all
# egress); every allowed flow is listed below. DNS to the VPC resolver is not subject
# to security groups.

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Internal ALB: HTTP from CloudFront VPC-origin interfaces, to the UI only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "ui" {
  name        = "${local.name}-ui"
  description = "UI tasks: from the ALB; to the API and HTTPS"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "API tasks: from the UI; to the database and HTTPS"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "jobs" {
  #checkov:skip=CKV2_AWS_5:Attached at run time by the purge schedule and the deploy workflow's run-task.
  name        = "${local.name}-jobs"
  description = "Migration and purge tasks: no inbound; to the database and HTTPS"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "RDS: PostgreSQL from the API and jobs; no egress"
  vpc_id      = aws_vpc.main.id
}

# CloudFront places its VPC-origin network interfaces in the ALB's (private) subnets.
# Nothing else that could send HTTP lives there: RDS has no egress.
resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  for_each          = toset(local.private_cidrs)
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from CloudFront VPC-origin interfaces"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = each.value
}

resource "aws_vpc_security_group_egress_rule" "alb_to_ui" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Forward and health-check UI tasks"
  ip_protocol                  = "tcp"
  from_port                    = 8501
  to_port                      = 8501
  referenced_security_group_id = aws_security_group.ui.id
}

resource "aws_vpc_security_group_ingress_rule" "ui_from_alb" {
  security_group_id            = aws_security_group.ui.id
  description                  = "Streamlit from the ALB"
  ip_protocol                  = "tcp"
  from_port                    = 8501
  to_port                      = 8501
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "ui_to_api" {
  security_group_id            = aws_security_group.ui.id
  description                  = "API over Cloud Map DNS"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.api.id
}

resource "aws_vpc_security_group_ingress_rule" "api_from_ui" {
  security_group_id            = aws_security_group.api.id
  description                  = "API from UI tasks only"
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
  referenced_security_group_id = aws_security_group.ui.id
}

# HTTPS out: ECR, Secrets Manager and CloudWatch Logs public endpoints (no NAT or
# interface endpoints in this design).
resource "aws_vpc_security_group_egress_rule" "https" {
  for_each = {
    ui   = aws_security_group.ui.id
    api  = aws_security_group.api.id
    jobs = aws_security_group.jobs.id
  }
  security_group_id = each.value
  description       = "HTTPS to AWS public endpoints"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "to_db" {
  for_each = {
    api  = aws_security_group.api.id
    jobs = aws_security_group.jobs.id
  }
  security_group_id            = each.value
  description                  = "PostgreSQL"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.db.id
}

resource "aws_vpc_security_group_ingress_rule" "db_from" {
  for_each = {
    api  = aws_security_group.api.id
    jobs = aws_security_group.jobs.id
  }
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from ${each.key}"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = each.value
}
