#!/bin/bash

# Phase 3 Comprehensive Benchmark Script
# Orchestrates fair comparison between Baseline and XDP performance

set -e  # Exit on any error

# Configuration
SCRIPT_DIR="$(dirname "$0")"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
RESULTS_DIR="$PROJECT_ROOT/results"

# Default parameters (can be overridden by command line)
INTERFACE="lo"
TEST_DURATION=60
TARGET_PPS=5000
PACKET_SIZE=100
NUM_FLOWS=4
NUM_THREADS=2
VERBOSE=false

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
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

# Print usage information
print_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Phase 3 Comprehensive Benchmark Script
Performs fair comparison between Baseline and XDP under identical conditions.

OPTIONS:
    -i, --interface IFACE    Network interface (default: lo)
    -d, --duration SEC       Test duration per mode (default: 60)
    -r, --rate PPS           Target packets per second (default: 5000)
    -s, --size BYTES         Packet size (default: 100)
    -f, --flows NUM          Number of UDP flows (default: 4)
    -t, --threads NUM        Number of traffic threads (default: 2)
    -v, --verbose            Verbose output
    -h, --help               Show this help

EXAMPLES:
    $0                                    # Quick test with defaults
    $0 -d 120 -r 10000 -v               # Longer high-rate test
    $0 -i enp5s0 -d 30 -r 1000          # Test on real interface
    
The script will:
1. Build all required components
2. Run baseline performance test
3. Run XDP performance test  
4. Generate side-by-side comparison report
5. Save all results and logs

EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -i|--interface)
                INTERFACE="$2"
                shift 2
                ;;
            -d|--duration)
                TEST_DURATION="$2"
                shift 2
                ;;
            -r|--rate)
                TARGET_PPS="$2"
                shift 2
                ;;
            -s|--size)
                PACKET_SIZE="$2"
                shift 2
                ;;
            -f|--flows)
                NUM_FLOWS="$2"
                shift 2
                ;;
            -t|--threads)
                NUM_THREADS="$2"
                shift 2
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done
}

# Setup directories and logging
setup_environment() {
    log_info "Setting up Phase 3 benchmark environment..."
    
    # Create necessary directories
    mkdir -p "$LOG_DIR" "$RESULTS_DIR"
    
    # Create timestamped subdirectory for this run
    TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
    RUN_DIR="$RESULTS_DIR/phase3_$TIMESTAMP"
    mkdir -p "$RUN_DIR"
    
    log_info "Results will be saved to: $RUN_DIR"
    
    # Check if we're in the right directory
    if [[ ! -f "$PROJECT_ROOT/Makefile" ]]; then
        log_error "Not in eBPF-Test project directory"
        exit 1
    fi
    
    # Check if required tools are available
    if ! command -v python3 &> /dev/null; then
        log_error "python3 is required but not installed"
        exit 1
    fi
    
    cd "$PROJECT_ROOT"
}

# Build all components
build_components() {
    log_info "Building all components..."
    
    if make all > "$RUN_DIR/build.log" 2>&1; then
        log_success "All components built successfully"
    else
        log_error "Build failed. Check $RUN_DIR/build.log"
        exit 1
    fi
    
    # Verify binaries exist
    local required_bins=(
        "build/performance_test"
        "build/xdp_loader"
        "build/xdp_preproc.o"
    )
    
    for bin in "${required_bins[@]}"; do
        if [[ ! -f "$bin" ]]; then
            log_error "Required binary not found: $bin"
            exit 1
        fi
    done
    
    log_success "All required binaries verified"
}

# Start traffic generator in background
start_traffic_generator() {
    local test_name="$1"
    local traffic_log="$RUN_DIR/traffic_${test_name}.log"
    
    log_info "Starting traffic generator for $test_name test..."
    
    # Calculate total duration (test + some buffer)
    local total_duration=$((TEST_DURATION + 10))
    
    python3 scripts/high_rate_traffic.py \
        --target 127.0.0.1 \
        --port 12345 \
        --rate "$TARGET_PPS" \
        --duration "$total_duration" \
        --size "$PACKET_SIZE" \
        --flows "$NUM_FLOWS" \
        --threads "$NUM_THREADS" \
        > "$traffic_log" 2>&1 &
    
    TRAFFIC_PID=$!
    
    # Wait a moment for traffic to stabilize
    sleep 3
    
    # Check if traffic generator is still running
    if ! kill -0 $TRAFFIC_PID 2>/dev/null; then
        log_error "Traffic generator failed to start. Check $traffic_log"
        exit 1
    fi
    
    log_success "Traffic generator started (PID: $TRAFFIC_PID)"
}

# Stop traffic generator
stop_traffic_generator() {
    if [[ -n "$TRAFFIC_PID" ]] && kill -0 $TRAFFIC_PID 2>/dev/null; then
        log_info "Stopping traffic generator..."
        kill $TRAFFIC_PID
        wait $TRAFFIC_PID 2>/dev/null || true
        log_success "Traffic generator stopped"
    fi
    TRAFFIC_PID=""
}

