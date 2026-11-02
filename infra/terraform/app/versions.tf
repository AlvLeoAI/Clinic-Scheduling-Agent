terraform {
  required_version = ">= 1.16.6, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "= 3.9.1"
    }
  }

  backend "s3" {
    bucket       = "clinic-scheduling-agent-tfstate-086739225026"
    key          = "app/terraform.tfstate"
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
      Root      = "app"
    }
  }
}
