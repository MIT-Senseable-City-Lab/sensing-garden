#!/bin/bash

# Check if the required arguments are provided
if [ "$#" -lt 4 ]; then
    echo "Usage: $0 --input <value> --hef-path <path>"
    exit 1
fi

# Parse command-line arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --input) INPUT="$2"; shift ;;
        --hef-path) HEF_PATH="$2"; shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift
done

# Validate arguments
if [ -z "$INPUT" ] || [ -z "$HEF_PATH" ]; then
    echo "Error: Both --input and --hef-path must be provided."
    exit 1
fi

# Path to the Python script you want to run
HAILO_PYTHON_SCRIPT="./basic_pipelines/detection.py"

# Log file for output and errors
HAILO_LOG_FILE="./log-files/hailort.log"

# Source the environment
source "./setup_env.sh"

# Run the Python script with parsed arguments and log output/errors
python3 "$HAILO_PYTHON_SCRIPT" --input "$INPUT" --hef-path "$HEF_PATH" >> "$HAILO_LOG_FILE" 2>&1

#sleep 540 # does not work in shells cript - ADD IN PYTHON SCRIPT
