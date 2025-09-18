# Branch for Sensing Garden deployments

Goal of this repo is to run two scripts for collecting data on insect activity and enviornmental variables. 

Collect 1min videos from the camera by running `python3 record/record_video.py`

Collect environmental data from sen55: 
1. Connect the senserion sen55 to your device (https://www.hackster.io/negar-rafieedolatabadi/voice-activated-smart-air-quality-monitor-using-sen55-11dce6). 
2. Make sure to enable I2C on the Raspberrypi via `raspi-config` and the double check connections: 
```
sudo apt-get install i2c-tools
```
Run to scan for connectios: 
```
i2cdetect -y 1
```
If you see the number `69`, all is set. 

3. Move to the folder `raspberry-pi-i2c-sen5x-master`. Here you can find the prepared files for collecting and saving environmental data from the Senserion sen55 sensor.
4. Install library needed to save data:

```
sudo apt install libcjson-dev
```
5. Compile the "sensing_garden_sen55_collection.c" by running `make`
6. Create a folder "sen55" with a file "env_data.jsonl" -> `/home/sg/sensing-garden/sen55/env_data.jsonl`. If your file path is different, make sure to change that in the file "sensing_garden_sen55_collection.c". 
7. Run the compiled file by the command `./sensing_garden_sen55_collection`. This will store environmental data every 30 seconds. 
