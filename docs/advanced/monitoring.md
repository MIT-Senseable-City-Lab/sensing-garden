# Monitoring

Tools and techniques for monitoring BugCam detection performance.

## Hailo Monitor

Monitor the Hailo AI accelerator hardware in real-time.

### Setup

To run the Hailo monitor, run the following command in a different terminal:

```bash
hailortcli monitor
```

In the terminal where you run your code, set the HAILO_MONITOR environment variable to 1 to enable the monitor:

```bash
export HAILO_MONITOR=1
```

Then run your detection:

```bash
bugcam detect start
# or
python basic_pipelines/detection.py --input rpi --hef-path resources/yolov8m.hef
```

The Hailo monitor will display real-time metrics including:
- Model inference time
- Frame rate (FPS)
- Hardware utilization
- Temperature

## CPU Monitor

Monitor CPU usage during detection to identify performance bottlenecks.

### Real-time CPU monitoring

```bash
# Basic real-time monitoring
top

# Better UI (install first)
btop  # or htop
```

### Installation

```bash
# Install btop
sudo apt install btop

# Install htop (alternative)
sudo apt install htop
```

### Interpreting Results

- **High CPU usage**: May indicate inefficient pre/post-processing
- **Low CPU usage with low FPS**: Bottleneck is likely in Hailo inference
- **Temperature**: Monitor with `vcgencmd measure_temp` to prevent throttling

## System Temperature

Monitor system temperature to prevent thermal throttling:

```bash
# Current temperature
vcgencmd measure_temp

# Continuous monitoring
watch -n 1 vcgencmd measure_temp
```

**Recommended**: Use active cooling (fan) with the Raspberry Pi AI HAT+ for optimal performance.

## Performance Metrics

### Measure FPS

When running detection, the console output includes FPS metrics:

```bash
bugcam detect start
# Output includes: FPS: 15.3, Detections: 2
```

### Log Detection Statistics

Save detections to a file and analyze later:

```bash
bugcam detect start --output detections.jsonl --duration 60
```

Then analyze with Python:

```python
import json
from collections import Counter

with open('detections.jsonl') as f:
    detections = [json.loads(line) for line in f]

# Count detections per class
classes = Counter(d['class'] for d in detections)
print(f"Total detections: {len(detections)}")
print(f"Classes: {classes}")

# Average confidence
avg_confidence = sum(d['confidence'] for d in detections) / len(detections)
print(f"Average confidence: {avg_confidence:.2f}")
```

## Network Monitoring

When using the hotspot setup, monitor connected devices:

```bash
# Show active connections
nmcli device show wlan0

# Monitor DHCP leases
sudo cat /var/lib/misc/dnsmasq.leases
```

## Systemd Service Monitoring

When using autostart, monitor the service:

```bash
# Service status
bugcam autostart status

# Live logs
bugcam autostart logs --follow

# Recent errors
journalctl -u bugcam-detect.service -p err

# Service restart history
systemctl status bugcam-detect.service
```

## Disk Usage

Monitor disk usage to prevent storage issues:

```bash
# Check available space
df -h

# Check output directory size
du -sh /path/to/detections/

# Find largest files
du -ah /home/pi | sort -rh | head -20
```

## Performance Tips

1. **Model Selection**: Use `yolov8s.hef` for faster inference if accuracy allows
2. **Resolution**: Lower camera resolution reduces processing time
3. **Cooling**: Active cooling prevents thermal throttling under sustained load
4. **Power**: Use official Raspberry Pi power supply (5V 5A recommended for Pi 5 + AI HAT+)
5. **Storage**: Use fast SD card or USB SSD for better I/O performance