# Run baseline performance test
run_baseline_test() {
    log_info "Running BASELINE performance test..."
    
    local baseline_log="$RUN_DIR/baseline_test.log"
    local verbose_flag=""
    
    if [[ "$VERBOSE" == "true" ]]; then
        verbose_flag="--verbose"
    fi
    
    # Start traffic generator
    start_traffic_generator "baseline"
    
    # Run baseline test
    if sudo ./build/performance_test \
        --mode baseline \
        --interface "$INTERFACE" \
        --duration "$TEST_DURATION" \
        --rate "$TARGET_PPS" \
        $verbose_flag \
        > "$baseline_log" 2>&1; then
        
        log_success "Baseline test completed successfully"
    else
        log_error "Baseline test failed. Check $baseline_log"
        stop_traffic_generator
        exit 1
    fi
    
    # Stop traffic generator
    stop_traffic_generator
    
    # Wait a moment between tests
    sleep 5
}

# Run XDP performance test
run_xdp_test() {
    log_info "Running XDP performance test..."
    
    local xdp_log="$RUN_DIR/xdp_test.log"
    local verbose_flag=""
    
    if [[ "$VERBOSE" == "true" ]]; then
        verbose_flag="--verbose"
    fi
    
    # Start traffic generator
    start_traffic_generator "xdp"
    
    # Run XDP test
    if sudo ./build/performance_test \
        --mode xdp \
        --interface "$INTERFACE" \
        --duration "$TEST_DURATION" \
        --rate "$TARGET_PPS" \
        $verbose_flag \
        > "$xdp_log" 2>&1; then
        
        log_success "XDP test completed successfully"
    else
        log_error "XDP test failed. Check $xdp_log"
        stop_traffic_generator
        exit 1
    fi
    
    # Stop traffic generator
    stop_traffic_generator
}

# Generate comparison report
generate_report() {
    log_info "Generating Phase 3 comparison report..."
    
    local report_file="$RUN_DIR/phase3_comparison_report.md"
    
    cat > "$report_file" << EOF
# Phase 3 Performance Comparison Report

**Date**: $(date '+%Y-%m-%d %H:%M:%S')  
**Test Configuration**: Fair comparison under identical conditions

## Test Parameters

| Parameter | Value |
|-----------|-------|
| Interface | $INTERFACE |
| Test Duration | $TEST_DURATION seconds |
| Target PPS | $TARGET_PPS |
| Packet Size | $PACKET_SIZE bytes |
| UDP Flows | $NUM_FLOWS |
| Traffic Threads | $NUM_THREADS |

## Baseline Results

\`\`\`
$(tail -n 50 "$RUN_DIR/baseline_test.log" | grep -A 20 "BASELINE PERFORMANCE RESULTS" || echo "Results not found")
\`\`\`

## XDP Results

\`\`\`
$(tail -n 50 "$RUN_DIR/xdp_test.log" | grep -A 20 "XDP PERFORMANCE RESULTS" || echo "Results not found")
\`\`\`

## Traffic Generation Logs

### Baseline Traffic
\`\`\`
$(tail -n 20 "$RUN_DIR/traffic_baseline.log" || echo "Traffic log not found")
\`\`\`

### XDP Traffic  
\`\`\`
$(tail -n 20 "$RUN_DIR/traffic_xdp.log" || echo "Traffic log not found")
\`\`\`

## Files Generated

- Baseline test: \`baseline_test.log\`
- XDP test: \`xdp_test.log\`
- Baseline traffic: \`traffic_baseline.log\`
- XDP traffic: \`traffic_xdp.log\`
- Build log: \`build.log\`
- This report: \`phase3_comparison_report.md\`

## Analysis

TODO: Add automated performance analysis comparing:
- Throughput (packets/sec)
- Latency (microseconds) 
- CPU usage (%)
- Memory usage (KB)
- Processing efficiency (ns/packet)

EOF

    log_success "Comparison report generated: $report_file"
    
    # Also create a summary for console output
    log_info "=== PHASE 3 BENCHMARK SUMMARY ==="
    log_info "Results saved to: $RUN_DIR"
    log_info "Report: $report_file"
    log_info "View results with: cat $report_file"
}

# Cleanup function
cleanup() {
    log_info "Cleaning up..."
    stop_traffic_generator
    cd "$PROJECT_ROOT"
}

# Set up cleanup trap
trap cleanup EXIT

# Main execution
main() {
    echo "======================================="
    echo "    eBPF-Test Phase 3 Benchmark"
    echo "    Fair Baseline vs XDP Comparison"
    echo "======================================="
    echo
    
    parse_arguments "$@"
    setup_environment
    build_components
    
    log_info "Starting comprehensive benchmark with the following configuration:"
    log_info "  Interface: $INTERFACE"
    log_info "  Duration: $TEST_DURATION seconds per test"
    log_info "  Target PPS: $TARGET_PPS"
    log_info "  Packet size: $PACKET_SIZE bytes"
    log_info "  Flows: $NUM_FLOWS"
    log_info "  Threads: $NUM_THREADS"
    log_info "  Verbose: $VERBOSE"
    echo
    
    # Run tests
    run_baseline_test
    run_xdp_test
    generate_report
    
    log_success "Phase 3 benchmark completed successfully!"
    log_info "Check the results in: $RUN_DIR"
}

# Execute main function with all arguments
main "$@" 