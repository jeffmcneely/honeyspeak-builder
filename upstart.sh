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
CURRENT_STEP=0

# Quiet mode flag
QUIET_MODE=false
if [[ "$*" == *"--quiet"* ]] || [[ "$*" == *"-q"* ]]; then
    QUIET_MODE=true
fi

print_step() {
    CURRENT_STEP=$((CURRENT_STEP + 1))
    local total_steps=$1
    local message=$2
    if [ "$QUIET_MODE" = false ]; then
        echo ""
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}[Step $CURRENT_STEP/$total_steps]${NC} $message"
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    else
        echo -e "${GREEN}[$CURRENT_STEP/$total_steps]${NC} $message"
    fi
}

print_success() {
    if [ "$QUIET_MODE" = false ]; then
        echo -e "${GREEN}✓${NC} $1"
    fi
}

print_info() {
    if [ "$QUIET_MODE" = false ]; then
        echo -e "${BLUE}ℹ${NC} $1"
    fi
}

print_warning() {
    # Always show warnings even in quiet mode
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    # Always show errors even in quiet mode
    echo -e "${RED}✗${NC} $1"
}

# Build and push multi-arch container using stryker-tcp Docker context
IMAGE_NAME="ghcr.io/jeffmcneely/honeyspeak-builder"
TAG="latest"
DOCKER_CONTEXT="stryker-tcp"

# Check for --no-context flag to skip context switching
SKIP_CONTEXT=false
if [[ "$*" == *"--no-context"* ]]; then
    SKIP_CONTEXT=true
fi

