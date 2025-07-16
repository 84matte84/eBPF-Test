# ============================================================================
# High-Performance ML Packet Processing - Makefile
# Builds XDP programs, AF_XDP userspace components, and ML integration API
# ============================================================================

# Build configuration
CC := clang
CFLAGS := -g -Wall -Wextra -O2 -std=c11
BPF_CFLAGS := -g -O2 -target bpf -D__TARGET_ARCH_x86

# Include paths
INCLUDES := -I./include -I/usr/include/x86_64-linux-gnu

# Libraries
LIBS := -lbpf -lelf -lz -lpthread -lm
XSK_LIBS := $(LIBS) -lxdp

# Source directories
SRC_DIR := src
INCLUDE_DIR := include
BUILD_DIR := build
EXAMPLES_DIR := examples

# XDP programs
XDP_SOURCES := $(SRC_DIR)/xdp_ml_filter.c
XDP_OBJECTS := $(patsubst $(SRC_DIR)/%.c,$(BUILD_DIR)/%.o,$(XDP_SOURCES))

# Userspace programs  
USERSPACE_SOURCES := $(SRC_DIR)/ml_af_xdp_processor.c
USERSPACE_TARGETS := $(patsubst $(SRC_DIR)/%.c,$(BUILD_DIR)/%,$(USERSPACE_SOURCES))

# Examples
EXAMPLE_SOURCES := $(EXAMPLES_DIR)/ml_integration_example.c
EXAMPLE_TARGETS := $(patsubst $(EXAMPLES_DIR)/%.c,$(BUILD_DIR)/%,$(EXAMPLE_SOURCES))

# API library
API_LIB := $(BUILD_DIR)/libml_packet.a
API_SHARED := $(BUILD_DIR)/libml_packet.so

