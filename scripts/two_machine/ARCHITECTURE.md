# Two-Machine Testing Architecture

**High-quality, production-ready testing framework for eBPF-Test XDP performance validation**

## 🎯 Overview

The two-machine testing system provides realistic network performance validation by separating traffic generation from eBPF/XDP testing, eliminating measurement bias and providing authentic network conditions.

## 🏗️ Architecture Design

```
┌─────────────────────┐         LAN          ┌─────────────────────┐
│    src_machine      │◄──────────────────►│    dst_machine      │
│                     │                     │                     │
│ • Traffic Generator │                     │ • XDP Program       │
│ • Test Coordinator  │                     │ • Performance Mon   │
│ • Cross-platform    │                     │ • Results Collector │
│   (Linux/Mac/Win)   │                     │   (Linux only)      │
└─────────────────────┘                     └─────────────────────┘
```

## 📦 Component Design

### src_machine Components

#### 1. `src_machine.py` - Main Traffic Generator
**Purpose**: Cross-platform UDP traffic generation with real-time control
**Features**:
- Multi-threaded traffic generation
- Configurable packet rates, sizes, and flows
- Real-time performance monitoring
- Coordination with dst_machine
- Cross-platform compatibility (Linux, macOS, Windows)

#### 2. `coordination.py` - Machine Coordination Protocol
**Purpose**: REST API-based communication between machines
**Features**:
- Test synchronization
- Configuration exchange
- Status monitoring
- Results collection

#### 3. `config.yaml` - Test Configuration
**Purpose**: Centralized configuration management
**Features**:
- Test parameters (rate, duration, flows)
- Network configuration (IPs, ports)
- Machine roles and capabilities
- Performance thresholds

### dst_machine Components

#### 1. `dst_machine.py` - XDP Testing Coordinator
**Purpose**: Orchestrate XDP testing and performance monitoring
**Features**:
- XDP program management (load/attach/detach)
- System resource monitoring
- Results collection and analysis
- Coordination with src_machine

#### 2. Performance Monitoring
**Purpose**: Comprehensive system metrics during testing
**Features**:
- CPU usage per core
- Memory utilization
- Network interface statistics
- XDP program statistics

## 🔄 Workflow Design

### 1. Setup Phase
```
1. Configure test parameters in config.yaml
2. Start dst_machine coordinator
3. Start src_machine traffic generator
4. Establish coordination connection
5. Exchange configuration and capabilities
```

### 2. Test Execution Phase
```
1. dst_machine loads and attaches XDP program
2. Coordination handshake (ready signals)
3. src_machine begins traffic generation
4. Real-time monitoring on both machines
5. Performance data collection
6. Test completion synchronization
```

### 3. Results Phase
```
1. src_machine stops traffic generation
2. dst_machine collects final statistics
3. Results aggregation and analysis
4. Report generation
5. Cleanup and resource release
```

## 🛡️ Quality Attributes

### Reliability
- **Error Handling**: Comprehensive exception handling with graceful degradation
- **Recovery**: Automatic retry mechanisms for network issues
- **Validation**: Input validation and sanity checks
- **Cleanup**: Guaranteed resource cleanup on exit

### Performance
- **Efficiency**: Minimal overhead from coordination protocol
- **Scalability**: Support for high packet rates (10+ Gbps)
- **Monitoring**: Real-time performance feedback
- **Optimization**: Optimized packet generation loops

### Maintainability
- **Modularity**: Clean separation of concerns
- **Configuration**: External configuration management
- **Logging**: Structured logging with configurable levels
- **Documentation**: Comprehensive inline documentation

### Usability
- **Setup**: Simple configuration and startup process
- **Cross-platform**: Works on Linux and macOS
- **Feedback**: Clear status reporting and progress indicators
- **Debugging**: Verbose modes for troubleshooting

## 🔧 Technical Specifications

### Communication Protocol
- **Transport**: HTTP REST API over TCP
- **Ports**: 8080 (coordination), 12345+ (test traffic)
- **Format**: JSON for control messages
- **Authentication**: Optional API keys for security

### Traffic Generation
- **Transport**: UDP over Ethernet
- **Rates**: 1 pps to 10M+ pps configurable
- **Patterns**: Configurable payload sizes and content
- **Flows**: Multiple concurrent flows with different parameters

### Performance Monitoring
- **Metrics**: CPU, memory, network, XDP statistics
- **Frequency**: Configurable sampling rates
- **Storage**: Time-series data for analysis
- **Export**: CSV, JSON, and real-time streaming

### Configuration Schema
```yaml
test_config:
  duration: 60
  packet_rate: 10000
  packet_size: 1500
  flows: 4
  
network_config:
  src_machine:
    ip: "192.168.1.100"
    control_port: 8080
  dst_machine:
    ip: "192.168.1.101"
    interface: "enp5s0"
    traffic_ports: [12345, 12346, 12347, 12348]

monitoring_config:
  sample_rate: 1.0  # seconds
  metrics: ["cpu", "memory", "network", "xdp"]
  
results_config:
  format: ["json", "csv"]
  real_time: true
```

## 📊 Expected Outcomes

### Performance Validation
- **Realistic Conditions**: Actual network stack and NIC performance
- **Comparative Analysis**: XDP vs baseline under identical conditions
- **Scalability Testing**: Performance across different packet rates
- **Resource Utilization**: CPU and memory efficiency metrics

### Quality Assurance
- **Reproducibility**: Consistent results across test runs
- **Reliability**: Stable operation under sustained load
- **Accuracy**: Precise measurement of performance metrics
- **Coverage**: Comprehensive testing scenarios

## 🚀 Implementation Priority

### Phase 1: Core Infrastructure
1. Basic coordination protocol
2. Simple traffic generation
3. XDP program integration
4. Basic monitoring

### Phase 2: Enhanced Features  
1. Multi-flow traffic patterns
2. Real-time performance monitoring
3. Configuration management
4. Error handling and recovery

### Phase 3: Production Polish
1. Cross-platform compatibility
2. Advanced monitoring and analysis
3. Comprehensive documentation
4. Performance optimization

This architecture ensures high-quality, maintainable code while providing authentic network performance validation for the eBPF-Test project. 