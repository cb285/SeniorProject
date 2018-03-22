#!/usr/bin/env python3

DEFAULT_TIMEOUT = 2 # seconds

LIGHT_SET_TRIES = 50

WAIT_TIME = 0.1

XB_CONF_HIGH = b'\x05'
XB_CONF_LOW = b'\x04'
XB_CONF_DINPUT = b'\x03'
XB_CONF_ADC = b'\x02'


"""
# ---------Lightswitch 1.0 PCB---------
RELAY_TOGGLE = 'D0'

# relay status
RELAY_STAT = 'D1'
RELAY_STAT_SAMPLE_IDENT = 'dio-1'

# number of DPOT positions
DPOT_NUM_POS = 30
# DPOT INC# pin
DPOT_INC_N = 'D6'
# DPOT U/D# pin
DPOT_UD_N = 'D4'
# D flip flop clear (clears CS#)
DFLIPCLR_N = 'D5'

# DPOT output pin
DPOT_OUT = 'D3'
DPOT_OUT_SAMPLE_IDENT = 'adc-3'

# current sense adc pin
CURRSENSE_OUT = 'D2'
CURRSENSE_SAMPLE_IDENT = 'adc-2'

# current sense values:
# voltage bias
CURRSENSE_BIAS = 0.7
# diode drop
CURRSENSE_DDROP = 0.5
# ac voltage
AC_VOLTAGE = 120
"""

# ---------BREADBOARD---------
# relay toggle (toggles relay on a rising edge)
RELAY_TOGGLE = 'D0'

# relay status
RELAY_STAT = 'D1'
RELAY_STAT_SAMPLE_IDENT = 'dio-1'

# number of DPOT positions
DPOT_NUM_POS = 100
# DPOT INC# pin
DPOT_INC_N = 'D2'
# DPOT U/D# pin
DPOT_UD_N = 'D4'
# D flip flop clear (clears CS#)
DFLIPCLR_N = 'D5'

# DPOT output pin
DPOT_OUT = 'D3'
DPOT_OUT_SAMPLE_IDENT = 'adc-3'



