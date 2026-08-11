#!/bin/bash
# Staging Deployment Script for daily-sql-backend-test
# Run this inside ~/daily-sql-backend-test/ on the VPS

echo "🚀 Deploying DailySQL Test Environment..."

# 1. Pull latest python-dsa changes
echo "📥 Pulling latest code from sql-dialect branch..."
git pull origin sql-dialect

# 2. Rebuild & Restart Containers from Staging Compose File
echo "🐳 Rebuilding staging containers..."
docker compose -f docker-compose.staging.yml up -d --build

# 3. Cleanup unused images
echo "🧹 Cleaning up old images..."
docker image prune -f

echo "✅ Test Environment Deployment Complete!"
