#!/usr/bin/env python3
"""
Source Machine Traffic Generator for eBPF-Test Two-Machine Testing

Cross-platform (Linux/macOS) UDP traffic generator with real-time coordination
for authentic network performance testing of XDP/eBPF systems.

Features:
- High-performance multi-threaded traffic generation
- Real-time coordination with dst_machine
- Cross-platform compatibility (Linux/macOS)
- Configurable traffic patterns and rates
- Comprehensive monitoring and reporting

Author: eBPF-Test Project
License: MIT
"""

import os
import sys
import time
import json
import yaml
import socket
import signal
import logging
import platform
import threading
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
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
class TrafficGenerationError(Exception):
    """Exception for traffic generation related errors."""
    pass


class ConfigurationError(Exception):
    """Exception for configuration related errors."""
    pass


@dataclass
class TrafficStats:
    """Statistics for traffic generation."""
    packets_sent: int = 0
    bytes_sent: int = 0
    packets_failed: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
    thread_id: int = 0
    flow_id: int = 0
    
    @property
    def duration(self) -> float:
        """Calculate duration."""
        return max(0.001, self.end_time - self.start_time) if self.end_time > 0 else 0.0
    
    @property
    def pps(self) -> float:
        """Calculate packets per second."""
        return self.packets_sent / self.duration if self.duration > 0 else 0.0
    
    @property
    def mbps(self) -> float:
        """Calculate megabits per second."""
        return (self.bytes_sent * 8) / (self.duration * 1_000_000) if self.duration > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)


@dataclass
class TrafficConfig:
    """Configuration for traffic generation."""
    target_ip: str
    traffic_ports: List[int]
    packet_rate: int
    packet_size: int
    flows: int
    threads: int
    duration: int
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'TrafficConfig':
        """Create TrafficConfig from dictionary."""
        try:
            return cls(
                target_ip=config['network_config']['dst_machine']['ip'],
                traffic_ports=config['network_config']['traffic_ports'],
                packet_rate=config['traffic_config']['packet_rate'],
                packet_size=config['traffic_config']['packet_size'],
                flows=config['traffic_config']['flows'],
                threads=config['traffic_config']['threads'],
                duration=config['test_config']['duration']
            )
        except KeyError as e:
            raise ConfigurationError(f"Missing required configuration key: {e}")
        except (TypeError, ValueError) as e:
            raise ConfigurationError(f"Invalid configuration value: {e}")
    
    def validate(self) -> None:
        """Validate configuration parameters."""
        if not self.target_ip:
            raise ConfigurationError("Target IP cannot be empty")
        
        if self.packet_rate <= 0:
            raise ConfigurationError("Packet rate must be positive")
        
        if self.packet_size <= 0 or self.packet_size > 9000:
            raise ConfigurationError("Packet size must be between 1 and 9000 bytes")
        
        if self.flows <= 0:
            raise ConfigurationError("Number of flows must be positive")
        
        if self.threads <= 0 or self.threads > 64:
            raise ConfigurationError("Number of threads must be between 1 and 64")
        
        if self.duration <= 0:
            raise ConfigurationError("Duration must be positive")
        
        if not self.traffic_ports:
            raise ConfigurationError("Traffic ports list cannot be empty")


