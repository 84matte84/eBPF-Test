#!/bin/bash

# eBPF-Test Two-Machine Setup Script
# Sets up the two-machine testing environment

set -e

echo "🚀 eBPF-Test Two-Machine Setup"
echo "================================"

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log_info "Script directory: $SCRIPT_DIR"
log_info "Project root: $PROJECT_ROOT"

# Function to check Python dependencies
check_python_deps() {
    local deps=("$@")
    local missing=()
    
    for dep in "${deps[@]}"; do
        if ! python3 -c "import $dep" 2>/dev/null; then
            missing+=("$dep")
        fi
    done
    
    if [ ${#missing[@]} -ne 0 ]; then
        log_warning "Missing Python packages: ${missing[*]}"
        log_info "Installing missing packages..."
        pip3 install "${missing[@]}"
    else
        log_success "All Python dependencies satisfied"
    fi
}

# Create necessary directories
log_info "Creating directory structure..."

# Create results directory
if [ ! -d "$PROJECT_ROOT/results/two_machine" ]; then
    mkdir -p "$PROJECT_ROOT/results/two_machine" 2>/dev/null || {
        log_warning "Cannot create results directory (permission issue)"
        log_info "Results will be created at runtime"
    }
fi

log_success "Directory structure ready"

# Check system type
SYSTEM_TYPE=$(uname -s)
log_info "Detected system: $SYSTEM_TYPE"

# Machine type detection
echo ""
echo "Which machine type are you setting up?"
echo "1) src_machine (Traffic Generator) - Linux/macOS"
echo "2) dst_machine (XDP Testing) - Linux only"
echo "3) Both (single machine development)"

read -p "Enter choice [1-3]: " machine_choice

case $machine_choice in
    1)
        MACHINE_TYPE="src"
        log_info "Setting up src_machine (Traffic Generator)"
        ;;
    2)
        MACHINE_TYPE="dst"
        log_info "Setting up dst_machine (XDP Testing)"
        ;;
    3)
        MACHINE_TYPE="both"
        log_info "Setting up both machine types"
        ;;
    *)
        log_error "Invalid choice"
        exit 1
        ;;
esac

# src_machine setup
if [[ "$MACHINE_TYPE" == "src" || "$MACHINE_TYPE" == "both" ]]; then
    echo ""
    log_info "=== Setting up src_machine dependencies ==="
    
    # Check Python version
    PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Python version: $PYTHON_VERSION"
    
    if python3 -c "import sys; exit(0 if sys.version_info >= (3, 8) else 1)"; then
        log_success "Python version is sufficient (≥3.8)"
    else
        log_error "Python 3.8+ required, found $PYTHON_VERSION"
        exit 1
    fi
    
    # Install Python dependencies for src_machine
    log_info "Checking Python dependencies for src_machine..."
    check_python_deps "yaml" "requests"
    
    # Make scripts executable
    chmod +x "$SCRIPT_DIR/src_machine.py" 2>/dev/null || true
    chmod +x "$SCRIPT_DIR/coordination.py" 2>/dev/null || true
    
    log_success "src_machine setup complete"
fi

