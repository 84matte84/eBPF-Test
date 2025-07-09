# eBPF-Test Two-Machine Testing System

**Production-ready testing framework for authentic XDP performance validation**

## 🎯 Overview

The two-machine testing system provides realistic network performance validation for eBPF/XDP packet processing. By separating traffic generation from XDP testing, it eliminates measurement bias and provides authentic network conditions that reflect real-world deployment scenarios.

## 🏗️ Architecture

```
┌─────────────────────┐         LAN          ┌─────────────────────┐
│    src_machine      │◄──────────────────►│    dst_machine      │
│                     │                     │                     │
│ • Traffic Generator │                     │ • XDP Program       │
│ • Test Coordinator  │                     │ • Performance Mon   │
│ • Cross-platform    │                     │ • Results Collector │
│   (Linux/Mac)       │                     │   (Linux only)      │
└─────────────────────┘                     └─────────────────────┘
```

### Key Benefits

- **Realistic Testing**: Actual network conditions with real NICs
- **Measurement Accuracy**: Eliminates single-machine testing bias
- **Scalability Validation**: Tests real 10+ Gbps performance
- **Production Fidelity**: Authentic deployment scenarios

## 📋 System Requirements

### src_machine (Traffic Generator)
- **OS**: Linux or macOS
- **Python**: ≥ 3.8
- **Memory**: ≥ 1GB RAM
- **Network**: LAN connectivity to dst_machine
- **Dependencies**: PyYAML, requests

### dst_machine (XDP Testing)
- **OS**: Linux (Ubuntu 22.04+ recommended)
- **Kernel**: ≥ 5.10 with XDP support
- **Memory**: ≥ 2GB RAM
- **Network**: NIC with XDP support (Intel X520/X540 or similar)
- **Privileges**: Root access for XDP operations
- **Dependencies**: clang, libbpf, bpftool, psutil

## 🚀 Quick Start

### 1. Setup dst_machine (Linux)

```bash
# On the destination machine (Linux)
cd eBPF-Test/scripts/two_machine

# Install Python dependencies
pip3 install pyyaml requests psutil

# Update configuration
sudo nano config.yaml

# Update these fields:
# network_config.dst_machine.ip: "192.168.1.101"  # Actual IP
# network_config.dst_machine.interface: "enp5s0"   # Actual interface

# Check system requirements
sudo python3 dst_machine.py --config config.yaml --check-only

# Start destination machine coordinator
sudo python3 dst_machine.py --config config.yaml
```

### 2. Setup src_machine (Linux/Mac)

```bash
# On the source machine (Linux or macOS)
cd eBPF-Test/scripts/two_machine

# Install Python dependencies
pip3 install pyyaml requests

# Update configuration
nano config.yaml

# Update these fields:
# network_config.src_machine.ip: "192.168.1.100"   # Actual IP
# network_config.dst_machine.ip: "192.168.1.101"   # dst_machine IP

# Start source machine traffic generator
python3 src_machine.py --config config.yaml
```

### 3. Run Test

The test will start automatically once both machines are running and coordinated.

## 📝 Configuration

### Basic Configuration (`config.yaml`)

```yaml
# Test parameters
test_config:
  duration: 60          # Test duration in seconds
  
# Traffic generation
traffic_config:
  packet_rate: 10000    # Packets per second
  packet_size: 1500     # Packet size in bytes
  flows: 4             # Number of concurrent flows
  threads: 2           # Traffic generation threads

# Network setup
network_config:
  src_machine:
    ip: "192.168.1.100"          # UPDATE: Actual src_machine IP
    control_port: 8080
  dst_machine:
    ip: "192.168.1.101"          # UPDATE: Actual dst_machine IP
    interface: "enp5s0"          # UPDATE: Actual interface name
    control_port: 8080
```

### Using Presets

```bash
# Quick test (30 seconds, 1K pps)
python3 src_machine.py --config config.yaml --preset quick_test

# Performance test (120 seconds, 50K pps)
python3 src_machine.py --config config.yaml --preset performance_test

# Stress test (300 seconds, 100K pps)
python3 src_machine.py --config config.yaml --preset stress_test
```

### Command Line Overrides

```bash
# Override destination IP
python3 src_machine.py --config config.yaml --dst-ip 192.168.1.101

# Override packet rate and duration
python3 src_machine.py --config config.yaml --rate 50000 --duration 120

# Standalone mode (no coordination)
python3 src_machine.py --config config.yaml --no-coordination

# Verbose output
python3 src_machine.py --config config.yaml --verbose
```

## 🔄 Usage Scenarios

### Scenario 1: XDP Performance Validation

Test XDP program performance under realistic network load:

```bash
# dst_machine
sudo python3 dst_machine.py --config config.yaml

# src_machine
python3 src_machine.py --config config.yaml --preset performance_test
```

### Scenario 2: Baseline vs XDP Comparison

Compare baseline userspace vs XDP performance:

```bash
# Run baseline test first
sudo python3 dst_machine.py --config config.yaml --mode baseline
python3 src_machine.py --config config.yaml --preset performance_test

# Then run XDP test
sudo python3 dst_machine.py --config config.yaml --mode xdp
python3 src_machine.py --config config.yaml --preset performance_test
```

### Scenario 3: Scalability Testing

Test performance across different packet rates:

