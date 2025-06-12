Clone the repository on your raspberrypi5:
```bash
git clone https://github.com/aasehaa/sensing-garden.git
```



## Utilizing RaspberryPi AI HAT+

The pipeline we run in the sensing garden project will be using [Hailo Apps Infra](https://github.com/hailo-ai/hailo-apps-infra) repo as a dependency. 

**Requirements**
- numpy < 2.0.0
- setproctitle
- opencv-python

```bash
sudo apt install hailo-all
```

# Setting up the Hailo AI accellerator on the RaspberryPi5 

*assuming you have physically connected the AI HAT like shown in the raspberryPi documentation: https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html)*


## Installation
Run the following script to automate the installation process:

```bash
./install.sh
```

## Running examples

When opening a new terminal session, ensure you have sourced the environment setup script:

```bash
source setup_env.sh
```


To run a full detection example, you need to specify the raspberrypi camera as input, and the HEF model you want to run:
```bash
python basic_pipelines/detection.py --input rpi --hef-path resources/yolov8m.hef
```
Make sure to have the HEF model available and the correct path. 


### Hailo monitor
To run the Hailo monitor, run the following command in a different terminal:

```bash
hailortcli monitor
```

In the terminal you run your code set the HAILO_MONITOR environment variable to 1 to enable the monitor.

```bash
export HAILO_MONITOR=1
```

### CPU monitor
If you are interested to monitor the CPU usage, use these commands in a new terminal: 
```bash
# real time monitoring of cpu usage
top

# better UI by running (install first)
btop # or htop
```

# Running as a cron job

To have the system start on reboot / when powered, you need to setup a cron job: 

```bash
# open crontab for editing - using sudo for reboot access
sudo crontab -e
```

Then in the botton of the file, add the shell script you want to run when powered. In this repo, we have two options. Make sure to have the files and models available before running the script. 

```bash
# running time lapse video
@reboot /path/to/your/project/run_sensing_garden_tl.sh

# running hailo detection - needs input and hef file path
@reboot /path/to/your/project/run_sensing_garden_hailo.sh --input rpi --hef-path /path/to/your/project/resources/yolov8m.hef

```

To monitor the cron jobs, you can use these commands: 
```bash
# check if cron service is running
systemctl status cron.service

# stop the cron service
sudo systemctl stop cron

# resume all jobs and restart service
sudo systemctl start cron

# kill process by id
sudo kill 813 # change id of process
```
