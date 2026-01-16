# Docker Deployment Setup

This repository is configured to automatically build and publish Docker images on every push to main/master.

## Setup

### 1. GitHub Container Registry (Recommended)

The included GitHub Actions workflow automatically builds and pushes images to GitHub Container Registry (ghcr.io).

**No additional setup needed** - it works automatically with GitHub's built-in `GITHUB_TOKEN`.

### 2. Environment Variables

Create a `.env` file for your deployment configuration:

```bash
# Use your GitHub username/org instead of "yourusername"
DOCKER_REGISTRY=ghcr.io
DOCKER_IMAGE=yourusername/podaccounting
IMAGE_TAG=latest
```

Update `docker-compose.yml` to use these values, or just replace `yourusername` with your actual GitHub username.

## Deployment

### First Time Setup

1. Push your code to GitHub
2. The workflow will automatically build and push the image
3. On your server, log in to GitHub Container Registry:
   ```bash
   echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
   ```

### Deploy Latest Image

Simply run:
```bash
./deploy.sh
```

Or manually:
```bash
docker compose pull
docker compose up -d
```

### Development

For local development with live code reloading:
```bash
docker compose -f docker-compose.dev.yml up
```

## Alternative: Docker Hub

If you prefer Docker Hub, update `docker-compose.yml`:
```yaml
image: yourdockerhubusername/podaccounting:latest
```

And update `.github/workflows/docker-publish.yml` to use Docker Hub credentials.