```bash
# Test at different rates
for rate in 1000 5000 10000 50000 100000; do
  echo "Testing at ${rate} pps..."
  python3 src_machine.py --config config.yaml --rate $rate --duration 60
  sleep 10  # Cool down between tests
done
```

## 📊 Results and Analysis

### Real-time Monitoring

Monitor test progress in real-time:

```bash
# Check dst_machine status
curl http://192.168.1.101:8080/status

# Get real-time metrics
curl http://192.168.1.101:8080/metrics

# Check src_machine status
curl http://192.168.1.100:8080/status
```

### Results Location

Test results are automatically saved to:
```
results/two_machine/test_YYYYMMDD_HHMMSS_TestName/
├── results.json          # Comprehensive results
├── results.csv           # CSV format for analysis
├── results.md           # Markdown report
└── raw_data/            # Raw performance data
```

### Key Metrics

**Traffic Generation (src_machine)**:
- Packets sent per second (actual vs target)
- Traffic generation efficiency
- Network throughput (Mbps)
- Multi-flow distribution

**XDP Performance (dst_machine)**:
- CPU usage (overall and per-core)
- Memory utilization
- Network interface statistics
- XDP program statistics (packets processed, latency)

## 🛠️ Advanced Usage

### Custom Traffic Patterns

Create custom traffic patterns by modifying `config.yaml`:

```yaml
traffic_config:
  patterns:
    - name: "burst_pattern"
      type: "burst"
      burst_rate: 50000
      burst_duration: 1
      inter_burst_gap: 2
```

### Network Discovery

Enable automatic network discovery:

```yaml
network_config:
  discovery:
    enabled: true
    method: "mdns"
    timeout: 10
```

### Performance Monitoring

Configure detailed monitoring:

```yaml
monitoring_config:
  sample_rate: 0.5  # 500ms sampling
  metrics:
    - "cpu_usage"
    - "memory_usage"
    - "network_stats"
    - "xdp_stats"
  real_time:
    enabled: true
    update_interval: 1.0
```

## 🔧 Troubleshooting

### Common Issues

**Connection refused between machines**:
```bash
# Check network connectivity
ping 192.168.1.101

# Check firewall
sudo ufw status
sudo iptables -L

# Check if coordination server is running
ss -tlnp | grep 8080
```

**XDP program fails to load**:
```bash
# Check interface status
ip link show enp5s0

# Check kernel support
lsmod | grep xdp
dmesg | grep -i xdp

# Check BPF program
sudo bpftool prog list
```

**Permission denied**:
```bash
# dst_machine requires root for XDP
sudo python3 dst_machine.py --config config.yaml

# Check capabilities
sudo python3 dst_machine.py --config config.yaml --check-only
```

**Traffic generation performance issues**:
```bash
# Reduce thread count or packet rate
python3 src_machine.py --config config.yaml --rate 1000

# Check system resources
htop
netstat -i
```

### Debug Mode

Enable verbose debugging:

```bash
# Both machines
python3 src_machine.py --config config.yaml --verbose
sudo python3 dst_machine.py --config config.yaml --verbose
```

### Log Files

Check log files for detailed information:
```bash
# Default log locations
tail -f two_machine_test.log
tail -f src_machine.log
tail -f dst_machine.log
```

## 🧪 Testing Validation

### Health Checks

Verify system health before testing:

```bash
# dst_machine health check
curl http://192.168.1.101:8080/health

# src_machine health check
curl http://192.168.1.100:8080/health
```

### Configuration Validation

Validate configuration without running tests:

```bash
# Dry run mode
python3 src_machine.py --config config.yaml --dry-run

# Check-only mode
sudo python3 dst_machine.py --config config.yaml --check-only
```

## 📈 Performance Expectations

### Expected Results

Based on Phase 3 validation, expect:

- **CPU Efficiency**: 5-100× improvement with XDP vs baseline
- **Scalability**: Linear performance up to NIC limits
- **Latency**: Microsecond-scale processing under load
- **Throughput**: 10+ Gbps sustainable with proper hardware

### Benchmark Targets

| Metric | Baseline | XDP | Improvement |
|--------|----------|-----|-------------|
| CPU Usage | 8%+ | 0.01%+ | 800×+ |
| Throughput | Rate-limited | Wire-speed | Variable |
| Latency | Variable | Consistent | 80%+ reduction |

## 🤝 Contributing

### Adding Features

1. Update configuration schema in `config.yaml`
2. Implement in appropriate module (`src_machine.py` or `dst_machine.py`)
3. Add coordination support in `coordination.py`
4. Update documentation

### Code Quality

- Follow existing code style and patterns
- Add comprehensive error handling
- Include logging for debugging
- Write clear documentation
- Test on both Linux and macOS (src_machine)

## 📄 File Reference

```
scripts/two_machine/
├── README.md              # This documentation
├── ARCHITECTURE.md        # Detailed architecture
├── config.yaml           # Configuration template
├── coordination.py        # Machine coordination
├── src_machine.py         # Traffic generator
└── dst_machine.py         # XDP testing coordinator
```

## 🔗 Related Documentation

- [Main Project README](../../README.md)
- [Architecture Guide](../../ARCHITECTURE.md)
- [Phase 3 Results](../../docs/phase3/PHASE3_ANALYSIS_REPORT.md)
- [Development Guide](../../docs/development/)

---

**Note**: This system replaces the legacy single-machine testing approach with realistic two-machine LAN testing for authentic XDP performance validation. 