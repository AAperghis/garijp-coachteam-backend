# Web App Template - Deployment Guide

This repository contains a full-stack web application template with a Next.js frontend, FastAPI backend, and Nginx reverse proxy, all containerized with Docker.

## Architecture Overview

```
Internet → DDNS Domain → Nginx (Port 80) → Frontend (Port 3000) / Backend (Port 8000)
```

- **Frontend**: Next.js application with TypeScript
- **Backend**: FastAPI Python application
- **Reverse Proxy**: Nginx for routing and load balancing
- **Containerization**: Docker Compose for orchestration

## Prerequisites

Before deploying, ensure you have:

1. **Docker and Docker Compose** installed on your server
2. **DDNS service** configured and pointing to your server's public IP
3. **Port 80** open on your server/router for HTTP traffic
4. **Domain name** or DDNS hostname ready

## Configuration

### 1. Environment Configuration

The application uses environment-specific configuration files:

- `.env.production` - Production environment variables
- `.env.dev` - Development environment variables

**Key Variables in `.env.production`:**
```bash
APP_NAME=example_app          # Your application name (used in URLs)
DOMAIN=groenendaal.ddns.net   # Your DDNS domain
BACKEND_PORT=8000             # Backend internal port
FRONTEND_PORT=3000            # Frontend internal port
NGINX_PORT=80                 # Nginx external port
GITHUB_SECRET=your_secret     # GitHub webhook secret (if using)
APP_PATH=/path/to/your/app    # Application deployment path
```

### 2. Customize for Your Application

Before deploying, update the following:

1. **Edit `.env.production`:**
   ```bash
   APP_NAME=your_app_name
   DOMAIN=your-domain.ddns.net
   GITHUB_SECRET=your_actual_github_secret
   APP_PATH=/your/deployment/path
   ```

2. **Verify nginx configuration** in `nginx/default.conf.template`
3. **Update frontend configuration** in `frontend/next.config.ts.template`

## Deployment Process

### Automated Deployment

The simplest way to deploy is using the provided build script:

```bash
# Make scripts executable
chmod +x scripts/build.sh scripts/generate.sh

# Deploy the application
./scripts/build.sh
```

### Manual Deployment Steps

If you prefer to run steps manually:

1. **Generate configuration files:**
   ```bash
   ./scripts/generate.sh
   ```
   This will:
   - Generate `nginx/default.conf` from the template
   - Generate `frontend/next.config.ts` from the template

2. **Build and start services:**
   ```bash
   docker compose up --build -d
   ```

### What Happens During Deployment

1. **Configuration Generation:**
   - Environment variables are substituted into template files
   - Nginx configuration is created with your domain and app name
   - Next.js configuration is created with the correct base path

2. **Docker Build Process:**
   - Backend Docker image is built from `backend/Dockerfile`
   - Frontend Docker image is built from `frontend/Dockerfile`
   - Nginx uses the official Alpine image with custom configuration

3. **Service Orchestration:**
   - All services start with proper networking
   - Nginx acts as reverse proxy for frontend and backend
   - Services restart automatically unless stopped

## Access Your Application

After successful deployment, your application will be accessible at:

- **Main Application**: `http://your-domain.ddns.net/your_app_name/`
- **API Endpoints**: `http://your-domain.ddns.net/your_app_name/api/`

Example with default configuration:
- **Frontend**: `http://groenendaal.ddns.net/example_app/`
- **Backend API**: `http://groenendaal.ddns.net/example_app/api/`

## Nginx Routing Configuration

The Nginx reverse proxy routes requests as follows:

```nginx
# Frontend requests
/your_app_name/ → http://frontend:3000/

# Backend API requests  
/your_app_name/api/ → http://backend:8000/
```

## Managing Your Deployment

### Check Service Status
```bash
docker compose ps
```

### View Logs
```bash
# All services
docker compose logs

# Specific service
docker compose logs frontend
docker compose logs backend
docker compose logs nginx
```

### Stop Services
```bash
docker compose down
```

