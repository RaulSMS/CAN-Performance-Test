#!/bin/bash
sudo ip link set pican1 down
sudo ip link set pican1 up type can bitrate 1000000 restart-ms 100
sudo ip link set pican1 txqueuelen 5000

while true
do

    cansend pican1 001#01

done