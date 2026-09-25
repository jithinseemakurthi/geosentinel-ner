output "vpc_id" {
  description = "VPC ID"
  value       = module.vpc.vpc_id
}

output "eks_cluster_name" {
  description = "EKS Cluster Name"
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS Cluster Endpoint"
  value       = module.eks.cluster_endpoint
}

output "postgres_db_address" {
  description = "PostgreSQL PostGIS Endpoint"
  value       = module.database.db_address
}

output "s3_rasters_bucket" {
  description = "S3 Bucket for Rasters"
  value       = module.storage.rasters_bucket
}

output "s3_mlflow_bucket" {
  description = "S3 Bucket for MLflow"
  value       = module.storage.mlflow_bucket
}
