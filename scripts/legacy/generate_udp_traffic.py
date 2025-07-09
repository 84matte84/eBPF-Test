#!/usr/bin/env python3

"""
UDP Traffic Generator for eBPF-Test Baseline Testing
Generates configurable UDP traffic to test packet processing performance
"""

import socket
import time
import argparse
import sys
import threading
from datetime import datetime

def generate_udp_traffic(target_ip, target_port, source_port, packet_size, packets_per_second, duration, payload_pattern="A"):
    """Generate UDP traffic with specified parameters"""
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('', source_port))
    
    # Create payload
    payload = (payload_pattern * (packet_size // len(payload_pattern) + 1))[:packet_size]
    payload_bytes = payload.encode('ascii')
    
    print(f"Generating UDP traffic:")
    print(f"  Target: {target_ip}:{target_port}")
    print(f"  Source port: {source_port}")
    print(f"  Packet size: {packet_size} bytes")
    print(f"  Rate: {packets_per_second} packets/sec")
    print(f"  Duration: {duration} seconds")
    print(f"  Total packets: {packets_per_second * duration}")
    
    start_time = time.time()
    packets_sent = 0
    
    try:
        while time.time() - start_time < duration:
            # Send packet
            sock.sendto(payload_bytes, (target_ip, target_port))
            packets_sent += 1
            
            # Rate limiting
            if packets_per_second > 0:
                time.sleep(1.0 / packets_per_second)
            
            # Progress update every 1000 packets
            if packets_sent % 1000 == 0:
                elapsed = time.time() - start_time
                actual_rate = packets_sent / elapsed if elapsed > 0 else 0
                print(f"\rSent: {packets_sent}, Rate: {actual_rate:.1f} pps", end='', flush=True)
                
    except KeyboardInterrupt:
        print("\nTraffic generation interrupted by user")
    finally:
        sock.close()
        
    elapsed = time.time() - start_time
    actual_rate = packets_sent / elapsed if elapsed > 0 else 0
    
    print(f"\n\nTraffic generation complete:")
    print(f"  Packets sent: {packets_sent}")
    print(f"  Duration: {elapsed:.2f} seconds") 
    print(f"  Actual rate: {actual_rate:.2f} packets/sec")

def run_multiple_flows(flows, duration):
    """Run multiple concurrent UDP flows"""
    
    print(f"Starting {len(flows)} concurrent UDP flows for {duration} seconds...")
    
    threads = []
    
    for i, flow in enumerate(flows):
        thread = threading.Thread(
            target=generate_udp_traffic,
            args=(flow['ip'], flow['port'], flow['src_port'], 
                  flow['size'], flow['rate'], duration, f"Flow{i}")
        )
        threads.append(thread)
    
    # Start all threads
    start_time = time.time()
    for thread in threads:
        thread.start()
    
    # Wait for completion
    for thread in threads:
        thread.join()
        
    elapsed = time.time() - start_time
    print(f"\nAll flows completed in {elapsed:.2f} seconds")

def main():
    parser = argparse.ArgumentParser(description='Generate UDP traffic for eBPF testing')
    
    # Basic parameters
    parser.add_argument('--target-ip', default='127.0.0.1', help='Target IP address')
    parser.add_argument('--target-port', type=int, default=12345, help='Target port')
    parser.add_argument('--source-port', type=int, default=54321, help='Source port')
    parser.add_argument('--packet-size', type=int, default=100, help='Packet size in bytes')
    parser.add_argument('--rate', type=int, default=1000, help='Packets per second (0 = unlimited)')
    parser.add_argument('--duration', type=int, default=10, help='Duration in seconds')
    
    # Advanced parameters
    parser.add_argument('--multiple-flows', type=int, default=1, help='Number of concurrent flows')
    parser.add_argument('--port-range', type=int, default=1, help='Port range for multiple flows')
    
    # Presets
    parser.add_argument('--preset', choices=['low', 'medium', 'high', 'stress'], 
                       help='Traffic presets: low(100pps), medium(1Kpps), high(10Kpps), stress(100Kpps)')
    
    args = parser.parse_args()
    
    # Apply presets
    if args.preset == 'low':
        args.rate = 100
    elif args.preset == 'medium':
        args.rate = 1000
    elif args.preset == 'high':
        args.rate = 10000
    elif args.preset == 'stress':
        args.rate = 100000
    
    try:
        if args.multiple_flows > 1:
            # Generate multiple flows
            flows = []
            for i in range(args.multiple_flows):
                flows.append({
                    'ip': args.target_ip,
                    'port': args.target_port + (i % args.port_range), 
                    'src_port': args.source_port + i,
                    'size': args.packet_size,
                    'rate': args.rate // args.multiple_flows  # Distribute rate across flows
                })
            run_multiple_flows(flows, args.duration)
        else:
            # Single flow
            generate_udp_traffic(
                args.target_ip, args.target_port, args.source_port,
                args.packet_size, args.rate, args.duration
            )
            
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main() 