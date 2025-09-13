#include "file_utils.h"
#include <stdlib.h>
#include <cjson/cJSON.h>
#include <stdio.h>
#include <math.h>
#include <time.h>

char *read_entire_file(FILE *fp) {
    if (!fp) return NULL;

    if (fseek(fp, 0, SEEK_END) != 0) {
        return NULL;
    }

    long filesize = ftell(fp);
    if (filesize < 0) {
        return NULL;
    }

    rewind(fp);

    char *buffer = (char *)malloc((size_t)filesize + 1);
    if (!buffer) {
        return NULL;
    }

    size_t read_size = fread(buffer, 1, (size_t)filesize, fp);
    if (read_size != (size_t)filesize) {
        free(buffer);
        return NULL;
    }

    buffer[filesize] = '\0';
    return buffer;
}

char *read_entire_file_by_name(const char *filename) {
    if (!filename) return NULL;

    FILE *fp = fopen(filename, "r");
    if (!fp) return NULL;

    char *result = read_entire_file(fp);
    fclose(fp);

    return result;
}

static void get_iso8601_timestamp(char *buffer, size_t buffer_size) {
    time_t now = time(NULL);
    struct tm *utc = gmtime(&now);
    strftime(buffer, buffer_size, "%Y-%m-%dT%H:%M:%SZ", utc);
}

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
) {
    if (!filename || !device_id) {
        return -1; // invalid params
    }

    // 1. Open file, read contents into a buffer
    FILE *fp_read = fopen(filename, "r");
    char *buffer = read_entire_file(fp_read); // You need to implement this
    cJSON *root = NULL;

    if (buffer) {
        root = cJSON_Parse(buffer); // root should be a cJSON array
        free(buffer);
    }
    if (!root) {
        // File missing or invalid, start new array
        root = cJSON_CreateArray();
    }


    // 2. add new measurements to object
    cJSON *item = cJSON_CreateObject();
    if (!item) return -2;

    cJSON_AddStringToObject(item, "device_id", device_id);

    char timestamp_str[25] = {0};
    get_iso8601_timestamp(timestamp_str, sizeof(timestamp_str));
    cJSON_AddStringToObject(item, "timestamp", timestamp_str);

    cJSON *data = cJSON_CreateObject();
    if (!data) {
        cJSON_Delete(item);
        return -3;
    }
    
    if (isnan(mass_concentration_pm1p0))
        cJSON_AddNullToObject(data, "pm1p0");
    else
        cJSON_AddNumberToObject(data, "pm1p0", mass_concentration_pm1p0);

    if (isnan(mass_concentration_pm2p5))
        cJSON_AddNullToObject(data, "pm2p5");
    else
        cJSON_AddNumberToObject(data, "pm2p5", mass_concentration_pm2p5);

    if (isnan(mass_concentration_pm4p0))
        cJSON_AddNullToObject(data, "pm4p0");
    else
        cJSON_AddNumberToObject(data, "pm4p0", mass_concentration_pm4p0);

    if (isnan(mass_concentration_pm10p0))
        cJSON_AddNullToObject(data, "pm10p0");
    else
        cJSON_AddNumberToObject(data, "pm10p0", mass_concentration_pm10p0);

    if (isnan(ambient_humidity))
        cJSON_AddNullToObject(data, "ambient_humidity");
    else
        cJSON_AddNumberToObject(data, "ambient_humidity", ambient_humidity);

    if (isnan(ambient_temperature))
        cJSON_AddNullToObject(data, "ambient_temperature");
    else
        cJSON_AddNumberToObject(data, "ambient_temperature", ambient_temperature);

    if (isnan(voc_index))
        cJSON_AddNullToObject(data, "voc_index");
    else
        cJSON_AddNumberToObject(data, "voc_index", voc_index);

    if (isnan(nox_index))
        cJSON_AddNullToObject(data, "nox_index");
    else
        cJSON_AddNumberToObject(data, "nox_index", nox_index);

    cJSON_AddItemToObject(item, "data", data);



    // add new item to root
    cJSON_AddItemToArray(root, item);

    // each measurement is appended as a new line
    // Serialize your cJSON measurement object as a string
    char *json_string = cJSON_PrintUnformatted(item);
    FILE *fp_append = fopen(filename, "a");
    fprintf(fp_append, "%s\n", json_string);
    fclose(fp_append);
    free(json_string);
    cJSON_Delete(item);



    // add new item to 
    //char *json_string = cJSON_Print(root);
    //if (!json_string) {
    //    cJSON_Delete(root);
    //    return -4;
    //}

    //FILE *fp = fopen(filename, "w");
    //if (!fp) {
       // free(json_string);
      //  cJSON_Delete(root);
     //   return -5;
    //}

    //fputs(json_string, fp);
    //fclose(fp);

    //free(json_string);
    //cJSON_Delete(root);
    

    return 0; // success
}