# Build function - builds and pushes the Docker image
build_image() {
    CURRENT_STEP=0
    local TOTAL_STEPS=3
    
    if [ "$QUIET_MODE" = false ]; then
        echo ""
        echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║${NC}        ${GREEN}Building Honeyspeak Builder Image${NC}                ${CYAN}║${NC}"
        echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
        echo ""
    else
        echo -e "${GREEN}Building Honeyspeak Builder Image${NC}"
    fi

    print_step $TOTAL_STEPS "Configuring Docker Build Environment"
    
    if [ "$SKIP_CONTEXT" = true ]; then
        print_info "Skipping Docker context switch (--no-context flag)"
        CURRENT_CONTEXT=$(docker context show 2>/dev/null || echo "default")
        print_info "Using current context: $CURRENT_CONTEXT"
    else
        print_info "Context: $DOCKER_CONTEXT"
        
        # Check if the context exists
        if ! docker context ls --format "{{.Name}}" 2>/dev/null | grep -q "^$DOCKER_CONTEXT$"; then
            print_warning "Docker context '$DOCKER_CONTEXT' not found"
            print_info "Available contexts:"
            docker context ls --format "  {{.Name}} ({{.Current}})" 2>/dev/null || true
            print_info "Using default context instead"
            DOCKER_CONTEXT="default"
        fi
        
        if docker context use $DOCKER_CONTEXT > /dev/null 2>&1; then
            print_success "Docker context switched to $DOCKER_CONTEXT"
        else
            print_error "Failed to switch Docker context to $DOCKER_CONTEXT"
            exit 1
        fi
    fi

    print_step $TOTAL_STEPS "Setting up Docker Buildx Builder"
    BUILDER_NAME="stryker-builder"

    # Prefer using docker buildx inspect to detect an existing builder. This
    # avoids fragile parsing of the human-readable `docker buildx ls` output
    # (the name can include a trailing '*' when active or have non-standard
    # spacing depending on Docker/Buildx versions).
    if docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
        print_info "Found existing builder: $BUILDER_NAME"

        # Try to switch to the existing builder (idempotent)
        if docker buildx use "$BUILDER_NAME" >/dev/null 2>&1; then
            print_success "Using existing builder: $BUILDER_NAME"
        else
            print_warning "Could not switch to builder '$BUILDER_NAME'. Attempting to recreate it..."
            docker buildx rm -f "$BUILDER_NAME" >/dev/null 2>&1 || true
            if docker buildx create --name "$BUILDER_NAME" --driver docker-container --use >/dev/null 2>&1; then
                print_success "Recreated buildx builder: $BUILDER_NAME"
            else
                print_warning "Recreate with docker-container driver failed; trying without driver..."
                if docker buildx create --name "$BUILDER_NAME" --use >/dev/null 2>&1; then
                    print_success "Recreated buildx builder (default driver): $BUILDER_NAME"
                else
                    print_error "Failed to recreate builder: $BUILDER_NAME"
                    print_info "Diagnostics follow:"
                    docker version || true
                    docker buildx version || true
                    docker buildx ls || true
                    print_info "Run: docker buildx rm -f $BUILDER_NAME && docker buildx create --name $BUILDER_NAME --use"
                    exit 1
                fi
            fi
        fi

        # Best-effort bootstrap; non-fatal unless it outright errors.
        if ! docker buildx inspect "$BUILDER_NAME" --bootstrap >/dev/null 2>&1; then
            print_warning "Builder '$BUILDER_NAME' bootstrap failed or incomplete"
            if [ "$QUIET_MODE" = false ]; then
                docker buildx inspect "$BUILDER_NAME" || true
            fi
        fi
    else
        # No existing builder - attempt to create one using the recommended
        # docker-container driver, with a fallback to the default driver.
        print_info "Creating new builder: $BUILDER_NAME"
        if docker buildx create --name "$BUILDER_NAME" --driver docker-container --use >/dev/null 2>&1; then
            print_success "Created new buildx builder: $BUILDER_NAME"
            docker buildx inspect "$BUILDER_NAME" --bootstrap >/dev/null 2>&1 || print_warning "Builder bootstrap warning (may work anyway)"
        else
            print_warning "Create with driver failed; trying without driver..."
            if docker buildx create --name "$BUILDER_NAME" --use >/dev/null 2>&1; then
                print_success "Created new buildx builder (default driver): $BUILDER_NAME"
                docker buildx inspect "$BUILDER_NAME" --bootstrap >/dev/null 2>&1 || print_warning "Builder bootstrap warning (may work anyway)"
            else
                print_error "Failed to create builder: $BUILDER_NAME"
                print_info "Diagnostics follow:"
                docker version || true
                docker buildx version || true
                docker buildx ls || true
                print_info "Run: docker buildx rm -f $BUILDER_NAME && docker buildx create --name $BUILDER_NAME --use"
                exit 1
            fi
        fi
    fi

    print_step $TOTAL_STEPS "Building Multi-Architecture Container Image"
    print_info "Image: $IMAGE_NAME:$TAG"
    print_info "Platforms: linux/amd64, linux/arm64"
    print_info "Builder: $BUILDER_NAME"
    echo ""
    
    # Build with quiet output, capture to log file
    BUILD_LOG="/tmp/honeyspeak-build-$$.log"
    echo -n "  Building image... "
    
    if docker buildx build --platform linux/amd64,linux/arm64 \
      -t $IMAGE_NAME:$TAG \
      --push \
      -f Dockerfile \
      --progress=auto \
      . > "$BUILD_LOG" 2>&1; then
        echo -e "${GREEN}✓${NC}"
        print_success "Image built and pushed to $IMAGE_NAME:$TAG"
        # Clean up log file on success
        rm -f "$BUILD_LOG"
    else
        echo -e "${RED}✗${NC}"
        print_error "Build failed! See details below:"
        echo ""
        echo -e "${RED}━━━━━━━━━━━ Build Error Output ━━━━━━━━━━━${NC}"
        cat "$BUILD_LOG"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        # Clean up log file
        rm -f "$BUILD_LOG"
        exit 1
    fi
    
    if [ "$QUIET_MODE" = false ]; then
        echo ""
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}✓ Build Complete!${NC}"
        echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
    else
        echo -e "${GREEN}✓ Build complete${NC}"
    fi
}

