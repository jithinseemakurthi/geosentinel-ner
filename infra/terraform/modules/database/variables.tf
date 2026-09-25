variable "environment" {
  type = string
}

variable "project_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "instance_class" {
  type    = string
  default = "db.r6g.xlarge"
}

variable "allocated_storage" {
  type    = number
  default = 100
}

variable "eks_security_group_id" {
  type    = string
  default = ""
}
