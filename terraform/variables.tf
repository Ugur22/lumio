variable "region" {
  type    = string
  default = "eu-north-1"
}

variable "ssh_cidr" {
  type        = string
  description = "Your public IP as x.x.x.x/32; the only address allowed on port 22."
}

variable "key_name" {
  type    = string
  default = "lumio-keypair"
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "ami" {
  type        = string
  description = "Only read on create; the instance ignores later AMI changes."
  default     = "ami-0fd9576cca965bd19"
}

variable "subnet_id" {
  type    = string
  default = "subnet-005deda3c35034d67"
}

variable "vpc_id" {
  type    = string
  default = "vpc-06c472eb96c6cc59e"
}
