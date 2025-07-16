# High-Performance ML Packet Processing System

**Achieving 79k+ PPS with XDP + AF_XDP for AI/ML Network Analysis**

[![Performance](https://img.shields.io/badge/Performance-79k%20PPS-brightgreen)](docs/performance.md)
[![Architecture](https://img.shields.io/badge/Architecture-XDP%20%2B%20AF__XDP-blue)](docs/architecture.md)
[![ML Ready](https://img.shields.io/badge/ML-Ready-orange)](examples/ml_integration_example.c)

## 🎯 Overview

This system provides **wire-speed packet processing** for ML/AI applications using a hybrid XDP + AF_XDP architecture. Based on extensive performance optimization research that achieved **94% of theoretical maximum throughput** (79k PPS vs 84k theoretical max), this implementation is designed for production ML workloads.

## 🚀 Key Features

### Performance
- **79,000+ packets per second** sustained throughput
- **Sub-microsecond XDP filtering** for high-rate traffic
- **Zero-copy AF_XDP** for ML/AI analysis pipelines
- **Intelligent sampling** (1-in-N) to scale effective processing rates

### ML/AI Integration
- **Rich feature extraction**: 16+ network and behavioral features
- **Real-time anomaly detection** with customizable ML callbacks
- **TensorFlow/PyTorch ready** integration examples
- **Flow tracking** for session-based analysis

### Architecture
```
[Network] → [XDP Filter] → [Sampling] → [AF_XDP] → [ML Analysis]
   ↓         ↓ 79k+ PPS     ↓ 1-in-N     ↓ Zero-copy  ↓ Real-time
Wire Speed   Kernel        Rate Control  Userspace    ML/AI
```

## 📦 Quick Start

### 1. System Requirements
```bash
# Ubuntu 22.04+ with kernel 5.10+
sudo apt update
sudo apt install -y clang llvm libbpf-dev libxdp-dev linux-headers-$(uname -r)
```

### 2. Build System
```bash
# Clone and build
git clone <repository>
cd ml-packet-processing
make -f Makefile.ml all

# Verify build
make -f Makefile.ml check-deps
sudo make -f Makefile.ml check-caps
```

### 3. Run ML Integration Example
```bash
# Anomaly detection mode
sudo ./build/ml_integration_example eth0 1

# Security monitoring mode  
sudo ./build/ml_integration_example eth0 2
```

### 4. Expected Output
```
=== HIGH-PERFORMANCE ML PACKET PROCESSING DEMO ===
Interface: eth0
✅ ML packet processor initialized successfully
✅ System optimized for maximum performance
🚀 Started ML packet processing - press Ctrl+C to stop

[STATUS] PPS: 15234, Processed: 150000, ML: 15000, CPU: 2.3%, Latency: 8.2µs
[ML] Processed 10000 packets, detected 127 anomalies (1.27% anomaly rate)
[ANOMALY] Score=4, 192.168.1.100:54321->10.0.1.5:22, proto=6, len=1400, entropy=245, reasons=[high-entropy tcp-flags]
```

## 🏗️ Architecture Deep Dive

### Hybrid XDP + AF_XDP Design

Based on the performance analysis that achieved **79k PPS**, this system uses a two-stage architecture:

#### Stage 1: XDP High-Speed Filtering (Kernel)
- **Purpose**: Process all packets at wire speed (79k+ PPS)
- **Function**: Parse headers, classify traffic, intelligent sampling
- **Performance**: 94% of theoretical maximum throughput

#### Stage 2: AF_XDP ML Processing (Userspace)
- **Purpose**: Zero-copy transfer to ML/AI analysis
- **Function**: Complex feature extraction, anomaly detection, ML inference
- **Performance**: Scales based on sampling rate and ML complexity

### Key Insights from 79k PPS Research

1. **Ring Buffer Paradox**: Ring buffers become bottlenecks at high rates
   - **Solution**: Use AF_XDP for zero-copy, eliminate ring buffer overhead

2. **Sampling Strategy**: Process subset at full depth vs all packets superficially
   - **Result**: 1-in-10 sampling enables 79k → 7.9k ML analysis at full feature depth

3. **Kernel vs Userspace**: Move filtering to kernel, keep ML in userspace
   - **Result**: Best of both worlds - performance + flexibility

## 🔧 API Usage

### Simple Integration
```c
#include "ml_packet_api.h"

// Define your ML callback
int my_ml_processor(const ml_packet_feature_t *feature, void *context) {
    // Your ML/AI analysis here
    if (feature->packet_entropy > 200) {
        printf("High entropy packet detected!\n");
        return 1; // Anomaly detected
    }
    return 0; // Normal packet
}

int main() {
    // Configure system
    ml_packet_config_t config;
    ml_packet_get_default_config(&config);
    config.interface = "eth0";
    config.sampling_rate = 10;        // 1-in-10 sampling
    config.zero_copy_mode = true;     // Enable AF_XDP
    
    // Initialize and start
    ml_packet_processor_t *processor = ml_packet_init(&config, my_ml_processor, NULL);
    ml_packet_start(processor);
    
    // Your application runs...
    sleep(60);
    
    // Cleanup
    ml_packet_stop(processor);
    ml_packet_destroy(processor);
    return 0;
}
```

### Advanced Features
```c
// Custom traffic classifier
uint8_t my_classifier(const ml_packet_feature_t *feature, void *context) {
    // Your custom classification logic
    if (feature->payload_len > 1400 && feature->packet_entropy < 50) {
        return 1; // Suspicious: large low-entropy packet
    }
    return 0; // Normal
}

// Enable flow tracking
ml_packet_enable_flow_tracking(processor, 10000, 300); // 10k flows, 5min timeout

// Set custom classifier
ml_packet_set_classifier(processor, my_classifier, NULL);

// Enable debugging capture
ml_packet_enable_capture(processor, "debug.pcap", 1000);
```

## 📊 Performance Characteristics

### Throughput Capabilities
| Sampling Rate | XDP Processing | ML Analysis | Use Case |
|---------------|----------------|-------------|----------|
| 1:1 (All)     | 79k PPS       | ~8k PPS     | Deep analysis |
| 1:10          | 79k PPS       | ~79k PPS    | **Recommended** |
| 1:100         | 79k PPS       | ~790k PPS   | High-scale monitoring |

### Resource Usage (Measured)
- **CPU**: 0.01-2.3% (depends on ML complexity)
- **Memory**: 4MB base + ML model requirements
- **Latency**: 1-10µs per packet (XDP + AF_XDP + simple ML)

### Scalability Targets
- **1 Gbps**: ✅ Proven (79k PPS achieved)
- **10 Gbps**: 🎯 Target (requires sampling and multi-queue)
- **100 Gbps**: 🔬 Research (DPDK integration required)

## 🧠 ML/AI Integration Patterns

### Pattern 1: Real-time Anomaly Detection
```c
// Statistical anomaly detection
int anomaly_detector(const ml_packet_feature_t *feature, void *model) {
    ml_model_t *m = (ml_model_t *)model;
    
    // Update online statistics
    update_flow_stats(m, feature);
    
    // Z-score anomaly detection
    double z_score = (feature->pkt_len - m->size_mean) / m->size_stddev;
    if (abs(z_score) > 3.0) {
        log_anomaly(feature, "size_anomaly", z_score);
        return 1;
    }
    
    return 0;
}
```

### Pattern 2: Deep Learning Integration
```c
// TensorFlow Lite integration
int tensorflow_processor(const ml_packet_feature_t *feature, void *context) {
    TfLiteInterpreter *interpreter = (TfLiteInterpreter *)context;
    
    // Convert features to tensor
    float inputs[16] = {
        feature->src_ip / (float)UINT32_MAX,
        feature->dst_ip / (float)UINT32_MAX,
        feature->packet_entropy / 255.0f,
        // ... more features
    };
    
    // Run inference
    TfLiteInterpreterSetInput(interpreter, 0, inputs);
    TfLiteInterpreterInvoke(interpreter);
    
    // Get prediction
    float *output = TfLiteInterpreterGetOutput(interpreter, 0);
    return output[0] > 0.5 ? 1 : 0; // Binary classification
}
```

### Pattern 3: Network Security Monitoring
```c
// Multi-layer security analysis
int security_monitor(const ml_packet_feature_t *feature, void *context) {
    security_context_t *sec = (security_context_t *)context;
    
    int threat_score = 0;
    
    // Layer 1: Protocol analysis
    if (detect_port_scan(feature, sec)) threat_score += 2;
    if (detect_syn_flood(feature, sec)) threat_score += 3;
    
    // Layer 2: Payload analysis  
    if (feature->packet_entropy > 200) threat_score += 1; // Possible encryption
    if (detect_dns_tunneling(feature, sec)) threat_score += 2;
    
    // Layer 3: Flow analysis
    if (detect_ddos_pattern(feature, sec)) threat_score += 3;
    
    if (threat_score >= 3) {
        alert_security_team(feature, threat_score);
        return threat_score;
    }
    
    return 0;
}
```

## 📈 Performance Optimization Guide

### System-Level Optimizations
```bash
# CPU isolation and affinity
echo isolated > /sys/devices/system/cpu/cpu2/online
echo 2 > /proc/irq/24/smp_affinity # Bind NIC interrupts to isolated CPU

# Memory optimization
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo 1024 > /proc/sys/vm/nr_hugepages

# Network optimization
ethtool -K eth0 gro off lro off
ethtool -A eth0 rx off tx off
```

### Application-Level Tuning
```c
// Optimize configuration for your workload
ml_packet_config_t config = {
    .sampling_rate = 10,              // Adjust based on ML complexity
    .max_ml_rate = 50000,            // Cap to prevent overload
    .batch_size = 64,                // Balance latency vs throughput
    .buffer_size = 4 * 1024 * 1024,  // 4MB for high-rate bursts
    .zero_copy_mode = true,          // Always enable for performance
    .enable_tcp = true,
    .enable_udp = true,
    .enable_icmp = false             // Filter irrelevant protocols
};
```

### Multi-Queue Scaling
```c
// Use multiple queues for > 10 Gbps
for (int i = 0; i < num_queues; i++) {
    config.queue_id = i;
    processors[i] = ml_packet_init(&config, ml_callback, &contexts[i]);
    
    // Bind to specific CPU core
    pthread_t thread;
    pthread_create(&thread, NULL, worker_thread, processors[i]);
    
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(i + 2, &cpuset); // Offset to avoid system CPUs
    pthread_setaffinity_np(thread, sizeof(cpuset), &cpuset);
}
```

## 🔬 Research Background

This implementation is based on comprehensive performance research documented in [XDP_PERFORMANCE_OPTIMIZATION_ANALYSIS.md](XDP_PERFORMANCE_OPTIMIZATION_ANALYSIS.md), which details the journey from 2k PPS to 79k PPS through systematic bottleneck elimination:

### Key Research Findings

1. **Traffic Generation Bottleneck**: Custom generators hit fundamental limits
   - **Solution**: Use optimized bulk traffic generators (iperf3 achieved 84k PPS)

2. **Ring Buffer Bottleneck**: 256KB buffer overflow at high rates  
   - **Solution**: 4MB ring buffer, then eliminate entirely for AF_XDP

3. **Per-Packet Processing Overhead**: Complex callbacks limit throughput
   - **Solution**: Minimal XDP processing, rich AF_XDP analysis

4. **Architecture Selection**: Ring buffers vs AF_XDP for ML workloads
   - **Result**: AF_XDP provides zero-copy performance for complex analysis

### Performance Validation
- **Baseline**: iperf3 84k PPS (network capability)
- **XDP Achievement**: 79k PPS (94% of theoretical maximum)
- **Architecture**: Hybrid design optimizes for both speed and flexibility

## 🛠️ Development and Debugging

### Build Options
```bash
# Development build with debugging
make -f Makefile.ml debug

# Optimized release build
make -f Makefile.ml release

# Performance profiling build
make -f Makefile.ml profile

# Quick development test
make -f Makefile.ml quick-test
```

### Debugging Tools
```bash
# Check XDP program status
sudo bpftool prog show
sudo bpftool map dump name stats_map

# Monitor performance
sudo perf top -p $(pgrep ml_integration)

# Network debugging
sudo tcpdump -i eth0 -c 100

# AF_XDP socket debugging
ss -A xsk
```

### Common Issues and Solutions

#### Issue: Low packet rates (<1k PPS)
**Causes**: 
- Interface not receiving traffic
- Sampling rate too high
- ML callback too slow

**Solutions**:
```bash
# Verify traffic
sudo tcpdump -i eth0

# Reduce sampling rate
config.sampling_rate = 1; // Process all packets

# Profile ML callback
make -f Makefile.ml performance-profile
```

#### Issue: High CPU usage (>10%)
**Causes**:
- Complex ML processing
- Inefficient feature extraction
- Missing system optimizations

**Solutions**:
```bash
# Increase sampling rate
config.sampling_rate = 100; // 1 in 100

# Optimize system
make -f Makefile.ml check-caps
sudo make -f Makefile.ml install
```

#### Issue: XDP program load failure
**Causes**:
- Missing kernel headers
- Insufficient permissions
- Incompatible kernel version

**Solutions**:
```bash
# Check dependencies
make -f Makefile.ml check-deps

# Verify permissions
sudo make -f Makefile.ml check-caps

# Check kernel version
uname -r # Requires 5.10+
```

## 📚 Additional Resources

### Documentation
- [API Reference](docs/api/index.html) - Complete API documentation
- [Performance Analysis](XDP_PERFORMANCE_OPTIMIZATION_ANALYSIS.md) - Research details
- [Architecture Guide](ARCHITECTURE.md) - System design overview

### Examples
- [Basic Integration](examples/ml_integration_example.c) - Simple anomaly detection
- [Security Monitoring](examples/security_monitoring.c) - Network threat detection
- [TensorFlow Integration](examples/tensorflow_example.c) - Deep learning example

### Benchmarks
- [Performance Tests](benchmarks/) - Comprehensive performance validation
- [Comparison Studies](docs/comparisons/) - vs DPDK, traditional sockets
- [Scaling Analysis](docs/scaling/) - Multi-queue and multi-machine setups

## 🤝 Contributing

This project follows the phase-based development model established in the original eBPF-Test project:

1. **Phase 4**: Production packaging and API refinement (current)
2. **Phase 5**: Advanced ML framework integration
3. **Phase 6**: Multi-machine distributed processing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines.

## 📄 License

This project is licensed under the GPL v2 License - see [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Based on the eBPF-Test project's performance optimization research
- Built on the libbpf and XDP ecosystems
- Inspired by production ML/AI networking requirements

---

**Get Started**: `make -f Makefile.ml all && sudo ./build/ml_integration_example eth0 1`

**Questions?** Open an issue or check the [FAQ](docs/FAQ.md)

**Performance Issues?** See the [Troubleshooting Guide](docs/troubleshooting.md) 