output "url" {
  description = "Public demo UI (HTTPS through CloudFront)."
  value       = "https://${aws_cloudfront_distribution.ui.domain_name}"
}

output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "cluster" {
  value = aws_ecs_cluster.main.name
}

output "deploy_parameter" {
  value = aws_ssm_parameter.deploy.name
}
