#!/bin/bash

# Path to the Python script you want to run
# TL_PYTHON_SCRIPT="./time-lapse/timelapse_video.py"

# Log file for output and errors
EDGE_LOG_FILE="./log-files/edge.log"

#sleep 540 # does not work in shells cript - ADD IN PYTHON SCRIPT

# Read CPU temperature in millidegrees Celsius and convert to degrees
cpu_temp=$(cat /sys/class/thermal/thermal_zone0/temp)
cpu_temp_c=$((cpu_temp / 1000))

# Only run script if temperature is below 80 degrees Celsius to prevent overheating
if [ "$cpu_temp_c" -lt 80 ]; then
    # Source the environment
    source venv_hailo_rpi5/bin/activate

    # Find base directory in /media/sg
    BASE_DIR=""
    if [ -d "/media/sg" ]; then
        # Find the first directory in /media/sg that exists
        for dir in /media/sg/*/; do
            if [ -d "$dir" ]; then
                BASE_DIR="$dir"
                break
            fi
        done
    fi

    # Check if we found a base directory
    if [ -z "$BASE_DIR" ]; then
        echo "No directory found in /media/sg. Exiting."
        exit 1
    fi

    # Set video directory path and create if it doesn't exist
    VIDEO_DIR="${BASE_DIR}videos"
    if [ ! -d "$VIDEO_DIR" ]; then
        echo "Creating video directory: $VIDEO_DIR"
        mkdir -p "$VIDEO_DIR"
    fi

    # Set device ID based on base directory
    if [[ "$BASE_DIR" == *"A476-B58D"* ]]; then
        DEVICE_ID="edge-sgsca1"
    elif [[ "$BASE_DIR" == *"92A9-FB17"* ]]; then
        DEVICE_ID="edge-sgsca2"
    elif [[ "$BASE_DIR" == *"F737-8E10"* ]]; then
        DEVICE_ID="edge-sgsca3"
    else
        DEVICE_ID="edge-sgsc-unknown"
        echo "Warning: Unknown USB drive, using default device ID"
    fi

    echo "Using video directory: $VIDEO_DIR"
    echo "Using device ID: $DEVICE_ID"

    # Change to edge directory and run the Python script with parsed arguments and log output/errors
    cd edge
    python3 run.py \
        --video-dir "$VIDEO_DIR" \
        --duration 30 \
        --upload-percentage 10 \
        --device-id "$DEVICE_ID" \
        --fps 10 \
        >> "../$EDGE_LOG_FILE" 2>&1 & # run the compiled file in paralell with run.py
        
    # Run the C executable in parallel - takes measurements every 30 sec
    ../sensing_garden_sen55_collection 

else
    echo "CPU temperature is $cpu_temp_c°C, which is above the safe threshold. Script will not run."
fi
