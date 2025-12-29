#!/bin/bash

# Quick Start Script for DigitMile
# Helps set up the project for first-time use

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

echo "╔════════════════════════════════════════════╗"
echo "║     DigitMile Quick Start Setup            ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Check if .env exists
if [ ! -f "$PROJECT_ROOT/DigitMilePanel/.env" ]; then
    echo "⚠️  .env file not found!"
    echo ""
    read -p "Create .env file from template? [Y/n]: " create_env

    if [[ $create_env != "n" && $create_env != "N" ]]; then
        cp "$PROJECT_ROOT/DigitMilePanel/.env.example" "$PROJECT_ROOT/DigitMilePanel/.env"
        echo "✓ Created DigitMilePanel/.env"
        echo ""
        echo "⚠️  IMPORTANT: Edit DigitMilePanel/.env and add your secrets!"
        echo ""
        read -p "Press Enter to continue after editing .env..."
    else
        echo "❌ Cannot continue without .env file. Exiting."
        exit 1
    fi
else
    echo "✓ .env file found"
fi

echo ""
echo "Select setup mode:"
echo "1) Development (localhost, HTTP only)"
echo "2) Development (localhost with HTTPS, self-signed)"
echo "3) Production (domain with Let's Encrypt SSL)"
echo ""
read -p "Enter choice [1-3]: " mode

case $mode in
    1)
        echo ""
        echo "Starting in DEVELOPMENT mode (HTTP only)..."
        echo ""

        cd "$PROJECT_ROOT"
        docker-compose up -d

        echo ""
        echo "✓ Services started!"
        echo ""
        echo "Access your application:"
        echo "  - Game:        http://localhost"
        echo "  - Backend API: http://localhost:8000/panel/"
        echo "  - Admin:       http://localhost:8000/admin/"
        echo ""
        echo "View logs: docker-compose logs -f"
        ;;

    2)
        echo ""
        echo "Starting in DEVELOPMENT mode (HTTPS with self-signed cert)..."
        echo ""

        # Check for self-signed cert
        if [ ! -f "$PROJECT_ROOT/nginx-proxy/ssl/nginx-selfsigned.crt" ]; then
            echo "Generating self-signed SSL certificate..."
            cd "$PROJECT_ROOT/nginx-proxy"
            bash generate-self-signed-cert.sh
        fi

        # Set up nginx config
        ln -sf nginx.conf.localhost "$PROJECT_ROOT/nginx-proxy/nginx.conf"

        cd "$PROJECT_ROOT"
        docker-compose -f docker-compose.yml -f docker-compose.localhost.yml up -d

        echo ""
        echo "✓ Services started with HTTPS!"
        echo ""
        echo "Access your application:"
        echo "  - Game (HTTP):  http://localhost"
        echo "  - Game (HTTPS): https://localhost (⚠️  browser warning expected)"
        echo "  - Backend API:  https://localhost/panel/"
        echo "  - Admin:        https://localhost/admin/"
        echo ""
        echo "Note: Browser will show 'Not Secure' warning for self-signed cert."
        echo "Click 'Advanced' → 'Proceed to localhost' to continue."
        echo ""
        echo "View logs: docker-compose logs -f"
        ;;

    3)
        echo ""
        echo "Setting up PRODUCTION mode..."
        echo ""

        read -p "Enter your domain (e.g., digitmile.com): " domain
        read -p "Enter your email for SSL certificates: " email

        # Verify DNS
        echo ""
        echo "Checking DNS..."
        server_ip=$(dig +short "$domain" | tail -n1)

        if [ -z "$server_ip" ]; then
            echo "⚠️  Warning: Could not resolve $domain"
            echo "Make sure your DNS A record points to this server!"
            echo ""
            read -p "Continue anyway? [y/N]: " continue_dns
            if [[ $continue_dns != "y" && $continue_dns != "Y" ]]; then
                exit 1
            fi
        else
            echo "✓ $domain resolves to $server_ip"
        fi

        # Update nginx config
        sed "s/your-domain.com/$domain/g" "$PROJECT_ROOT/nginx-proxy/nginx.conf.production" > "$PROJECT_ROOT/nginx-proxy/nginx.conf.production.tmp"
        mv "$PROJECT_ROOT/nginx-proxy/nginx.conf.production.tmp" "$PROJECT_ROOT/nginx-proxy/nginx.conf.production"
        ln -sf nginx.conf.production "$PROJECT_ROOT/nginx-proxy/nginx.conf"

        echo ""
        echo "Starting services..."
        cd "$PROJECT_ROOT"
        docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

        echo ""
        echo "Requesting SSL certificate from Let's Encrypt..."
        bash "$SCRIPT_DIR/init-letsencrypt.sh" "$domain" "$email"

        echo ""
        echo "✓ Production setup complete!"
        echo ""
        echo "Your application is now available at:"
        echo "  - https://$domain"
        echo "  - https://$domain/panel/ (API)"
        echo "  - https://$domain/admin/ (Admin)"
        echo ""
        echo "SSL certificate will auto-renew every 90 days."
        echo ""
        echo "View logs: docker-compose logs -f"
        ;;

    *)
        echo "Invalid choice. Exiting."
        exit 1
        ;;
esac

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║  Setup Complete! 🚀                        ║"
echo "╚════════════════════════════════════════════╝"