# dst_machine setup
if [[ "$MACHINE_TYPE" == "dst" || "$MACHINE_TYPE" == "both" ]]; then
    echo ""
    log_info "=== Setting up dst_machine dependencies ==="
    
    # Check if running on Linux
    if [ "$SYSTEM_TYPE" != "Linux" ]; then
        log_error "dst_machine requires Linux"
        if [ "$MACHINE_TYPE" != "both" ]; then
            exit 1
        else
            log_warning "Skipping dst_machine setup on non-Linux system"
        fi
    else
        # Check for root privileges
        if [ "$EUID" -ne 0 ]; then
            log_warning "dst_machine setup requires root privileges"
            log_info "Some setup steps will be skipped"
            log_info "Run 'sudo ./setup.sh' for complete setup"
        fi
        
        # Install Python dependencies for dst_machine
        log_info "Checking Python dependencies for dst_machine..."
        check_python_deps "yaml" "requests" "psutil"
        
        # Check system tools
        log_info "Checking system tools..."
        missing_tools=()
        
        for tool in ip bpftool; do
            if ! command -v "$tool" >/dev/null 2>&1; then
                missing_tools+=("$tool")
            fi
        done
        
        if [ ${#missing_tools[@]} -ne 0 ]; then
            log_warning "Missing system tools: ${missing_tools[*]}"
            if [ "$EUID" -eq 0 ]; then
                log_info "Installing missing tools..."
                apt update && apt install -y "${missing_tools[@]}" 2>/dev/null || {
                    log_warning "Could not install tools automatically"
                    log_info "Please install manually: ${missing_tools[*]}"
                }
            else
                log_info "Run as root to install automatically"
            fi
        else
            log_success "All system tools available"
        fi
        
        # Check if eBPF project is built
        if [ ! -f "$PROJECT_ROOT/build/xdp_loader" ]; then
            log_warning "XDP loader not found"
            log_info "Building eBPF project..."
            cd "$PROJECT_ROOT"
            if make all; then
                log_success "eBPF project built successfully"
            else
                log_error "Failed to build eBPF project"
                log_info "Please run 'make all' in the project root"
            fi
        else
            log_success "eBPF project already built"
        fi
        
        # Make scripts executable
        chmod +x "$SCRIPT_DIR/dst_machine.py" 2>/dev/null || true
        chmod +x "$SCRIPT_DIR/coordination.py" 2>/dev/null || true
        
        log_success "dst_machine setup complete"
    fi
fi

# Configuration setup
echo ""
log_info "=== Configuration Setup ==="

CONFIG_FILE="$SCRIPT_DIR/config.yaml"
if [ ! -f "$CONFIG_FILE" ]; then
    log_error "Configuration file not found: $CONFIG_FILE"
    exit 1
fi

log_info "Configuration file: $CONFIG_FILE"
log_warning "You need to update the IP addresses in the configuration:"

if [[ "$MACHINE_TYPE" == "src" || "$MACHINE_TYPE" == "both" ]]; then
    echo "  - src_machine IP (network_config.src_machine.ip)"
fi

if [[ "$MACHINE_TYPE" == "dst" || "$MACHINE_TYPE" == "both" ]]; then
    echo "  - dst_machine IP (network_config.dst_machine.ip)"
    echo "  - Network interface (network_config.dst_machine.interface)"
fi

# Network interface detection (Linux only)
if [ "$SYSTEM_TYPE" == "Linux" ] && [[ "$MACHINE_TYPE" == "dst" || "$MACHINE_TYPE" == "both" ]]; then
    log_info "Detecting network interfaces..."
    
    # List active interfaces
    active_interfaces=$(ip link show | grep "state UP" | grep -v "lo:" | awk -F': ' '{print $2}' || true)
    
    if [ -n "$active_interfaces" ]; then
        log_info "Active network interfaces found:"
        echo "$active_interfaces" | while read -r iface; do
            if [ -n "$iface" ]; then
                echo "  - $iface"
            fi
        done
        log_info "Update config.yaml with the appropriate interface name"
    else
        log_warning "No active network interfaces found (besides loopback)"
    fi
fi

# Next steps
echo ""
log_info "=== Next Steps ==="

case $MACHINE_TYPE in
    "src")
        echo "1. Update config.yaml with correct IP addresses"
        echo "2. Test connection: python3 src_machine.py --config config.yaml --dry-run"
        echo "3. Run traffic generator: python3 src_machine.py --config config.yaml"
        ;;
    "dst")
        echo "1. Update config.yaml with correct IP addresses and interface"
        echo "2. Test setup: sudo python3 dst_machine.py --config config.yaml --check-only"
        echo "3. Run coordinator: sudo python3 dst_machine.py --config config.yaml"
        ;;
    "both")
        echo "1. Update config.yaml with correct IP addresses and interface"
        echo "2. Test dst_machine: sudo python3 dst_machine.py --config config.yaml --check-only"
        echo "3. Test src_machine: python3 src_machine.py --config config.yaml --dry-run"
        echo "4. Run both machines for testing"
        ;;
esac

echo ""
log_success "Setup complete!"
log_info "See README.md for detailed usage instructions" 