# Run TensorFlow Lite (tflite) on Raspberry Pi

*Official guide from Ultralytics platform: https://docs.ultralytics.com/guides/raspberry-pi/#install-ultralytics-package*

*This guide will show you how you can convert and run a tflite model on your Raspberry Pi with no AI HAT connected*

**Note**: This is an alternative approach to the Hailo-accelerated detection. The primary bugcam workflow uses Hailo HEF models for better performance. Use this guide only if you need to run without the AI HAT.

---

Running TensorFlow Lite (TFLite) models on a Raspberry Pi offers several key advantages:

- **Improved Performance**: TFLite models are optimized for on-device inference, resulting in faster execution times on resource-constrained devices like the Raspberry Pi.
- **Reduced Latency**: By processing data locally, TFLite minimizes the need for cloud-based computation, leading to quicker response times in real-time applications.
- **Offline Capability**: TFLite models can run without an internet connection, making them suitable for remote or disconnected environments.
- **Power Efficiency**: TFLite's optimization techniques result in lower power consumption, which is crucial for battery-powered or energy-constrained Raspberry Pi projects.
- **Versatility**: TFLite supports various applications on Raspberry Pi, including computer vision tasks, object detection, and image classification.
- **Hardware Acceleration**: TFLite can leverage hardware acceleration on the Raspberry Pi, further improving performance for neural network computations.

## Convert Model to TFLite

First step is to convert your YOLO model to tflite:

### 1. Convert model:

```python
from ultralytics import YOLO

# Load a YOLO11n PyTorch model
model = YOLO("yolo11n.pt") # make sure the path is correct for your model

# Export the model to TFLite format
model.export(format="tflite")  # creates 'best_saved_model' folder
```

### 2. Check model size (optional)

If you want to check the model sizes and compare after exporting to tflite, you can run this code:

```python
import os

yolo11n_file = "runs/detect/train/weights/best.pt"
tflite_file = "runs/detect/train/weights/best_saved_model/best_int8.tflite"

def get_model_size(filepath):
    # Get the file size in bytes
    file_size = os.path.getsize(filepath)

    # Convert to MB for readability
    file_size_MB = file_size / (1024 * 1024)

    print(f"Model size: {file_size_MB:.2f} MB")

get_model_size(yolo11n_file)
get_model_size(tflite_file)
```

## Use Raspberry Pi Camera with the Model

There are 2 methods of using the Raspberry Pi Camera to inference YOLO11 models.

### Method 1: Using Picamera2

We can use `picamera2` which comes pre-installed with Raspberry Pi OS to access the camera and inference YOLO11 models.

```python
import cv2
from picamera2 import Picamera2

from ultralytics import YOLO

# Initialize the Picamera2
picam2 = Picamera2()
picam2.preview_configuration.main.size = (1280, 720)
picam2.preview_configuration.main.format = "RGB888"
picam2.preview_configuration.align()
picam2.configure("preview")
picam2.start()

# Load the YOLO11 model
model = YOLO("models/best_int8.tflite") # edit based on model name above

while True:
    # Capture frame-by-frame
    frame = picam2.capture_array()

    # Run tflite-model inference on the frame
    results = model(frame)

    # Visualize the results on the frame
    annotated_frame = results[0].plot()

    # Display the resulting frame
    cv2.imshow("Camera", annotated_frame)

    # Break the loop if 'q' is pressed
    if cv2.waitKey(1) == ord("q"):
        break

# Release resources and close windows
cv2.destroyAllWindows()
```

### Method 2: Using TCP Stream

We need to initiate a TCP stream with `rpicam-vid` from the connected camera so that we can use this stream URL as an input when we are inferencing later. Execute the following command to start the TCP stream.

```bash
rpicam-vid -n -t 0 --inline --listen -o tcp://127.0.0.1:8888
```

Learn more about `rpicam-vid` usage on [official Raspberry Pi documentation](https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-vid).

Then run inference:

```python
from ultralytics import YOLO

# Load a YOLO11n PyTorch model
model = YOLO("yolo11n.pt")

# Run inference
results = model("tcp://127.0.0.1:8888")
```

## Performance Comparison

**TFLite vs Hailo HEF:**
- **TFLite**: ~3-5 FPS on Raspberry Pi 5 without AI HAT
- **Hailo HEF**: ~15-25 FPS on Raspberry Pi 5 with AI HAT+

For production use with the Sensing Garden project, we recommend using the Hailo-accelerated pipeline for better real-time performance.
