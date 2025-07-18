#!/bin/sh

# Initial nginx start
nginx

# Get SSL certificate
certbot --nginx --non-interactive --agree-tos --email your-email@domain.com -d ${DOMAIN}

# Reload nginx with SSL
nginx -s reload

# Keep container running
tail -f /var/log/nginx/access.log