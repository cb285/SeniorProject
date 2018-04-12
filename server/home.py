#!/usr/bin/env python3

import sys
import os
import json
import atexit
from xbee import ZigBee
import serial
import logging
from systemd.journal import JournalHandler
import time
from threading import *
from apscheduler.schedulers.background import BackgroundScheduler
from queue import *
import RPi.GPIO as gpio
gpio.setmode(gpio.BCM) # set gpio numbering mode to BCM

DEVICE_DB_FILENAME = ".devices.json"               # path to device db file
#TASKS_DB_FILENAME = "sqlite:///.tasks.db"          # path to task db file
THERM_SETTINGS_FILENAME = ".thermostat.json"       # path to thermostat settings file
LEVEL_UNK = -1                                     # special device level used to mean level is unknown
UNK = "unknown"

SWITCH_TYPE = "switch"
DIMMER_TYPE = "dimmer"
CUSTOM_SWITCH = "cust-switch"
CUSTOM_PULSE = "cust-pulse"
CUSTOM_INPUT = "cust-input"
CUSTOM_TYPES = [CUSTOM_SWITCH, CUSTOM_PULSE, CUSTOM_INPUT]
NORMAL_TYPES = [SWITCH_TYPE, DIMMER_TYPE]
DEVICE_TYPES = [SWITCH_TYPE, DIMMER_TYPE, CUSTOM_SWITCH, CUSTOM_PULSE, CUSTOM_INPUT] # list of valid device types

POWER_LOG_TASKID = "__power_logger_task__"
TEMP_LOG_TASKID = "__temp_logger_task__"
THERM_TASKID = "__therm_task__"

###################### Logging Constants ###########################
LOG_FILENAME = "main_log.log"
LOG_FORMAT = '%(asctime)s : %(name)s : %(message)s'
LOG_TIMESTAMP = "%Y-%m-%d %H:%M:%S"

POWER_LOG_FILENAME = "power_log.csv"
POWER_LOG_INTERVAL = .1 # interval in minutes
POWER_TIMESTAMP = LOG_TIMESTAMP

TEMP_LOG_FILENAME = "temp_log.csv"
TEMP_LOG_INTERVAL = 5 # interval in minutes
TEMP_LOG_UNITS = "F" # possible values: "F", "C", "K"
TEMP_TIMESTAMP = LOG_TIMESTAMP

##################### Thermostat Constants ########################
# default settings
INIT_TEMP_MODE = "off"   # possible values: "off", "auto", "heat", "cool"
INIT_FAN_MODE = "off"    # possible values: "off", "auto", "on", "off"
INIT_SET_TEMP = 70       # initial set temperature in degrees Fahrenheit
INIT_LOWER_DIFF = 3      # init lower difference bound from set temperature in degrees Fahrenheit
INIT_UPPER_DIFF = 3      # init upper difference bound from set temperature in degrees Fahrenheit

DEFAULT_TEMP_UNITS = "F" # default units returned and used to set temp, possible values: "F", "C", "K"

THERM_INTERVAL = 30      # seconds in time between thermostat relay adjustments

# control pins (BCM numbering)
THERM_AC_CTRL = 13
THERM_HEAT_CTRL = 19
THERM_FAN_CTRL = 26

TEMP_ADC = 'D0'

###################### XBee Constants ###########################
DEFAULT_TIMEOUT = 2 # seconds

MAX_RX_TRIES = 3

XB_CONF_HIGH = b'\x05'
XB_CONF_LOW = b'\x04'
XB_CONF_DINPUT = b'\x03'
XB_CONF_ADC = b'\x02'

##################### Device Constants #########################
# max inc/dec tries before giving up on setting light level
LIGHT_SET_TRIES = 50

CUSTOM_PULSE_TIME = 0.25 # seconds

# relay toggle pin
RELAY_TOGGLE = 'D0'
# relay status pin
RELAY_STAT = 'D1'
# number of DPOT positions
DPOT_NUM_POS = 30
LEVEL_ONEV = (1023 / 1.2)
# DPOT INC# pin
DPOT_INC_N = 'D6'
# DPOT U/D# pin
DPOT_UD_N = 'D4'
# D flip flop clear
DFLIPCLR_N = 'D5'
# DPOT analog output pin
DPOT_OUT = 'D3'

# current sense adc pin
CURRSENSE_OUT = 'D2'
# diode drop
DIODE_DROP = 0.326
# ac voltage
AC_VOLTAGE = 120

