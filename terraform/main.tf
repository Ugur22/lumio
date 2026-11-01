# Adopt the existing resources into state (do not apply before `terraform plan` shows no changes):
#   terraform import aws_key_pair.lumio lumio-keypair
#   terraform import aws_security_group.lumio sg-0a176b7962d3e3206
#   terraform import aws_instance.lumio i-000cc65622436296c
#   terraform import aws_eip.lumio eipalloc-07607fd866757c60c
#   terraform import aws_eip_association.lumio eipassoc-0a8da8706dca84fc0

resource "aws_key_pair" "lumio" {
  key_name = var.key_name
  # AWS never returns the public key, so Terraform cannot compare it; the placeholder is never sent
  # because prevent_destroy stops a replacement.
  public_key = "placeholder-ignored-after-import"

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [public_key]
  }
}

# Name and description must match the console-created group exactly: changing either forces a replacement.
resource "aws_security_group" "lumio" {
  name        = "launch-wizard-1"
  description = "launch-wizard-1 created 2026-10-30T15:23:47.681Z"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.ssh_cidr]
  }

  # Terraform deletes AWS's default allow-all egress unless it is declared.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_instance" "lumio" {
  ami                    = var.ami
  instance_type          = var.instance_type
  subnet_id              = var.subnet_id
  key_name               = aws_key_pair.lumio.key_name
  vpc_security_group_ids = [aws_security_group.lumio.id]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20
    iops                  = 3000
    throughput            = 125
    encrypted             = false
    delete_on_termination = true
  }

  tags = {
    Name = "Lumio"
  }

  # A new AMI or user_data would replace the instance and wipe /var/lib/lumio; the box is patched in place.
  lifecycle {
    prevent_destroy = true
    ignore_changes  = [ami, user_data]
  }
}

# The sslip.io hostname is hardcoded in deploy/lumio.service, deploy/Caddyfile and the Makefile, so the IP must survive.
resource "aws_eip" "lumio" {
  domain = "vpc"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_eip_association" "lumio" {
  instance_id   = aws_instance.lumio.id
  allocation_id = aws_eip.lumio.id
}
