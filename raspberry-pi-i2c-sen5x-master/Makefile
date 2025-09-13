common_sources = sensirion_config.h sensirion_common.h sensirion_common.c
i2c_sources = sensirion_i2c_hal.h sensirion_i2c.h sensirion_i2c.c
sen5x_sources = sen5x_i2c.h sen5x_i2c.c
helper_sources = file_utils.c

i2c_implementation ?= sensirion_i2c_hal.c

CFLAGS = -Os -Wall -fstrict-aliasing -Wstrict-aliasing=1 -Wsign-conversion -fPIC -I.
LDFLAGS = -lcjson -lm

ifdef CI
    CFLAGS += -Werror
endif

.PHONY: all clean

all: sensing_garden_sen55_collection

sensing_garden_sen55_collection: clean
	$(CC) $(CFLAGS) -o $@ ${sen5x_sources} ${i2c_sources} \
	    ${i2c_implementation} ${common_sources} ${helper_sources} sensing_garden_sen55_collection.c \
	    $(LDFLAGS)

clean:
	$(RM) sensing_garden_sen55_collection
