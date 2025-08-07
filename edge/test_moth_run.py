import sys
from time import sleep
from picamera2 import Picamera2
from picamera2.encoders import H264Encoder, Quality
from picamera2.outputs import FfmpegOutput
from datetime import datetime
import sys

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <sleep_duration>")
    sys.exit(1)

sleep_duration = 30

picam2 = Picamera2(0)
only_mode = picam2.sensor_modes[0]
picam2.video_configuration = picam2.create_video_configuration(
    raw={"size": only_mode["size"], "format": only_mode["format"].format}
)
picam2.configure("video")
picam2.set_controls({"FrameRate": only_mode["fps"]})
#picam2.set_controls({"ExposureTime": exposure_time, "AnalogueGain": 10.0})
# adjusting both AnalogueGain and Exposure time automatically
picam2.set_controls({"AeEnable": True})
encoder_config = H264Encoder()
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
output_file = FfmpegOutput(f"/home/sg/global-shutter/global-video/{timestamp}-{int(sleep_duration*100)}.mp4")
picam2.start_recording(encoder_config, output_file, quality=Quality.HIGH)
sleep(sleep_duration)
picam2.stop_recording()
