#!/usr/bin/env python3

# default settings
INIT_TEMP_MODE = "off"  # possible values: "off", "auto", "heat", "cool"
INIT_FAN_MODE = "off"   # possible values: "off", "auto", "on", "off"
INIT_SET_TEMP = 70      # initial set temperature in degrees Fahrenheit
INIT_LOWER_DIFF = 3     # init lower difference bound from set temperature in degrees Fahrenheit
INIT_UPPER_DIFF = 3     # init upper difference bound from set temperature in degrees Fahrenheit

DEFAULT_TEMP_UNITS = "F" # default units returned and used to set temp, possible values: "F", "C", "K"

THERM_INTERVAL = 60     # seconds in time between temperature checks and setting adjustments

# control pins (BCM numbering)
THERM_AC_CTRL = 17 
THERM_HEAT_CTRL = 27
THERM_FAN_CTRL = 22
