#!/bin/bash

# Path to the Python script you want to run
TL_PYTHON_SCRIPT="./time-lapse/timelapse_video.py"

# Log file for output and errors
TIME_LAPSE_LOG_FILE="./log-files/timelapse.log"

#sleep 540 # does not work in shells cript - ADD IN PYTHON SCRIPT

# Read CPU temperature in millidegrees Celsius and convert to degrees
cpu_temp=$(cat /sys/class/thermal/thermal_zone0/temp)
cpu_temp_c=$((cpu_temp / 1000))

# Only run script if temperature is below 80 degrees Celsius to prevent overheating
if [ "$cpu_temp_c" -lt 80 ]; then
    # Source the environment
    source "./setup_env.sh"

    # Run the Python script with parsed arguments and log output/errors
    python3 "$TL_PYTHON_SCRIPT" >> "$TIME_LAPSE_LOG_FILE" 2>&1

else
    echo "CPU temperature is $cpu_temp_c°C, which is above the safe threshold. Script will not run."
fi
