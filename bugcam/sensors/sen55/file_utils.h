#ifndef FILE_UTILS_H
#define FILE_UTILS_H

#include <stdio.h>

// Reads the entire contents of the file pointer 'fp' into a newly allocated null-terminated string.
// Returns pointer to the buffer on success, or NULL on failure.
// Caller is responsible for calling free() on the returned buffer.
char *read_entire_file(FILE *fp);

// Reads the entire contents of the file specified by filename into a null-terminated string.
// Returns pointer to buffer on success or NULL on failure.
// Caller must free() returned buffer.
char *read_entire_file_by_name(const char *filename);

// Save sensor data to JSON file with device ID and timestamp in nested "data" object.
// The caller provides the sensor values and output filename.
// Returns 0 on success, non-zero on failure.
int save_sensor_data_with_metadata(
    const char *filename,
    const char *device_id,
    float mass_concentration_pm1p0,
    float mass_concentration_pm2p5,
    float mass_concentration_pm4p0,
    float mass_concentration_pm10p0,
    float ambient_humidity,
    float ambient_temperature,
    float voc_index,
    float nox_index
);

#endif // FILE_UTILS_H
