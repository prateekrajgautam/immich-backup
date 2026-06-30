#!/bin/sh
# updateapp.sh — build, tag, and push the image to Docker Hub
# Usage: ./updateapp.sh
#
# To also start and tail logs locally after pushing, uncomment
# the block at the bottom of this file.

set -e

version=$(head version -n1)

IMAGE="prateekrajgautam/immich-backup:latest"
IMAGE_VER="prateekrajgautam/immich-backup:$version"

echo "⏹  Stopping running container (if any)..."
docker-compose down || true

echo "⬇️  Pulling base image updates..."
docker-compose pull || true

echo "🔨 Building image: $IMAGE"
# docker-compose -f docker-compose-build.yml build --no-cache ## optional
docker-compose -f docker-compose-build.yml build

echo "⬆️  Pushing to Docker Hub: $IMAGE"
docker push "$IMAGE"

# get image id tag it with verison and push
IMAGE_ID=$(docker images --format '{{.ID}}' $IMAGE)
echo IMAGE_ID

#docker tag IMAGE_ID IMAGE_VER
docker tag $IMAGE $IMAGE_VER
docker push $IMAGE_VER




echo "✅ Done — $IMAGE is live on Docker Hub."

# -----------------------------------------------------------
# Uncomment below to start and test locally after pushing
# -----------------------------------------------------------
echo "🚀 Starting locally..."
docker-compose up -d
echo "📋 Logs (Ctrl+C to detach)..."
docker-compose logs -f
