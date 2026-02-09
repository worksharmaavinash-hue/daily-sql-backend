#!/bin/bash
# Simple Deployment Script for DailySQL Backend
# Run this on the VPS after setting up authentication (SSH keys or password)

echo "🚀 Deploying DailySQL Backend..."

# 1. Pull latest changes
echo "📥 Pulling latest code..."
git pull origin main

# 2. Rebuild & Restart Containers from Production Compose File
echo "🐳 Rebuilding containers..."
docker compose -f docker-compose.prod.yml up -d --build

# 3. Cleanup unused images
echo "🧹 Cleaning up old images..."
docker image prune -f

echo "✅ Deployment Complete!"
