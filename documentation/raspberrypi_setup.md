## Getting started with RaspberryPi 

Follow the guide to setup your raspberry pi on their official webpage: 

[Official guide on the RaspberryPi Website](https://www.raspberrypi.com/documentation/computers/getting-started.html)


TIPS: Enable [RaspberryPi Connect](https://www.raspberrypi.com/documentation/computers/getting-started.html#raspberry-pi-connect) to be able to connect to your raspberryPi remotely. 



# Camera Module

*Official documentation for the camera module: https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf#page=6.10*

---

As of mid-September 2022, Picamera2 is pre-installed in all Raspberry Pi OS images. You can update it with a full system update, or via the terminal with:

```
sudo apt install -y python3-picamera2
``` 

You can check that libcamera is working by opening a command window and typing:

```python
rpicam-hello
```

You should see a camera preview window for about five seconds. If you do not, please refer to the Raspberry Pi camera documentation.


*Note to self: If you're using picamera2 installed through `apt`, you don't need a virtual environment. Just run your script directly with the system's Python*


### First example

The following script will:
1. Open the camera system
2. Generate a camera configuration suitable for preview
3. Configure the camera system with that preview configuration
4. Start the preview window
5. Start the camera running
6. Wait for two seconds and capture a JPEG file (still in the preview resolution)


GUI users should enter:

```python
from picamera2 import Picamera2, Preview
import time
picam2 = Picamera2()
camera_config = picam2.create_preview_configuration()
picam2.configure(camera_config)
picam2.start_preview(Preview.QTGL)
picam2.start()
time.sleep(2)
picam2.capture_file("test.jpg")

```
