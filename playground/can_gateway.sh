#!/bin/bash
candump -x any &
while read line; do
  # Expecting input format: interface CAN_ID#DATA
  # Example: pican1 123#DEADBEEF
  iface=$(echo "$line" | awk '{print $1}')
  frame=$(echo "$line" | awk '{print $2}')
  if [[ -n "$iface" && -n "$frame" ]]; then
    cansend "$iface" "$frame"
  fi
done