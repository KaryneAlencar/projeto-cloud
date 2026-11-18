output "state_bucket" {
  description = "Bucket S3 do state remoto."
  value       = aws_s3_bucket.state.bucket
}

output "backend_config" {
  description = "Conteúdo de ../backend.hcl. O lock usa o próprio S3 (use_lockfile), sem DynamoDB."
  value       = <<-EOT
    bucket       = "${aws_s3_bucket.state.bucket}"
    key          = "${var.project}/${var.environment}/terraform.tfstate"
    region       = "${var.region}"
    encrypt      = true
    use_lockfile = true
  EOT
}
