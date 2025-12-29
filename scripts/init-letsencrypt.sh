#!/bin/bash

# Initialize Let's Encrypt SSL certificates
# Usage: ./init-letsencrypt.sh your-domain.com your-email@example.com

if [ $# -lt 2 ]; then
    echo "Usage: $0 <domain> <email>"
    echo "Example: $0 digitmile.com admin@digitmile.com"
    exit 1
fi

DOMAIN=$1
EMAIL=$2

# Create required directories
mkdir -p certbot/conf
mkdir -p certbot/www

# Download recommended TLS parameters
if [ ! -e "certbot/conf/options-ssl-nginx.conf" ] || [ ! -e "certbot/conf/ssl-dhparams.pem" ]; then
  echo "### Downloading recommended TLS parameters ..."
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf > certbot/conf/options-ssl-nginx.conf
  curl -s https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem > certbot/conf/ssl-dhparams.pem
  echo
fi

# Update nginx configuration with actual domain
echo "### Updating nginx configuration with domain: $DOMAIN"
sed "s/your-domain.com/$DOMAIN/g" nginx-proxy/nginx.conf.production > nginx-proxy/nginx.conf.production.tmp
mv nginx-proxy/nginx.conf.production.tmp nginx-proxy/nginx.conf.production

echo "### Starting nginx in HTTP-only mode for ACME challenge ..."
docker-compose up -d nginx-proxy

echo "### Requesting Let's Encrypt certificate for $DOMAIN ..."
docker-compose run --rm certbot certonly --webroot \
    --webroot-path=/var/www/certbot \
    --email $EMAIL \
    --agree-tos \
    --no-eff-email \
    --force-renewal \
    -d $DOMAIN -d www.$DOMAIN

if [ $? -eq 0 ]; then
    echo "### Success! Certificate obtained."
    echo "### Reloading nginx with SSL configuration ..."
    docker-compose restart nginx-proxy
else
    echo "### Failed to obtain certificate. Check your domain DNS settings."
    exit 1
fi

echo "### Done! Your site should now be available at https://$DOMAIN"
