import can
import time

# Configure the CAN BUS
can_interface = 'pican1'
bus = can.interface.Bus(can_interface, bustype='socketcan')

# Configure the Message  to be sent
msg = can.Message(arbitration_id=0x123, data=[0x11]*8, is_extended_id=False)

# Send Send_Frames messages in Send_Time secconds
Send_Frames     = 3000
Send_Time       = 1
# As indication. in a 250 KBaud BUS, we can theoretically send ~ 2293 frames/second
Send_delay = (Send_Time/Send_Frames)*0.8    #There is some delay introduced already on the sending, so we reduce the extra delay by approx 80%
OK_Frames       = 0
Error_Frames    = 0

# Open bus
try: 
    start_time = time.time()
    for _ in range(Send_Frames):
        try:
            bus.send(msg)
            OK_Frames+=1
            time.sleep(Send_delay)
        except can.CanError as e:
            Error_Frames+=1
            print(f"Error sending frame: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
finally:
    end_time = time.time()
    delta_time = end_time - start_time
    print(f"Total time to send {Send_Frames} messages: {delta_time} seconds")
    print(f"Mean sent rate: {Send_Frames/delta_time} frames per second")
    print(f"Ok_Frames = {OK_Frames}")
    print(f"Error_Frames = {Error_Frames}")
    
    bus.shutdown()