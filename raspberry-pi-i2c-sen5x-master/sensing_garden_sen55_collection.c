/*
 * I2C-Generator: 0.3.0
 * Yaml Version: 2.1.3
 * Template Version: 0.7.0-109-gb259776
 */
/*
 * Copyright (c) 2021, Sensirion AG
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions are met:
 *
 * * Redistributions of source code must retain the above copyright notice, this
 *   list of conditions and the following disclaimer.
 *
 * * Redistributions in binary form must reproduce the above copyright notice,
 *   this list of conditions and the following disclaimer in the documentation
 *   and/or other materials provided with the distribution.
 *
 * * Neither the name of Sensirion AG nor the names of its
 *   contributors may be used to endorse or promote products derived from
 *   this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
 * LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 * CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 * SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 * INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 * CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 * ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 * POSSIBILITY OF SUCH DAMAGE.
 */

#include <math.h>   // NAN
#include <stdio.h>  // printf
#include <cjson/cJSON.h> // saving to JSON format
#include <stdlib.h>


#include "sen5x_i2c.h"
#include "sensirion_common.h"
#include "sensirion_i2c_hal.h"
#include "file_utils.h" // helper function to read file


/*
 * TO USE CONSOLE OUTPUT (PRINTF) YOU MAY NEED TO ADAPT THE INCLUDE ABOVE OR
 * DEFINE IT ACCORDING TO YOUR PLATFORM:
 * #define printf(...)
 */

/**
 * Linux specific configuration. Adjust the following define to the device path
 * of your sensor.
 */
#define I2C_DEVICE_PATH "/dev/i2c-1"

int main(void) {
    int16_t error = 0;

    sensirion_i2c_hal_init(I2C_DEVICE_PATH);

    error = sen5x_device_reset();
    if (error) {
        printf("Error executing sen5x_device_reset(): %i\n", error);
    }

    unsigned char serial_number[32];
    uint8_t serial_number_size = 32;
    error = sen5x_get_serial_number(serial_number, serial_number_size);
    if (error) {
        printf("Error executing sen5x_get_serial_number(): %i\n", error);
    } else {
        printf("Serial number: %s\n", serial_number);
    }

    unsigned char product_name[32];
    uint8_t product_name_size = 32;
    error = sen5x_get_product_name(product_name, product_name_size);
    if (error) {
        printf("Error executing sen5x_get_product_name(): %i\n", error);
    } else {
        printf("Product name: %s\n", product_name);
    }

    uint8_t firmware_major;
    uint8_t firmware_minor;
    bool firmware_debug;
    uint8_t hardware_major;
    uint8_t hardware_minor;
    uint8_t protocol_major;
    uint8_t protocol_minor;
    error = sen5x_get_version(&firmware_major, &firmware_minor, &firmware_debug,
                              &hardware_major, &hardware_minor, &protocol_major,
                              &protocol_minor);
    if (error) {
        printf("Error executing sen5x_get_version(): %i\n", error);
    } else {
        printf("Firmware: %u.%u, Hardware: %u.%u\n", firmware_major,
               firmware_minor, hardware_major, hardware_minor);
    }

    // set a temperature offset in degrees celsius
    // Note: supported by SEN54 and SEN55 sensors
    // By default, the temperature and humidity outputs from the sensor
    // are compensated for the modules self-heating. If the module is
    // designed into a device, the temperature compensation might need
    // to be adapted to incorporate the change in thermal coupling and
    // self-heating of other device components.
    //
    // A guide to achieve optimal performance, including references
    // to mechanical design-in examples can be found in the app note
    // “SEN5x – Temperature Compensation Instruction” at www.sensirion.com.
    // Please refer to those application notes for further information
    // on the advanced compensation settings used in
    // `sen5x_set_temperature_offset_parameters`,
    // `sen5x_set_warm_start_parameter` and `sen5x_set_rht_acceleration_mode`.
    //
    // Adjust temp_offset to account for additional temperature offsets
    // exceeding the SEN module's self heating.
    float temp_offset = 0.0f;
    error = sen5x_set_temperature_offset_simple(temp_offset);
    if (error) {
        printf("Error executing sen5x_set_temperature_offset_simple(): %i\n",
               error);
    } else {
        printf("Temperature Offset set to %.2f °C (SEN54/SEN55 only)\n",
               temp_offset);
    }

    // Start Measurement
    error = sen5x_start_measurement();

    if (error) {
        printf("Error executing sen5x_start_measurement(): %i\n", error);
    }

    // 1) Add 30s initial delay before first measurement
    sensirion_i2c_hal_sleep_usec(30000000);

    for (int i = 0; i < 600; i++) {
        // Read Measurement

        float mass_concentration_pm1p0;
        float mass_concentration_pm2p5;
        float mass_concentration_pm4p0;
        float mass_concentration_pm10p0;
        float ambient_humidity;
        float ambient_temperature;
        float voc_index;
        float nox_index;

        error = sen5x_read_measured_values(
            &mass_concentration_pm1p0, &mass_concentration_pm2p5,
            &mass_concentration_pm4p0, &mass_concentration_pm10p0,
            &ambient_humidity, &ambient_temperature, &voc_index, &nox_index);
        if (error) {
            printf("Error executing sen5x_read_measured_values(): %i\n", error);
        } else {
            // saving env data in /home/sg/sensing-garden/sen55/env_data.jsonl
            int res = save_sensor_data_with_metadata(
                "/home/sg/sensing-garden/sen55/env_data.jsonl",
                "sensor-123", 
                mass_concentration_pm1p0,
                mass_concentration_pm2p5,
                mass_concentration_pm4p0,
                mass_concentration_pm10p0,
                ambient_humidity,
                ambient_temperature, 
                voc_index,
                nox_index
            );

            if (res == 0) {
                printf("Sensor data saved successfully.\n");
            } else {
                printf("Failed to save sensor data. Error code: %d\n", res);
            }
            
        }
        // Sleep 30 seconds before next measurement, except after last iteration
        if (i < 599) {
            sensirion_i2c_hal_sleep_usec(30000000);
        }
    }

    error = sen5x_stop_measurement();
    if (error) {
        printf("Error executing sen5x_stop_measurement(): %i\n", error);
    }

    return 0;
}