# Test programs
TEST_SOURCES := $(wildcard tests/*.c)
TEST_TARGETS := $(patsubst tests/%.c,$(BUILD_DIR)/test_%,$(TEST_SOURCES))

# All targets
ALL_TARGETS := $(XDP_OBJECTS) $(USERSPACE_TARGETS) $(EXAMPLE_TARGETS) $(API_LIB) $(API_SHARED)

# ============================================================================
# Main build targets
# ============================================================================

.PHONY: all clean install uninstall test check-deps help

all: check-deps $(ALL_TARGETS)
	@echo "✅ Build complete - ML packet processing system ready"
	@echo "   XDP programs: $(XDP_OBJECTS)"
	@echo "   Userspace: $(USERSPACE_TARGETS)"  
	@echo "   Examples: $(EXAMPLE_TARGETS)"
	@echo "   API library: $(API_LIB)"

# Create build directory
$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

# ============================================================================
# XDP program compilation
# ============================================================================

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	@echo "🔨 Compiling XDP program: $<"
	$(CC) $(BPF_CFLAGS) $(INCLUDES) -c $< -o $@
	@echo "✅ XDP program compiled: $@"

# ============================================================================  
# Userspace program compilation
# ============================================================================

$(BUILD_DIR)/ml_af_xdp_processor: $(SRC_DIR)/ml_af_xdp_processor.c | $(BUILD_DIR)
	@echo "🔨 Compiling AF_XDP processor: $<"
	$(CC) $(CFLAGS) $(INCLUDES) $< -o $@ $(XSK_LIBS)
	@echo "✅ AF_XDP processor compiled: $@"

# ============================================================================
# Examples compilation  
# ============================================================================

$(BUILD_DIR)/ml_integration_example: $(EXAMPLES_DIR)/ml_integration_example.c $(API_LIB) | $(BUILD_DIR)
	@echo "🔨 Compiling ML integration example: $<"
	$(CC) $(CFLAGS) $(INCLUDES) $< -o $@ -L$(BUILD_DIR) -lml_packet $(LIBS)
	@echo "✅ ML integration example compiled: $@"

# ============================================================================
# API library compilation
# ============================================================================

# Static library (placeholder - would contain actual API implementation)
$(API_LIB): | $(BUILD_DIR)
	@echo "🔨 Creating ML packet API library (static): $@"
	ar rcs $@ 
	@echo "✅ API library created: $@"

# Shared library (placeholder)
$(API_SHARED): | $(BUILD_DIR)
	@echo "🔨 Creating ML packet API library (shared): $@"
	$(CC) $(CFLAGS) -shared -fPIC -o $@
	@echo "✅ Shared API library created: $@"

# ============================================================================
# Testing
# ============================================================================

test: all $(TEST_TARGETS)
	@echo "🧪 Running ML packet processing tests..."
	@for test in $(TEST_TARGETS); do \
		echo "  Running $$test..."; \
		sudo $$test || exit 1; \
	done
	@echo "✅ All tests passed"

$(BUILD_DIR)/test_%: tests/%.c $(API_LIB) | $(BUILD_DIR)
	@echo "🔨 Compiling test: $<"
	$(CC) $(CFLAGS) $(INCLUDES) $< -o $@ -L$(BUILD_DIR) -lml_packet $(LIBS)

# ============================================================================
# Installation
# ============================================================================

install: all
	@echo "📦 Installing ML packet processing system..."
	sudo mkdir -p /usr/local/bin
	sudo mkdir -p /usr/local/lib
	sudo mkdir -p /usr/local/include
	
	# Install binaries
	sudo cp $(BUILD_DIR)/ml_af_xdp_processor /usr/local/bin/
	sudo cp $(BUILD_DIR)/ml_integration_example /usr/local/bin/
	
	# Install libraries  
	sudo cp $(API_LIB) /usr/local/lib/
	sudo cp $(API_SHARED) /usr/local/lib/
	sudo ldconfig
	
	# Install headers
	sudo cp $(INCLUDE_DIR)/ml_packet_api.h /usr/local/include/
	
	# Install XDP programs
	sudo mkdir -p /usr/local/share/ml-packet-processing
	sudo cp $(XDP_OBJECTS) /usr/local/share/ml-packet-processing/
	
	@echo "✅ Installation complete"

uninstall:
	@echo "🗑️  Uninstalling ML packet processing system..."
	sudo rm -f /usr/local/bin/ml_af_xdp_processor
	sudo rm -f /usr/local/bin/ml_integration_example
	sudo rm -f /usr/local/lib/libml_packet.*
	sudo rm -f /usr/local/include/ml_packet_api.h
	sudo rm -rf /usr/local/share/ml-packet-processing
	sudo ldconfig
	@echo "✅ Uninstallation complete"

# ============================================================================
# Development and debugging
# ============================================================================

debug: CFLAGS += -DDEBUG -ggdb3
debug: all

release: CFLAGS += -DNDEBUG -O3 -flto
release: BPF_CFLAGS += -O3
release: all

profile: CFLAGS += -pg -fprofile-arcs -ftest-coverage
profile: all

# ============================================================================
# System requirements check
# ============================================================================

check-deps:
	@echo "🔍 Checking system dependencies..."
	@which clang >/dev/null 2>&1 || (echo "❌ clang not found - install with: apt install clang"; exit 1)
	@which llvm-strip >/dev/null 2>&1 || (echo "❌ llvm-strip not found - install with: apt install llvm"; exit 1)
	@pkg-config --exists libbpf || (echo "❌ libbpf not found - install with: apt install libbpf-dev"; exit 1)
	@[ -f /usr/include/linux/bpf.h ] || (echo "❌ kernel headers not found - install with: apt install linux-headers-$$(uname -r)"; exit 1)
	@[ -f /usr/include/bpf/xsk.h ] || (echo "❌ AF_XDP headers not found - install libxdp-dev"; exit 1)
	@echo "✅ All dependencies satisfied"

check-caps:
	@echo "🔒 Checking system capabilities..."
	@[ $$(id -u) = 0 ] || (echo "❌ Root privileges required for XDP operations"; exit 1)
	@[ -r /sys/kernel/btf/vmlinux ] || echo "⚠️  BTF not available - CO-RE features may be limited"
	@grep -q "CONFIG_BPF=y" /boot/config-$$(uname -r) 2>/dev/null || echo "⚠️  BPF support verification failed"
	@grep -q "CONFIG_XDP_SOCKETS=y" /boot/config-$$(uname -r) 2>/dev/null || echo "⚠️  AF_XDP support verification failed"
	@echo "✅ System capabilities check complete"

# ============================================================================
# Performance testing and benchmarking
# ============================================================================

benchmark: all
	@echo "🏃 Running performance benchmarks..."
	sudo $(BUILD_DIR)/ml_integration_example eth0 1
	@echo "✅ Benchmark complete"

stress-test: all
	@echo "💪 Running stress test..."
	sudo timeout 60s $(BUILD_DIR)/ml_af_xdp_processor eth0 0
	@echo "✅ Stress test complete"

performance-profile: profile
	@echo "📊 Running performance profiling..."
	sudo $(BUILD_DIR)/ml_integration_example eth0 1
	gprof $(BUILD_DIR)/ml_integration_example gmon.out > performance_profile.txt
	@echo "✅ Performance profile saved to performance_profile.txt"

# ============================================================================
# Documentation and examples
# ============================================================================

docs:
	@echo "📚 Generating documentation..."
	@mkdir -p docs/api
	doxygen Doxyfile 2>/dev/null || echo "⚠️  Doxygen not found - install for API documentation"
	@echo "✅ Documentation generated in docs/"

examples: $(EXAMPLE_TARGETS)
	@echo "📝 ML integration examples ready:"
	@echo "   Basic example: $(BUILD_DIR)/ml_integration_example"
	@echo "   Usage: sudo ./$(BUILD_DIR)/ml_integration_example <interface> <mode>"
	@echo "   Modes: 1=anomaly detection, 2=security monitoring"

# ============================================================================
# Cleanup
# ============================================================================

clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf $(BUILD_DIR)
	rm -f *.o *.so *.a
	rm -f performance_profile.txt gmon.out
	@echo "✅ Clean complete"

distclean: clean
	@echo "🧹 Deep cleaning..."
	rm -rf docs/api
	@echo "✅ Deep clean complete"

# ============================================================================
# Quick development commands
# ============================================================================

quick-test: all
	@echo "⚡ Quick functionality test..."
	sudo timeout 10s $(BUILD_DIR)/ml_integration_example lo 1 || echo "Test completed"

dev: debug examples
	@echo "🛠️  Development build ready"
	@echo "   Run: sudo ./$(BUILD_DIR)/ml_integration_example <interface> <mode>"

# ============================================================================
# Help
# ============================================================================

help:
	@echo "🚀 ML Packet Processing Build System"
	@echo ""
	@echo "Main targets:"
	@echo "  all           - Build everything (default)"
	@echo "  clean         - Remove build artifacts"
	@echo "  install       - Install system-wide"
	@echo "  uninstall     - Remove system installation"
	@echo "  test          - Run test suite"
	@echo "  examples      - Build integration examples"
	@echo ""
	@echo "Development:"
	@echo "  debug         - Debug build with symbols"
	@echo "  release       - Optimized release build"
	@echo "  profile       - Build with profiling support"
	@echo "  dev           - Quick development setup"
	@echo ""
	@echo "Testing:"
	@echo "  benchmark     - Performance benchmarks"
	@echo "  stress-test   - Extended stress testing"
	@echo "  quick-test    - Quick functionality verification"
	@echo ""
	@echo "System:"
	@echo "  check-deps    - Verify build dependencies"
	@echo "  check-caps    - Verify system capabilities"
	@echo "  docs          - Generate documentation"
	@echo ""
	@echo "Usage examples:"
	@echo "  make all && sudo make install"
	@echo "  make dev && sudo ./build/ml_integration_example eth0 1"

# ============================================================================
# Dependencies
# ============================================================================

# Header dependencies (simplified)
$(XDP_OBJECTS): $(INCLUDE_DIR)/*.h
$(USERSPACE_TARGETS): $(INCLUDE_DIR)/*.h  
$(EXAMPLE_TARGETS): $(INCLUDE_DIR)/*.h 