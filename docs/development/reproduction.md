# eBPF-Test Project Reproduction Guide

**For New Machines & AI Agents**  
**Project Status**: Phase 1 Complete (Baseline Established)  
**Target**: Complete reproduction in ~15-20 minutes

## 🎯 Quick Start (TL;DR)

```bash
# 1. Clone/recreate project structure
mkdir eBPF-Test && cd eBPF-Test

# 2. Run automated setup (Ubuntu 24.04+ required)
./scripts/setup_environment.sh

# 3. Build and test baseline
make baseline
sudo timeout 10s ./build/baseline lo &
python3 scripts/generate_udp_traffic.py --preset low --duration 8
```

**Expected Result**: ~800 UDP packets processed, ~0.4µs average latency

---

## 📋 System Requirements

### ✅ Verified Compatible Systems
- **OS**: Ubuntu 24.04.2 LTS (primary tested)
- **Kernel**: ≥6.11.0-29-generic (minimum: ≥5.10)
- **CPU**: x86_64, minimum 4 cores (tested: Intel i7-6700HQ)
- **RAM**: 4GB+ recommended
- **Network**: Any Ethernet interface (enp5s0, eth0, etc.)

### ⚠️ Compatibility Notes
- **Ubuntu 22.04**: Should work (untested)
- **CentOS/RHEL**: Package names differ, manual installation needed
- **Other Distros**: Manual dependency installation required

---

## 🔧 Complete File Structure

```
eBPF-Test/
├── .changelog                    # Version history
├── .dependencies               # System requirements
├── .code_structure             # Architecture mapping  
├── .context                    # Business domain info
├── README.md                   # Project overview
├── Makefile                    # Build system
├── PROJECT_REPRODUCTION.md     # This file
├── SETUP_REPORT.md            # Environment setup details
├── BASELINE_TEST_LOG.md       # Implementation log
├── BASELINE_PERFORMANCE.md    # Performance benchmarks
├── include/
│   └── feature.h              # Shared feature structure
├── benchmarks/
│   └── baseline.c             # Userspace baseline processor
├── scripts/
│   ├── setup_environment.sh   # Automated setup script
│   └── generate_udp_traffic.py # UDP traffic generator
├── src/                       # (Future XDP programs)
└── build/                     # (Generated binaries)
```

---

## 🚀 Step-by-Step Reproduction

### Step 1: Environment Setup

**Option A: Automated (Recommended)**
```bash
chmod +x scripts/setup_environment.sh
./scripts/setup_environment.sh
```

**Option B: Manual Installation**
```bash
# System check
uname -r  # Should be ≥5.10
lsb_release -a  # Should be Ubuntu

# Install dependencies
sudo apt update
sudo apt install -y clang llvm libbpf-dev linux-headers-$(uname -r) build-essential iperf3 netperf

# Verify installations
clang --version  # Should be ≥18.x
pkg-config --modversion libbpf  # Should be ≥1.3.0
bpftool --version  # Should work
```

### Step 2: Build Baseline

```bash
# Check system compatibility
make check-system

# Build baseline processor
make baseline

# Verify build
ls -la build/baseline  # Should exist and be executable
```

### Step 3: Test Baseline

**⚠️ CRITICAL: Never run `sudo command &` - it breaks with password prompts**

**Correct Testing Method:**
```bash
# Terminal 1: Start traffic generator (no sudo needed)
python3 scripts/generate_udp_traffic.py --preset low --duration 15 &

# Terminal 2: Start baseline processor (requires sudo)
sudo timeout 12s ./build/baseline lo

# OR Sequential approach:
python3 scripts/generate_udp_traffic.py --preset low --duration 30 &
sleep 2 && sudo timeout 25s ./build/baseline lo
```

**Expected Output:**
```
Packets processed: ~2,000-4,000
Packets per second: ~100-200 pps  
Average latency: ~0.3-0.5 µs
Min latency: ~0.05 µs
Max latency: <50 µs
```

---

## ❌ Critical Issues & Solutions

### Issue 1: Sudo Background Process Failure
**Problem**: `sudo timeout 15s ./build/baseline lo &` 
**Symptoms**: Process stops, password becomes command
**Solution**: Never background sudo commands, use sequential execution

### Issue 2: Interface Mismatch
**Problem**: Traffic to 127.0.0.1 but baseline on enp5s0
**Solution**: Use `lo` interface for localhost traffic testing

