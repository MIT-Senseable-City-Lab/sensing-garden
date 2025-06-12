## *Note: This branch is used for deployments of the Sensing Garden monitoring system. Changes will be automatically updated for all deployed devices.*

# Prod branch for Sensing Garden

Deployment settings for the sensing garden:

1. Continiously running the time-lapse/timelapse_video.py script between 6:00 AM and 10:00 PM. Taking 1min video, and storing on SD card. 
2. Twice a day, the device is checking for updates in the github branch and rebooting the system to keep itself updated. 
3. If the device is connected to internet, it will send the video file to the cloud. If not, the video is stored on the SD card. 
4. If the device is too hot (above 75 degrees celcius), the device will not run the provided scripts. 




Script: daily_pull_and_reboot.sh
```bash
#!/bin/bash
cd /path/to/your/project 
/usr/bin/git pull >> /path/to/git_pull.log 2>&1
/sbin/shutdown -r now
```

Crontab file: 
Pull and reboot at 00:00 (midnight) and 13:30 (1:30 PM). 

```bash
#!/bin/bash
0 0 * * * /path/to/daily_pull_and_reboot.sh
30 13 * * * /path/to/daily_pull_and_reboot.sh

```

*tips: Open your crontab with `crontab -e`*
