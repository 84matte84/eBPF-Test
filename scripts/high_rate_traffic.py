#!/usr/bin/env python3
"""
High-Rate UDP Traffic Generator for eBPF-Test Phase 3
Designed for sustained high-throughput testing to fairly compare baseline vs XDP performance.
"""

import socket
import time
import threading
import argparse
import sys
import signal
import struct
import random
from concurrent.futures import ThreadPoolExecutor

class HighRateTrafficGenerator:
    def __init__(self, target_ip="127.0.0.1", base_port=12345, 
                 packet_size=100, target_pps=1000, duration=30, 
                 num_flows=1, num_threads=1):
        self.target_ip = target_ip
        self.base_port = base_port
        self.packet_size = packet_size
        self.target_pps = target_pps
        self.duration = duration
        self.num_flows = num_flows
        self.num_threads = num_threads
        
        # Statistics
        self.packets_sent = 0
        self.bytes_sent = 0
        self.errors = 0
        self.start_time = 0
        self.end_time = 0
        self.running = False
        
        # Thread synchronization
        self.stats_lock = threading.Lock()
        
        # Pre-generated payload for performance
        self.payload = self._generate_payload()
        
        # Signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        print(f"\nReceived signal {signum}, stopping traffic generation...")
        self.running = False
    
    def _generate_payload(self):
        """Generate a payload of the specified size."""
        # Create a realistic payload pattern
        base_pattern = b"eBPF-Test-Phase3-UDP-Packet-Data-"
        remaining = self.packet_size - len(base_pattern)
        
        if remaining <= 0:
            return base_pattern[:self.packet_size]
        
        # Fill remainder with pattern
        filler = (b"0123456789ABCDEF" * ((remaining // 16) + 1))[:remaining]
        return base_pattern + filler
    
    def _update_stats(self, packets=0, bytes_sent=0, errors=0):
        """Thread-safe statistics update."""
        with self.stats_lock:
            self.packets_sent += packets
            self.bytes_sent += bytes_sent
            self.errors += errors
    
    def _worker_thread(self, thread_id, packets_per_thread, delay_between_packets):
        """Worker thread for packet generation."""
        try:
            # Create socket for this thread
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            
            # Use different source ports for each flow
            flows = []
            for flow_id in range(self.num_flows):
                port = self.base_port + (thread_id * self.num_flows) + flow_id
                flows.append((self.target_ip, port))
            
            packets_sent_thread = 0
            bytes_sent_thread = 0
            errors_thread = 0
            flow_index = 0
            
            start_time = time.time()
            next_send_time = start_time
            
            while self.running and packets_sent_thread < packets_per_thread:
                current_time = time.time()
                
                # Rate limiting - wait if we're ahead of schedule
                if current_time < next_send_time:
                    sleep_time = next_send_time - current_time
                    if sleep_time > 0.001:  # Only sleep if > 1ms
                        time.sleep(sleep_time)
                
                try:
                    # Send packet to current flow
                    target = flows[flow_index]
                    sock.sendto(self.payload, target)
                    
                    packets_sent_thread += 1
                    bytes_sent_thread += len(self.payload)
                    
                    # Round-robin through flows
                    flow_index = (flow_index + 1) % len(flows)
                    
                except Exception as e:
                    errors_thread += 1
                    if errors_thread <= 10:  # Limit error printing
                        print(f"Thread {thread_id} send error: {e}")
                
                # Update next send time
                next_send_time += delay_between_packets
                
                # Periodic statistics update (every 1000 packets)
                if packets_sent_thread % 1000 == 0:
                    self._update_stats(1000, len(self.payload) * 1000, 0)
                    packets_sent_thread = 0  # Reset local counter
                    bytes_sent_thread = 0
            
            # Final statistics update
            if packets_sent_thread > 0:
                self._update_stats(packets_sent_thread, bytes_sent_thread, errors_thread)
            
            sock.close()
            
        except Exception as e:
            print(f"Worker thread {thread_id} failed: {e}")
            self._update_stats(0, 0, 1)
    
    def generate_traffic(self):
        """Main traffic generation method."""
        print(f"Starting high-rate traffic generation...")
        print(f"Target: {self.target_ip}:{self.base_port}+")
        print(f"Rate: {self.target_pps:,} pps for {self.duration} seconds")
        print(f"Flows: {self.num_flows}, Threads: {self.num_threads}")
        print(f"Packet size: {self.packet_size} bytes")
        
        # Calculate per-thread parameters
        pps_per_thread = self.target_pps // self.num_threads
        packets_per_thread = (pps_per_thread * self.duration) // self.num_threads
        delay_between_packets = 1.0 / pps_per_thread if pps_per_thread > 0 else 0.001
        
        print(f"Per thread: {pps_per_thread} pps, {packets_per_thread} packets, {delay_between_packets:.6f}s delay")
        print("\nTraffic generation starting in 3 seconds...")
        time.sleep(3)
        
        self.running = True
        self.start_time = time.time()
        
        # Start worker threads
        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            futures = []
            for thread_id in range(self.num_threads):
                future = executor.submit(self._worker_thread, thread_id, 
                                       packets_per_thread, delay_between_packets)
                futures.append(future)
            
            # Monitor progress
            last_stats_time = time.time()
            last_packets = 0
            
            while self.running and (time.time() - self.start_time) < self.duration:
                time.sleep(1)
                
                current_time = time.time()
                if current_time - last_stats_time >= 1.0:
                    with self.stats_lock:
                        elapsed = current_time - self.start_time
                        current_pps = (self.packets_sent - last_packets)
                        avg_pps = self.packets_sent / elapsed if elapsed > 0 else 0
                        
                        print(f"\rElapsed: {elapsed:.1f}s | "
                              f"Packets: {self.packets_sent:,} | "
                              f"Current: {current_pps:,} pps | "
                              f"Average: {avg_pps:.0f} pps | "
                              f"Errors: {self.errors}", end="", flush=True)
                        
                        last_packets = self.packets_sent
                        last_stats_time = current_time
            
            # Stop all threads
            self.running = False
            
            # Wait for threads to complete
            for future in futures:
                try:
                    future.result(timeout=5)
                except Exception as e:
                    print(f"\nThread completion error: {e}")
        
        self.end_time = time.time()
        self._print_final_stats()
    
    def _print_final_stats(self):
        """Print final traffic generation statistics."""
        elapsed = self.end_time - self.start_time
        actual_pps = self.packets_sent / elapsed if elapsed > 0 else 0
        actual_mbps = (self.bytes_sent * 8) / (elapsed * 1000000) if elapsed > 0 else 0
        
        print(f"\n\n===== TRAFFIC GENERATION RESULTS =====")
        print(f"Duration: {elapsed:.2f} seconds")
        print(f"Packets sent: {self.packets_sent:,}")
        print(f"Bytes sent: {self.bytes_sent:,}")
        print(f"Errors: {self.errors}")
        print(f"Target PPS: {self.target_pps:,}")
        print(f"Actual PPS: {actual_pps:.0f}")
        print(f"Efficiency: {(actual_pps/self.target_pps)*100:.1f}%")
        print(f"Throughput: {actual_mbps:.2f} Mbps")
        print(f"Packet size: {self.packet_size} bytes")
        print(f"Flows used: {self.num_flows}")
        print(f"Threads used: {self.num_threads}")
        print("======================================")

def create_preset_configs():
    """Define preset configurations for different test scenarios."""
    return {
        'low': {
            'target_pps': 100,
            'duration': 10,
            'num_flows': 1,
            'num_threads': 1,
            'description': 'Low rate for basic functionality testing'
        },
        'medium': {
            'target_pps': 1000,
            'duration': 30,
            'num_flows': 4,
            'num_threads': 2,
            'description': 'Medium rate for performance comparison'
        },
        'high': {
            'target_pps': 5000,
            'duration': 60,
            'num_flows': 8,
            'num_threads': 4,
            'description': 'High rate for stress testing'
        },
        'extreme': {
            'target_pps': 10000,
            'duration': 60,
            'num_flows': 16,
            'num_threads': 8,
            'description': 'Extreme rate for maximum performance testing'
        }
    }

def main():
    parser = argparse.ArgumentParser(
        description='High-Rate UDP Traffic Generator for eBPF-Test Phase 3',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --preset medium
  %(prog)s --rate 5000 --duration 60 --flows 8
  %(prog)s --target 192.168.1.100 --port 8080 --rate 1000
  %(prog)s --preset high --threads 8 --size 150
        """
    )
    
    # Preset configurations
    presets = create_preset_configs()
    parser.add_argument('--preset', choices=presets.keys(),
                       help='Use predefined configuration')
    
    # Basic parameters
    parser.add_argument('--target', default='127.0.0.1',
                       help='Target IP address (default: 127.0.0.1)')
    parser.add_argument('--port', type=int, default=12345,
                       help='Base UDP port (default: 12345)')
    parser.add_argument('--rate', type=int, default=1000,
                       help='Target packets per second (default: 1000)')
    parser.add_argument('--duration', type=int, default=30,
                       help='Duration in seconds (default: 30)')
    parser.add_argument('--size', type=int, default=100,
                       help='Packet size in bytes (default: 100)')
    
    # Advanced parameters
    parser.add_argument('--flows', type=int, default=1,
                       help='Number of UDP flows (different ports) (default: 1)')
    parser.add_argument('--threads', type=int, default=1,
                       help='Number of sender threads (default: 1)')
    
    # Display options
    parser.add_argument('--list-presets', action='store_true',
                       help='List available presets and exit')
    parser.add_argument('--verbose', action='store_true',
                       help='Verbose output')
    
    args = parser.parse_args()
    
    # List presets if requested
    if args.list_presets:
        print("Available presets:")
        for name, config in presets.items():
            print(f"  {name:8s}: {config['description']}")
            print(f"           Rate: {config['target_pps']:,} pps, "
                  f"Duration: {config['duration']}s, "
                  f"Flows: {config['num_flows']}, "
                  f"Threads: {config['num_threads']}")
        return
    
    # Apply preset if specified
    if args.preset:
        preset = presets[args.preset]
        if args.verbose:
            print(f"Using preset '{args.preset}': {preset['description']}")
        
        # Override with preset values (command line args take precedence)
        rate = preset['target_pps'] if args.rate == 1000 else args.rate  # 1000 is default
        duration = preset['duration'] if args.duration == 30 else args.duration  # 30 is default
        flows = preset['num_flows'] if args.flows == 1 else args.flows  # 1 is default
        threads = preset['num_threads'] if args.threads == 1 else args.threads  # 1 is default
    else:
        rate = args.rate
        duration = args.duration
        flows = args.flows
        threads = args.threads
    
    # Validation
    if rate <= 0:
        print("Error: Rate must be positive")
        sys.exit(1)
    if duration <= 0:
        print("Error: Duration must be positive")
        sys.exit(1)
    if args.size < 20:
        print("Error: Packet size must be at least 20 bytes")
        sys.exit(1)
    
    # Create and run traffic generator
    generator = HighRateTrafficGenerator(
        target_ip=args.target,
        base_port=args.port,
        packet_size=args.size,
        target_pps=rate,
        duration=duration,
        num_flows=flows,
        num_threads=threads
    )
    
    try:
        generator.generate_traffic()
    except KeyboardInterrupt:
        print("\nTraffic generation interrupted by user")
    except Exception as e:
        print(f"\nTraffic generation failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 