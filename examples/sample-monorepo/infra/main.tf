provider "aws" {
  region = "eu-north-1"
}

resource "aws_s3_bucket" "invoices" {
  bucket = "acme-invoices"
  acl    = "public-read"
}

resource "aws_security_group" "api" {
  name = "api"
  ingress {
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_db_instance" "orders" {
  engine            = "postgres"
  instance_class    = "db.t3.micro"
  storage_encrypted = false
}
