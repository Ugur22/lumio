output "elastic_ip" {
  value = aws_eip.lumio.public_ip
}

output "hostname" {
  value = "${replace(aws_eip.lumio.public_ip, ".", "-")}.sslip.io"
}
