#!/bin/bash
# Generate self-signed SSL certificate for localhost testing

mkdir -p ssl

openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout ssl/nginx-selfsigned.key \
  -out ssl/nginx-selfsigned.crt \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

echo "Self-signed certificate generated in ssl/ directory"
echo "Files created:"
echo "  - ssl/nginx-selfsigned.crt"
echo "  - ssl/nginx-selfsigned.key"
