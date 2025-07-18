#!/bin/bash
set -a
source .env.production
set +a

# Render NGINX config
envsubst < nginx/default.conf.template > nginx/default.conf

# Render next.config.ts
envsubst < frontend/next.config.ts.template > frontend/next.config.ts
