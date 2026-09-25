variable "environment" {
  description = "Deployment environment (staging, production)"
  type        = string
  default     = "staging"
}

variable "aws_region" {
  description = "Target AWS Region"
  type        = string
  default     = "ap-south-1" # Mumbai / India Region for NER Landslide Platform
}

variable "project_name" {
  description = "Project name prefix for resources"
  type        = string
  default     = "geosentinel"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.10.0.0/16"
}

variable "eks_cluster_version" {
  description = "Kubernetes control plane version"
  type        = string
  default     = "1.29"
}

variable "node_instance_types" {
  description = "EC2 instance types for EKS node group"
  type        = list(string)
  default     = ["t3.xlarge", "m5.xlarge"]
}

variable "db_instance_class" {
  description = "RDS DB instance class"
  type        = string
  default     = "db.r6g.xlarge"
}

variable "db_allocated_storage" {
  description = "Allocated storage in GB for PostgreSQL PostGIS"
  type        = number
  default     = 100
}

variable "domain_name" {
  description = "Base domain name for GeoSentinel ingress"
  type        = string
  default     = "geosentinel.in"
}
