#!/usr/bin/env python3
"""
Minimal SocketCAN test for Raspberry Pi
Tests direct socket writing performance vs cansend command
"""

import socket
import struct
import time

class CANSocket:
    """Direct SocketCAN interface - bypasses cansend overhead"""
    
    # CAN frame format constants
    CAN_EFF_FLAG = 0x80000000  # Extended Frame Format flag
    CAN_RTR_FLAG = 0x40000000  # Remote Transmission Request flag
    CAN_ERR_FLAG = 0x20000000  # Error frame flag
    
    def __init__(self, interface='pican2'):
        """Initialize CAN socket on specified interface"""
        self.interface = interface
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            self.sock.bind((interface,))
            print(f"✓ Bound to CAN interface: {interface}")
        except OSError as e:
            print(f"✗ Failed to bind to {interface}: {e}")
            print("  Make sure the interface is up: sudo ip link set pican2 up type can bitrate 250000")
            raise
    
    def send(self, can_id, data, extended=False):
        """
        Send a CAN frame directly via socket
        
        Args:
            can_id: CAN identifier (11-bit standard or 29-bit extended)
            data: bytes object with payload (max 8 bytes)
            extended: True for 29-bit extended ID, False for 11-bit standard
        """
        if len(data) > 8:
            raise ValueError("CAN data cannot exceed 8 bytes")
        
        # Set extended flag if needed
        can_id_flags = can_id
        if extended:
            can_id_flags |= self.CAN_EFF_FLAG
        
        # Pack CAN frame: ID (4 bytes), DLC (1 byte), padding (3 bytes), data (8 bytes)
        frame = struct.pack("=IB3x8s", 
                           can_id_flags,
                           len(data),
                           data.ljust(8, b'\x00'))
        
        self.sock.send(frame)
    
    def close(self):
        """Close the socket"""
        self.sock.close()


def performance_test(interface='pican2', num_messages=1000):
    """
    Test SocketCAN performance by sending messages as fast as possible
    """
    print(f"\n{'='*60}")
    print(f"SocketCAN Performance Test")
    print(f"{'='*60}")
    print(f"Interface: {interface}")
    print(f"Messages: {num_messages}")
    print(f"{'='*60}\n")
    
    can = CANSocket(interface)
    
    # Test 1: Maximum throughput
    print("Test 1: Maximum throughput (no delay)")
    payload = 0x01AA
    start_time = time.time()
    
    for i in range(num_messages):
        # Create 2-byte payload
        data = struct.pack(">H", payload)
        can.send(0x001, data)
        payload = (payload + 1) & 0xFFFF
    
    elapsed = time.time() - start_time
    fps = num_messages / elapsed
    avg_time_us = (elapsed / num_messages) * 1_000_000
    
    print(f"  Time: {elapsed:.3f} seconds")
    print(f"  Rate: {fps:.1f} frames/second")
    print(f"  Avg per frame: {avg_time_us:.1f} μs")
    print(f"  Bus utilization: {(fps/3289)*100:.1f}% of theoretical max @ 250kbps\n")
    
    # Test 2: Simulated 10ms periodic messages (like your use case)
    print("Test 2: Periodic messages (10ms interval, like your gateway)")
    payload = 0x02AA
    num_periodic = 100
    start_time = time.time()
    
    for i in range(num_periodic):
        send_start = time.time()
        data = struct.pack(">H", payload)
        can.send(0x123, data)
        payload = (payload + 1) & 0xFFFF
        
        # Sleep to maintain 10ms period
        elapsed_msg = time.time() - send_start
        sleep_time = max(0, 0.010 - elapsed_msg)
        time.sleep(sleep_time)
    
    total_elapsed = time.time() - start_time
    actual_rate = num_periodic / total_elapsed
    
    print(f"  Target rate: 100 fps (10ms period)")
    print(f"  Actual rate: {actual_rate:.1f} fps")
    print(f"  Average send time: {(elapsed_msg * 1000):.3f} ms")
    print(f"  Jitter: {abs(100 - actual_rate):.1f} fps\n")
    
    # Test 3: Burst test
    print("Test 3: Burst of 50 messages")
    payload = 0x03AA
    start_time = time.time()
    
    for i in range(50):
        data = struct.pack(">H", payload)
        can.send(0x456, data)
        payload = (payload + 1) & 0xFFFF
    
    burst_elapsed = time.time() - start_time
    burst_rate = 50 / burst_elapsed
    
    print(f"  Burst time: {burst_elapsed*1000:.2f} ms")
    print(f"  Burst rate: {burst_rate:.1f} frames/second")
    print(f"  Time per frame: {(burst_elapsed/50)*1000:.3f} ms\n")
    
    can.close()
    
    print(f"{'='*60}")
    print("✓ Test complete!")
    print(f"{'='*60}\n")
    
    print("Comparison with cansend command:")
    print(f"  cansend overhead: ~2.4 ms per frame (~417 fps max)")
    print(f"  Direct socket: ~{avg_time_us/1000:.3f} ms per frame (~{fps:.0f} fps)")
    print(f"  Speedup: {2.4/(avg_time_us/1000):.0f}x faster! 🚀\n")


def simple_test(interface='pican2'):
    """
    Simple test - send a few messages and verify they appear
    Run 'candump -xt any' in another terminal to see the output
    """
    print(f"\n{'='*60}")
    print("Simple SocketCAN Test")
    print("Run 'candump -xt any' in another terminal to see messages")
    print(f"{'='*60}\n")
    
    can = CANSocket(interface)
    
    print("Sending 5 test messages...")
    for i in range(5):
        data = bytes([0x01, 0xAA + i, 0xBB, 0xCC])
        can.send(0x123, data)
        print(f"  Sent: ID=0x123 Data=[{' '.join(f'{b:02X}' for b in data)}]")
        time.sleep(0.5)
    
    can.close()
    print("\n✓ Test complete!\n")


if __name__ == "__main__":
    import sys
    
    # Check command line arguments
    if len(sys.argv) > 1:
        interface = sys.argv[1]
    else:
        interface = 'pican2'
    
    try:
        # Run simple test first
        simple_test(interface)
        
        # Then performance test
        response = input("Run performance test? (y/n): ")
        if response.lower() == 'y':
            performance_test(interface)
    
    except KeyboardInterrupt:
        print("\n\n✗ Test interrupted by user")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nTroubleshooting:")
        print("  1. Check interface is up: ip link show pican2")
        print("  2. Bring it up: sudo ip link set pican2 up type can bitrate 250000")
        print("  3. Check permissions: sudo usermod -a -G dialout $USER")