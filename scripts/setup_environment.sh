#!/bin/bash

# eBPF-Test Environment Setup Script
# This script sets up all dependencies for XDP/eBPF development
# Tested on Ubuntu 24.04.2 LTS with kernel 6.11.0-29-generic

set -e

echo "🚀 Starting eBPF-Test Environment Setup..."

# Color codes for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# Check system requirements
print_info "Checking system requirements..."

# Check kernel version (minimum 5.10)
KERNEL_VERSION=$(uname -r | cut -d. -f1,2)
KERNEL_MAJOR=$(echo $KERNEL_VERSION | cut -d. -f1)
KERNEL_MINOR=$(echo $KERNEL_VERSION | cut -d. -f2)

if [ "$KERNEL_MAJOR" -gt 5 ] || ([ "$KERNEL_MAJOR" -eq 5 ] && [ "$KERNEL_MINOR" -ge 10 ]); then
    print_status "Kernel version $KERNEL_VERSION meets requirements (≥5.10)"
else
    print_error "Kernel version $KERNEL_VERSION is too old. Minimum required: 5.10"
    exit 1
fi

# Check if Ubuntu
if ! lsb_release -a 2>/dev/null | grep -q "Ubuntu"; then
    print_error "This script is designed for Ubuntu. Manual installation may be required."
    exit 1
fi

print_status "System requirements check passed"

# Update package lists
print_info "Updating package lists..."
sudo apt update
print_status "Package lists updated"

# Install core eBPF development tools
print_info "Installing clang and LLVM..."
sudo apt install -y clang llvm
print_status "Clang and LLVM installed"

# Install libbpf and build tools
print_info "Installing libbpf and build essentials..."
sudo apt install -y libbpf-dev linux-headers-$(uname -r) build-essential
print_status "eBPF development packages installed"

# Install traffic generation tools
print_info "Installing traffic generation tools..."
sudo apt install -y iperf3 netperf
print_status "Traffic generation tools installed"

# Verify installations
print_info "Verifying installations..."

# Check clang
if clang --version > /dev/null 2>&1; then
    CLANG_VER=$(clang --version | head -1)
    print_status "Clang: $CLANG_VER"
else
    print_error "Clang installation failed"
    exit 1
fi

# Check libbpf
if pkg-config --exists libbpf; then
    LIBBPF_VER=$(pkg-config --modversion libbpf)
    print_status "libbpf: v$LIBBPF_VER"
else
    print_error "libbpf installation failed"
    exit 1
fi

# Check bpftool
if bpftool version > /dev/null 2>&1; then
    BPFTOOL_VER=$(bpftool version | head -1)
    print_status "bpftool: $BPFTOOL_VER"
else
    print_error "bpftool not available"
    exit 1
fi

# Check ethtool
if ethtool --version > /dev/null 2>&1; then
    ETHTOOL_VER=$(ethtool --version | head -1)
    print_status "ethtool: $ETHTOOL_VER"
else
    print_error "ethtool not available"
    exit 1
fi

# Check iperf3
if iperf3 --version > /dev/null 2>&1; then
    IPERF_VER=$(iperf3 --version | head -1)
    print_status "iperf3: $IPERF_VER"
else
    print_error "iperf3 installation failed"
    exit 1
fi

# Check BPF target in LLVM
if llvm-objdump --version | grep -q "bpf.*BPF"; then
    print_status "LLVM BPF target support confirmed"
else
    print_error "LLVM BPF target not found"
    exit 1
fi

# Check network interfaces
print_info "Available network interfaces:"
ip link show | grep -E "^[0-9]+:" | while read line; do
    interface=$(echo $line | awk -F': ' '{print $2}' | awk '{print $1}')
    print_info "  - $interface"
done

echo ""
print_status "🎉 Environment setup completed successfully!"
echo ""
print_info "Next steps:"
echo "  1. Create userspace baseline implementation"
echo "  2. Develop XDP packet processing program"  
echo "  3. Run performance benchmarks"
echo ""
print_info "System Summary:"
echo "  - Kernel: $(uname -r)"
echo "  - OS: $(lsb_release -d | cut -f2)"
echo "  - CPU: $(lscpu | grep "Model name" | cut -d: -f2 | xargs)"
echo "  - Cores: $(nproc)" 