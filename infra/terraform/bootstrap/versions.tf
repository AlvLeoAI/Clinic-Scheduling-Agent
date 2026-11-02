terraform {
  required_version = ">= 1.16.6, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.0"
    }
  }

  # This root creates the bucket, so its first apply uses local state through a
  # gitignored backend_override.tf, then `terraform init -migrate-state` moves it here.
  # See "AWS deployment" in SYSTEM_DESIGN.md.
  backend "s3" {
    bucket       = "clinic-scheduling-agent-tfstate-086739225026"
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true
  }
}

# No profile here: local runs set AWS_PROFILE=clinic-sandbox, CI uses OIDC.
provider "aws" {
  region              = "us-east-2"
  allowed_account_ids = ["086739225026"]

  default_tags {
    tags = {
      Project   = "clinic-scheduling-agent"
      ManagedBy = "terraform"
      Root      = "bootstrap"
    }
  }
}