### Restart Services
```bash
docker compose restart
```

### Update Application
```bash
# Pull latest changes
git pull

# Rebuild and restart
./scripts/build.sh
```

## Troubleshooting

### Common Issues

1. **Port 80 already in use:**
   ```bash
   # Check what's using port 80
   sudo netstat -tlnp | grep :80
   
   # Stop conflicting service (e.g., Apache)
   sudo systemctl stop apache2
   ```

2. **Domain not resolving:**
   - Verify DDNS service is active
   - Check if domain points to correct IP: `nslookup your-domain.ddns.net`
   - Ensure port 80 is forwarded in router settings

3. **Services not starting:**
   ```bash
   # Check detailed logs
   docker compose logs -f
   
   # Verify configuration files were generated
   ls nginx/default.conf
   ls frontend/next.config.ts
   ```

4. **Cannot access from external network:**
   - Verify firewall allows port 80
   - Check router port forwarding configuration
   - Ensure DDNS domain resolves to correct public IP

### Debug Commands

```bash
# Test nginx configuration
docker compose exec nginx nginx -t

# Check container networking
docker network ls
docker network inspect web_app_template_default

# Verify environment variables
docker compose config
```

## GitHub Webhook Integration

This template includes automatic deployment via GitHub webhooks. When you push to the main branch, GitHub can automatically trigger a redeploy of your application.

### Setting Up GitHub Webhook

1. **Configure webhook secret in `.env.production`:**
   ```bash
   GITHUB_SECRET=your_secure_random_string_here
   ```
   Generate a secure secret:
   ```bash
   openssl rand -hex 20
   ```

2. **In your GitHub repository, go to Settings → Webhooks → Add webhook:**
   - **Payload URL**: `http://your-domain.ddns.net/your_app_name/api/webhook/`
   - **Content type**: `application/json`
   - **Secret**: Enter the same secret from your `.env.production`
   - **Events**: Select "Just the push event"
   - **Active**: ✓ Checked

3. **Test the webhook:**
   - Push a commit to the main branch
   - Check the webhook delivery in GitHub (Settings → Webhooks → Recent Deliveries)
   - Monitor application logs: `docker compose logs backend`

### Webhook Security

- The webhook verifies GitHub signatures using HMAC-SHA256
- Only processes pushes to the `main` branch
- Requires valid GitHub secret for authentication

- A new secret can be generated with:

```bash
openssl rand -hex 20
```

### Manual Webhook Testing

You can test the webhook endpoint manually:
```bash
curl -X POST http://your-domain.ddns.net/your_app_name/api/webhook/ \
  -H "Content-Type: application/json" \
  -H "X-Hub-Signature-256: sha256=your_signature" \
  -d '{"ref":"refs/heads/main"}'
```

## Security Considerations

1. **HTTPS Setup**: Consider setting up SSL/TLS certificates with Let's Encrypt
2. **Firewall**: Only expose necessary ports (80, 443)
3. **Updates**: Regularly update Docker images and dependencies
4. **Secrets**: Use secure methods for managing secrets in production

## Development vs Production

- **Development**: Use `.env.dev` and run services locally
- **Production**: Use `.env.production` and deploy with Docker Compose

Switch between environments by modifying which env file `generate.sh` sources.

## File Structure

```
web_app_template/
├── backend/                 # FastAPI backend
│   ├── Dockerfile
│   ├── main.py
│   └── src/
├── frontend/               # Next.js frontend
│   ├── Dockerfile
│   ├── next.config.ts.template
│   └── src/
├── nginx/                  # Nginx reverse proxy
│   ├── Dockerfile
│   ├── default.conf.template
│   └── default.conf        # Generated
├── scripts/
│   ├── build.sh           # Main deployment script
│   └── generate.sh        # Configuration generator
├── docker-compose.yml     # Service orchestration
├── .env.production       # Production config
└── .env.dev             # Development config
```

This template provides a solid foundation for deploying full-stack web applications with proper reverse proxy setup and containerization.
