#!/usr/bin/env python3

INIT_TEMP_MODE = "auto" # possible values: "auto", "heat", "cool"
INIT_FAN_MODE = "auto"  # possible values: "auto", "on", "off"
INIT_SET_TEMP = 70      # initial set temperature in degrees Fahrenheit
INIT_LOWER_DIFF = 3     # init lower difference bound from set temperature in degrees Fahrenheit
INIT_UPPER_DIFF = 3     # init upper difference bound from set temperature in degrees Fahrenheit

DEFAULT_TEMP_UNITS = "F" # default units returned and used to set temp, possible values: "F", "C", "K"
