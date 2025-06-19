## *Note: This branch is used for deployments of the Sensing Garden monitoring system. Changes will be automatically updated for all deployed devices.*

# Prod branch for Sensing Garden


Deployment settings for the sensing garden:

1. Continiously running the time-lapse/timelapse_video.py script between 6:00 AM and 10:00 PM. Taking 1min video, and storing on SD card. 
2. Twice a day, the device is checking for updates in the github branch and rebooting the system to keep itself updated. Log files are saved to `home/sg/sensing-garden-log/` folder
3. If the device is connected to internet, it will send the video file to the cloud. If not, the video is stored on the SD card. 
4. If the device is too hot (above 75 degrees celcius), the device will not run the provided scripts. 




Script: update_and_reboot.sh
```bash
#!/bin/bash
cd /home/sg/sensing-garden
git fetch origin
if ! git diff --quiet HEAD origin/prod; then
    git pull origin prod
    sudo shutdown -r now
fi
```

Crontab file `sudo crontab -e`:  

```bash
#!/bin/bash

# running time lapse video on reboot
@reboot cd /home/sg/sensing-garden && ./run_sensing_garden_tl.sh

# Pull and reboot at 00:00 (midnight) and 13:30 (1:30 PM), and log output to log files
0 0 * * * /home/sg/sensing-garden/update_and_reboot.sh >> /home/sg/sensing-garden-log/update_log.txt 2>&1
30 13 * * * /home/sg/sensing-garden/update_and_reboot.sh >> /home/sg/sensing-garden-log/update_log.txt 2>&1
```

Manage crontab for running processes on device:

```bash
#!/bin/bash
# open systemctl to check processes running on device
systemctl status cron.service 

# kill processes with the process number from the overview
sudo kill 888
```