class PayloadGenerator:
    """Utility class for generating realistic packet payloads."""
    
    @staticmethod
    def generate_payload(packet_size: int, pattern: Optional[str] = None) -> bytes:
        """Generate realistic packet payload."""
        if pattern is None:
            pattern = f"eBPF-Test-SrcMachine-{datetime.now().strftime('%Y%m%d')}-"
        
        # Calculate effective payload size
        header_overhead = 42  # Ethernet(14) + IP(20) + UDP(8)
        effective_payload_size = max(64, packet_size - header_overhead)
        
        # Create repeating pattern
        pattern_bytes = pattern.encode('ascii')
        repetitions = (effective_payload_size // len(pattern_bytes)) + 1
        payload = (pattern_bytes * repetitions)[:effective_payload_size]
        
        return payload


class SocketManager:
    """Manages socket creation and configuration for traffic generation."""
    
    @staticmethod
    def create_socket() -> socket.socket:
        """Create and configure a UDP socket for traffic generation."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Set socket buffer sizes for better performance
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
            
            # Platform-specific optimizations
            if platform.system() == 'Linux':
                # On Linux, we can set additional socket options
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except (OSError, AttributeError):
                    pass  # Not available on all Linux versions
            
            return sock
            
        except OSError as e:
            raise TrafficGenerationError(f"Failed to create socket: {e}")


class TrafficGenerator:
    """High-performance UDP traffic generator."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        self.logger = logging.getLogger(f"{__name__}.TrafficGenerator")
        
        try:
            # Parse and validate configuration
            self.traffic_config = TrafficConfig.from_config(config)
            self.traffic_config.validate()
        except (ConfigurationError, ValidationError) as e:
            self.logger.error(f"Configuration error: {e}")
            raise
        
        # Control flags
        self.running = False
        self.stop_event = threading.Event()
        
        # Statistics
        self.stats_lock = threading.Lock()
        self.thread_stats: List[TrafficStats] = []
        self.total_stats = TrafficStats()
        
        # Pre-generate payload for performance
        self.payload = PayloadGenerator.generate_payload(self.traffic_config.packet_size)
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        self.logger.debug(f"TrafficGenerator initialized: {self.traffic_config}")
    
    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        self.logger.info(f"Received signal {signum}, stopping traffic generation...")
        self.stop()
    
    def _create_flow_targets(self) -> List[Tuple[str, int]]:
        """Create list of flow targets (IP, port) combinations."""
        targets = []
        for i in range(self.traffic_config.flows):
            port = self.traffic_config.traffic_ports[i % len(self.traffic_config.traffic_ports)]
            targets.append((self.traffic_config.target_ip, port))
        return targets
    
    def _calculate_thread_parameters(self) -> Tuple[int, int]:
        """Calculate per-thread packet rate and total packets."""
        pps_per_thread = max(1, self.traffic_config.packet_rate // self.traffic_config.threads)
        total_packets = self.traffic_config.packet_rate * self.traffic_config.duration
        packets_per_thread = max(1, total_packets // self.traffic_config.threads)
        
        return pps_per_thread, packets_per_thread
    
    def _worker_thread(
        self, 
        thread_id: int, 
        pps_per_thread: int, 
        packets_per_thread: int
    ) -> TrafficStats:
        """Worker thread for traffic generation."""
        stats = TrafficStats(thread_id=thread_id, start_time=time.time())
        sock: Optional[socket.socket] = None
        
        try:
            # Create socket for this thread
            sock = SocketManager.create_socket()
            
            # Calculate timing parameters
            delay_between_packets = 1.0 / pps_per_thread if pps_per_thread > 0 else 0.001
            next_send_time = time.time()
            
            # Setup flow targets
            flow_targets = self._create_flow_targets()
            flow_index = 0
            packets_sent = 0
            
            self.logger.debug(
                f"Thread {thread_id} starting: {pps_per_thread} pps, "
                f"{packets_per_thread} packets, {len(flow_targets)} flows"
            )
            
            while (not self.stop_event.is_set() and 
                   packets_sent < packets_per_thread and 
                   self.running):
                
                current_time = time.time()
                
                # Rate limiting - wait if we're ahead of schedule
                if current_time < next_send_time:
                    sleep_time = next_send_time - current_time
                    if sleep_time > 0.001:  # Only sleep for significant delays
                        time.sleep(sleep_time)
                
                try:
                    # Send packet to current flow
                    target = flow_targets[flow_index % len(flow_targets)]
                    sock.sendto(self.payload, target)
                    
                    packets_sent += 1
                    stats.packets_sent += 1
                    stats.bytes_sent += len(self.payload)
                    
                    # Move to next flow (round-robin)
                    flow_index += 1
                    
                except OSError as e:
                    stats.packets_failed += 1
                    if stats.packets_failed <= 10:  # Limit error logging
                        self.logger.warning(f"Thread {thread_id} send error: {e}")
                except Exception as e:
                    stats.packets_failed += 1
                    self.logger.error(f"Thread {thread_id} unexpected error: {e}")
                
                # Update next send time
                next_send_time += delay_between_packets
                
                # Periodic progress update
                if packets_sent % 10000 == 0 and packets_sent > 0:
                    elapsed = time.time() - stats.start_time
                    actual_pps = packets_sent / elapsed if elapsed > 0 else 0
                    self.logger.debug(f"Thread {thread_id}: {packets_sent} packets, "
                                    f"{actual_pps:.0f} pps")
            
            stats.end_time = time.time()
            
            self.logger.info(f"Thread {thread_id} completed: {stats.packets_sent} packets "
                           f"in {stats.duration:.2f}s ({stats.pps:.0f} pps)")
            
        except Exception as e:
            self.logger.error(f"Thread {thread_id} failed: {e}")
            self.logger.debug(f"Thread {thread_id} traceback: {traceback.format_exc()}")
            stats.end_time = time.time()
        finally:
            if sock:
                sock.close()
        
        return stats
    
    def start(self) -> bool:
        """Start traffic generation."""
        if self.running:
            self.logger.warning("Traffic generation already running")
            return False
        
        try:
            self.logger.info("Starting traffic generation...")
            self.logger.info(f"Target: {self.traffic_config.target_ip}")
            self.logger.info(f"Rate: {self.traffic_config.packet_rate:,} pps for {self.traffic_config.duration} seconds")
            self.logger.info(f"Packet size: {self.traffic_config.packet_size} bytes")
            self.logger.info(f"Flows: {self.traffic_config.flows}, Threads: {self.traffic_config.threads}")
            
            # Calculate per-thread parameters
            pps_per_thread, packets_per_thread = self._calculate_thread_parameters()
            
            self.logger.info(f"Per thread: {pps_per_thread} pps, {packets_per_thread} packets")
            
            # Reset statistics
            self.thread_stats.clear()
            self.total_stats = TrafficStats(start_time=time.time())
            
            self.running = True
            self.stop_event.clear()
            
            # Start worker threads
            with ThreadPoolExecutor(max_workers=self.traffic_config.threads) as executor:
                # Submit all worker tasks
                futures = []
                for thread_id in range(self.traffic_config.threads):
                    future = executor.submit(
                        self._worker_thread, 
                        thread_id, 
                        pps_per_thread, 
                        packets_per_thread
                    )
                    futures.append(future)
                
                # Monitor progress and collect results
                completed_threads = 0
                for future in as_completed(futures):
                    try:
                        stats = future.result()
                        with self.stats_lock:
                            self.thread_stats.append(stats)
                        completed_threads += 1
                        
                        self.logger.debug(f"Thread completed ({completed_threads}/{self.traffic_config.threads})")
                        
                    except Exception as e:
                        self.logger.error(f"Thread execution error: {e}")
            
            # Calculate total statistics
            self._calculate_total_stats()
            
            self.logger.info("Traffic generation completed successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Traffic generation failed: {e}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            self.running = False
    
    def stop(self) -> None:
        """Stop traffic generation."""
        if not self.running:
            return
        
        self.logger.info("Stopping traffic generation...")
        self.running = False
        self.stop_event.set()
    
    def _calculate_total_stats(self) -> None:
        """Calculate aggregated statistics from all threads."""
        with self.stats_lock:
            if not self.thread_stats:
                return
            
            self.total_stats.end_time = time.time()
            
            # Aggregate from all threads
            for stats in self.thread_stats:
                self.total_stats.packets_sent += stats.packets_sent
                self.total_stats.bytes_sent += stats.bytes_sent
                self.total_stats.packets_failed += stats.packets_failed
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get comprehensive traffic statistics."""
        with self.stats_lock:
            # Thread-level statistics
            thread_data = []
            pps_values = []
            
            for stats in self.thread_stats:
                thread_data.append(stats.to_dict())
                if stats.pps > 0:
                    pps_values.append(stats.pps)
            
            # Calculate statistics
            total_pps = self.total_stats.pps
            avg_pps = statistics.mean(pps_values) if pps_values else 0
            pps_stddev = statistics.stdev(pps_values) if len(pps_values) > 1 else 0
            
            # Calculate efficiency
            target_pps = self.traffic_config.packet_rate
            efficiency_percent = (total_pps / target_pps * 100) if target_pps > 0 else 0
            
            return {
                'summary': {
                    'total_packets_sent': self.total_stats.packets_sent,
                    'total_bytes_sent': self.total_stats.bytes_sent,
                    'total_packets_failed': self.total_stats.packets_failed,
                    'duration': self.total_stats.duration,
                    'target_pps': target_pps,
                    'actual_pps': total_pps,
                    'efficiency_percent': efficiency_percent,
                    'throughput_mbps': self.total_stats.mbps,
                    'packet_size': self.traffic_config.packet_size,
                    'flows': self.traffic_config.flows,
                    'threads': self.traffic_config.threads
                },
                'performance': {
                    'average_pps_per_thread': avg_pps,
                    'pps_standard_deviation': pps_stddev,
                    'thread_efficiency': (avg_pps * self.traffic_config.threads / target_pps * 100) if target_pps > 0 else 0
                },
                'threads': thread_data,
                'configuration': asdict(self.traffic_config)
            }


class SrcMachineCoordinator(CoordinationHandler):
    """Coordination handler for src_machine functionality."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        super().__init__()
        self.logger = logging.getLogger(f"{__name__}.SrcMachineCoordinator")
        
        self.traffic_generator: Optional[TrafficGenerator] = None
        self.test_active = False
        self.test_thread: Optional[threading.Thread] = None
        
        # Update initial status and config
        self.status = "ready"
        self.config.update(config)
        
        self.logger.info("SrcMachineCoordinator initialized")
    
    def start_test(self, test_params: Dict[str, Any]) -> bool:
        """Start traffic generation test."""
        if self.test_active:
            self.logger.warning("Test already active")
            return False
        
        try:
            self.logger.info("Starting traffic generation test")
            self.status = "running"
            
            # Merge test parameters with existing config
            test_config = self.config.copy()
            if test_params:
                # Deep merge for nested dictionaries
                for key, value in test_params.items():
                    if isinstance(value, dict) and key in test_config:
                        test_config[key].update(value)
                    else:
                        test_config[key] = value
            
            # Validate merged configuration
            try:
                traffic_config = TrafficConfig.from_config(test_config)
                traffic_config.validate()
            except (ConfigurationError, ValidationError) as e:
                self.logger.error(f"Invalid test configuration: {e}")
                self.status = "failed"
                return False
            
            # Create traffic generator
            self.traffic_generator = TrafficGenerator(test_config)
            
            # Start traffic generation in background thread
            def run_traffic() -> None:
                try:
                    if self.traffic_generator is not None:
                        success = self.traffic_generator.start()
                        if success:
                            self.results = self.traffic_generator.get_statistics()
                            self.status = "completed"
                        else:
                            self.status = "failed"
                    else:
                        self.status = "failed"
                except Exception as e:
                    self.logger.error(f"Traffic generation error: {e}")
                    self.status = "failed"
                finally:
                    self.test_active = False
            
            self.test_thread = threading.Thread(target=run_traffic, daemon=True, name="TrafficGenThread")
            self.test_thread.start()
            
            self.test_active = True
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start test: {e}")
            self.logger.debug(f"Traceback: {traceback.format_exc()}")
            self.status = "failed"
            return False
    
    def stop_test(self, stop_params: Dict[str, Any]) -> Dict[str, Any]:
        """Stop traffic generation test."""
        if not self.test_active or not self.traffic_generator:
            self.logger.warning("No active test to stop")
            return {}
        
        try:
            self.logger.info("Stopping traffic generation test")
            self.traffic_generator.stop()
            
            # Wait for test thread to complete
            if self.test_thread and self.test_thread.is_alive():
                self.test_thread.join(timeout=10.0)
                if self.test_thread.is_alive():
                    self.logger.warning("Test thread did not complete within timeout")
            
            # Get final results
            final_results = self.traffic_generator.get_statistics()
            self.results.update(final_results)
            
            self.status = "stopped"
            self.test_active = False
            
            return final_results
            
        except Exception as e:
            self.logger.error(f"Error stopping test: {e}")
            self.status = "failed"
            return {}
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get real-time metrics during test execution."""
        base_metrics = super().get_metrics()
        
        if self.traffic_generator and self.test_active:
            try:
                traffic_metrics = self.traffic_generator.get_statistics()
                base_metrics.update({
                    'traffic_generation': traffic_metrics,
                    'test_active': self.test_active,
                    'system_info': {
                        'platform': platform.platform(),
                        'python_version': platform.python_version(),
                        'thread_count': threading.active_count()
                    }
                })
            except Exception as e:
                self.logger.error(f"Error getting traffic metrics: {e}")
        
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
            log_file = log_config['file_logging'].get('log_file', 'src_machine.log')
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        
    except Exception as e:
        print(f"Warning: Failed to setup logging: {e}")
        logging.basicConfig(level=logging.INFO)


def print_banner() -> None:
    """Print application banner."""
    banner = """
╔══════════════════════════════════════════════════════════╗
║              eBPF-Test Source Machine                    ║
║           High-Performance Traffic Generator             ║
╚══════════════════════════════════════════════════════════╝
    """
    print(banner)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description='eBPF-Test Source Machine Traffic Generator')
    parser.add_argument('--config', required=True, help='Configuration file path')
    parser.add_argument('--preset', help='Configuration preset to use')
    parser.add_argument('--dst-ip', help='Override destination IP')
    parser.add_argument('--rate', type=int, help='Override packet rate')
    parser.add_argument('--duration', type=int, help='Override test duration')
    parser.add_argument('--no-coordination', action='store_true', help='Run without coordination')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose output')
    parser.add_argument('--check-only', action='store_true', help='Check configuration and exit')
    
    args = parser.parse_args()
    
    try:
        print_banner()
        
        # Load configuration
        config = load_config(args.config)
        
        # Apply preset if specified
        if args.preset:
            presets = config.get('presets', {})
            if args.preset not in presets:
                print(f"Error: Preset '{args.preset}' not found")
                return 1
            
            preset_config = presets[args.preset]
            # Deep merge preset configuration
            for key, value in preset_config.items():
                if isinstance(value, dict) and key in config:
                    config[key].update(value)
                else:
                    config[key] = value
        
        # Apply command line overrides
        if args.dst_ip:
            config['network_config']['dst_machine']['ip'] = args.dst_ip
        if args.rate:
            config['traffic_config']['packet_rate'] = args.rate
        if args.duration:
            config['test_config']['duration'] = args.duration
        if args.verbose:
            config.setdefault('logging_config', {})['level'] = 'DEBUG'
        
        # Setup logging
        setup_logging(config)
        logger = logging.getLogger(__name__)
        
        # Validate configuration
        try:
            traffic_config = TrafficConfig.from_config(config)
            traffic_config.validate()
            logger.info("Configuration validation successful")
        except (ConfigurationError, ValidationError) as e:
            logger.error(f"Configuration validation failed: {e}")
            return 1
        
        # Check-only mode
        if args.check_only:
            print("✓ Configuration is valid")
            return 0
        
        if args.no_coordination:
            # Run standalone traffic generation
            logger.info("Running in standalone mode (no coordination)")
            generator = TrafficGenerator(config)
            success = generator.start()
            
            if success:
                stats = generator.get_statistics()
                logger.info("Traffic generation completed successfully")
                print(json.dumps(stats, indent=2))
                return 0
            else:
                logger.error("Traffic generation failed")
                return 1
        else:
            # Run with coordination
            coordinator = SrcMachineCoordinator(config)
            
            # Start coordination server
            server = CoordinationServer(
                host='0.0.0.0',
                port=config['network_config']['src_machine']['control_port'],
                coordination_handler=coordinator
            )
            
            try:
                server.start()
                logger.info("Source machine ready for coordination")
                
                # Keep running until interrupted
                while True:
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                logger.info("Received interrupt signal")
            finally:
                server.stop()
                logger.info("Source machine shutdown complete")
            
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