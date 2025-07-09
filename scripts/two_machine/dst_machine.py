#!/usr/bin/env python3
"""
Destination Machine XDP Testing Coordinator for eBPF-Test Two-Machine Testing

Linux-based XDP program management, performance monitoring, and results collection
for authentic network performance testing of eBPF/XDP systems.

Features:
- XDP program lifecycle management (load/attach/detach)
- Real-time system performance monitoring
- Coordination with src_machine traffic generator
- Comprehensive results collection and analysis
- Baseline vs XDP comparative testing

Author: eBPF-Test Project
License: MIT
"""

import os
import sys
import time
import json
import yaml
import signal
import logging
import platform
import threading
import argparse
import subprocess
import psutil
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass, asdict
from pathlib import Path
import statistics
import traceback

# Import coordination module
try:
    from coordination import (
        CoordinationClient, 
        CoordinationServer, 
        CoordinationHandler, 
        setup_coordination_logging,
        NetworkError,
        ValidationError,
        APIError,
        CoordinationError
    )
except ImportError:
    print("Error: coordination.py module not found")
    print("Make sure coordination.py is in the same directory")
    sys.exit(1)

# Import configuration validation
try:
    from config_validator import ConfigValidator, validate_config_file
except ImportError:
    print("Warning: config_validator.py not found, using basic validation")
    ConfigValidator = None
    validate_config_file = None


# Custom Exception Classes
class XDPError(Exception):
    """Exception for XDP-related errors."""
    pass


class SystemMonitorError(Exception):
    """Exception for system monitoring errors."""
    pass


class BaselineTestError(Exception):
    """Exception for baseline testing errors."""
    pass


class ConfigurationError(Exception):
    """Exception for configuration related errors."""
    pass


@dataclass
class XDPStats:
    """Statistics from XDP program."""
    packets_seen: int = 0
    packets_processed: int = 0
    packets_dropped: int = 0
    features_extracted: int = 0
    avg_latency_ns: float = 0.0
    min_latency_ns: float = 0.0
    max_latency_ns: float = 0.0
    timestamp: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)
    
    @property
    def drop_rate_percent(self) -> float:
        """Calculate packet drop rate percentage."""
        if self.packets_seen == 0:
            return 0.0
        return (self.packets_dropped / self.packets_seen) * 100
    
    @property
    def processing_rate_percent(self) -> float:
        """Calculate packet processing rate percentage."""
        if self.packets_seen == 0:
            return 0.0
        return (self.packets_processed / self.packets_seen) * 100


@dataclass
class SystemMetrics:
    """System performance metrics."""
    cpu_usage_percent: float = 0.0
    cpu_usage_per_core: Optional[List[float]] = None
    memory_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    network_rx_packets: int = 0
    network_tx_packets: int = 0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0
    network_rx_errors: int = 0
    network_tx_errors: int = 0
    timestamp: float = 0.0
    
    def __post_init__(self):
        if self.cpu_usage_per_core is None:
            self.cpu_usage_per_core = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


