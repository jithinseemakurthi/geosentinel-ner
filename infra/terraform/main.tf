module "vpc" {
  source       = "./modules/vpc"
  environment  = var.environment
  project_name = var.project_name
  vpc_cidr     = var.vpc_cidr
}

module "eks" {
  source          = "./modules/eks"
  environment     = var.environment
  project_name    = var.project_name
  cluster_version = var.eks_cluster_version
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnet_ids
  instance_types  = var.node_instance_types
}

module "database" {
  source            = "./modules/database"
  environment       = var.environment
  project_name      = var.project_name
  vpc_id            = module.vpc.vpc_id
  subnet_ids        = module.vpc.database_subnet_ids
  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
}

module "storage" {
  source       = "./modules/storage"
  environment  = var.environment
  project_name = var.project_name
}

module "kafka" {
  source       = "./modules/kafka"
  environment  = var.environment
  project_name = var.project_name
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnet_ids
}
