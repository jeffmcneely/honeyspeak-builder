
#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Progress tracking
TOTAL_STEPS=6
CURRENT_STEP=0

print_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}[Step $CURRENT_STEP/$TOTAL_STEPS]${NC} $1"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Build and push multi-arch container using stryker-tcp Docker context
IMAGE_NAME="ghcr.io/jeffmcneely/honeyspeak-builder"
TAG="latest"
DOCKER_CONTEXT="stryker-tcp"

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}        ${GREEN}Honeyspeak Builder Deployment Script${NC}             ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

print_step "Switching Docker Context"
print_info "Context: $DOCKER_CONTEXT"
docker context use $DOCKER_CONTEXT
print_success "Docker context switched to $DOCKER_CONTEXT"

print_step "Setting up Docker Buildx Builder"
BUILDER_NAME="stryker-builder"
print_info "Builder name: $BUILDER_NAME"
print_info "Driver: docker-container"

if docker buildx create --name $BUILDER_NAME --driver docker-container $DOCKER_CONTEXT --use 2>/dev/null; then
    print_success "Created new buildx builder: $BUILDER_NAME"
else
    print_warning "Builder already exists, using existing: $BUILDER_NAME"
    docker buildx use $BUILDER_NAME
fi

print_step "Building Multi-Architecture Container Image"
print_info "Image: $IMAGE_NAME:$TAG"
print_info "Platforms: linux/amd64, linux/arm64"
print_info "Builder: $BUILDER_NAME"
echo ""

docker buildx build --platform linux/amd64,linux/arm64 \
  -t $IMAGE_NAME:$TAG \
  --push \
  -f Dockerfile \
  --progress=plain \
  .

echo ""
print_success "Image built and pushed to $IMAGE_NAME:$TAG"

print_step "Generating Helm Configuration"

# Copy .env to custom-values.yaml for Helm (convert KEY=VALUE to YAML)
if [ -f .env ]; then
  print_info "Reading configuration from .env file"
  
  cat > custom-values.yaml << 'EOF'
