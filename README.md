# CAN-Performance-Test

Python script using cantools to send several CAN frames.
It can be used to check on the target how many frames are lost.

## Dependencies

```bash
sudo apt install python3-pip
pip install python-can
```

## Observations

On a raspberry pi

### cansend

Max cansend in a loop (even with 1Mb baudrate)

- ~3ms in between messages
- 350 messages/ second

```bash
 (000.003590)  pican1  TX - -  001   [1]  01
 (000.002314)  pican1  TX - -  001   [1]  01
 (000.003119)  pican1  TX - -  001   [1]  01
```

### candump

Much faster, can reach to the baud limit

### Socket can

Can also reach the baud limit:

```text
Bringing down interface pican1...
Bringing up interface pican1 with baudrate 1000000...
Interface setup complete.

Sending 5000 messages on pican1 at 1000000 bps...

=== Performance Metrics ===
Total time: 0.562005 s
Messages per second: 8896.71
Inter-message time (s): min=0.000037, mean=0.000112, max=0.011181
Estimated bus load: 96.08%
```

```text
Bringing down interface pican1...
Bringing up interface pican1 with baudrate 250000...
Interface setup complete.

Sending 5000 messages on pican1 at 250000 bps...

=== Performance Metrics ===
Total time: 2.200748 s
Messages per second: 2271.96
Inter-message time (s): min=0.000038, mean=0.000440, max=0.011884
Estimated bus load: 98.15%
SocketcanBus was not properly shut down
```