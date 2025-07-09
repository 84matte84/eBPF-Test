#!/usr/bin/env python3
"""
Performance Optimization Module for eBPF-Test Two-Machine Testing

Provides advanced performance optimization techniques for high-rate traffic
generation, system resource optimization, and monitoring efficiency.

Author: eBPF-Test Project
License: MIT
"""

import os
import sys
import time
import socket
import threading
import multiprocessing
import platform
import logging
import psutil
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import ctypes
import mmap


class PerformanceError(Exception):
    """Exception for performance optimization errors."""
    pass


@dataclass
class SystemCapabilities:
    """System capabilities for performance optimization."""
    cpu_count: int
    memory_gb: float
    network_interfaces: List[str]
    supports_numa: bool
    supports_huge_pages: bool
    supports_cpu_affinity: bool
    max_socket_buffer: int
    kernel_version: str
    
    @classmethod
    def detect(cls) -> 'SystemCapabilities':
        """Detect system capabilities."""
        cpu_count = multiprocessing.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024**3)
        
        # Get network interfaces
        network_interfaces = list(psutil.net_if_addrs().keys())
        
        # Check NUMA support
        supports_numa = os.path.exists('/sys/devices/system/node')
        
        # Check huge pages support
        supports_huge_pages = os.path.exists('/proc/sys/vm/nr_hugepages')
        
        # Check CPU affinity support
        supports_cpu_affinity = hasattr(os, 'sched_setaffinity')
        
        # Get max socket buffer size
        max_socket_buffer = 0
        try:
            with open('/proc/sys/net/core/rmem_max', 'r') as f:
                max_socket_buffer = int(f.read().strip())
        except (IOError, ValueError):
            max_socket_buffer = 212992  # Default Linux value
        
        # Get kernel version
        kernel_version = platform.release()
        
        return cls(
            cpu_count=cpu_count,
            memory_gb=memory_gb,
            network_interfaces=network_interfaces,
            supports_numa=supports_numa,
            supports_huge_pages=supports_huge_pages,
            supports_cpu_affinity=supports_cpu_affinity,
            max_socket_buffer=max_socket_buffer,
            kernel_version=kernel_version
        )


class MemoryOptimizer:
    """Memory optimization utilities."""
    
    @staticmethod
    def enable_huge_pages(num_pages: int = 128) -> bool:
        """Enable huge pages for better memory performance."""
        try:
            if not os.path.exists('/proc/sys/vm/nr_hugepages'):
                return False
            
            # Check current huge pages
            with open('/proc/sys/vm/nr_hugepages', 'r') as f:
                current_pages = int(f.read().strip())
            
            if current_pages < num_pages:
                # Try to allocate more huge pages
                with open('/proc/sys/vm/nr_hugepages', 'w') as f:
                    f.write(str(num_pages))
                
                # Verify allocation
                with open('/proc/sys/vm/nr_hugepages', 'r') as f:
                    allocated_pages = int(f.read().strip())
                
                return allocated_pages >= num_pages
            
            return True
            
        except (IOError, ValueError, PermissionError):
            return False
    
    @staticmethod
    def optimize_memory_for_networking() -> Dict[str, Any]:
        """Optimize memory settings for high-rate networking."""
        optimizations = {}
        
        try:
            # Increase network buffer sizes
            net_params = {
                '/proc/sys/net/core/rmem_max': 134217728,    # 128MB
                '/proc/sys/net/core/wmem_max': 134217728,    # 128MB
                '/proc/sys/net/core/rmem_default': 262144,   # 256KB
                '/proc/sys/net/core/wmem_default': 262144,   # 256KB
                '/proc/sys/net/ipv4/udp_mem': '102400 873800 16777216',
                '/proc/sys/net/core/netdev_max_backlog': 5000,
            }
            
            for param, value in net_params.items():
                try:
                    if os.path.exists(param):
                        with open(param, 'r') as f:
                            original = f.read().strip()
                        
                        with open(param, 'w') as f:
                            f.write(str(value))
                        
                        optimizations[param] = {
                            'original': original,
                            'optimized': str(value),
                            'success': True
                        }
                except (IOError, PermissionError):
                    optimizations[param] = {'success': False, 'error': 'Permission denied'}
            
        except Exception as e:
            optimizations['error'] = str(e)
        
        return optimizations


