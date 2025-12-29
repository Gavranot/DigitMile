#!/bin/bash

# Helper script to set up nginx configuration based on environment

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"
NGINX_DIR="$PROJECT_ROOT/nginx-proxy"

echo "DigitMile NGINX Configuration Setup"
echo "===================================="
echo ""

# Ask user for environment
echo "Select configuration:"
echo "1) Localhost (self-signed SSL)"
echo "2) Production (Let's Encrypt SSL with domain)"
echo ""
read -p "Enter choice [1-2]: " choice

case $choice in
    1)
        echo "Setting up for LOCALHOST with self-signed SSL..."

        # Check if self-signed cert exists
        if [ ! -f "$NGINX_DIR/ssl/nginx-selfsigned.crt" ]; then
            echo "Generating self-signed SSL certificate..."
            cd "$NGINX_DIR"
            bash generate-self-signed-cert.sh
        else
            echo "Self-signed certificate already exists."
        fi

        # Create symlink to localhost config
        ln -sf nginx.conf.localhost "$NGINX_DIR/nginx.conf"

        echo ""
        echo "✓ Configuration set for localhost"
        echo ""
        echo "To start:"
        echo "  docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d"
        echo ""
        echo "Access your app at:"
        echo "  - HTTP:  http://localhost"
        echo "  - HTTPS: https://localhost (browser will show warning - this is normal)"
        ;;

    2)
        echo "Setting up for PRODUCTION with Let's Encrypt..."

        read -p "Enter your domain (e.g., digitmile.com): " domain
        read -p "Enter your email for SSL certificate: " email

        # Update production config with domain
        sed "s/your-domain.com/$domain/g" "$NGINX_DIR/nginx.conf.production" > "$NGINX_DIR/nginx.conf.production.tmp"
        mv "$NGINX_DIR/nginx.conf.production.tmp" "$NGINX_DIR/nginx.conf.production"

        # Create symlink to production config
        ln -sf nginx.conf.production "$NGINX_DIR/nginx.conf"

        echo ""
        echo "✓ Configuration set for production"
        echo ""
        echo "Next steps:"
        echo "1. Ensure DNS points to your server:"
        echo "   $domain → your-server-ip"
        echo ""
        echo "2. Initialize Let's Encrypt:"
        echo "   cd $PROJECT_ROOT"
        echo "   ./scripts/init-letsencrypt.sh $domain $email"
        echo ""
        echo "3. Start containers:"
        echo "   docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
        ;;

    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac
