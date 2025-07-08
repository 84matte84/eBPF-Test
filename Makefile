# eBPF-Test Makefile
# Builds userspace baseline and will support XDP programs

CC = gcc
CLANG = clang
BPFTOOL = bpftool

# Directories
SRC_DIR = src
INCLUDE_DIR = include
BUILD_DIR = build
DEPS_DIR = deps

# Target architecture for BPF
BPF_TARGET = bpf
BPF_ARCH = $(shell uname -m | sed 's/x86_64/x86/' | sed 's/aarch64/arm64/')

# Compiler flags
COMMON_CFLAGS = -Wall -Wextra -O2 -g
USERSPACE_CFLAGS = $(COMMON_CFLAGS) -I$(INCLUDE_DIR)
BPF_CFLAGS = $(COMMON_CFLAGS) -target $(BPF_TARGET) -D__BPF_TRACING__ \
             -I$(INCLUDE_DIR) -I/usr/include/$(shell uname -m)-linux-gnu \
             -fno-stack-protector

# Libraries
LIBS = -lbpf -lelf -lz

# Source files
XDP_SRC = $(SRC_DIR)/xdp_preproc.c
LOADER_SRC = $(SRC_DIR)/loader.c
BASELINE_SRC = benchmarks/baseline.c
PERFTEST_SRC = benchmarks/performance_test.c

# Object files
XDP_OBJ = $(BUILD_DIR)/xdp_preproc.o
LOADER_OBJ = $(BUILD_DIR)/loader.o
BASELINE_OBJ = $(BUILD_DIR)/baseline.o
PERFTEST_OBJ = $(BUILD_DIR)/performance_test.o

# Target binaries
LOADER_BIN = $(BUILD_DIR)/xdp_loader
BASELINE_BIN = $(BUILD_DIR)/baseline_app
PERFTEST_BIN = $(BUILD_DIR)/performance_test

# Header dependencies  
HEADERS = $(INCLUDE_DIR)/feature.h

# Default target
all: setup $(XDP_OBJ) $(LOADER_BIN) $(BASELINE_BIN) $(PERFTEST_BIN)

# Create build directory
setup:
	@mkdir -p $(BUILD_DIR)
	@echo "Build directory created"

# Build XDP program (BPF object)
$(XDP_OBJ): $(XDP_SRC) $(HEADERS)
	@echo "Compiling XDP program..."
	$(CLANG) $(BPF_CFLAGS) -c $< -o $@
	@echo "XDP program compiled: $@"

# Build userspace loader
$(LOADER_BIN): $(LOADER_SRC) $(HEADERS)
	@echo "Compiling XDP loader..."
	$(CC) $(USERSPACE_CFLAGS) $< -o $@ $(LIBS)
	@echo "XDP loader compiled: $@"

# Build baseline application
$(BASELINE_BIN): $(BASELINE_SRC) $(HEADERS)
	@echo "Compiling baseline application..."
	$(CC) $(USERSPACE_CFLAGS) $< -o $@
	@echo "Baseline application compiled: $@"

# Build performance test application
$(PERFTEST_BIN): $(PERFTEST_SRC) $(HEADERS)
	@echo "Compiling performance test application..."
	$(CC) $(USERSPACE_CFLAGS) $< -o $@ -lpthread
	@echo "Performance test application compiled: $@"

# Generate BTF info (for CO-RE)
btf: $(XDP_OBJ)
	@echo "Generating BTF information..."
	$(BPFTOOL) gen skeleton $(XDP_OBJ) > $(INCLUDE_DIR)/xdp_preproc.skel.h
	@echo "BTF skeleton generated"

# Verify BPF program
verify: $(XDP_OBJ)
	@echo "Verifying BPF program..."
	$(BPFTOOL) prog load $(XDP_OBJ) /sys/fs/bpf/xdp_preproc_test 2>/dev/null || true
	$(BPFTOOL) prog show pinned /sys/fs/bpf/xdp_preproc_test 2>/dev/null || echo "Program verification failed"
	@rm -f /sys/fs/bpf/xdp_preproc_test

# Install dependencies (Ubuntu/Debian)
install-deps:
	@echo "Installing BPF development dependencies..."
	sudo apt-get update
	sudo apt-get install -y \
		clang \
		llvm \
		libbpf-dev \
		bpftool \
		linux-tools-common \
		linux-tools-$(shell uname -r) \
		build-essential \
		pkg-config \
		libelf-dev \
		zlib1g-dev

# Check system capabilities
check-caps:
	@echo "Checking BPF capabilities..."
	@echo "Kernel version: $(shell uname -r)"
	@echo "BPF syscall available: $(shell [ -e /proc/sys/kernel/unprivileged_bpf_disabled ] && echo "Yes" || echo "No")"
	@echo "BPF JIT enabled: $(shell [ "$$(cat /proc/sys/net/core/bpf_jit_enable 2>/dev/null)" = "1" ] && echo "Yes" || echo "No")"
	@echo "Available tools:"
	@which clang || echo "  clang: NOT FOUND"
	@which bpftool || echo "  bpftool: NOT FOUND" 
	@pkg-config --exists libbpf && echo "  libbpf: OK" || echo "  libbpf: NOT FOUND"

# Test XDP program loading
test-load: $(XDP_OBJ)
	@echo "Testing XDP program loading..."
	sudo $(LOADER_BIN) lo $(XDP_OBJ) &
	@sleep 2
	@pkill -f $(LOADER_BIN) || true
	@echo "Load test completed"

# Run baseline benchmark
benchmark-baseline: $(BASELINE_BIN)
	@echo "Running baseline benchmark..."
	sudo $(BASELINE_BIN) 10

# Run XDP benchmark
benchmark-xdp: $(LOADER_BIN) $(XDP_OBJ)
	@echo "Running XDP benchmark..."
	sudo $(LOADER_BIN) enp5s0 $(XDP_OBJ)

# Phase 3: Run comprehensive performance tests
test-performance-baseline: $(PERFTEST_BIN)
	@echo "Running comprehensive baseline performance test..."
	sudo $(PERFTEST_BIN) --mode baseline --duration 30 --rate 1000 --verbose

test-performance-xdp: $(PERFTEST_BIN) $(XDP_OBJ)
	@echo "Running comprehensive XDP performance test..."
	sudo $(PERFTEST_BIN) --mode xdp --duration 30 --rate 1000 --verbose

# Phase 3: Run fair comparison tests
benchmark-comparison: $(PERFTEST_BIN) $(XDP_OBJ)
	@echo "Running fair baseline vs XDP comparison..."
	@echo "This will run both tests under identical conditions for fair comparison"
	@echo "Starting baseline test..."
	sudo $(PERFTEST_BIN) --mode baseline --duration 60 --rate 5000 --verbose
	@echo "Waiting 10 seconds before XDP test..."
	@sleep 10
	@echo "Starting XDP test..."
	sudo $(PERFTEST_BIN) --mode xdp --duration 60 --rate 5000 --verbose

# Phase 3: High-rate traffic generation
generate-high-traffic:
	@echo "Starting high-rate traffic generation..."
	python3 scripts/high_rate_traffic.py --preset medium --verbose

generate-extreme-traffic:
	@echo "Starting extreme traffic generation..."
	python3 scripts/high_rate_traffic.py --preset extreme --verbose

# Generate traffic for testing
generate-traffic:
	@echo "Generating UDP test traffic..."
	@echo "Run this in another terminal: sudo iperf3 -s -p 8080"
	@echo "Then run: iperf3 -c localhost -p 8080 -u -b 100M -t 30"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf $(BUILD_DIR)
	rm -f $(INCLUDE_DIR)/xdp_preproc.skel.h

# Deep clean (including pinned BPF programs)
clean-all: clean
	@echo "Cleaning pinned BPF programs..."
	sudo rm -f /sys/fs/bpf/xdp_*
	@echo "Detaching any remaining XDP programs..."
	sudo bpftool prog show | grep xdp || true

# Help target
help:
	@echo "Available targets:"
	@echo "  all              - Build all components"
	@echo "  setup            - Create build directory"
	@echo "  btf              - Generate BTF skeleton"
	@echo "  verify           - Verify BPF program"
	@echo "  install-deps     - Install system dependencies"
	@echo "  check-caps       - Check BPF system capabilities"
	@echo "  test-load        - Test XDP program loading"
	@echo "  benchmark-baseline - Run baseline performance test"
	@echo "  benchmark-xdp    - Run XDP performance test"
	@echo ""
	@echo "Phase 3 Targets:"
	@echo "  test-performance-baseline - Comprehensive baseline test"
	@echo "  test-performance-xdp     - Comprehensive XDP test"
	@echo "  benchmark-comparison     - Fair baseline vs XDP comparison"
	@echo "  generate-high-traffic    - High-rate traffic generation"
	@echo "  generate-extreme-traffic - Extreme-rate traffic generation"
	@echo ""
	@echo "  generate-traffic - Instructions for traffic generation"
	@echo "  clean            - Clean build artifacts"
	@echo "  clean-all        - Deep clean including BPF programs"
	@echo "  help             - Show this help"

# Phony targets
.PHONY: all setup btf verify install-deps check-caps test-load \
        benchmark-baseline benchmark-xdp generate-traffic \
        clean clean-all help

# Dependencies
$(LOADER_BIN): $(HEADERS)
$(BASELINE_BIN): $(HEADERS)
$(XDP_OBJ): $(HEADERS) 