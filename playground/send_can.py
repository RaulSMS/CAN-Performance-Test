import can
import time
import random
import sys

# --- Configuration ---
# Interface name is 'pican1' as specified in your setup command
CAN_INTERFACE = 'pican1'
# Bus type for SocketCAN on Linux
CAN_BUS_TYPE = 'socketcan'
# Sending interval in seconds (500 ms)
SEND_INTERVAL = 0.5 

def send_random_can_messages():
    """
    Initializes the CAN bus and sends random messages every 500 ms.
    """
    try:
        # 1. Initialize the CAN Bus
        # The script connects to the existing 'pican1' interface.
        bus = can.interface.Bus(channel=CAN_INTERFACE, bustype=CAN_BUS_TYPE)
        print(f"Successfully connected to CAN interface: {CAN_INTERFACE}")
        print("Sending random messages every 500ms. Press Ctrl+C to stop.")

        message_count = 0
        
        while True:
            # 2. Generate a random CAN message
            # Standard CAN ID (11-bit), from 0x100 to 0x7FF
            message_id = random.randint(0x100, 0x7FF) 
            # 8 bytes of random data (0-255)
            data = bytes([random.randint(0, 255) for _ in range(8)]) 
            
            # Create the Message object
            msg = can.Message(
                arbitration_id=message_id,
                data=data,
                is_extended_id=False  # Use standard 11-bit ID
            )
            
            # 3. Send the message
            bus.send(msg)
            message_count += 1

            print(f"[{message_count:04d}] Sent: ID={hex(msg.arbitration_id)}, Data={msg.data.hex()}")
            
            # 4. Wait for the specified interval
            time.sleep(SEND_INTERVAL)

    except can.exceptions.CanError as e:
        print(f"\nCAN Error: Could not connect to interface '{CAN_INTERFACE}'.")
        print("Please ensure the interface is configured and active. Run:")
        print(f"  sudo ip link set {CAN_INTERFACE} up type can bitrate 250000 restart-ms 10")
        print(f"Error details: {e}")
        sys.exit(1)
        
    except KeyboardInterrupt:
        print("\nStopping message sending...")
        
    finally:
        # 5. Clean up and shut down the bus connection
        if 'bus' in locals():
            bus.shutdown()
            print("CAN bus shut down.")

if __name__ == "__main__":
    send_random_can_messages()