### Issue 3: No UDP Packets Processed
**Problem**: Baseline shows 0 packets processed
**Causes**: 
- Wrong interface (use `lo` for localhost traffic)
- No traffic running (start traffic generator first)
- Firewall blocking (check `sudo ufw status`)

### Issue 4: Permission Denied
**Problem**: Raw socket creation fails
**Solution**: Run baseline with `sudo`

### Issue 5: Build Failures
**Problem**: Compilation errors
**Solutions**:
- Missing headers: `sudo apt install linux-headers-$(uname -r)`
- Missing libbpf: `sudo apt install libbpf-dev`
- Wrong compiler: Ensure clang ≥18.x installed

---

## 🧪 Validation Checklist

### ✅ Environment Validation
- [ ] Kernel ≥5.10 (check: `uname -r`)
- [ ] Ubuntu system (check: `lsb_release -a`)
- [ ] Clang installed (check: `clang --version`)
- [ ] libbpf available (check: `pkg-config --exists libbpf`)
- [ ] Network interface UP (check: `ip link show`)

### ✅ Build Validation
- [ ] `make baseline` succeeds
- [ ] `build/baseline` executable exists
- [ ] No critical compilation errors (warnings OK)

### ✅ Functionality Validation  
- [ ] Baseline binds to interface successfully
- [ ] UDP traffic generator works
- [ ] Baseline processes UDP packets (>0 processed)
- [ ] Performance stats display correctly
- [ ] Graceful shutdown with Ctrl+C

### ✅ Performance Validation
- [ ] Throughput: 100-200 pps typical
- [ ] Latency: <1µs average  
- [ ] No packet corruption
- [ ] Statistics accuracy

---

## 📊 Expected Baseline Performance

**Reference System**: Ubuntu 24.04.2, Intel i7-6700HQ, 8 cores

| Metric | Typical Range | Status |
|--------|---------------|--------|
| **Throughput** | 100-200 pps | ✅ Normal |
| **Avg Latency** | 0.3-0.5 µs | ✅ Good |
| **Min Latency** | 0.05-0.1 µs | ✅ Excellent |
| **Max Latency** | 10-50 µs | ✅ Acceptable |
| **Drop Rate** | 40-60% | ✅ Expected (non-UDP) |

**Performance Variations**:
- Faster CPUs: Higher throughput, lower latency
- Slower systems: Lower throughput, higher latency  
- Different traffic rates: Proportional processing load

---

## 🔄 Troubleshooting Commands

```bash
# System diagnostics
make check-system
uname -r
lsb_release -a
nproc

# Network diagnostics  
ip link show
sudo netstat -tuln | grep 12345

# Build diagnostics
make clean && make baseline
ldd build/baseline

# Process diagnostics
ps aux | grep baseline
sudo ss -tuln | grep 12345

# Permission diagnostics
id
groups
sudo -v
```

---

## 📈 Phase 2 Preparation

**Current Status**: Ready for XDP development
**Next Components Needed**:
1. XDP program (`src/xdp_preproc.c`)
2. Userspace loader (`src/loader.c`)  
3. Ring buffer implementation
4. Performance comparison tools

**Performance Targets for XDP**:
- Throughput: >635 pps (5× baseline minimum)
- Latency: <0.1 µs average
- CPU efficiency: <50% of baseline usage

---

## 💾 File Backup Priority

**Critical Files** (must preserve):
1. `include/feature.h` - Core data structures
2. `benchmarks/baseline.c` - Reference implementation
3. `scripts/generate_udp_traffic.py` - Testing infrastructure
4. `Makefile` - Build system
5. `BASELINE_PERFORMANCE.md` - Reference metrics

**Generated Files** (can rebuild):
- `build/` directory
- Compiled binaries

**Documentation** (valuable for context):
- All `.md` files
- `.changelog`, `.dependencies`, etc.

---

## 🤝 Handoff to New AI Agent

**Project Context**: High-performance packet preprocessing with XDP/eBPF
**Current Phase**: Phase 1 complete, baseline established (127.29 pps, 0.40µs latency)
**Next Phase**: XDP kernel program development
**Success Criteria**: >5× performance improvement vs baseline

**Key Architecture Decision**: Module-first approach - prove performance before ML integration

**Critical Dependencies**: Ubuntu 24.04+, kernel ≥5.10, clang ≥18.x, libbpf ≥1.3.0

**Known Working Configuration**: 
- Ubuntu 24.04.2 LTS
- Kernel 6.11.0-29-generic  
- Intel i7-6700HQ @ 2.60GHz
- 8 cores, x86_64

This guide ensures 100% reproducibility for Phase 2 development. 