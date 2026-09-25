variable "environment" {
  type = string
}

variable "project_name" {
  type = string
}

resource "aws_s3_bucket" "rasters" {
  bucket = "${var.project_name}-${var.environment}-rasters-dem"

  tags = {
    Name        = "DEM Rasters and Satellite Geotiff"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "rasters" {
  bucket = aws_s3_bucket.rasters.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket" "mlflow" {
  bucket = "${var.project_name}-${var.environment}-mlflow-models"

  tags = {
    Name        = "MLflow Model Registry & Artifacts"
    Environment = var.environment
  }
}

resource "aws_s3_bucket" "citizen_media" {
  bucket = "${var.project_name}-${var.environment}-citizen-media"

  tags = {
    Name        = "Citizen Landslide Report Photos"
    Environment = var.environment
  }
}

output "rasters_bucket" {
  value = aws_s3_bucket.rasters.bucket
}

output "mlflow_bucket" {
  value = aws_s3_bucket.mlflow.bucket
}

output "citizen_media_bucket" {
  value = aws_s3_bucket.citizen_media.bucket
}