class Home():
    def __init__(self): #, thermostat_function, power_log_function, temp_log_function):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_TIMESTAMP)
        self._log = logging.getLogger('home')
        self._log.addHandler(JournalHandler())
        
        self.Log("starting server, please wait...")

        # setup task scheduler
        self._sched = BackgroundScheduler()
        #self._sched.add_jobstore('sqlalchemy', url=TASKS_DB_FILENAME)

        # set up zigbee
        self._Setup_zigbee()

        # set up thermostat
        self._Setup_therm()

        # send discovery packet
        self.Send_discovery_packet()

        # start scheduler
        self._sched.start()

        self.Log_power_usage()
        
        # start power usage logger task
        self._sched.add_job(self.Log_power_usage, trigger='interval', minutes=POWER_LOG_INTERVAL, id=POWER_LOG_TASKID, replace_existing=True)

        # start temperature logger task
        self._sched.add_job(self.Log_temp, trigger='interval', minutes=TEMP_LOG_INTERVAL, id=TEMP_LOG_TASKID, replace_existing=True)

        # start thermostat updater task
        self._sched.add_job(self.Thermostat_update, trigger='interval', seconds=THERM_INTERVAL, id=THERM_TASKID, replace_existing=True)

        # register shutdown proceedure
        atexit.register(self.Exit)

        # setup complete
        self.Log("server ready!")

    def Exit(self):

        # log
        self.Log("shutdown procedure started...")

        # stop scheduler
        self._sched.shutdown()

        # write device database to file
        # get db lock
        with self._db_lock:
            # dump db to file
            with open(DEVICE_DB_FILENAME, 'w') as f:
                json.dump(self._device_db, f)
        
        # get thermostat lock
        with self._therm_lock:
            # dump thermostat settings to file
            with open(THERM_SETTINGS_FILENAME, 'w') as f:
                json.dump(self._therm_settings, f)

            # set gpio back to defaults
            gpio.cleanup()

        # close serial connection
        with self._zb_lock:
            self._ser.close()

        self.Log("shutdown procedure complete")

    def _Setup_zigbee(self):

        # create lock for zigbee access
        self._zb_lock = RLock()

        # create lock for device_db access
        self._db_lock = RLock()

        # create lock for permission to process zigbee packets
        self._process_packets_lock = RLock()

        # create queue for holding pending zigbee packets
        self._packet_queue = Queue(maxsize=10)

        # setup serial connection to zigbee module
        ser = serial.Serial()
        ser.port = "/dev/ttyS0"
        ser.baudrate = 9600
        ser.timeout = 3
        ser.write_timeout = 3
        ser.exclusive = True
        ser.open()

        self._ser = ser

        # create zigbee api object
        self._zb = ZigBee(ser, escaped=True, callback=self.Recv_handler)

        # load/create db file
        # check if need to create new db file
        if (not os.path.isfile(DEVICE_DB_FILENAME)):
            self.Log(DEVICE_DB_FILENAME + " file doesn't exist, creating a new one")
            self._device_db = dict()
        # if db file already exists
        else:
            with open(DEVICE_DB_FILENAME) as f:
                self._device_db = json.load(f)
            self.Log("opened existing device database file: " + DEVICE_DB_FILENAME)

    def _Setup_therm(self):

        # configure output pins
        gpio.setup(THERM_HEAT_CTRL, gpio.OUT, initial=gpio.LOW)
        gpio.setup(THERM_AC_CTRL, gpio.OUT, initial=gpio.LOW)
        gpio.setup(THERM_FAN_CTRL, gpio.OUT, initial=gpio.LOW)

        # configure temperature sensor adc on local xbee
        with self._zb_lock:
            self._zb.at(command=TEMP_ADC, parameter=XB_CONF_ADC)
        
        # create lock for thermostat io and settings access
        self._therm_lock = RLock()

        # initialize current thermostat modes
        self._curr_temp_mode = "off"
        self._curr_fan_mode = "off"
        
        # acquire thermostat lock
        with self._therm_lock:

            # if need to make new thermostat settings file
            if (not os.path.isfile(THERM_SETTINGS_FILENAME)):
                self.Log(THERM_SETTINGS_FILENAME + " file doesn't exist, creating a new one")
                self._therm_settings = dict()
                # initialize settings to defaults
                self._Initialize_therm_settings()
            # if file already exists
            else:
                with open(THERM_SETTINGS_FILENAME) as f:
                    self._therm_settings = json.load(f)
                self.Log("opened existing thermostat settings file: " + THERM_SETTINGS_FILENAME)

            # update thermostat
            self.Thermostat_update()

    def _Initialize_therm_settings(self):

        with self._therm_lock:

            # temp mode
            self.Set_temp_mode(INIT_TEMP_MODE)
            self._Set_curr_temp_mode("off")
            # fan mode
            self.Set_fan_mode(INIT_FAN_MODE)
            self._Set_curr_fan_mode("off")
            # set temp
            self.Set_temp(INIT_SET_TEMP)
            # temp diffs
            self.Set_temp_lower_diff(INIT_LOWER_DIFF)
            self.Set_temp_upper_diff(INIT_UPPER_DIFF)

    def Get_curr_temp(self, units=DEFAULT_TEMP_UNITS):

        #self.Log("getting curr temp")

        temp_adc_sample_ident = self.Pin2SampleIdent(TEMP_ADC, adc=True)
        
        samples = self._Sample_xbee(pins=[temp_adc_sample_ident])

        # check if could not get sample
        if(not samples):
            return LEVEL_UNK

        sample_val = samples[temp_adc_sample_ident]

        sample_volts = (sample_val / 1023)*1.2

        # convert to specified units
        return self.Convert_temp(((sample_volts - 0.5) / .01), "C", units)

    def Get_set_temp(self, units=DEFAULT_TEMP_UNITS):

        # acquire lock
        with self._therm_lock:
            # get set temperature from settings
            set_temp_f = self._therm_settings["set_temp"]

        return self.Convert_temp(set_temp_f, "F", units)

    def Set_temp(self, temp, units=DEFAULT_TEMP_UNITS):

        temp_f = self.Convert_temp(temp, units, "F")

        with self._therm_lock:
            self._therm_settings["set_temp"] = temp_f

        # update thermostat
        Thread(target=lambda: self.Thermostat_update()).start()
            
        return True

    @staticmethod
    def Convert_temp(temp, from_units, to_units):

        if(from_units == to_units):
            return temp

        if(from_units == "F"):
            temp_f = temp
        elif(from_units == "C"):
            temp_f = (9.0/5.0)*temp + 32
        elif(from_units == "K"):
            temp_f = (9.0/5.0)*(temp - 273) + 32
        else:
            raise Exception("invalid \"from\" units specified")

        if(to_units == "F"):
            return temp_f
        elif(to_units == "C"):
            return (5.0/9.0)*(temp_f-32)
        elif(to_units == "K"):
            return (5.0/9.0)*(temp_f-32) + 273
        else:
            raise Exception("invalid \"to\" units specified")

    def Set_temp_lower_diff(self, lower_diff, units=DEFAULT_TEMP_UNITS):

        lower_diff_f = self.Convert_temp(lower_diff, units, "F")

        with self._therm_lock:
            self._therm_settings["lower_diff"] = lower_diff_f

        return True

    def Set_temp_upper_diff(self, upper_diff, units=DEFAULT_TEMP_UNITS):

        upper_diff_f = self.Convert_temp(upper_diff, units, "F")

        with self._therm_lock:
            self._therm_settings["upper_diff"] = upper_diff_f

        return True

    def Set_temp_mode(self, temp_mode):

        if(temp_mode not in ["auto", "heat", "cool", "off"]):
            self.Log("invalid temp_mode: " + str(temp_mode))
            return False

        with self._therm_lock:
            self._therm_settings["temp_mode"] = temp_mode

        # update thermostat
        Thread(target=lambda: self.Thermostat_update()).start()

        return True

    def Set_fan_mode(self, fan_mode):

        if(fan_mode not in ["off", "on", "auto"]):
            self.Log("invalid fan_mode: " + str(fan_mode))
            return False
        
        with self._therm_lock:
            self._therm_settings["fan_mode"] = fan_mode

        # update thermostat
        Thread(target=lambda: self.Thermostat_update()).start()
            
        return True
    
    def Get_temp_mode(self):

        with self._therm_lock:
            return self._therm_settings["temp_mode"]

    def Get_fan_mode(self):

        with self._therm_lock:
            return self._therm_settings["fan_mode"]

    def Get_curr_modes(self):
        return {"temp_mode":self._curr_temp_mode, "fan_mode":self._curr_fan_mode}

    def Log_temp(self):
        
        # if file is not already created
        if(not os.path.isfile(TEMP_LOG_FILENAME)):
            with open(TEMP_LOG_FILENAME, 'a+') as f:
                f.write("time,temperature,units,temp_mode,fan_mode\n")

        # open power log file
        with open(TEMP_LOG_FILENAME, 'a+') as f:

            # for each device in database
            for device_name in self._device_db:
                
                # get current power usage
                curr_temp = self.Get_curr_temp(TEMP_LOG_UNITS)
                
                # add line to csv
                f.write(time.strftime(TEMP_TIMESTAMP) + "," + curr_temp + "," + TEMP_LOG_UNITS + "," +
                        self.Get_temp_mode() + "," + self.Get_fan_mode() + "\n")

    def _Set_curr_fan_mode(self, fan_mode):

        # check if no change is needed
        if(fan_mode == self._curr_fan_mode):
            pass

        elif(fan_mode == "on"):
            # turn fan on
            self.Log("turning fan on")
            gpio.output(THERM_FAN_CTRL, gpio.HIGH)
            self._curr_fan_mode = fan_mode

        elif(fan_mode == "off"):
            # turn fan off
            self.Log("turning fan off")
            gpio.output(THERM_FAN_CTRL, gpio.LOW)
            self._curr_fan_mode = fan_mode

        else:
            self.Log("invalid fan mode: " + str(fan_mode))

    def _Set_curr_temp_mode(self, temp_mode):

        # check if no change is needed
        if(temp_mode == self._curr_temp_mode):
            pass

        # change to cool
        elif(temp_mode == "cool"):
            self.Log("turning AC on")
            # turn heat off
            gpio.output(THERM_HEAT_CTRL, gpio.LOW)
            # turn ac on
            gpio.output(THERM_AC_CTRL, gpio.HIGH)
            # update current mode
            self._curr_temp_mode = temp_mode
            
        # change to heat
        elif(temp_mode == "heat"):
            self.Log("turning heat on")
            # turn cool off
            gpio.output(THERM_AC_CTRL, gpio.LOW)
            # turn heat on
            gpio.output(THERM_HEAT_CTRL, gpio.HIGH)
            # update current mode
            self._curr_temp_mode = temp_mode

        # change to off
        elif(temp_mode == "off"):
            self.Log("turning heat/AC off")
            # turn cool off
            gpio.output(THERM_AC_CTRL, gpio.LOW)
            # turn heat off
            gpio.output(THERM_HEAT_CTRL, gpio.LOW)
            # update current mode
            self._curr_temp_mode = temp_mode
        # invalid mode
        else:
            self.Log("invalid temp mode: " + str(temp_mode))

    def Thermostat_update(self):

        #self.Log("updating thermostat")
        
        # acquire thermostat lock
        with self._therm_lock:
            
            # get current settings
            set_temp = self._therm_settings["set_temp"]
            upper_diff = self._therm_settings["upper_diff"]
            lower_diff = self._therm_settings["lower_diff"]
            temp_mode = self._therm_settings["temp_mode"]
            fan_mode = self._therm_settings["fan_mode"]
            
            curr_fan_mode = self._curr_fan_mode
            curr_temp_mode = self._curr_temp_mode
            
            # get current temperature
            curr_temp = self.Get_curr_temp(units="F")

            if(curr_temp == LEVEL_UNK):
                self.Log("temperature could not be measured, doing nothing")
                return
            
            #self.Log("curr temp = " + str(curr_temp))
            #self.Log("set temp = " + str(set_temp))

            #self.Log("set temp mode = " + temp_mode)
            #self.Log("set fan mode = " + fan_mode)

            #self.Log("curr temp mode = " + curr_temp_mode)
            #self.Log("curr fan mode = " + curr_fan_mode)
            
            # if fan set to off or on
            if(fan_mode != "auto"):
                # set to on or off
                self._Set_curr_fan_mode(fan_mode)

                # if fan is off
                if(fan_mode == "off"):
                    # turn ac/heat off too
                    self._Set_curr_temp_mode("off")
                    return
                # if fan is on
                else:
                    # if temp mode is not auto
                    if(temp_mode != "auto"):
                        # set to specified temp mode
                        self._Set_curr_temp_mode(temp_mode)
                        return

            # if fan or temp mode is set to auto
            
            # get difference from set temperature
            temp_diff = curr_temp - set_temp

            if(temp_mode == "auto" and fan_mode == "on"):
                temp_diff = (upper_diff + lower_diff)

            # if temperature is too high
            if(temp_diff > upper_diff):
                self.Log("too high")
                # if can turn ac on
                if(fan_mode in ["on", "auto"]):
                    if(temp_mode != "heat"):
                        self._Set_curr_fan_mode("on")
                    if(temp_mode in ["cool", "auto"]):
                        # turn on ac
                        self._Set_curr_temp_mode("cool")
                        return

            # if temperature is too low
            elif(-1*temp_diff > lower_diff):
                self.Log("too low")
                # check if can change current fan mode
                if(fan_mode in ["on", "auto"]):
                    if(temp_mode != "cool"):
                        self._Set_curr_fan_mode("on")
                    if(temp_mode in ["heat", "auto"]):
                        # turn heat on
                        self._Set_curr_temp_mode("heat")
                        return

            # if temperature is within bounds
            else:
                self.Log("just right")
                # check if can change current fan mode
                if(fan_mode in ["off", "auto"]):
                    # turn fan off
                    self._Set_curr_fan_mode("off")
                    self._Set_curr_temp_mode("off")
                    return

    def Get_power_usage(self, device_name):

        currsense_out_sample_ident = self.Pin2SampleIdent(CURRSENSE_OUT, adc=True)
        
        # sample device's current sense pin
        samples = self._Sample_xbee(device_name, pins=[currsense_out_sample_ident])
        
        # if could not get sample
        if(not samples):
            return LEVEL_UNK

        # get sampled value
        sample_val = samples[currsense_out_sample_ident]

        # convert to voltage
        sample_voltage = (sample_val / 1023.0) * 1.2

        off = False
        checked_stat = False

        # if relay is off, recalibrate and return 0 power usage
        if(self.Get_device_level(device_name) == 0):
            with self._db_lock:
                #self._device_db[device_name]["noload_vout"] = (DIODE_DROP + sample_voltage)/0.4
                #self.Log("noload_vout = " + str(self._device_db[device_name]["noload_vout"]))
                self._device_db[device_name]["voltage_div"] = (DIODE_DROP + sample_voltage)/2.5
            return 0.0
        
        with self._db_lock:
            if("voltage_div" not in self._device_db[device_name]):
                #noload_vout = 2.5
                voltage_div = 0.4
            else:
                #diode_drop = self._device_db[device_name]["diode_drop"]
                #noload_vout = self._device_db[device_name]["noload_vout"]
                voltage_div = self._device_db[device_name]["voltage_div"]

        diode_drop = DIODE_DROP
        noload_vout = 2.5

        #self.Log("sample voltage = " + str(sample_voltage))
        #self.Log("chip output voltage = " + str((sample_voltage + diode_drop) / voltage_div))
        #self.Log("voltage divider = " + str(voltage_div))
        #self.Log("diode drop = " + str(diode_drop))
        #self.Log("noload_vout = " + str(noload_vout))
        
        # convert to ac current amplitude (A)
        ac_current = abs(((sample_voltage + diode_drop) / voltage_div) - noload_vout)*10

        #self.Log("current = " + str(ac_current))
        
        if(ac_current <= 0):
            return 0.0
        
        # calculate apparent power (VA)
        apparent_power = ac_current*AC_VOLTAGE

        # get power factor
        with self._db_lock:
            if("power_factor" in self._device_db[device_name]):
                power_factor = self._device_db[device_name]["power_factor"]

            # assume purely resistive load if not specified
            else:
                power_factor = 1.0

        # return approximate real power (W)
        return apparent_power * power_factor

    def Log_power_usage(self):

        self.Log("logging power usage")
            
        # if file is not already created
        if(not os.path.isfile(POWER_LOG_FILENAME)):
            with open(POWER_LOG_FILENAME, 'a+') as f:
                f.write("time,device_name,power_usage\n")

                # open power log file
        with open(POWER_LOG_FILENAME, 'a+') as f:
            
            # for each device in database
            for device_name in self._device_db:

                # get current power usage
                power_usage = self.Get_power_usage(device_name)
                self.Log(device_name + " power usage = " + str(power_usage) + " W")
                
                # add line to csv
                f.write(time.strftime(POWER_TIMESTAMP) + "," + device_name + "," + str(power_usage) + "\n")

    """
    Function: Mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    @staticmethod
    def Mac2bytes(mac):
        return bytearray.fromhex(mac)

    @staticmethod
    def Bytes2mac(mac):
        return mac.hex()

    def Get_device_type(self, device_name):

        with self._db_lock:
            # check if device in db
            if(not self.Name_in_db(device_name)):
                # return unknown
                return UNK

            return self._device_db[device_name]["type"]

    def Get_device_mac(self, device_name):

        with self._db_lock:
            # check if device in db
            if(not self.Name_in_db(device_name)):
                # return unknown
                return UNK

            return self._device_db[device_name]["mac"]
    
    def Get_device_level(self, device_name):
        
        device_type = self.Get_device_type(device_name)

        # check if device in db
        if(device_type == UNK):
            self.Log("cannot sample device \"" + device_name + "\", no device with that name in db")
            # return unknown
            return LEVEL_UNK

        # switch device
        if(device_type == SWITCH_TYPE):

            relay_stat_sample_ident = self.Pin2SampleIdent(RELAY_STAT)
            
            # get relay status
            samples = self._Sample_xbee(device_name=device_name, pins=[relay_stat_sample_ident])

            if(not samples):
                return LEVEL_UNK
            return samples[relay_stat_sample_ident]
            
        # dimmer device
        elif(device_type == DIMMER_TYPE):

            relay_stat_sample_ident = self.Pin2SampleIdent(RELAY_STAT)
            dpot_out_sample_ident = self.Pin2SampleIdent(DPOT_OUT, adc=True)
            
            samples = self._Sample_xbee(device_name=device_name, pins=[relay_stat_sample_ident, dpot_out_sample_ident])

            if(not samples):
                return LEVEL_UNK
            
            relay_level = samples[relay_stat_sample_ident]

            # if relay is off
            if(relay_level == 0):
                return 0

            # if relay is on
            else:
                # get level
                dpot_level = LEVEL_ONEV - samples[dpot_out_sample_ident]
                
                # calculate brightness
                brightness = int(round(100*((dpot_level**2) / (LEVEL_ONEV**2))))

                if(brightness >= 99):
                    brightness = 100
                elif(brightness <= 0):
                    brightness = 1
                
                return brightness

    def _Sample_xbee(self, device_name=False, pins=False, timeout=DEFAULT_TIMEOUT):
        
        # if remote device
        if(device_name != False):
            
            # get device mac
            mac_addr = self.Get_device_mac(device_name)
            
            if(mac_addr == UNK):
                self.Log("cannot sample device \"" + device_name + "\", no device with that name in db")
                # return unknown
                return LEVEL_UNK

            bytes_mac = self.Mac2bytes(mac_addr)

        # get process packets lock
        with self._process_packets_lock:
            # clear the queue
            while(not self._packet_queue.empty()):
                self._packet_queue.get(block=False)
                
        try:
            # record start time
            start_time = time.time()
            
            # if remote device
            if(device_name != False):
                with self._zb_lock:
                    # request sample (periodic sampling every 255 ms)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x0FF')
            else:
                with self._zb_lock:
                    # request sample
                    self._zb.at(command='IS')

            with self._process_packets_lock:
                # for each try
                for x in range(MAX_RX_TRIES):
                    self.Log(str(x) + " try")
                    try:
                        # check if timed out
                        if(time.time() - start_time >= timeout):
                            self.Log("could not get sample from device \"" + device_name + "\", check the device")
                            return False
                            
                        # wait for a packet
                        packet = self._packet_queue.get(block=True, timeout=timeout)
                        
                        self.Log("packet = " + str(packet))
                        
                    except Empty:
                        if(device_name != False):
                            self.Log("could not get sample from device \"" + device_name + "\", check the device")
                            return False
                        else:
                            self.Log("could not get sample from local xbee, check the device")
                            return False
                        
                    # check if packet is from desired device
                    if("source_addr_long" not in packet):
                        if(not device_name):
                            if("parameter" in packet):
                                if(type(packet["parameter"]) is list):
                                    return packet["parameter"][0]
                        continue

                    if (device_name != False):
                        if((bytearray(packet['source_addr_long'])) != bytes_mac):
                            self.Log("mac doesn't match")
                            continue
                        
                    # check if sample packet
                    if("samples" in packet):    
                        samples = packet["samples"][0]
                            
                        # if no specific pin given, return all
                        if(not pins):
                            return samples
                            
                        sample_dict = dict()

                        cont = False
                        
                        # if specific pins given, make sure all are present
                        for pin in pins:
                            if(pin not in samples):
                                cont = True
                                break
                            elif(type(samples[pin]) is bool):
                                if(samples[pin]):
                                    sample_dict[pin] = 100
                                else:
                                    sample_dict[pin] = 0
                            else:
                                sample_dict[pin] = samples[pin]

                        if(cont):
                            continue

                        return sample_dict
                    
                # if couldn't get desired samples
                if(device_name != False):
                    self.Log("couldn't sample device \"" + device_name + "\", please check device status")
                    return False
                else:
                    self.Log("could not get sample from local xbee, check the device")
                    return False
            
        finally:                    
            if(device_name != False):
                with self._zb_lock:
                    self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');

    """
    Function: Set_device_level
    receives a device name and a level to set it to
    returns True if successful, False otherwise

    level is an integer in the range [0, 100] from off to on

    valid levels for device types:
    outlet     : 0,  100 (off,  on)
    light      : 0 - 100 (off - on)
    thermostat : 0 - 100 (0 - 100 degrees fahrenheit)
    """
    def Set_device_level(self, device_name, level):
        
        if(not self.Name_in_db(device_name)):
            self.Log("could not set level of device \"" + device_name + "\", name not in db")
            return False

        # get db lock
        with self._db_lock:
            # get device type
            device_type = self._device_db[device_name]['type']

        if(device_type in CUSTOM_TYPES):
            if(device_type == CUSTOM_SWITCH):
                # get db lock
                with self._db_lock:
                    curr_level = self._device_db[device_name]['status']
            else:
                curr_level = 0
        elif(device_type in NORMAL_TYPES):
            # get current device level
            curr_level = self.Get_device_level(device_name)
        else:
            self.Log("could not set device level to " + str(level) + ", not a valid device type")
            return False
        
        # check if got a sample
        if(curr_level == LEVEL_UNK):
            self.Log("could not set device \"" + device_name +"\" level to " + str(level) + ", could not communicate with module")
            return False

        # check if need to change the level
        if(curr_level == level):
            self.Log("did not need to set device \"" + device_name +"\" level to " + str(level) + ", was already set")
            return True
        
        # if switch
        if(device_type == SWITCH_TYPE):
            # toggle relay
            self._Toggle_relay(device_name)
            return True
        elif(device_type == DIMMER_TYPE):
            self.Log("here")
            # set light level using a thread
            Thread(target=lambda: self._Set_light(device_name, curr_level, level)).start()
            return True
        elif(device_type == CUSTOM_SWITCH):
            self._Set_custom_switch(device_name, curr_level=curr_level)
            return True
        elif(device_type == CUSTOM_PULSE):
            self._Toggle_custom_pulse(device_name)
            return True

    def _Set_custom_switch(self, device_name, curr_level = False):

        with self._db_lock:
            # get custom control pin number
            pin = self._device_db[device_name]['pin']
            # get current level
            if(not curr_level):
                curr_level = self._device_db[device_name]['status']
            device_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

        if(curr_level == 0):
            with self._zb_lock:
                # make pin low
                self._zb.remote_at(dest_addr_long=device_mac, command=pin, parameter=XB_CONF_LOW)
        else:
            with self._zb_lock:
                # set pin high
                self._zb.remote_at(dest_addr_long=device_mac, command=pin, parameter=XB_CONF_HIGH)

    def _Toggle_custom_pulse(self, device_name):

        self.Log("in toggle_custom_pulse")
        
        with self._db_lock:
            # get custom control pin number
            pin = self._device_db[device_name]['pin']
            device_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

        self.Log("custom pin = " + str(pin))
            
        with self._zb_lock:
            # set pin high
            self._zb.remote_at(dest_addr_long=device_mac, command=pin, parameter=XB_CONF_HIGH)
            self.Log("set high")
            time.sleep(CUSTOM_PULSE_TIME)
            # make pin low
            self._zb.remote_at(dest_addr_long=device_mac, command=pin, parameter=XB_CONF_LOW)
            self.Log("set low")

    def _Toggle_relay(self, device_name):

        # get db lock
        with self._db_lock:
            # get device mac
            device_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

        # get zigbee lock
        with self._zb_lock:
            # set relay toggle pin high
            self._zb.remote_at(dest_addr_long=device_mac, command=RELAY_TOGGLE, parameter=XB_CONF_HIGH)
            # make relay toggle pin low
            self._zb.remote_at(dest_addr_long=device_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

    def _Set_light(self, device_name, curr_level, level):

        # get db lock
        with self._db_lock:
            # get device mac
            bytes_mac = self.Mac2bytes(self._device_db[device_name]['mac'])
            
        if(curr_level == 0):
            # turn on the relay
            self._Toggle_relay(device_name)
                
        curr_level = self.Get_device_level(device_name)

        if(curr_level == LEVEL_UNK):
            self.Log("couldn't set light level, couldn't communicate with device")
            return

        if(level == 0):
            if(curr_level != 0):
                self._Toggle_relay(device_name)
                
        try:
            # get zigbee lock
            with self._zb_lock:
                # set D flip flop CLR# to low (cleared)
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_LOW)

            # if light is too bright
            if(curr_level > level):
                # set U/D# to high (up)
                # get zigbee lock
                with self._zb_lock:
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_HIGH)
                    
                num_tries = 0
                
                # while the light is too bright
                while(level < curr_level):
                    
                    self.Log("inc")

                    # get zigbee lock
                    with self._zb_lock:
                        # increment the dpot
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_HIGH)
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                        
                    num_tries += 1
                        
                    if(num_tries >= LIGHT_SET_TRIES):
                        self.Log("could not set light to desired level, giving up")
                        return
                    
                    curr_level = self.Get_device_level(device_name)

                    if(curr_level == LEVEL_UNK):
                        self.Log("couldn't set light level, couldn't communicate with device")
                        return
                        
            # light is too dim
            else:
                # get zigbee lock
                with self._zb_lock:
                    # set U/D# to low (down)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)
                    
                num_tries = 0
                
                # while the light is too dim
                while(curr_level < level):

                    self.Log("dec")

                    # get zigbee lock
                    with self._zb_lock:
                        # decrement the dpot
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_HIGH)
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)

                    num_tries += 1
                        
                    if(num_tries >= LIGHT_SET_TRIES):
                        self.Log("could not set light to desired level, giving up")
                        return

                    curr_level = self.Get_device_level(device_name)
                    
                    if(curr_level == LEVEL_UNK):
                        self.Log("couldn't set light level, couldn't communicate with device")
                        return    

        finally:
            # get zigbee lock
            with self._zb_lock:
                # set D flip flop CLR# to input (not cleared)
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_DINPUT)
                # set U/D# back to low
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)

    """
    Function: Name_in_db
    given device name
    returns true if device with that name is in db, false otherwise
    """
    def Name_in_db(self, device_name):
        # get db lock
        with self._db_lock:
        
            for device in self._device_db:
                if(device == device_name):
                    return True
                
            return False

    """
    Function: Mac_in_db
    given device mac address (hex string or bytearray)
    returns true if device with that mac address is in db, false otherwise
    """
    def Mac_in_db(self, device_mac):
        # get db lock
        with self._db_lock:
        
            if(type(device_mac) is bytearray):
                byte_format = True
            else:
                byte_format = False
            
            if(byte_format):
                for device in self._device_db:
                    if(self.Mac2bytes(self._device_db[device]['mac']) == device_mac):
                        return True
                    
                return False

            else:
                for device in self._device_db:
                    if(self._device_db[device]['mac'] == device_mac):
                        return True
                    
                return False

    """
    Function: Mac2name
    given device mac address (hex string or bytearray)
    returns name of device if in db, empty string ("") otherwise
    """
    def Mac2name(self, mac):
        # get db lock
        with self._db_lock:

            if(type(mac) is bytearray):
                for device_name in self._device_db:
                    if(self.Mac2bytes(self._device_db[device_name]['mac']) == mac):
                        return device_name

            else:
                for device_name in self._device_db:
                    if(self._device_db[device_name]['mac'] == mac):
                        return device_name

            return False

    @staticmethod
    def Pin2SampleIdent(pin, adc=False):
        if(not adc):
            return "dio-" + pin[1:]
        else:
            return "adc-" + pin[1:]

    """
    Function: Add_device
    attempts to add a device to the db, returns True if successful, false otherwise
    """
    def Add_device(self, device_name, device_mac, device_type):        
            
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name)):
                self.Log("there is already a device with name \"" + device_name + "\" in the db")
                return False
            elif(self.Mac_in_db(device_mac)):
                self.Log("there is already a device with mac address \"" + device_mac + "\" in the db")
                return False
            
            # check if invalid device type
            if(device_type not in DEVICE_TYPES):
                self.Log("invalid device type \"" + device_type + "\", cannot add to db")
                return False

            # get mac as bytes
            bytes_mac = self.Mac2bytes(device_mac)

            custom = False

            if(device_type in [SWITCH_TYPE, DIMMER_TYPE]):

                # acquire zigbee lock
                with self._zb_lock:
                    # set RELAY_STATUS (D1) to input
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_STAT, parameter=XB_CONF_DINPUT)

                    # set CURRSENSE_OUT (D3) to analog input
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=CURRSENSE_OUT, parameter=XB_CONF_ADC)
                    
                    # set RELAY_TOGGLE (D0) to output low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

            if(device_type == DIMMER_TYPE):
                # acquire zigbee lock
                with self._zb_lock:
                    # set DPOT_OUT (D2) to analog input
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_OUT, parameter=XB_CONF_ADC)
                    
                    # set D flip flop CLR# to high
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_HIGH)
                    
                    # DPOT INC# to low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                
                    # set U/D# to low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)

            elif(device_type.split("-")[0] == "cust"):

                custom = True
                
                split_ident = device_name.split("_")
                if(len(split_ident) != 3):
                    self.Log("invalid custom device identifier: " + str(device_name))
                    return False

                # get io pin number
                dio = split_ident[1].upper()
                
                # check if seems like valid io pin
                if(dio[0] != "D"):
                    self.Log("invalid pin identifier: " + str(dio))
                    return False

                # check if two characters
                if(len(dio) != 2):
                    self.Log("invalid pin identifier: " + str(dio) + ", only pins D0 to D9 work with this XBee API")

                # custom switch or pulse
                if(device_type in [CUSTOM_SWITCH, CUSTOM_PULSE]):
                    # acquire zigbee lock
                    with self._zb_lock:
                        # set pin to output low initially
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=dio, parameter=XB_CONF_LOW)

                # custom input
                elif(device_type == CUSTOM_INPUT):
                    # acquire zigbee lock
                    with self._zb_lock:
                        # set pin to digital input
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=dio, parameter=XB_CONF_DINPUT)

            if(device_name.split("-")[0] == "cust"):
                # create node identifier
                node_identifier = device_name
            else:
                # create node identifier
                node_identifier = device_type + "_" + device_mac[12:]
                
            # acquire zigbee lock
            with self._zb_lock:
                
                # write node identifier to device
                self._zb.remote_at(dest_addr_long=bytes_mac, command='NI', parameter=node_identifier)
                
                # apply changes
                self._zb.remote_at(dest_addr_long=bytes_mac, command='AC')
                # save configuration
                self._zb.remote_at(dest_addr_long=bytes_mac, command='WR')

            with self._db_lock:
                if(custom):
                    # add to db dict
                    self._device_db[device_name] = {'name':device_name, 'mac':device_mac, 'type':device_type, 'pin':dio, 'status':0}
                else:
                    # add to db dict
                    self._device_db[device_name] = {'name':device_name, 'mac':device_mac, 'type':device_type}

            self.Log("added device \"" + device_name + "\" of type \"" + device_type + "\" to db")
            return True

    """
    Function: Remove_device
    attempts to remove a device from the db, returns True if successful, false otherwise
    """
    def Remove_device(self, device_name):
        # get db lock
        with self._db_lock:

            # check if device with that name or mac is already in db
            if(not self.Name_in_db(device_name)):
                self.Log("could not remove device \"" + device_name + "\" from db, no device with that name exists")
                return False

            # remove from db
            del(self._device_db[device_name])

            self.Log("removed device \"" + device_name + "\" from db")
            return True

    """
    Function: Change_device_name
    given old name and new name, changes device name
    returns True if successful, false otherwise
    """
    def Change_device_name(self, orig_name, new_name):
        # get db lock
        with self._db_lock:
    
            # check if device with that name is in db
            if(not self.Name_in_db(orig_name)):
                self.Log("could not rename device called \"" + orig_name + "\" from the db, no device with that name exists")
                return False
            
            # check if new name already in db
            if(self.Name_in_db(new_name)):
                self.Log("could not change name to \"" + new_name + "\", device with name already in db")
                return False
            
            # save device
            saved_device = self._device_db[orig_name]
            
            # remove old device name from db
            del(self._device_db[orig_name])
            
            # add new device name to db
            saved_device["name"] = new_name
            self._device_db[new_name] = saved_device

            self.Log("changed device name from \"" + orig_name + "\" to \"" + new_name + "\"")
            return True

    """
    Function: Recv_handler
    receives all packets from ZigBee modules (runs on separate thread)
    handles packets containing change detection samples
    """
    def Recv_handler(self, packet):
        
        # acquire process packets lock
        acquired = self._process_packets_lock.acquire(blocking=False)

        # if could not get lock
        if(not acquired):
            # put packet into queue
            self._packet_queue.put(packet, block=True, timeout=DEFAULT_TIMEOUT)
            return

        # if could get lock:
        try:
            # if discovery packet response
            if("parameter" in packet):
                discovery_data = packet['parameter']
                if("node_identifier" in discovery_data):
                    with self._db_lock:
                        
                        self.Log("received discovery packet response")
                        
                        # get mac address
                        device_mac = self.Bytes2mac(bytearray(discovery_data['source_addr_long']))
                        
                        # check if already in db
                        if(self.Mac2name(device_mac)):
                            self.Log("discovered device that is already in the db")
                            return
                        
                        # try to identify device using node identifier
                        node_identifier = discovery_data["node_identifier"].decode("utf-8")
                        
                        self.Log("NI = " + node_identifier)
                        
                        split_ident = node_identifier.split("_")
                        
                        if(len(split_ident) >= 2):       
                            # get needed values
                            device_type = split_ident[0]
                        else:
                            self.Log("can't add discovered device, unrecognized identifier: " + str(node_identifier))
                            return
                        
                        # attempt to add to db
                        success = self.Add_device(node_identifier, device_mac, device_type)
                        
                        if(success):
                            self.Log("discovered device with mac \"" + device_mac + "\" of type \"" + device_type + "\"")
                            self.Log("device named \"" + node_identifier + "\", use change_device_name command to change it to a better name")
                            return
                        else:
                            self.Log("failed to add discovered device to db")
                            return
        finally:
            # release process_packets lock
            self._process_packets_lock.release()

    """
    Function: Send_discovery_packet
    sends network discovery command to local zigbee.
    discovered devices are handled in Recv_handler
    """
    def Send_discovery_packet(self):
        self.Log("sending device discovery packet")

        # get lock
        with self._zb_lock:
            # tell local zigbee to discover devices on network
            self._zb.at(command='ND')

    """
    Function: Add_task
    given a dict of commands, adds a task to apscheduler

    required params:
       task_type    : "repeating", "once"    
       task_id      : unique identifying string
       task_command : any valid set device level command

    repeating:
       one or more of the following: "year", "month", "day", "hour", "minute", "second"

    once:
       all of the following: "year", "month", "day", "hour", "minute", "second"
    """
    """
    def Add_task(self, params):
        
        if("task_type" not in params):
            self.Log("can't add task, no \"task_type\" in parameters")
            return False

        if("task_id" not in params):
            self.Log("can't add task, no \"task_id\" in parameters")
            return False

        if("task_command" not in params):
            self.Log("can't add task, no \"task_command\" in parameters")
            return False
        
        task_command = params["task_command"]
        task_type = params['task_type']
        task_id = params["task_id"]

        # create copy of params to pass to run_command function
        run_params = params

        # re define command to task command
        run_params["command"] = task_command

        year = None
        month = None
        day = None
        hour = None
        minute = None
        second = None
        
        # if interval type
        if(task_type == "interval"):
            if("year" in params):
                year = int(params["year"])
            if("month" in params):
                month = params["month"]
            if("day" in params):
                day = params["day"]
            if("hour" in params):
                hour = int(params["hour"])
            if("minute" in params):
                minute  = int(params["minute"])
            if("second" in params):
                second  = int(params["second"])

            # add job
            self._sched.add_job(self._task_function, trigger='interval', years=year, months=month, days=day, hours=hour, minutes=minute, seconds=second, args=[run_params], id=task_id, replace_existing=True)

        # if repeating type
        elif(task_type == "day"):

            if("day" in params):
                day_of_week = int(params["day"])
            if("hour" in params):
                hour = int(params["hour"])
            if("minute" in params):
                minute = int(params["minute"])
            if("second" in params):
                second = int(params["second"])

            # add job
            self._sched.add_job(self._task_function, trigger='cron', day_of_week=day_of_week, hour=hour, minute=minute, second=second, args=[run_params], id=task_id, replace_existing=True)
            
        # if single occurance type
        elif(task_type == "once"):

            if(not("year" in params and "month" in params and "day" in params and "hour" in params
                   and "minute" in params and "seconds" in params)):
                self.Log("adding task failed, did not include one of these required params: year, month, day, hour, minute, second")
                return False

            year = int(params["year"])
            month = params["month"]
            day = params["day"]
            hour = int(params["hour"])
            minute  = int(params["minute"])
            second  = int(params["second"])

            self._sched.add_job(self._task_function, trigger='date',
                              run_date=time.datetime(year, month, day, hour, minute, second),
                                args=[task_command], id=task_id, replace_existing=True)

        else:
            self.Log("invalid task type \"" + task_type + "\"")
            return False

        self.Log("added task \"" + task_id + "\" to schedule")
        return True
    """

    """
    def Remove_task(self, task_id):
        self._sched.remove_job(task_id)
        self.Log("removed task \"" + task_id + "\" from schedule")

    def Get_tasks(self):
        return self._sched.get_jobs()
    """

    """
    Function: Run_command
    recieves a dict of command to execute
    commands = test, get(level), set(level), add(name, mac, type), remove(name)
    """
    def Run_command(self, params):
        """
        if("task_id" in params):
            self.Log("executing task \"" + params["task_id"] + "\"")
        """

        # get the command
        if("cmd" in params):
            command = params["cmd"]
        elif("command" in params):
            command = params["commands"]
        else:
            command = "invalid"

        # check for delayed command
        if("delay_seconds" in params):
            delay = float(params["delay_seconds"])
            del(params["delay_seconds"])
            t = Timer(delay, self.Run_command, params)
            t.start()
            return("ok")

        # test
        if (command == "test"):
            self.Log("receieved test command")
            return("ok")

        # get current temp
        elif(command == "get_curr_temp"):
            # check if units are specified
            if("units" in params):
                units = params["units"][0].upper()
                return str(self.Get_curr_temp(units=units))
            else:
                return str(self.Get_curr_temp())

        # get set temp
        elif(command == "get_set_temp"):

            # check if units are specified
            if("units" in params):
                units = params["units"][0].upper()
                return str(self.Get_set_temp(units=units))
            else:
                return str(self.Get_set_temp())

        # set temperature
        elif(command == "set_temp"):
            # check if temp is given
            if("temp" not in params):
                self.Log("set_temp failed, must specify \"temp\"")
                return "failed"

            temp = float(params["temp"])
            
            # check if units are specified
            if("units" in params):
                units = params["units"][0].upper()
                success = self.Set_temp(temp, units=units)
            else:
                success = self.Set_temp(temp)

            if(success):
                return ("ok")
            else:
                return ("failed")

        # set temperature mode
        elif(command == "set_temp_mode"):
            # check if temp_mode is given
            if("temp_mode" not in params):
                self.Log("set_temp_mode failed, must specify \"temp_mode\"")
                return "failed"

            temp_mode = params["temp_mode"]
            
            success = self.Set_temp_mode(temp_mode)

            if(success):
                return ("ok")
            else:
                return ("failed")

        # set fan mode
        elif(command == "set_fan_mode"):
            # check if temp_mode is given
            if("fan_mode" not in params):
                self.Log("set_fan_mode failed, must specify \"fan_mode\"")
                return "failed"

            fan_mode = params["fan_mode"]

            success = self.Set_fan_mode(fan_mode)

            if(success):
                return ("ok")
            else:
                return ("failed")

        # get temp mode
        elif(command == "get_temp_mode"):
            return self.Get_temp_mode()

        # get fan mode
        elif(command == "get_fan_mode"):
            return self.Get_fan_mode()

        # set level
        elif (command == "set_device_level"):

            if('name' not in params):
                self.Log("cannot run set command, must specify \"name\"")
                return("failed")
            
            # get device name
            device_name = params['name']

            if('level' not in params):
                self.Log("cannot run set command, must specify \"level\"")
                return("failed")

            level = params['level']
            
            if(level == "off"):
                level = 0
            elif(level == "on"):
                level = 100
            elif(level in ["dimmed", "dim"]):
                level = 50
            else:
                level = int(params['level'])

            if(level < 0 or level > 100):
                self.Log("level was invalid")
                return("failed")

            success = self.Set_device_level(device_name, int(level))

            if(not success):
                return("failed")
            else:
                return("ok")

        # get level
        elif(command == "get_device_level"):

            if('name' not in params):
                self.Log("cannot run get command, must specify \"name\"")
                return("failed")
            
            # get device name
            device_name = params['name']

            curr_level = self.Get_device_level(device_name)

            if(curr_level == LEVEL_UNK):
                return("unk")
            else:
                return(str(curr_level))

        # add a device
        elif(command == "add_device"):

            if('name' not in params):
                self.Log("cannot run add command, must specify \"name\"")
                return("failed")

            if('mac' not in params):
                self.Log("cannot run add command, must specify \"mac\"")
                return("failed")

            if('type' not in params):
                self.Log("cannot run add command, must specify \"type\"")
                return("failed")
            
            # get device name, mac addr, and type
            device_name = params['name']
            mac = params['mac']
            device_type = params['type']

            success = self.Add_device(device_name, mac, device_type)

            if(success):
                return("ok")
            else:
                return("failed")
        
        # remove a device
        elif(command == "remove_device"):

            if('name' not in params):
                self.Log("cannot run remove command, must specify \"name\"")
                return("failed")
            
            device_name = params['name']

            success = self.Remove_device(device_name)

            if(success):
                return("ok")
            else:
                return("failed")

        # change a device name
        elif(command == "change_device_name"):

            if("name" not in params):
                self.Log("cannot run change_device_name command, must specify \"name\"")
                return("failed")

            if("new_name" not in params):
                self.Log("cannot run change_device_name command, must specify \"new_name\"")
                return("failed")

            orig_name = params["name"]
            new_name = params["new_name"]

            success = self.Change_device_name(orig_name, new_name)

            if(success):
                return("ok")
            else:
                return("failed")

        # discover devices
        elif(command == "discover_devices"):
            self.Send_discovery_packet()
            return("ok")

        # list devices
        elif(command == "list_devices"):

            device_list = ""

            if(len(self._device_db) == 0):
                return ("none")
            
            for k in self._device_db:
                device_list = device_list + k + ","

            # return without extra ","
            return (device_list[:-1])
        
        elif(command == "list_devices_with_types"):
            device_list = ""

            if(len(self._device_db) == 0):
                return ("none")
            
            for device_name in self._device_db:
                device_list = device_list + device_name + ":" + self._device_db[device_name]["type"] + ","

            # return without extra ","
            return (device_list[:-1])

        else:
            self.Log("recieved invalid command")
            return("invalid")

        """
        # add a task
        elif(command == "add_task"):
            success = self.Add_task(params)

            if(success):
                return("ok")
            else:
                return("failed")
        """

    """
    Function: Log
    prints string to console and log file with a timestamp
    """
    def Log(self, logstr):
        self._log.info(logstr)
        print(time.strftime(LOG_TIMESTAMP) + ": " + logstr)

if(__name__ == "__main__"):
    print("this is a library. import it to use it")
    exit(0)