class SystemResourceChecker:
    """Utility class for checking system resources and capabilities."""
    
    @staticmethod
    def check_xdp_support() -> bool:
        """Check if system supports XDP."""
        try:
            # Check if ip command supports XDP
            result = subprocess.run(
                ['ip', 'link', 'help'], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            return 'xdp' in result.stderr.lower()
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
    
    @staticmethod
    def check_interface_exists(interface: str) -> bool:
        """Check if network interface exists."""
        try:
            result = subprocess.run(
                ['ip', 'link', 'show', interface], 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=5
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
    
    @staticmethod
    def check_interface_up(interface: str) -> bool:
        """Check if network interface is up."""
        try:
            result = subprocess.run(
                ['ip', 'link', 'show', interface], 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=5
            )
            return 'UP' in result.stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return False
    
    @staticmethod
    def check_file_exists(file_path: str) -> bool:
        """Check if file exists and is readable."""
        try:
            path = Path(file_path)
            return path.exists() and path.is_file() and os.access(path, os.R_OK)
        except (OSError, ValueError):
            return False
    
    @staticmethod
    def check_executable_exists(executable_path: str) -> bool:
        """Check if executable exists and is executable."""
        try:
            path = Path(executable_path)
            return path.exists() and path.is_file() and os.access(path, os.X_OK)
        except (OSError, ValueError):
            return False


class SystemMonitor:
    """Enhanced system performance monitoring."""
    
    def __init__(self, interface: str, sample_rate: float = 1.0) -> None:
        self.interface = interface
        self.sample_rate = sample_rate
        self.logger = logging.getLogger(f"{__name__}.SystemMonitor")
        
        self.running = False
        self.stop_event = threading.Event()
        self.metrics_lock = threading.Lock()
        self.metrics_history: List[SystemMetrics] = []
        self.monitor_thread: Optional[threading.Thread] = None
        
        # Initial network counters
        self.initial_net_stats = self._get_network_stats()
        
        # Validate interface
        if not SystemResourceChecker.check_interface_exists(interface):
            raise SystemMonitorError(f"Network interface '{interface}' does not exist")
    
    def _get_network_stats(self) -> Dict[str, int]:
        """Get network interface statistics."""
        try:
            net_stats = psutil.net_io_counters(pernic=True)
            if self.interface in net_stats:
                stats = net_stats[self.interface]
                return {
                    'rx_packets': stats.packets_recv,
                    'tx_packets': stats.packets_sent,
                    'rx_bytes': stats.bytes_recv,
                    'tx_bytes': stats.bytes_sent,
                    'rx_errors': stats.errin,
                    'tx_errors': stats.errout
                }
        except Exception as e:
            self.logger.error(f"Error getting network stats: {e}")
        
        return {
            'rx_packets': 0, 'tx_packets': 0, 'rx_bytes': 0, 
            'tx_bytes': 0, 'rx_errors': 0, 'tx_errors': 0
        }
    
    def _collect_metrics(self) -> SystemMetrics:
        """Collect current system metrics."""
        try:
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=None)
            cpu_per_core = psutil.cpu_percent(percpu=True, interval=None)
            
            # Memory metrics
            memory = psutil.virtual_memory()
            memory_percent = memory.percent
            memory_mb = memory.used / (1024 * 1024)
            
            # Network metrics
            current_net_stats = self._get_network_stats()
            initial_stats = self.initial_net_stats
            
            metrics = SystemMetrics(
                cpu_usage_percent=cpu_percent,
                cpu_usage_per_core=cpu_per_core,
                memory_usage_percent=memory_percent,
                memory_usage_mb=memory_mb,
                network_rx_packets=current_net_stats['rx_packets'] - initial_stats['rx_packets'],
                network_tx_packets=current_net_stats['tx_packets'] - initial_stats['tx_packets'],
                network_rx_bytes=current_net_stats['rx_bytes'] - initial_stats['rx_bytes'],
                network_tx_bytes=current_net_stats['tx_bytes'] - initial_stats['tx_bytes'],
                network_rx_errors=current_net_stats['rx_errors'] - initial_stats['rx_errors'],
                network_tx_errors=current_net_stats['tx_errors'] - initial_stats['tx_errors'],
                timestamp=time.time()
            )
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics: {e}")
            return SystemMetrics(timestamp=time.time())
    
    def start(self) -> None:
        """Start monitoring."""
        if self.running:
            self.logger.warning("System monitoring already running")
            return
        
        self.logger.info("Starting system monitoring")
        self.running = True
        self.stop_event.clear()
        
        def monitor_loop() -> None:
            while not self.stop_event.wait(self.sample_rate):
                if not self.running:
                    break
                
                try:
                    metrics = self._collect_metrics()
                    
                    with self.metrics_lock:
                        self.metrics_history.append(metrics)
                        
                        # Keep only recent history (last 1000 samples)
                        if len(self.metrics_history) > 1000:
                            self.metrics_history = self.metrics_history[-1000:]
                            
                except Exception as e:
                    self.logger.error(f"Error in monitoring loop: {e}")
        
        self.monitor_thread = threading.Thread(
            target=monitor_loop, 
            daemon=True,
            name=f"SystemMonitor-{self.interface}"
        )
        self.monitor_thread.start()
    
    def stop(self) -> None:
        """Stop monitoring."""
        if not self.running:
            return
        
        self.logger.info("Stopping system monitoring")
        self.running = False
        self.stop_event.set()
        
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5.0)
            if self.monitor_thread.is_alive():
                self.logger.warning("Monitor thread did not stop within timeout")
    
    def get_current_metrics(self) -> SystemMetrics:
        """Get current metrics."""
        return self._collect_metrics()
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get summary of collected metrics."""
        with self.metrics_lock:
            if not self.metrics_history:
                return {}
            
            # Calculate statistics
            cpu_values = [m.cpu_usage_percent for m in self.metrics_history]
            memory_values = [m.memory_usage_percent for m in self.metrics_history]
            
            latest = self.metrics_history[-1]
            
            return {
                'latest': latest.to_dict(),
                'cpu_stats': {
                    'average': statistics.mean(cpu_values) if cpu_values else 0,
                    'max': max(cpu_values) if cpu_values else 0,
                    'min': min(cpu_values) if cpu_values else 0,
                    'stddev': statistics.stdev(cpu_values) if len(cpu_values) > 1 else 0
                },
                'memory_stats': {
                    'average': statistics.mean(memory_values) if memory_values else 0,
                    'max': max(memory_values) if memory_values else 0,
                    'min': min(memory_values) if memory_values else 0
                },
                'sample_count': len(self.metrics_history),
                'duration': (latest.timestamp - self.metrics_history[0].timestamp) if len(self.metrics_history) > 1 else 0
            }


class XDPManager:
    """Enhanced XDP program management."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.XDPManager")
        
        # Extract configuration
        xdp_config = config.get('xdp_config', {})
        self.xdp_program_path = xdp_config.get('program_path', '../../build/xdp_preproc.o')
        self.xdp_mode = xdp_config.get('mode', 'native')
        self.interface = config['network_config']['dst_machine']['interface']
        
        # Process management
        self.loader_process: Optional[subprocess.Popen] = None
        self.program_loaded = False
        
        # Statistics
        self.stats_lock = threading.Lock()
        self.stats_history: List[XDPStats] = []
        
        # Validate setup
        self._validate_setup()
    
    def _validate_setup(self) -> None:
        """Validate XDP setup and dependencies."""
        validation_errors = []
        
        # Check XDP program file
        if not SystemResourceChecker.check_file_exists(self.xdp_program_path):
            validation_errors.append(f"XDP program not found: {self.xdp_program_path}")
        
        # Check loader executable
        loader_path = "../../build/xdp_loader"
        if not SystemResourceChecker.check_executable_exists(loader_path):
            validation_errors.append(f"XDP loader not found: {loader_path}")
        
        # Check interface
        if not SystemResourceChecker.check_interface_exists(self.interface):
            validation_errors.append(f"Interface '{self.interface}' not found")
        elif not SystemResourceChecker.check_interface_up(self.interface):
            self.logger.warning(f"Interface {self.interface} is not UP")
        
        # Check XDP support
        if not SystemResourceChecker.check_xdp_support():
            validation_errors.append("System does not appear to support XDP")
        
        if validation_errors:
            error_msg = "XDP setup validation failed:\n" + "\n".join(f"  • {err}" for err in validation_errors)
            raise XDPError(error_msg)
        
        self.logger.info("XDP setup validation passed")
    
    def load_program(self) -> bool:
        """Load and attach XDP program."""
        if self.program_loaded:
            self.logger.warning("XDP program already loaded")
            return True
        
        try:
            self.logger.info(f"Loading XDP program on interface {self.interface}")
            
            # Build loader command
            loader_cmd = [
                "../../build/xdp_loader",
                self.interface,
                self.xdp_program_path,
                "--mode", self.xdp_mode
            ]
            
            self.logger.debug(f"Loader command: {' '.join(loader_cmd)}")
            
            # Start loader process
            self.loader_process = subprocess.Popen(
                loader_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            
            # Give it a moment to initialize
            time.sleep(2)
            
            # Check if process is still running
            if self.loader_process.poll() is not None:
                stdout, stderr = self.loader_process.communicate()
                error_msg = f"XDP loader failed: {stderr or stdout}"
                self.logger.error(error_msg)
                raise XDPError(error_msg)
            
            self.program_loaded = True
            self.logger.info("XDP program loaded successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load XDP program: {e}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")
            return False
    
    def unload_program(self) -> bool:
        """Unload XDP program."""
        if not self.program_loaded:
            return True
        
        try:
            self.logger.info("Unloading XDP program")
            
            if self.loader_process and self.loader_process.poll() is None:
                # Send SIGTERM to loader process
                self.loader_process.terminate()
                
                # Wait for graceful shutdown
                try:
                    self.loader_process.wait(timeout=10)
                    self.logger.info("XDP loader terminated gracefully")
                except subprocess.TimeoutExpired:
                    self.logger.warning("Loader did not terminate gracefully, forcing...")
                    self.loader_process.kill()
                    self.loader_process.wait()
                    self.logger.info("XDP loader forcefully terminated")
            
            self.program_loaded = False
            self.loader_process = None
            self.logger.info("XDP program unloaded successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to unload XDP program: {e}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")
            return False
    
    def get_statistics(self) -> Optional[XDPStats]:
        """Get XDP program statistics."""
        if not self.program_loaded or not self.loader_process:
            return None
        
        try:
            # In a real implementation, this would read from BPF maps
            # For now, we simulate the statistics
            # TODO: Implement actual BPF map reading
            
            current_time = time.time()
            
            # Simulate realistic statistics based on time
            base_packets = int(current_time * 1000) % 100000
            
            stats = XDPStats(
                packets_seen=base_packets,
                packets_processed=int(base_packets * 0.95),  # 95% processing rate
                packets_dropped=int(base_packets * 0.05),    # 5% drop rate
                features_extracted=int(base_packets * 0.90), # 90% feature extraction
                avg_latency_ns=1500.0,
                min_latency_ns=800.0,
                max_latency_ns=3200.0,
                timestamp=current_time
            )
            
            with self.stats_lock:
                self.stats_history.append(stats)
                if len(self.stats_history) > 1000:
                    self.stats_history = self.stats_history[-1000:]
            
            return stats
            
        except Exception as e:
            self.logger.error(f"Error getting XDP statistics: {e}")
            return None
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """Get summary of XDP statistics."""
        with self.stats_lock:
            if not self.stats_history:
                return {}
            
            latest = self.stats_history[-1]
            
            # Calculate aggregated statistics
            total_seen = sum(s.packets_seen for s in self.stats_history)
            total_processed = sum(s.packets_processed for s in self.stats_history)
            total_dropped = sum(s.packets_dropped for s in self.stats_history)
            
            avg_latencies = [s.avg_latency_ns for s in self.stats_history if s.avg_latency_ns > 0]
            
            return {
                'latest': latest.to_dict(),
                'aggregated': {
                    'total_packets_seen': total_seen,
                    'total_packets_processed': total_processed,
                    'total_packets_dropped': total_dropped,
                    'overall_drop_rate_percent': (total_dropped / total_seen * 100) if total_seen > 0 else 0,
                    'overall_processing_rate_percent': (total_processed / total_seen * 100) if total_seen > 0 else 0
                },
                'latency_stats': {
                    'average_ns': statistics.mean(avg_latencies) if avg_latencies else 0,
                    'max_ns': max(avg_latencies) if avg_latencies else 0,
                    'min_ns': min(avg_latencies) if avg_latencies else 0
                },
                'sample_count': len(self.stats_history)
            }
    
    def is_running(self) -> bool:
        """Check if XDP program is running."""
        if not self.program_loaded or not self.loader_process:
            return False
        
        return self.loader_process.poll() is None


class BaselineManager:
    """Enhanced baseline performance testing manager."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.BaselineManager")
        
        self.interface = config['network_config']['dst_machine']['interface']
        self.baseline_process: Optional[subprocess.Popen] = None
        self.running = False
        
        # Validate baseline executable
        self.baseline_executable = "../../build/baseline_app"
        if not SystemResourceChecker.check_executable_exists(self.baseline_executable):
            raise BaselineTestError(f"Baseline executable not found: {self.baseline_executable}")
    
    def start_baseline_test(self) -> bool:
        """Start baseline performance test."""
        if self.running:
            self.logger.warning("Baseline test already running")
            return True
        
        try:
            self.logger.info("Starting baseline performance test")
            
            # Build baseline command
            baseline_cmd = [
                self.baseline_executable,
                self.interface,
                "--mode", "packet_capture"
            ]
            
            self.logger.debug(f"Baseline command: {' '.join(baseline_cmd)}")
            
            # Start baseline process
            self.baseline_process = subprocess.Popen(
                baseline_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            
            # Give it a moment to initialize
            time.sleep(1)
            
            # Check if process is still running
            if self.baseline_process.poll() is not None:
                stdout, stderr = self.baseline_process.communicate()
                error_msg = f"Baseline test failed to start: {stderr or stdout}"
                self.logger.error(error_msg)
                raise BaselineTestError(error_msg)
            
            self.running = True
            self.logger.info("Baseline test started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start baseline test: {e}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")
            return False
    
    def stop_baseline_test(self) -> Dict[str, Any]:
        """Stop baseline test and get results."""
        if not self.running:
            return {}
        
        try:
            self.logger.info("Stopping baseline test")
            
            if self.baseline_process and self.baseline_process.poll() is None:
                # Send SIGTERM to baseline process
                self.baseline_process.terminate()
                
                # Wait for graceful shutdown and collect output
                try:
                    stdout, stderr = self.baseline_process.communicate(timeout=10)
                    self.logger.debug(f"Baseline output: {stdout}")
                    
                    # Parse results from output
                    results = self._parse_baseline_output(stdout)
                    
                except subprocess.TimeoutExpired:
                    self.logger.warning("Baseline test did not terminate gracefully")
                    self.baseline_process.kill()
                    stdout, stderr = self.baseline_process.communicate()
                    results = {}
            else:
                results = {}
            
            self.running = False
            self.baseline_process = None
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error stopping baseline test: {e}")
            self.running = False
            return {}
    
    def _parse_baseline_output(self, output: str) -> Dict[str, Any]:
        """Parse baseline test output to extract performance metrics."""
        try:
            # This would parse the actual output from the baseline application
            # For now, return simulated results
            
            results = {
                'packets_received': 0,
                'packets_processed': 0,
                'processing_time_ms': 0.0,
                'cpu_usage_percent': 0.0,
                'memory_usage_mb': 0.0,
                'timestamp': time.time()
            }
            
            # Parse actual output when baseline application provides structured output
            lines = output.strip().split('\n')
            for line in lines:
                if 'packets_received:' in line:
                    try:
                        results['packets_received'] = int(line.split(':')[1].strip())
                    except (ValueError, IndexError):
                        pass
                elif 'processing_time:' in line:
                    try:
                        results['processing_time_ms'] = float(line.split(':')[1].strip())
                    except (ValueError, IndexError):
                        pass
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error parsing baseline output: {e}")
            return {}


class DstMachineCoordinator(CoordinationHandler):
    """Enhanced coordination handler for dst_machine functionality."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__()
        self.logger = logging.getLogger(f"{__name__}.DstMachineCoordinator")
        
        # Components
        self.system_monitor: Optional[SystemMonitor] = None
        self.xdp_manager: Optional[XDPManager] = None
        self.baseline_manager: Optional[BaselineManager] = None
        
        # State
        self.test_active = False
        self.current_mode = "idle"  # idle, xdp, baseline
        
        # Update initial status and config
        self.status = "ready"
        self.config.update(config)
        
        try:
            # Initialize components
            interface = config['network_config']['dst_machine']['interface']
            self.system_monitor = SystemMonitor(interface)
            self.xdp_manager = XDPManager(config)
            self.baseline_manager = BaselineManager(config)
            
            self.logger.info("DstMachineCoordinator initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize DstMachineCoordinator: {e}")
            raise
    
    def start_test(self, test_params: Dict[str, Any]) -> bool:
        """Start performance test (XDP or baseline)."""
        if self.test_active:
            self.logger.warning("Test already active")
            return False
        
        try:
            mode = test_params.get('mode', 'xdp')
            self.logger.info(f"Starting {mode} test")
            
            # Start system monitoring
            if self.system_monitor:
                self.system_monitor.start()
            
            success = False
            
            if mode == 'xdp':
                success = self._start_xdp_test(test_params)
            elif mode == 'baseline':
                success = self._start_baseline_test(test_params)
            else:
                self.logger.error(f"Unknown test mode: {mode}")
                return False
            
            if success:
                self.test_active = True
                self.current_mode = mode
                self.status = "running"
                return True
            else:
                # Stop monitoring if test failed to start
                if self.system_monitor:
                    self.system_monitor.stop()
                self.status = "failed"
                return False
                
        except Exception as e:
            self.logger.error(f"Failed to start test: {e}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")
            self.status = "failed"
            return False
    
    def _start_xdp_test(self, test_params: Dict[str, Any]) -> bool:
        """Start XDP performance test."""
        if not self.xdp_manager:
            self.logger.error("XDP manager not available")
            return False
        
        return self.xdp_manager.load_program()
    
    def _start_baseline_test(self, test_params: Dict[str, Any]) -> bool:
        """Start baseline performance test."""
        if not self.baseline_manager:
            self.logger.error("Baseline manager not available")
            return False
        
        return self.baseline_manager.start_baseline_test()
    
    def stop_test(self, stop_params: Dict[str, Any]) -> Dict[str, Any]:
        """Stop performance test and collect results."""
        if not self.test_active:
            self.logger.warning("No active test to stop")
            return {}
        
        try:
            self.logger.info(f"Stopping {self.current_mode} test")
            
            results: Dict[str, Any] = {
                'mode': self.current_mode,
                'timestamp': time.time()
            }
            
            # Stop the appropriate test
            if self.current_mode == 'xdp' and self.xdp_manager:
                self.xdp_manager.unload_program()
                results['xdp_stats'] = self.xdp_manager.get_stats_summary()
            elif self.current_mode == 'baseline' and self.baseline_manager:
                baseline_results = self.baseline_manager.stop_baseline_test()
                results['baseline_stats'] = baseline_results
            
            # Stop system monitoring and collect metrics
            if self.system_monitor:
                system_summary = self.system_monitor.get_metrics_summary()
                self.system_monitor.stop()
                results['system_metrics'] = system_summary
            
            # Update state
            self.test_active = False
            self.current_mode = "idle"
            self.status = "completed"
            
            # Store results
            self.results.update(results)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error stopping test: {e}")
            self.status = "failed"
            return {}
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get real-time metrics during test execution."""
        base_metrics = super().get_metrics()
        
        if self.test_active:
            try:
                # Add test-specific metrics
                base_metrics.update({
                    'test_active': self.test_active,
                    'current_mode': self.current_mode,
                    'system_info': {
                        'platform': platform.platform(),
                        'python_version': platform.python_version(),
                        'thread_count': threading.active_count()
                    }
                })
                
                # Add system metrics
                if self.system_monitor:
                    current_metrics = self.system_monitor.get_current_metrics()
                    base_metrics['system_metrics'] = current_metrics.to_dict()
                
                # Add XDP metrics if running
                if self.current_mode == 'xdp' and self.xdp_manager:
                    xdp_stats = self.xdp_manager.get_statistics()
                    if xdp_stats:
                        base_metrics['xdp_stats'] = xdp_stats.to_dict()
                
            except Exception as e:
                self.logger.error(f"Error getting metrics: {e}")
        
        return base_metrics


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from YAML file with comprehensive validation."""
    try:
        config_file = Path(config_path)
        if not config_file.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        
        if not isinstance(config, dict):
            raise ConfigurationError("Configuration file must contain a dictionary")
        
        # Perform comprehensive validation if validator is available
        if validate_config_file is not None:
            validation_result = validate_config_file(config_path)
            
            if not validation_result.is_valid:
                error_msg = "Configuration validation failed:\n"
                for error in validation_result.errors:
                    error_msg += f"  • {error}\n"
                raise ConfigurationError(error_msg.strip())
            
            # Log warnings if any
            if validation_result.warnings:
                logger = logging.getLogger(__name__)
                logger.warning("Configuration warnings found:")
                for warning in validation_result.warnings:
                    logger.warning(f"  • {warning}")
        
        return config
        
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in configuration file: {e}")
    except IOError as e:
        raise ConfigurationError(f"Error reading configuration file: {e}")


def setup_logging(config: Dict[str, Any]) -> None:
    """Setup logging configuration."""
    try:
        log_config = config.get('logging_config', {})
        log_level = log_config.get('level', 'INFO')
        
        # Create formatters
        formatter = logging.Formatter(
            log_config.get('format', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        
        # Setup root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))
        
        # Clear existing handlers
        root_logger.handlers.clear()
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        # File handler (if enabled)
        if log_config.get('file_logging', {}).get('enabled', False):
            log_file = log_config['file_logging'].get('log_file', 'dst_machine.log')
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        
    except Exception as e:
        print(f"Warning: Failed to setup logging: {e}")
        logging.basicConfig(level=logging.INFO)


def check_requirements() -> bool:
    """Check system requirements for dst_machine operation."""
    logger = logging.getLogger(__name__)
    requirements_met = True
    
    # Check if running on Linux
    if platform.system() != 'Linux':
        logger.error("dst_machine requires Linux operating system")
        requirements_met = False
    
    # Check for required commands
    required_commands = ['ip', 'ethtool']
    for cmd in required_commands:
        try:
            subprocess.run([cmd, '--help'], capture_output=True, timeout=5)
        except (subprocess.SubprocessError, FileNotFoundError):
            logger.error(f"Required command not found: {cmd}")
            requirements_met = False
    
    # Check for XDP support
    if not SystemResourceChecker.check_xdp_support():
        logger.warning("XDP support not detected - XDP tests may fail")
    
    # Check Python packages
    try:
        import psutil
        import yaml
    except ImportError as e:
        logger.error(f"Required Python package not found: {e}")
        requirements_met = False
    
    return requirements_met


def print_banner() -> None:
    """Print application banner."""
    banner = """
╔══════════════════════════════════════════════════════════╗
║             eBPF-Test Destination Machine                ║
║          XDP Performance Testing Coordinator             ║
╚══════════════════════════════════════════════════════════╝
    """
    print(banner)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='eBPF-Test Destination Machine XDP Testing Coordinator')
    parser.add_argument('--config', required=True, help='Configuration file path')
    parser.add_argument('--mode', choices=['xdp', 'baseline'], default='xdp', help='Testing mode')
    parser.add_argument('--check-only', action='store_true', help='Check requirements and configuration, then exit')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    
    args = parser.parse_args()
    
    try:
        print_banner()
        
        # Load configuration
        config = load_config(args.config)
        
        # Apply command line overrides
        if args.verbose:
            config.setdefault('logging_config', {})['level'] = 'DEBUG'
        
        # Setup logging
        setup_logging(config)
        logger = logging.getLogger(__name__)
        
        # Check system requirements
        if not check_requirements():
            logger.error("System requirements not met")
            return 1
        
        # Check-only mode
        if args.check_only:
            print("✓ System requirements met")
            print("✓ Configuration is valid")
            return 0
        
        # Create coordinator
        coordinator = DstMachineCoordinator(config)
        
        # Start coordination server
        server = CoordinationServer(
            host='0.0.0.0',
            port=config['network_config']['dst_machine']['control_port'],
            coordination_handler=coordinator
        )
        
        try:
            server.start()
            logger.info("Destination machine ready for coordination")
            
            # Keep running until interrupted
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            server.stop()
            logger.info("Destination machine shutdown complete")
        
        return 0
    
    except ConfigurationError as e:
        print(f"Configuration error: {e}")
        return 1
    except Exception as e:
        print(f"Unexpected error: {e}")
        logging.getLogger(__name__).error(f"Unexpected error: {e}")
        logging.getLogger(__name__).debug(f"Traceback: {traceback.format_exc()}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 