env:
EOF
  
  # Process env vars - only process lines that are not blank, not comments, and match KEY=VALUE
  ENV_COUNT=0
  grep -v '^#' .env | grep -v '^$' | grep -E '^[A-Za-z_][A-Za-z0-9_]*=.*' | while IFS='=' read -r key value; do
    # Remove leading/trailing whitespace from key and value
    key=$(echo "$key" | xargs)
    value=$(echo "$value" | xargs)
    # Only output if key and value are non-empty
    if [ -n "$key" ] && [ -n "$value" ]; then
      echo "  $key: \"$value\"" >> custom-values.yaml
      ENV_COUNT=$((ENV_COUNT + 1))
    fi
  done
  
  print_success "Processed environment variables from .env"
  
  # Add storage configuration if STORAGE_* vars are set in .env
  print_info "Processing storage configuration..."
  
  STORAGE_MOUNT_PATH=$(grep '^STORAGE_MOUNT_PATH=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_DIRECTORY=$(grep '^STORAGE_DIRECTORY=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_SIZE=$(grep '^STORAGE_SIZE=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_ACCESS_MODE=$(grep '^STORAGE_ACCESS_MODE=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_SERVER=$(grep '^STORAGE_SERVER=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_SHARE=$(grep '^STORAGE_SHARE=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_USERNAME=$(grep '^STORAGE_USERNAME=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  STORAGE_PASSWORD=$(grep '^STORAGE_PASSWORD=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
  
  if [ -n "$STORAGE_MOUNT_PATH" ] || [ -n "$STORAGE_DIRECTORY" ] || [ -n "$STORAGE_SIZE" ] || [ -n "$STORAGE_ACCESS_MODE" ]; then
    echo "" >> custom-values.yaml
    echo "storage:" >> custom-values.yaml
    if [ -n "$STORAGE_MOUNT_PATH" ]; then
      echo "  mountPath: \"$STORAGE_MOUNT_PATH\"" >> custom-values.yaml
      print_info "  Mount path: $STORAGE_MOUNT_PATH"
    fi
    if [ -n "$STORAGE_DIRECTORY" ]; then
      echo "  storageDirectory: \"$STORAGE_DIRECTORY\"" >> custom-values.yaml
      print_info "  Storage directory: $STORAGE_DIRECTORY"
    fi
  fi
  
  if [ -n "$STORAGE_SIZE" ] || [ -n "$STORAGE_ACCESS_MODE" ] || [ -n "$STORAGE_SERVER" ] || [ -n "$STORAGE_SHARE" ] || [ -n "$STORAGE_USERNAME" ] || [ -n "$STORAGE_PASSWORD" ]; then
    echo "" >> custom-values.yaml
    echo "pvc:" >> custom-values.yaml
    [ -n "$STORAGE_SIZE" ] && echo "  storage: \"$STORAGE_SIZE\"" >> custom-values.yaml && print_info "  PVC size: $STORAGE_SIZE"
    [ -n "$STORAGE_ACCESS_MODE" ] && echo "  accessMode: \"$STORAGE_ACCESS_MODE\"" >> custom-values.yaml && print_info "  Access mode: $STORAGE_ACCESS_MODE"
    
    if [ -n "$STORAGE_SERVER" ] || [ -n "$STORAGE_SHARE" ] || [ -n "$STORAGE_USERNAME" ] || [ -n "$STORAGE_PASSWORD" ]; then
      echo "  smb:" >> custom-values.yaml
      echo "    enabled: true" >> custom-values.yaml
      print_info "  SMB storage enabled"
      [ -n "$STORAGE_SERVER" ] && echo "    server: \"$STORAGE_SERVER\"" >> custom-values.yaml && print_info "    Server: $STORAGE_SERVER"
      [ -n "$STORAGE_SHARE" ] && echo "    share: \"$STORAGE_SHARE\"" >> custom-values.yaml && print_info "    Share: $STORAGE_SHARE"
      [ -n "$STORAGE_USERNAME" ] && echo "    username: \"$STORAGE_USERNAME\"" >> custom-values.yaml && print_info "    Username: $STORAGE_USERNAME"
      [ -n "$STORAGE_PASSWORD" ] && echo "    password: \"$STORAGE_PASSWORD\"" >> custom-values.yaml && print_info "    Password: [REDACTED]"
    fi
  fi
  
  print_success "Generated custom-values.yaml from .env"
else
  print_warning "No .env file found, using default values"
fi

print_step "Deploying to Kubernetes with Helm"
print_info "Release name: builder"
print_info "Namespace: honeyspeak"
print_info "Chart: ./helm"
print_info "Values: custom-values.yaml"
echo ""

if helm upgrade --install builder ./helm -n honeyspeak -f custom-values.yaml; then
    print_success "Helm release 'builder' deployed successfully"
else
    print_error "Helm deployment failed"
    exit 1
fi

print_step "Verifying Deployment"
echo ""
print_info "Checking pod status..."
kubectl get pods -n honeyspeak -l app=flask
kubectl get pods -n honeyspeak -l app=celery
kubectl get pods -n honeyspeak -l app=redis

echo ""
print_info "Checking services..."
kubectl get svc -n honeyspeak

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}✓ Deployment Complete!${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}Useful commands:${NC}"
echo -e "  ${YELLOW}View Flask logs:${NC}   kubectl logs -f -n honeyspeak -l app=flask"
echo -e "  ${YELLOW}View Celery logs:${NC}  kubectl logs -f -n honeyspeak -l app=celery"
echo -e "  ${YELLOW}View Redis logs:${NC}   kubectl logs -f -n honeyspeak -l app=redis"
echo -e "  ${YELLOW}Get pod details:${NC}   kubectl describe pod -n honeyspeak -l app=flask"
echo -e "  ${YELLOW}Restart all deployments:${NC}      kubectl rollout restart deployment -n honeyspeak"



echo ""
echo -e "${GREEN}Access the application:${NC}"
echo -e "  ${CYAN}NodePort:${NC} http://<node-ip>:32003"
echo ""
