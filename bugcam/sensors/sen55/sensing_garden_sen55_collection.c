#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "sen5x_i2c.h"
#include "sensirion_i2c_hal.h"

#define I2C_DEVICE_PATH "/dev/i2c-1"
#define DEFAULT_INTERVAL_SECONDS 60
#define DEFAULT_WARMUP_SECONDS 2

typedef struct {
    float pm1p0;
    float pm2p5;
    float pm4p0;
    float pm10p0;
    float humidity;
    float temperature;
    float voc_index;
    float nox_index;
} measurement_t;

static void print_usage(FILE* stream) {
    fprintf(stream,
            "Usage: sen55_reader --oneshot | --output <path> [--interval-seconds N] [--warmup-seconds N]\n");
}

static int parse_integer_arg(const char* value, int* output) {
    char* endptr = NULL;
    long parsed = strtol(value, &endptr, 10);
    if (!value || *value == '\0' || (endptr && *endptr != '\0') || parsed <= 0) {
        return -1;
    }
    *output = (int)parsed;
    return 0;
}

static void write_json_number(FILE* stream, const char* key, float value, bool last) {
    fprintf(stream, "\"%s\":", key);
    if (isnan(value)) {
        fprintf(stream, "null");
    } else {
        fprintf(stream, "%.6f", value);
    }
    if (!last) {
        fprintf(stream, ",");
    }
}

static void emit_measurement_json(FILE* stream, const measurement_t* measurement) {
    time_t now = time(NULL);
    struct tm utc_now;
    char timestamp[32] = {0};

    gmtime_r(&now, &utc_now);
    strftime(timestamp, sizeof(timestamp), "%Y-%m-%dT%H:%M:%SZ", &utc_now);

    fprintf(stream, "{");
    fprintf(stream, "\"timestamp\":\"%s\",", timestamp);
    write_json_number(stream, "pm1p0", measurement->pm1p0, false);
    write_json_number(stream, "pm2p5", measurement->pm2p5, false);
    write_json_number(stream, "pm4p0", measurement->pm4p0, false);
    write_json_number(stream, "pm10p0", measurement->pm10p0, false);
    write_json_number(stream, "humidity", measurement->humidity, false);
    write_json_number(stream, "temperature", measurement->temperature, false);
    write_json_number(stream, "voc_index", measurement->voc_index, false);
    write_json_number(stream, "nox_index", measurement->nox_index, true);
    fprintf(stream, "}\n");
    fflush(stream);
}

static int read_measurement(measurement_t* measurement) {
    return sen5x_read_measured_values(
        &measurement->pm1p0,
        &measurement->pm2p5,
        &measurement->pm4p0,
        &measurement->pm10p0,
        &measurement->humidity,
        &measurement->temperature,
        &measurement->voc_index,
        &measurement->nox_index
    );
}

int main(int argc, char* argv[]) {
    bool oneshot = false;
    const char* output_path = NULL;
    int interval_seconds = DEFAULT_INTERVAL_SECONDS;
    int warmup_seconds = DEFAULT_WARMUP_SECONDS;
    int16_t error = 0;
    FILE* output_file = NULL;

    for (int index = 1; index < argc; index++) {
        if (strcmp(argv[index], "--oneshot") == 0) {
            oneshot = true;
        } else if (strcmp(argv[index], "--output") == 0 && index + 1 < argc) {
            output_path = argv[++index];
        } else if (strcmp(argv[index], "--interval-seconds") == 0 && index + 1 < argc) {
            if (parse_integer_arg(argv[++index], &interval_seconds) != 0) {
                fprintf(stderr, "Invalid interval seconds\n");
                return 2;
            }
        } else if (strcmp(argv[index], "--warmup-seconds") == 0 && index + 1 < argc) {
            if (parse_integer_arg(argv[++index], &warmup_seconds) != 0) {
                fprintf(stderr, "Invalid warmup seconds\n");
                return 2;
            }
        } else {
            print_usage(stderr);
            return 2;
        }
    }

    if (!oneshot && output_path == NULL) {
        print_usage(stderr);
        return 2;
    }

    sensirion_i2c_hal_init(I2C_DEVICE_PATH);
    error = sen5x_device_reset();
    if (error) {
        fprintf(stderr, "Error executing sen5x_device_reset(): %i\n", error);
        return 1;
    }

    error = sen5x_start_measurement();
    if (error) {
        fprintf(stderr, "Error executing sen5x_start_measurement(): %i\n", error);
        return 1;
    }

    sensirion_i2c_hal_sleep_usec((uint32_t)warmup_seconds * 1000000U);

    if (output_path != NULL) {
        output_file = fopen(output_path, "a");
        if (output_file == NULL) {
            fprintf(stderr, "Could not open output file: %s\n", output_path);
            sen5x_stop_measurement();
            return 1;
        }
    }

    while (true) {
        measurement_t measurement;
        error = read_measurement(&measurement);
        if (error) {
            fprintf(stderr, "Error executing sen5x_read_measured_values(): %i\n", error);
            if (output_file != NULL) {
                fclose(output_file);
            }
            sen5x_stop_measurement();
            return 1;
        }

        emit_measurement_json(output_file != NULL ? output_file : stdout, &measurement);
        if (oneshot) {
            break;
        }
        sensirion_i2c_hal_sleep_usec((uint32_t)interval_seconds * 1000000U);
    }

    if (output_file != NULL) {
        fclose(output_file);
    }
    sen5x_stop_measurement();
    return 0;
}
