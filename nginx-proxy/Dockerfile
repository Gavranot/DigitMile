FROM nginx:alpine

# Copy nginx configuration
COPY nginx.conf.production /etc/nginx/conf.d/default.conf

# Create directory for Let's Encrypt challenges
RUN mkdir -p /var/www/certbot

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
