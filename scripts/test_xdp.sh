#!/bin/bash

# XDP Integration Test Script
# Tests XDP packet processing with generated UDP traffic

set -e

INTERFACE=${1:-"lo"}
XDP_PROGRAM="./build/xdp_preproc.o"
XDP_LOADER="./build/xdp_loader"
TEST_DURATION=5
UDP_PORT=8080

echo "=== XDP Integration Test ==="
echo "Interface: $INTERFACE"
echo "Test duration: $TEST_DURATION seconds"
echo "UDP port: $UDP_PORT"
echo ""

# Check if programs exist
if [ ! -f "$XDP_PROGRAM" ]; then
    echo "Error: XDP program not found at $XDP_PROGRAM"
    echo "Run 'make all' first"
    exit 1
fi

if [ ! -f "$XDP_LOADER" ]; then
    echo "Error: XDP loader not found at $XDP_LOADER"
    echo "Run 'make all' first"
    exit 1
fi

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run with sudo"
    echo "Usage: sudo $0 [interface]"
    exit 1
fi

echo "1. Starting UDP test server..."
# Start UDP server in background
nc -u -l -p $UDP_PORT > /dev/null 2>&1 &
UDP_SERVER_PID=$!
sleep 1

echo "2. Loading XDP program..."
# Start XDP loader in background
timeout $TEST_DURATION $XDP_LOADER $INTERFACE $XDP_PROGRAM &
XDP_PID=$!
sleep 2

echo "3. Generating UDP test traffic..."
# Generate UDP packets
for i in {1..10}; do
    echo "Test packet $i - timestamp: $(date +%s.%N)" | nc -u -w1 localhost $UDP_PORT &
    sleep 0.1
done

echo "4. Waiting for test completion..."
wait $XDP_PID 2>/dev/null || true

echo "5. Cleaning up..."
kill $UDP_SERVER_PID 2>/dev/null || true
pkill -f "nc.*$UDP_PORT" 2>/dev/null || true

echo ""
echo "=== Test completed ==="
echo "Check the output above for XDP performance statistics" 