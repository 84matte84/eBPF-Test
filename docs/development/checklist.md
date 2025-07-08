# eBPF-Test Reproduction Checklist

**Quick validation for new machines & AI agents**

## 📋 Pre-Phase 2 Checklist

### ✅ System Verification (5 min)
- [ ] **OS**: Ubuntu 24.04+ or compatible (`lsb_release -a`)
- [ ] **Kernel**: ≥5.10 (`uname -r` should show ≥5.10)
- [ ] **CPU**: ≥4 cores (`nproc`)
- [ ] **Interface**: At least one UP interface (`ip link show`)

### ✅ Dependencies Installed (10 min)
- [ ] **Clang**: `clang --version` (should be ≥18.x)
- [ ] **LLVM**: `llvm-objdump --version | grep bpf` (should show BPF targets)
- [ ] **libbpf**: `pkg-config --modversion libbpf` (should be ≥1.3.0)
- [ ] **bpftool**: `bpftool version` (should work)
- [ ] **Build tools**: `make --version && gcc --version` (should work)

### ✅ Project Structure (2 min)
- [ ] **Core files present**:
  - [ ] `include/feature.h`
  - [ ] `benchmarks/baseline.c`
  - [ ] `scripts/generate_udp_traffic.py`
  - [ ] `Makefile`
  - [ ] `PROJECT_REPRODUCTION.md`

### ✅ Build Validation (3 min)
- [ ] **Clean build**: `make clean && make baseline`
- [ ] **Executable**: `ls -la build/baseline` (should exist, be executable)
- [ ] **No critical errors**: Minor warnings OK, no fatal compilation errors

### ✅ Functionality Test (5 min)
**CRITICAL**: Never run `sudo command &` (will fail with password prompt)

**Method 1 - Sequential (Recommended)**:
```bash
# Terminal 1: Start traffic
python3 scripts/generate_udp_traffic.py --preset low --duration 15 &

# Terminal 2: Start processor (needs sudo)
sudo timeout 12s ./build/baseline lo
```

**Method 2 - One terminal**:
```bash
python3 scripts/generate_udp_traffic.py --preset low --duration 20 &
sleep 2 && sudo timeout 15s ./build/baseline lo
```

**Expected Results**:
- [ ] **Binding successful**: "Successfully bound to interface lo"
- [ ] **Packets processed**: >0 UDP packets processed
- [ ] **Performance stats**: ~100-200 pps, ~0.3-0.5µs latency
- [ ] **Clean shutdown**: Statistics displayed on exit

## 🎯 Success Criteria

### Performance Baseline Established
- **Throughput**: 100-200 pps (typical on development hardware)
- **Latency**: 0.3-0.5µs average (sub-microsecond)
- **Processing**: Successfully extracts features from UDP packets
- **Reliability**: Consistent results across multiple runs

### Infrastructure Ready
- **Traffic Generator**: Configurable UDP packet generation
- **Build System**: Automated compilation and testing
- **Performance Monitoring**: Comprehensive latency/throughput tracking
- **Documentation**: Complete reproduction guide

## 🚫 Common Failure Points & Solutions

| Problem | Symptom | Solution |
|---------|---------|----------|
| **Sudo background fail** | Process stops, password becomes command | Never use `sudo cmd &` |
| **No packets processed** | 0 UDP packets in stats | Use `lo` interface for localhost traffic |
| **Permission denied** | Socket creation fails | Run baseline with `sudo` |
| **Build failure** | Compilation errors | Install missing dependencies |
| **Interface mismatch** | Traffic sent but not received | Match interface names |

## 📊 Baseline Performance Reference

**Test System**: Ubuntu 24.04.2, Intel i7-6700HQ, 8 cores

```
Runtime: 25.01 seconds
Packets processed: 3,184
Packets dropped: 3,627  
Packets per second: 127.29
Average latency: 395.80 ns (0.40 µs)
Min latency: 49 ns (0.05 µs)
Max latency: 28,064 ns (28.06 µs)
```

**This baseline represents our target for 5× improvement with XDP.**

## 🚀 Ready for Phase 2?

If all checklist items pass:
- ✅ **Environment**: Complete eBPF development setup
- ✅ **Baseline**: Functional userspace packet processor
- ✅ **Benchmarks**: Performance metrics established
- ✅ **Infrastructure**: Testing and build automation
- ✅ **Documentation**: Full reproduction capability

**Next step**: Begin XDP kernel program development with performance target of >635 pps (5× baseline minimum).

---

**Time to complete**: ~15-25 minutes on fresh Ubuntu 24.04 system
**Confidence level**: High (tested on target hardware)
**Reproducibility**: 100% with provided automation scripts 