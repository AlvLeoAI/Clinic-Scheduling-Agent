data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = "us-east-2"
  name       = "clinic-scheduling-agent"
  vpc_cidr   = "10.40.0.0/16"
  zones      = ["us-east-2a", "us-east-2b"]

  # Tasks: public subnets with a public IP and no inbound path (security groups).
  # Database, internal ALB and CloudFront's VPC-origin interfaces: private subnets
  # with no route out of the VPC.
  public_cidrs  = ["10.40.0.0/24", "10.40.1.0/24"]
  private_cidrs = ["10.40.10.0/24", "10.40.11.0/24"]
}

resource "aws_vpc" "main" {
  #checkov:skip=CKV2_AWS_11:Flow logs cost per GB ingested; the demo runs only while it is being shown.
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

# Removes the default security group's rules so nothing can use it by accident.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-default-unused" }
}

# Also required by CloudFront VPC origins, even though the ALB stays private.
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count                   = length(local.zones)
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.zones[count.index]
  cidr_block              = local.public_cidrs[count.index]
  map_public_ip_on_launch = false
  tags                    = { Name = "${local.name}-public-${local.zones[count.index]}" }
}

resource "aws_subnet" "private" {
  count             = length(local.zones)
  vpc_id            = aws_vpc.main.id
  availability_zone = local.zones[count.index]
  cidr_block        = local.private_cidrs[count.index]
  tags              = { Name = "${local.name}-private-${local.zones[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-public" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count          = length(local.zones)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Local route only.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = length(local.zones)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}
