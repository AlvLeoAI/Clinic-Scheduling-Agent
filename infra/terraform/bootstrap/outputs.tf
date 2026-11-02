output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "deploy_role_arn" {
  description = "Set as the AWS_DEPLOY_ROLE_ARN variable of the aws-sandbox environment."
  value       = aws_iam_role.deploy.arn
}

output "image_repositories" {
  value = { for name, repo in aws_ecr_repository.image : name => repo.repository_url }
}