# Deploy function - generates Helm config and deploys to Kubernetes
deploy_to_kubernetes() {
    CURRENT_STEP=0
    local TOTAL_STEPS=3
    
    if [ "$QUIET_MODE" = false ]; then
        echo ""
        echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${CYAN}║${NC}        ${GREEN}Deploying Honeyspeak Builder${NC}                     ${CYAN}║${NC}"
        echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
        echo ""
    else
        echo -e "${GREEN}Deploying Honeyspeak Builder${NC}"
    fi

    print_step $TOTAL_STEPS "Generating Helm Configuration"


    print_step $TOTAL_STEPS "Generating Helm Configuration"

    # Copy .env to custom-values.yaml for Helm (convert KEY=VALUE to YAML)
    if [ -f .env ]; then
      if [ "$QUIET_MODE" = false ]; then
          print_info "Reading configuration from .env file"
      fi
      
      cat > custom-values.yaml << 'EOF'
env:
EOF
      
      # Process env vars - only process lines that are not blank, not comments, and match KEY=VALUE
      ENV_COUNT=0
      # Include CELERY_BROKER_URL and CELERY_RESULT_BACKEND explicitly
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
      
      # Add storage configuration if STORAGE_* vars are set in .env
      
      STORAGE_MOUNT_PATH=$(grep '^STORAGE_MOUNT_PATH=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_DIRECTORY=$(grep '^STORAGE_DIRECTORY=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_SIZE=$(grep '^STORAGE_SIZE=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_ACCESS_MODE=$(grep '^STORAGE_ACCESS_MODE=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_SERVER=$(grep '^STORAGE_SERVER=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_SHARE=$(grep '^STORAGE_SHARE=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_USERNAME=$(grep '^STORAGE_USERNAME=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      STORAGE_PASSWORD=$(grep '^STORAGE_PASSWORD=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      HOST_COMFYUI_FOLDER=$(grep '^HOST_COMFYUI_FOLDER=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      COMFY_OUTPUT_FOLDER=$(grep '^COMFY_OUTPUT_FOLDER=' .env 2>/dev/null | cut -d'=' -f2 | xargs)
      
      if [ -n "$STORAGE_MOUNT_PATH" ] || [ -n "$STORAGE_DIRECTORY" ] || [ -n "$STORAGE_SIZE" ] || [ -n "$STORAGE_ACCESS_MODE" ] || [ -n "$HOST_COMFYUI_FOLDER" ]; then
        echo "" >> custom-values.yaml
        echo "storage:" >> custom-values.yaml
        if [ -n "$STORAGE_MOUNT_PATH" ]; then
          echo "  mountPath: \"$STORAGE_MOUNT_PATH\"" >> custom-values.yaml
        fi
        if [ -n "$STORAGE_DIRECTORY" ]; then
          echo "  storageDirectory: \"$STORAGE_DIRECTORY\"" >> custom-values.yaml
        fi
        
        # Add ComfyUI output folder configuration if set
        if [ -n "$HOST_COMFYUI_FOLDER" ]; then
          echo "  comfy:" >> custom-values.yaml
          echo "    enabled: true" >> custom-values.yaml
          if [ -n "$COMFY_OUTPUT_FOLDER" ]; then
            echo "    mountPath: \"$COMFY_OUTPUT_FOLDER\"" >> custom-values.yaml
          else
            echo "    mountPath: \"/comfyout\"" >> custom-values.yaml
          fi
          echo "    hostPath:" >> custom-values.yaml
          echo "      enabled: true" >> custom-values.yaml
          echo "      path: \"$HOST_COMFYUI_FOLDER\"" >> custom-values.yaml
        fi
      fi
      
      if [ -n "$STORAGE_SIZE" ] || [ -n "$STORAGE_ACCESS_MODE" ] || [ -n "$STORAGE_SERVER" ] || [ -n "$STORAGE_SHARE" ] || [ -n "$STORAGE_USERNAME" ] || [ -n "$STORAGE_PASSWORD" ]; then
        echo "" >> custom-values.yaml
        echo "pvc:" >> custom-values.yaml
        [ -n "$STORAGE_SIZE" ] && echo "  storage: \"$STORAGE_SIZE\"" >> custom-values.yaml
        [ -n "$STORAGE_ACCESS_MODE" ] && echo "  accessMode: \"$STORAGE_ACCESS_MODE\"" >> custom-values.yaml
        
        if [ -n "$STORAGE_SERVER" ] || [ -n "$STORAGE_SHARE" ] || [ -n "$STORAGE_USERNAME" ] || [ -n "$STORAGE_PASSWORD" ]; then
          echo "  smb:" >> custom-values.yaml
          echo "    enabled: true" >> custom-values.yaml
          [ -n "$STORAGE_SERVER" ] && echo "    server: \"$STORAGE_SERVER\"" >> custom-values.yaml
          [ -n "$STORAGE_SHARE" ] && echo "    share: \"$STORAGE_SHARE\"" >> custom-values.yaml
          [ -n "$STORAGE_USERNAME" ] && echo "    username: \"$STORAGE_USERNAME\"" >> custom-values.yaml
          [ -n "$STORAGE_PASSWORD" ] && echo "    password: \"$STORAGE_PASSWORD\"" >> custom-values.yaml
        fi
      fi
      
      print_success "Generated custom-values.yaml"
    else
      print_warning "No .env file found, using default values"
    fi

    print_step $TOTAL_STEPS "Deploying to Kubernetes with Helm"
    print_info "Release name: builder"
    print_info "Namespace: honeyspeak"
    echo ""
    
    # Deploy with quiet output, capture to log file
    DEPLOY_LOG="/tmp/honeyspeak-deploy-$$.log"
    echo -n "  Deploying with Helm... "
    
    if helm upgrade --install builder ./helm -n honeyspeak -f custom-values.yaml > "$DEPLOY_LOG" 2>&1; then
        echo -e "${GREEN}✓${NC}"
        print_success "Helm release 'builder' deployed successfully"
        # Clean up log file on success
        rm -f "$DEPLOY_LOG"
    else
        echo -e "${RED}✗${NC}"
        print_error "Helm deployment failed! See details below:"
        echo ""
        echo -e "${RED}━━━━━━━━━━━ Deployment Error Output ━━━━━━━━━━━${NC}"
        cat "$DEPLOY_LOG"
        echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        # Clean up log file
        rm -f "$DEPLOY_LOG"
        exit 1
    fi

    print_step $TOTAL_STEPS "Restarting Deployments and Verifying"
    
    if [ "$QUIET_MODE" = false ]; then
        echo ""
        echo -n "  Restarting deployments... "
    fi
    
    if kubectl rollout restart deployment -n honeyspeak > /dev/null 2>&1; then
        if [ "$QUIET_MODE" = false ]; then
            echo -e "${GREEN}✓${NC}"
            print_success "Deployments restarted"
        fi
    else
        if [ "$QUIET_MODE" = false ]; then
            echo -e "${RED}✗${NC}"
        fi
        print_error "Failed to restart deployments"
    fi
    
    if [ "$QUIET_MODE" = false ]; then
        echo ""
        print_info "Current pod status:"
        echo ""
        kubectl get pods -n honeyspeak --no-headers | while read line; do
            echo "  $line"
        done
        
        echo ""
        print_info "Service endpoints:"
        kubectl get svc -n honeyspeak --no-headers | grep -v kubernetes | while read line; do
            echo "  $line"
        done
    fi

    if [ "$QUIET_MODE" = false ]; then
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
    else
        echo -e "${GREEN}✓ Deployment complete${NC} - Access at http://<node-ip>:32003"
    fi
}

# Main script logic
# Remove --quiet/-q and --no-context flags from arguments for case statement
ARGS=()
for arg in "$@"; do
    if [[ "$arg" != "--quiet" ]] && [[ "$arg" != "-q" ]] && [[ "$arg" != "--no-context" ]]; then
        ARGS+=("$arg")
    fi
done

case "${ARGS[0]:-all}" in
    build)
        # Build and push Docker image only
        build_image
        ;;
    deploy)
        # Restart all containers
        CURRENT_STEP=0
        TOTAL_STEPS=1
        
        if [ "$QUIET_MODE" = false ]; then
            echo ""
            echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${CYAN}║${NC}        ${GREEN}Restarting All Deployments${NC}                       ${CYAN}║${NC}"
            echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
            echo ""
        else
            echo -e "${GREEN}Restarting All Deployments${NC}"
        fi

        print_step $TOTAL_STEPS "Restarting All Deployments"
        
        if [ "$QUIET_MODE" = false ]; then
            echo ""
            echo -n "  Restarting all deployments... "
        fi
        
        if kubectl rollout restart deployment -n honeyspeak > /dev/null 2>&1; then
            if [ "$QUIET_MODE" = false ]; then
                echo -e "${GREEN}✓${NC}"
                print_success "All deployments restarted"
            fi
        else
            if [ "$QUIET_MODE" = false ]; then
                echo -e "${RED}✗${NC}"
            fi
            print_error "Failed to restart deployments"
        fi
        
        if [ "$QUIET_MODE" = false ]; then
            echo ""
            print_info "Current pod status:"
            echo ""
            kubectl get pods -n honeyspeak --no-headers | while read line; do
                echo "  $line"
            done
            
            echo ""
            echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${GREEN}✓ Restart Complete!${NC}"
            echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo ""
        else
            echo -e "${GREEN}✓ Restart complete${NC}"
        fi
        ;;
    all)
        # Build and deploy all containers
        build_image
        deploy_to_kubernetes
        ;;
    app)
        # Build and restart celery and flask deployments only
        build_image
        
        CURRENT_STEP=0
        TOTAL_STEPS=1
        
        if [ "$QUIET_MODE" = false ]; then
            echo ""
            echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
            echo -e "${CYAN}║${NC}        ${GREEN}Restarting App Deployments${NC}                       ${CYAN}║${NC}"
            echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
            echo ""
        else
            echo -e "${GREEN}Restarting App Deployments${NC}"
        fi

        print_step $TOTAL_STEPS "Restarting Celery and Flask Deployments"
        
        if [ "$QUIET_MODE" = false ]; then
            echo ""
            echo -n "  Restarting celery deployment... "
        fi
        
        if kubectl rollout restart deployment -n honeyspeak celery > /dev/null 2>&1; then
            if [ "$QUIET_MODE" = false ]; then
                echo -e "${GREEN}✓${NC}"
                print_success "Celery deployment restarted"
            fi
        else
            if [ "$QUIET_MODE" = false ]; then
                echo -e "${RED}✗${NC}"
            fi
            print_error "Failed to restart celery deployment"
        fi
        
        if [ "$QUIET_MODE" = false ]; then
            echo -n "  Restarting flask deployment... "
        fi
        
        if kubectl rollout restart deployment -n honeyspeak flask > /dev/null 2>&1; then
            if [ "$QUIET_MODE" = false ]; then
                echo -e "${GREEN}✓${NC}"
                print_success "Flask deployment restarted"
            fi
        else
            if [ "$QUIET_MODE" = false ]; then
                echo -e "${RED}✗${NC}"
            fi
            print_error "Failed to restart flask deployment"
        fi
        
        if [ "$QUIET_MODE" = false ]; then
            echo ""
            print_info "Current pod status:"
            echo ""
            kubectl get pods -n honeyspeak -l 'app in (celery,flask)' --no-headers | while read line; do
                echo "  $line"
            done
            
            echo ""
            echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo -e "${GREEN}✓ Restart Complete!${NC}"
            echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
            echo ""
            echo -e "${BLUE}Useful commands:${NC}"
            echo -e "  ${YELLOW}View Flask logs:${NC}   kubectl logs -f -n honeyspeak -l app=flask"
            echo -e "  ${YELLOW}View Celery logs:${NC}  kubectl logs -f -n honeyspeak -l app=celery"
            echo ""
        else
            echo -e "${GREEN}✓ Restart complete${NC}"
        fi
        ;;
    help|--help|-h)
        echo "Usage: $0 [command] [options]"
        echo ""
        echo "Commands:"
        echo "  all        Build and deploy all containers (Helm upgrade + rollout restart) [default]"
        echo "  build      Build and push Docker image only"
        echo "  deploy     Restart all containers"
        echo "  app        Build and restart celery and flask containers only"
        echo "  help       Show this help message"
        echo ""
        echo "Options:"
        echo "  --quiet, -q      Minimal output (only show errors and final status)"
        echo "  --no-context     Skip Docker context switching (use current context)"
        echo ""
        echo "Examples:"
        echo "  $0                     # Build and deploy everything (default: all)"
        echo "  $0 all                 # Build and deploy everything (explicit)"
        echo "  $0 build               # Build and push image only"
        echo "  $0 deploy              # Restart all containers"
        echo "  $0 app                 # Build and restart flask/celery"
        echo "  $0 build -q            # Build only with minimal output"
        echo "  $0 build --no-context  # Build without switching Docker context"
        echo ""
        exit 0
        ;;
    *)
        echo -e "${RED}Error: Unknown command '${ARGS[0]}'${NC}"
        echo ""
        echo "Usage: $0 [command] [options]"
        echo "Commands: build | deploy | all | app | help"
        echo "Try '$0 help' for more information."
        echo ""
        exit 1
        ;;
esac