class CPUOptimizer:
    """CPU optimization utilities."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.CPUOptimizer")
        self.capabilities = SystemCapabilities.detect()
    
    def set_thread_affinity(self, thread_id: int, cpu_cores: List[int]) -> bool:
        """Set CPU affinity for a thread."""
        if not self.capabilities.supports_cpu_affinity:
            return False
        
        try:
            # Get the current thread
            if thread_id == threading.get_ident():
                # Current thread
                pid = os.getpid()
            else:
                # This is simplified - in practice you'd need to track thread PIDs
                return False
            
            # Validate CPU cores
            valid_cores = [c for c in cpu_cores if 0 <= c < self.capabilities.cpu_count]
            if not valid_cores:
                return False
            
            # Set affinity
            os.sched_setaffinity(pid, valid_cores)
            return True
            
        except (OSError, AttributeError):
            return False
    
    def get_optimal_thread_distribution(self, num_threads: int) -> List[List[int]]:
        """Get optimal CPU core distribution for threads."""
        if num_threads <= 0:
            return []
        
        cpu_count = self.capabilities.cpu_count
        
        if num_threads >= cpu_count:
            # One thread per core, round-robin for extras
            return [[i % cpu_count] for i in range(num_threads)]
        else:
            # Distribute threads across cores evenly
            cores_per_thread = cpu_count // num_threads
            remainder = cpu_count % num_threads
            
            distributions = []
            start_core = 0
            
            for i in range(num_threads):
                cores = cores_per_thread + (1 if i < remainder else 0)
                thread_cores = list(range(start_core, start_core + cores))
                distributions.append(thread_cores)
                start_core += cores
            
            return distributions
    
    def optimize_process_priority(self, priority: int = -10) -> bool:
        """Set process priority for better performance."""
        try:
            os.nice(priority)
            return True
        except (OSError, PermissionError):
            return False


class NetworkOptimizer:
    """Network optimization utilities."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.NetworkOptimizer")
    
    def optimize_socket(self, sock: socket.socket, buffer_size: Optional[int] = None) -> Dict[str, Any]:
        """Optimize socket settings for high-performance networking."""
        optimizations = {}
        
        try:
            # Set socket buffer sizes
            if buffer_size is None:
                buffer_size = min(8 * 1024 * 1024, 134217728)  # 8MB or system max
            
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_size)
                optimizations['send_buffer'] = buffer_size
            except OSError as e:
                optimizations['send_buffer_error'] = str(e)
            
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_size)
                optimizations['recv_buffer'] = buffer_size
            except OSError as e:
                optimizations['recv_buffer_error'] = str(e)
            
            # Enable socket reuse
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                optimizations['reuse_addr'] = True
            except OSError:
                pass
            
            # Platform-specific optimizations
            if platform.system() == 'Linux':
                # Enable SO_REUSEPORT on Linux for better load balancing
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    optimizations['reuse_port'] = True
                except (OSError, AttributeError):
                    pass
                
                # Set IP_TOS for better QoS
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, 0x10)  # Low delay
                    optimizations['ip_tos'] = True
                except (OSError, AttributeError):
                    pass
            
        except Exception as e:
            optimizations['error'] = str(e)
        
        return optimizations
    
    def create_optimized_socket_pool(self, pool_size: int) -> List[socket.socket]:
        """Create a pool of optimized sockets for high-rate traffic generation."""
        sockets = []
        
        for i in range(pool_size):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.optimize_socket(sock)
                sockets.append(sock)
            except Exception as e:
                self.logger.error(f"Failed to create socket {i}: {e}")
        
        return sockets
    
    def get_interface_capabilities(self, interface: str) -> Dict[str, Any]:
        """Get network interface capabilities."""
        capabilities = {
            'mtu': 1500,
            'speed': 'unknown',
            'duplex': 'unknown',
            'driver': 'unknown',
            'supports_gso': False,
            'supports_tso': False,
            'rx_rings': 1,
            'tx_rings': 1
        }
        
        try:
            # Get MTU
            import fcntl
            import struct
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                # Get MTU using ioctl
                ifr = struct.pack('16sH', interface.encode()[:15], 0)
                result = fcntl.ioctl(sock.fileno(), 0x8921, ifr)  # SIOCGIFMTU
                capabilities['mtu'] = struct.unpack('16sH', result)[1]
            except (OSError, struct.error):
                pass
            finally:
                sock.close()
            
            # Try to get ethtool information
            try:
                import subprocess
                result = subprocess.run(
                    ['ethtool', interface], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                
                if result.returncode == 0:
                    output = result.stdout
                    
                    # Parse speed
                    for line in output.split('\n'):
                        line = line.strip()
                        if line.startswith('Speed:'):
                            capabilities['speed'] = line.split(':', 1)[1].strip()
                        elif line.startswith('Duplex:'):
                            capabilities['duplex'] = line.split(':', 1)[1].strip()
                
                # Get driver info
                result = subprocess.run(
                    ['ethtool', '-i', interface], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                
                if result.returncode == 0:
                    output = result.stdout
                    for line in output.split('\n'):
                        line = line.strip()
                        if line.startswith('driver:'):
                            capabilities['driver'] = line.split(':', 1)[1].strip()
                
                # Get feature info
                result = subprocess.run(
                    ['ethtool', '-k', interface], 
                    capture_output=True, 
                    text=True, 
                    timeout=5
                )
                
                if result.returncode == 0:
                    output = result.stdout
                    capabilities['supports_gso'] = 'generic-segmentation-offload: on' in output
                    capabilities['supports_tso'] = 'tcp-segmentation-offload: on' in output
            
            except (subprocess.SubprocessError, FileNotFoundError):
                pass
            
        except Exception as e:
            self.logger.debug(f"Error getting interface capabilities: {e}")
        
        return capabilities


class PayloadOptimizer:
    """Payload generation and caching optimization."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.PayloadOptimizer")
        self._payload_cache: Dict[int, bytes] = {}
        self._cache_lock = threading.Lock()
    
    def generate_optimized_payload(self, size: int, pattern: Optional[str] = None) -> bytes:
        """Generate optimized payload with caching."""
        with self._cache_lock:
            if size in self._payload_cache:
                return self._payload_cache[size]
        
        if pattern is None:
            # Use a fast, simple pattern for high-rate generation
            pattern = b"eBPF-Test-" + str(int(time.time())).encode()
        elif isinstance(pattern, str):
            pattern = pattern.encode('ascii')
        
        # Generate payload efficiently
        if size <= len(pattern):
            payload = pattern[:size]
        else:
            # Use multiplication for speed
            repetitions = (size // len(pattern)) + 1
            payload = (pattern * repetitions)[:size]
        
        # Cache for reuse
        with self._cache_lock:
            if len(self._payload_cache) < 100:  # Limit cache size
                self._payload_cache[size] = payload
        
        return payload
    
    def create_payload_variants(self, base_size: int, count: int = 10) -> List[bytes]:
        """Create multiple payload variants to avoid pattern detection."""
        payloads = []
        
        for i in range(count):
            # Slight size variations
            size = base_size + (i % 5) - 2  # ±2 bytes variation
            size = max(64, size)  # Minimum size
            
            # Pattern variations
            pattern = f"eBPF-Test-Var{i:02d}-"
            payload = self.generate_optimized_payload(size, pattern)
            payloads.append(payload)
        
        return payloads


class MonitoringOptimizer:
    """Monitoring and metrics collection optimization."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.MonitoringOptimizer")
    
    def optimize_monitoring_frequency(self, target_rate: float, system_load: float) -> float:
        """Optimize monitoring frequency based on system load."""
        base_frequency = 1.0  # 1 second default
        
        # Reduce monitoring frequency under high load
        if system_load > 0.8:
            return base_frequency * 2.0  # Monitor every 2 seconds
        elif system_load > 0.6:
            return base_frequency * 1.5  # Monitor every 1.5 seconds
        elif system_load < 0.3 and target_rate > 50000:
            return base_frequency * 0.5  # Monitor every 0.5 seconds for high-rate tests
        
        return base_frequency
    
    def create_efficient_metrics_collector(self) -> callable:
        """Create an efficient metrics collector function."""
        
        # Pre-compile the metrics collection to avoid repeated setup
        def collect_metrics() -> Dict[str, Any]:
            try:
                # Efficient CPU measurement
                cpu_percent = psutil.cpu_percent(interval=None)
                
                # Efficient memory measurement
                memory = psutil.virtual_memory()
                
                # Only collect network stats if needed
                network_stats = {}
                try:
                    net_io = psutil.net_io_counters()
                    network_stats = {
                        'bytes_sent': net_io.bytes_sent,
                        'bytes_recv': net_io.bytes_recv,
                        'packets_sent': net_io.packets_sent,
                        'packets_recv': net_io.packets_recv
                    }
                except AttributeError:
                    pass
                
                return {
                    'timestamp': time.time(),
                    'cpu_percent': cpu_percent,
                    'memory_percent': memory.percent,
                    'memory_mb': memory.used / (1024 * 1024),
                    'network': network_stats
                }
                
            except Exception as e:
                return {'error': str(e), 'timestamp': time.time()}
        
        return collect_metrics


class PerformanceProfiler:
    """Performance profiling and analysis utilities."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.PerformanceProfiler")
        self.start_time = 0.0
        self.samples: List[Dict[str, Any]] = []
    
    def start_profiling(self) -> None:
        """Start performance profiling."""
        self.start_time = time.time()
        self.samples.clear()
    
    def add_sample(self, operation: str, duration: float, **kwargs) -> None:
        """Add a performance sample."""
        sample = {
            'timestamp': time.time(),
            'operation': operation,
            'duration': duration,
            'elapsed_time': time.time() - self.start_time,
            **kwargs
        }
        self.samples.append(sample)
    
    def get_performance_report(self) -> Dict[str, Any]:
        """Get comprehensive performance report."""
        if not self.samples:
            return {}
        
        # Group samples by operation
        operations = {}
        for sample in self.samples:
            op = sample['operation']
            if op not in operations:
                operations[op] = []
            operations[op].append(sample['duration'])
        
        # Calculate statistics
        report = {
            'total_samples': len(self.samples),
            'total_time': time.time() - self.start_time,
            'operations': {}
        }
        
        for op, durations in operations.items():
            report['operations'][op] = {
                'count': len(durations),
                'total_time': sum(durations),
                'average_time': sum(durations) / len(durations),
                'min_time': min(durations),
                'max_time': max(durations),
                'ops_per_second': len(durations) / report['total_time']
            }
        
        return report


class PerformanceOptimizationSuite:
    """Comprehensive performance optimization suite."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.PerformanceOptimizationSuite")
        self.capabilities = SystemCapabilities.detect()
        self.memory_optimizer = MemoryOptimizer()
        self.cpu_optimizer = CPUOptimizer()
        self.network_optimizer = NetworkOptimizer()
        self.payload_optimizer = PayloadOptimizer()
        self.monitoring_optimizer = MonitoringOptimizer()
        self.profiler = PerformanceProfiler()
    
    def optimize_system_for_testing(self) -> Dict[str, Any]:
        """Apply comprehensive system optimizations for testing."""
        results = {
            'timestamp': time.time(),
            'system_capabilities': self.capabilities,
            'optimizations': {}
        }
        
        try:
            # Memory optimizations
            self.logger.info("Applying memory optimizations...")
            memory_opts = self.memory_optimizer.optimize_memory_for_networking()
            results['optimizations']['memory'] = memory_opts
            
            # CPU optimizations
            self.logger.info("Applying CPU optimizations...")
            cpu_priority_success = self.cpu_optimizer.optimize_process_priority()
            results['optimizations']['cpu'] = {
                'priority_optimization': cpu_priority_success
            }
            
            # Log results
            successful_opts = 0
            total_opts = 0
            
            for category, opts in results['optimizations'].items():
                if isinstance(opts, dict):
                    for opt_name, opt_result in opts.items():
                        total_opts += 1
                        if (isinstance(opt_result, dict) and opt_result.get('success')) or opt_result is True:
                            successful_opts += 1
            
            self.logger.info(f"Applied {successful_opts}/{total_opts} optimizations successfully")
            
        except Exception as e:
            self.logger.error(f"Error applying optimizations: {e}")
            results['error'] = str(e)
        
        return results
    
    def get_optimization_recommendations(self, test_config: Dict[str, Any]) -> List[str]:
        """Get optimization recommendations based on test configuration."""
        recommendations = []
        
        # Analyze test requirements
        packet_rate = test_config.get('traffic_config', {}).get('packet_rate', 0)
        threads = test_config.get('traffic_config', {}).get('threads', 1)
        flows = test_config.get('traffic_config', {}).get('flows', 1)
        
        # CPU recommendations
        if threads > self.capabilities.cpu_count:
            recommendations.append(
                f"Consider reducing threads to {self.capabilities.cpu_count} (number of CPU cores)"
            )
        
        if packet_rate > 100000:
            recommendations.append("Enable CPU affinity for high packet rate workloads")
            recommendations.append("Consider increasing socket buffer sizes")
        
        # Memory recommendations
        if self.capabilities.memory_gb < 4:
            recommendations.append("Consider upgrading to at least 4GB RAM for optimal performance")
        
        if packet_rate > 50000 and not self.capabilities.supports_huge_pages:
            recommendations.append("Enable huge pages for better memory performance")
        
        # Network recommendations
        if flows > 100:
            recommendations.append("High flow count may benefit from SO_REUSEPORT optimization")
        
        if packet_rate > 1000000:
            recommendations.append("Consider using multiple network interfaces for extreme packet rates")
        
        return recommendations
    
    def benchmark_performance(self, duration: int = 10) -> Dict[str, Any]:
        """Run performance benchmarks."""
        self.logger.info(f"Running performance benchmarks for {duration} seconds...")
        
        self.profiler.start_profiling()
        
        # Benchmark socket creation
        start_time = time.time()
        sockets = self.network_optimizer.create_optimized_socket_pool(10)
        socket_creation_time = time.time() - start_time
        self.profiler.add_sample('socket_creation', socket_creation_time, count=len(sockets))
        
        # Benchmark payload generation
        start_time = time.time()
        payloads = self.payload_optimizer.create_payload_variants(1500, 100)
        payload_generation_time = time.time() - start_time
        self.profiler.add_sample('payload_generation', payload_generation_time, count=len(payloads))
        
        # Benchmark metrics collection
        collector = self.monitoring_optimizer.create_efficient_metrics_collector()
        start_time = time.time()
        for _ in range(100):
            metrics = collector()
        metrics_collection_time = time.time() - start_time
        self.profiler.add_sample('metrics_collection', metrics_collection_time, count=100)
        
        # Clean up
        for sock in sockets:
            sock.close()
        
        # Generate report
        report = self.profiler.get_performance_report()
        report['system_capabilities'] = self.capabilities
        
        return report


