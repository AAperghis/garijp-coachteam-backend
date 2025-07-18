# nginx/Dockerfile
FROM nginx:alpine

# Install certbot for Let's Encrypt
RUN apk add --no-cache certbot certbot-nginx

COPY default.conf.template /etc/nginx/templates/
COPY ssl-setup.sh /ssl-setup.sh
RUN chmod +x /ssl-setup.sh

EXPOSE 80 443