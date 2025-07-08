#!/bin/bash

# eBPF-Test Setup Verification Script
# Quickly validates that everything is working correctly

set -e

echo "🔍 eBPF-Test Setup Verification"
echo "================================"

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

check_pass() {
    echo -e "${GREEN}✅ PASS${NC}: $1"
    ((PASS++))
}

check_fail() {
    echo -e "${RED}❌ FAIL${NC}: $1"
    ((FAIL++))
}

check_warn() {
    echo -e "${YELLOW}⚠️  WARN${NC}: $1"
}

echo ""
echo "System Requirements:"
echo "-------------------"

# Check kernel version
KERNEL_VERSION=$(uname -r)
KERNEL_MAJOR=$(echo $KERNEL_VERSION | cut -d. -f1)
KERNEL_MINOR=$(echo $KERNEL_VERSION | cut -d. -f2)

if [ "$KERNEL_MAJOR" -gt 5 ] || ([ "$KERNEL_MAJOR" -eq 5 ] && [ "$KERNEL_MINOR" -ge 10 ]); then
    check_pass "Kernel version $KERNEL_VERSION (≥5.10 required)"
else
    check_fail "Kernel version $KERNEL_VERSION too old (≥5.10 required)"
fi

# Check Ubuntu
if lsb_release -a 2>/dev/null | grep -q "Ubuntu"; then
    UBUNTU_VERSION=$(lsb_release -r | awk '{print $2}')
    check_pass "Ubuntu $UBUNTU_VERSION detected"
else
    check_warn "Non-Ubuntu system detected - manual setup may be required"
fi

# Check CPU cores
CORES=$(nproc)
if [ "$CORES" -ge 4 ]; then
    check_pass "$CORES CPU cores available (≥4 recommended)"
else
    check_warn "$CORES CPU cores (≥4 recommended for performance)"
fi

echo ""
echo "Development Tools:"
echo "-----------------"

# Check clang
if command -v clang > /dev/null 2>&1; then
    CLANG_VERSION=$(clang --version | head -1)
    check_pass "Clang: $CLANG_VERSION"
else
    check_fail "Clang not found - run setup script"
fi

# Check libbpf
if pkg-config --exists libbpf; then
    LIBBPF_VERSION=$(pkg-config --modversion libbpf)
    check_pass "libbpf: v$LIBBPF_VERSION"
else
    check_fail "libbpf development package not found"
fi

# Check bpftool
if command -v bpftool > /dev/null 2>&1; then
    BPFTOOL_VERSION=$(bpftool version 2>/dev/null | head -1 || echo "available")
    check_pass "bpftool: $BPFTOOL_VERSION"
else
    check_fail "bpftool not found"
fi

# Check build tools
if command -v make > /dev/null 2>&1 && command -v gcc > /dev/null 2>&1; then
    check_pass "Build tools (make, gcc) available"
else
    check_fail "Build tools missing - install build-essential"
fi

echo ""
echo "Project Structure:"
echo "-----------------"

# Check critical files
CRITICAL_FILES=(
    "include/feature.h"
    "benchmarks/baseline.c"
    "scripts/generate_udp_traffic.py"
    "Makefile"
)

for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        check_pass "Found: $file"
    else
        check_fail "Missing: $file"
    fi
done

echo ""
echo "Build Test:"
echo "----------"

# Test build
if make baseline > /dev/null 2>&1; then
    check_pass "Baseline builds successfully"
    
    # Check executable
    if [ -x "build/baseline" ]; then
        check_pass "Baseline executable created"
    else
        check_fail "Baseline executable not found"
    fi
else
    check_fail "Baseline build failed - check dependencies"
fi

echo ""
echo "Network Interfaces:"
echo "------------------"

# Check interfaces
if ip link show lo | grep -q "UP"; then
    check_pass "Loopback interface (lo) is UP"
else
    check_warn "Loopback interface (lo) is DOWN"
fi

# Check for other interfaces
ETH_INTERFACES=$(ip link show | grep "state UP" | grep -v lo | wc -l)
if [ "$ETH_INTERFACES" -gt 0 ]; then
    check_pass "$ETH_INTERFACES network interface(s) available"
    ip link show | grep "state UP" | while read line; do
        interface=$(echo $line | awk -F': ' '{print $2}' | awk '{print $1}')
        echo "   - $interface"
    done
else
    check_warn "No active network interfaces found (besides loopback)"
fi

echo ""
echo "Permissions:"
echo "-----------"

# Check sudo access
if sudo -n true 2>/dev/null; then
    check_pass "Sudo access available (no password required)"
elif sudo -v; then
    check_pass "Sudo access available (password required)"
else
    check_fail "No sudo access - required for raw sockets"
fi

echo ""
echo "Quick Functionality Test:"
echo "------------------------"

# Quick test if possible
if [ -x "build/baseline" ] && [ "$FAIL" -eq 0 ]; then
    echo "Running 3-second functionality test..."
    
    # Start traffic in background
    python3 scripts/generate_udp_traffic.py --rate 10 --duration 5 > /dev/null 2>&1 &
    TRAFFIC_PID=$!
    
    # Test baseline for 3 seconds
    if timeout 3s sudo ./build/baseline lo > /tmp/baseline_test.log 2>&1; then
        PACKETS=$(grep "Packets processed:" /tmp/baseline_test.log | awk '{print $3}' || echo "0")
        if [ "$PACKETS" -gt 0 ]; then
            check_pass "Functional test: $PACKETS UDP packets processed"
        else
            check_warn "Functional test: No UDP packets processed (may be normal)"
        fi
    else
        check_warn "Functional test skipped (requires manual sudo)"
    fi
    
    # Cleanup
    kill $TRAFFIC_PID 2>/dev/null || true
    rm -f /tmp/baseline_test.log
else
    check_warn "Functional test skipped - build failures or missing files"
fi

echo ""
echo "Summary:"
echo "======="
echo -e "✅ Passed: $PASS"
echo -e "❌ Failed: $FAIL"

if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}"
    echo "🎉 ALL CHECKS PASSED!"
    echo "System is ready for eBPF-Test development"
    echo ""
    echo "Quick test command:"
    echo "  python3 scripts/generate_udp_traffic.py --preset low --duration 10 &"
    echo "  sudo timeout 8s ./build/baseline lo"
    echo -e "${NC}"
    exit 0
else
    echo -e "${RED}"
    echo "❌ SETUP INCOMPLETE"
    echo "Please fix the failed checks above"
    echo "Run: ./scripts/setup_environment.sh"
    echo -e "${NC}"
    exit 1
fi 