def main() -> int:
    """Command-line interface for performance optimization."""
    import argparse
    
    parser = argparse.ArgumentParser(description='eBPF-Test Performance Optimization Tool')
    parser.add_argument('--benchmark', action='store_true', help='Run performance benchmarks')
    parser.add_argument('--optimize', action='store_true', help='Apply system optimizations')
    parser.add_argument('--analyze', help='Analyze configuration file for optimization opportunities')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    suite = PerformanceOptimizationSuite()
    
    try:
        if args.benchmark:
            print("🔄 Running performance benchmarks...")
            results = suite.benchmark_performance()
            
            print("\n📊 Benchmark Results:")
            for op, stats in results.get('operations', {}).items():
                print(f"  {op}: {stats['ops_per_second']:.1f} ops/sec")
            
            return 0
        
        elif args.optimize:
            print("⚡ Applying system optimizations...")
            results = suite.optimize_system_for_testing()
            
            print("\n✅ Optimization Results:")
            for category, opts in results.get('optimizations', {}).items():
                print(f"  {category}: {opts}")
            
            return 0
        
        elif args.analyze:
            import yaml
            
            print(f"🔍 Analyzing configuration: {args.analyze}")
            
            with open(args.analyze, 'r') as f:
                config = yaml.safe_load(f)
            
            recommendations = suite.get_optimization_recommendations(config)
            
            print("\n💡 Optimization Recommendations:")
            for i, rec in enumerate(recommendations, 1):
                print(f"  {i}. {rec}")
            
            return 0
        
        else:
            print("🔧 System Capabilities:")
            caps = SystemCapabilities.detect()
            print(f"  CPU Cores: {caps.cpu_count}")
            print(f"  Memory: {caps.memory_gb:.1f} GB")
            print(f"  Network Interfaces: {len(caps.network_interfaces)}")
            print(f"  NUMA Support: {caps.supports_numa}")
            print(f"  Huge Pages: {caps.supports_huge_pages}")
            print(f"  CPU Affinity: {caps.supports_cpu_affinity}")
            print(f"  Max Socket Buffer: {caps.max_socket_buffer:,} bytes")
            
            return 0
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 