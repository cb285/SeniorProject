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

from thermostat_constants import *
from logging_constants import *
from xbee_constants import *

DEVICE_DB_FILENAME = ".devices.json"               # path to device db file
TASKS_DB_FILENAME = "sqlite:///.tasks.db"          # path to task db file
THERM_SETTINGS_FILENAME = ".thermostat.json"       # path to thermostat settings file
SETUP_WAIT = 5                                     # time in seconds to wait for samples to be received on server startup
DISCOVERY_TASKID = "__discovery_task__"               # task id to use for network discovery task
LEVEL_UNK = -1                                     # special device level used to mean level is unknown

COORDINATOR_MAC = "0013a20041553733"
MAX_RX_TRIES = 3

SWITCH_TYPE = "switch"
DIMMER_TYPE = "dimmer"
DEVICE_TYPES = [SWITCH_TYPE, DIMMER_TYPE]   # valid device types

UNK = "unknown"

POWER_LOG_TASKID = "__power_logger_task__"
TEMP_LOG_TASKID = "__temp_logger_task__"
THERM_TASKID = "__therm_task__"

class Home():
    def __init__(self, thermostat_function, task_function, power_usage_function):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_TIMESTAMP)
        self._log = logging.getLogger('home')
        self._log.addHandler(JournalHandler())
        
        self.Log("starting server, please wait...")

        # setup task scheduler
        self._sched = BackgroundScheduler()
        self._sched.add_jobstore('sqlalchemy', url=TASKS_DB_FILENAME)

        # set up zigbee
        self._Setup_zigbee()

        # set up thermostat
        self._Setup_therm()

        # send discovery packet
        self.Send_discovery_packet()

        # start scheduler
        self._sched.start()

        # start power usage logger task
        #self._sched.add_job(power_log_function, trigger='interval', minutes=POWER_LOG_INTERVAL, id=POWER_LOG_TASKID, replace_existing=True)

        # start temperature logger task
        #self._sched.add_job(temp_log_function, trigger='interval', minutes=TEMP_LOG_INTERVAL, id=TEMP_LOG_TASKID, replace_existing=True)

        # start thermostat updater task
        self._sched.add_job(thermostat_function, trigger='interval', seconds=THERM_INTERVAL, id=THERM_TASKID, replace_existing=True)

        # store task_function for adding tasks
        self._task_function = task_function

        # register shutdown proceedure
        atexit.register(self.Exit)

        # setup complete
        self.Log("server ready!")

    def Exit(self):

        # log
        self.Log("shutdown procedure started...")
        
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
            self.Log("opened existing db " + DEVICE_DB_FILENAME)

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
        self._curr_temp_mode = "unk"
        self._curr_fan_mode = "unk"
        
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
                self.Log("opened existing thermostat settings file " + THERM_SETTINGS_FILENAME)

    def _Initialize_therm_settings(self):

        with self._therm_lock:

            # temp mode
            self.Set_temp_mode(INIT_TEMP_MODE)
            # fan mode
            self.Set_fan_mode(INIT_FAN_MODE)
            # set temp
            self.Set_temp(INIT_SET_TEMP)
            # temp diffs
            self.Set_temp_lower_diff(INIT_LOWER_DIFF)
            self.Set_temp_upper_diff(INIT_UPPER_DIFF)

    def Get_curr_temp(self, units=DEFAULT_TEMP_UNITS):

        # acquire i2c lock
        with self._i2c_lock:
            # read adc
            pass
        
        # convert to degrees F
        curr_temp_f = 70

        return self.Convert_temp(curr_temp_f, "F", units)

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

        if(temp_mode not in ["heat", "cool", "off"]):
            self.Log("invalid temp_mode: " + str(temp_mode))
            return False

        with self._therm_lock:
            self._therm_settings["temp_mode"] = temp_mode

        return True

    def Set_fan_mode(self, fan_mode):

        if(fan_mode not in ["off", "on", "auto"]):
            self.Log("invalid fan_mode: " + str(fan_mode))
            return False
        
        with self._therm_lock:
            self._therm_settings["fan_mode"] = fan_mode

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

    def _Set_curr_therm_mode(self, temp_mode=None, fan_mode=None):
        
        # if changing temp mode
        if(temp_mode):

            # check if no change is needed
            if(temp_mode == self._curr_temp_mode):
                pass

            # change to cool
            elif(temp_mode == "cool"):
                self.Log("turning AC on")
                # turn heat off
                gpio.output(THERM_HEAT_CTRL, gpio.low)
                # turn ac on
                gpio.output(THERM_AC_CTRL, gpio.high)
                # update current mode
                self._curr_temp_mode = temp_mode

            # change to heat
            elif(temp_mode == "heat"):
                self.Log("turning heat on")
                # turn cool off
                gpio.output(THERM_AC_CTRL, gpio.low)
                # turn heat on
                gpio.output(THERM_HEAT_CTRL, gpio.high)
                # update current mode
                self._curr_temp_mode = temp_mode

            # change to off
            elif(temp_mode == "off"):
                self.Log("turning heat/AC off")
                # turn cool off
                gpio.output(THERM_AC_CTRL, gpio.low)
                # turn heat off
                gpio.output(THERM_HEAT_CTRL, gpio.high)
                # update current mode
                self._curr_temp_mode = temp_mode
            # invalid mode
            else:
                self.Log("invalid temp_mode: " + str(temp_mode))

        # if changing fan mode
        if(fan_mode):

            # check if no change is needed
            if(fan_mode == self._curr_fan_mode):
                pass

            # change to on
            elif(fan_mode == "on"):
                self.Log("turning fan on")
                # turn fan on
                gpio.output(THERM_FAN_CTRL, gpio.high)
                # update current mode
                self._curr_fan_mode = fan_mode

            # change to off
            elif(fan_mode == "off"):
                self.Log("turning fan off")
                # turn ac off
                gpio.output(THERM_AC_CTRL, gpio.low)
                # turn heat off
                gpio.output(THERM_HEAT_CTRL, gpio.low)
                # turn fan off
                gpio.output(THERM_FAN_CTRL, gpio.low)
                # update current mode
                self._curr_fan_mode = fan_mode
            else:
                self.Log("invalid fan_mode: " + str(fan_mode))

    def Thermostat_update(self):
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

            # get difference from set temperature
            temp_diff = curr_temp - set_temp

            # if temperature is too high
            if(temp_diff > upper_diff):
                # check if should change current fan mode
                if(curr_fan_mode != "on"):
                    # check if can change current fan mode
                    if(fan_mode in ["on", "auto"]):
                        # turn fan on
                        self._Set_curr_therm_mode(fan_mode="on")

                    # check if should change current temp mode
                    if(curr_temp_mode != "cool"):
                        # check if can change current temp mode
                        if(temp_mode in ["cool", "auto"]):
                            # turn on ac
                            self._Set_curr_therm_mode(temp_mode="cool")
            # if temperature is too low
            elif(-1*temp_diff > lower_diff):
                # check if should change current fan mode
                if(curr_fan_mode != "on"):
                    # check if can change current fan mode
                    if(fan_mode in ["on", "auto"]):
                        # turn fan on
                        self._Set_curr_therm_mode(fan_mode="on")
                    
                    # check if should change current temp mode
                    if(curr_temp_mode in ["heat", "auto"]):
                        # check if can change current temp mode
                        if(temp_mode in ["heat", "auto"]):
                            # turn on heat
                            self._Set_curr_therm_mode(temp_mode="heat")
            # if temperature is within bounds
            else:
                # check if should change current fan mode
                if(curr_fan_mode != "off"):
                    # check if can change current fan mode
                    if(fan_mode in ["off", "auto"]):
                        # turn fan off
                        self._Set_curr_therm_mode(fan_mode="off")
                    
                    # check if should change current temp mode
                    if(curr_temp_mode != "cool"):
                        # check if can change current temp mode
                        if(temp_mode in ["cool", "auto"]):
                            # turn on ac
                            self._Set_curr_therm_mode(temp_mode="cool")

    def Get_power_usage(self, device_name):
        
        # sample device's current sense pin
        sample_val = _Sample_xbee(device_name, pins=[CURRSENSE_SAMPLE_IDENT])

        # if could not get sample
        if(sample_val == LEVEL_UNK):
            return LEVEL_UNK

        # convert to voltage
        sample_voltage = (sample_val / 1023.0) * 1.2

        # convert to ac current amplitude (mA)
        ac_current = ((sample_voltage - CURRSENSE_BIAS + CURRSENSE_DDROP) / 66.66)

        # calculate apparent power (mVA)
        apparent_power = ac_current*AC_VOLTAGE

        # get power factor
        with self._db_lock:
            if("power_factor" in self._device_db[device_name]):
                power_factor = self._device_db[device_name]["power_factor"]

            # assume reative if not specified
            else:
                power_factor = 1.0

        # return approximate real power (mW)
        return int(round(apparent_power * power_factor))

    def Log_power_usages(self):

        # get database lock
        with self._db_lock:

            # if file is not already created
            if(not os.path.isfile(POWER_LOG_FILENAME)):
                with open(POWER_LOG_FILENAME, 'a+') as f:
                    f.write("time, device_name, power_usage\n")

            # open power log file
            with open(POWER_LOG_FILENAME, 'a+') as f:
            
                # for each device in database
                for device_name in self._device_db:
                    
                    # get current power usage
                    power_usage = Get_power_usage(device_name)

                    # add line to csv
                    f.write(time.strftime(POWER_TIMESTAMP) + "," + device_name + "," + power_usage + "\n")

    """
    Function: Mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    def Mac2bytes(self, mac):
        return bytearray.fromhex(mac)

    def Bytes2mac(self, mac):
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
            # get relay status
            samples = self._Sample_xbee(device_name=device_name, pins=[RELAY_STAT_SAMPLE_IDENT])

            if(not samples):
                return LEVEL_UNK
            return samples[RELAY_STAT_SAMPLE_IDENT]
            
        # dimmer device
        elif(device_type == DIMMER_TYPE):
            samples = self._Sample_xbee(device_name=device_name, pins=[RELAY_STAT_SAMPLE_IDENT, DPOT_OUT_SAMPLE_IDENT])

            if(not samples):
                return LEVEL_UNK
            
            relay_level = samples[RELAY_STAT_SAMPLE_IDENT]
            
            # if relay is off
            if(relay_level == 0):
                # turn off sampling
                return 0

            # if relay is on
            else:
                # get level
                dpot_level = int(round(100*((samples[DPOT_OUT_SAMPLE_IDENT] / 1023.0) * 1.2)))

                # adjust the level
                if(dpot_level >= 95):
                    dpot_level = 100
                elif(dpot_level <= 0):
                    dpot_level = 1

                # return level
                return dpot_level

    def _Sample_xbee(self, device_name=False, pins=False, timeout=DEFAULT_TIMEOUT):
        
        # if remote device
        if(device_name):
            # get db lock
            with self._db_lock:
                
                # get device mac
                mac_addr = self.Get_device_mac(device_name)

                if(mac_addr == UNK):
                    self.Log("cannot sample device \"" + device_name + "\", no device with that name in db")
                    # return unknown
                    return LEVEL_UNK

                bytes_mac = self.Mac2bytes(mac_addr)

        else:
            bytes_mac = self.Mac2bytes(COORDINATOR_MAC)

        # get process packets lock
        with self._process_packets_lock:
            
            # clear the queue
            while(not self._packet_queue.empty()):
                self._packet_queue.get(block=False)
                
            with self._zb_lock:
                try:
                    # if remote device
                    if(device_name):
                        # request sample (periodic sampling every 255 ms)
                        self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x0FF')
                    else:
                        # request sample
                        self._zb.at(command='IS')
                        
                    # for each try
                    for x in range(MAX_RX_TRIES):
                        try:
                            # wait for a packet
                            packet = self._packet_queue.get(block=True, timeout=timeout)
                        except Empty:
                            packet = False
                            
                        # if didn't receive packet
                        if(not packet):
                            if(device_name):
                                self.Log("could not get sample from device \"" + device_name + "\", check the device")
                                return False
                            else:
                                self.Log("could not get sample from local xbee, check the device")
                                return False

                        # check if packet is from desired device
                        if("source_addr_long" not in packet):
                            continue
                        if((bytearray(packet['source_addr_long'])) != bytes_mac):
                            continue

                        # check if sample packet
                        if("samples" in packet):                        
                            samples = packet["samples"][0]
                            
                            # if no specific pin given, return all
                            if(not pins):
                                return samples
                            
                            sample_dict = dict()
                            
                            for pin in pins:
                                if(pin not in samples):
                                    continue
                                
                                if(type(samples[pin]) is bool):
                                    if(samples[pin]):
                                        sample_dict[pin] = 100
                                    else:
                                        sample_dict[pin] = 0
                                else:
                                    sample_dict[pin] = samples[pin]
                                    
                            return sample_dict
                        
                    # if couldn't get desired samples
                    return False
                    
                    # turn off periodic sampling
                finally:
                    if(device_name):
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
        
        # get current device level
        curr_level = self.Get_device_level(device_name)
        
        # check if got a sample
        if(curr_level == LEVEL_UNK):
            self.Log("could not set device \"" + device_name +"\" level to " + str(level) + ", could not communicate with module")
            return False

        # check if need to change the level
        if(curr_level == level):
            self.Log("did not need to set device \"" + device_name +"\" level to " + str(level) + ", was already set")
            return True
        
        # get db lock
        with self._db_lock:
            
            # get device type
            device_type = self._device_db[device_name]['type']
            
            # if outlet
            if(device_type == SWITCH_TYPE):
                # toggle relay
                self._Toggle_relay(device_name)
                return True

            elif(device_type == DIMMER_TYPE):
                # set light level using a thread
                Thread(target=lambda: self._Set_light(device_name, curr_level, level)).start()
                return True

    def _Toggle_relay(self, device_name):

        # get db lock
        with self._db_lock:
            # get device mac
            device_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

        # get zigbee lock
        with self._zb_lock:
            # set relay toggle pin high
            self._zb.remote_at(dest_addr_long=device_mac, command=RELAY_TOGGLE, parameter=XB_CONF_HIGH)
            # wait
            time.sleep(WAIT_TIME)
            # make relay toggle pin low
            self._zb.remote_at(dest_addr_long=device_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

    def _Set_light(self, device_name, curr_level, level):

        # get db lock
        with self._db_lock:
            # get device mac
            bytes_mac = self.Mac2bytes(self._device_db[device_name]['mac'])
            
        # get zigbee lock
        with self._zb_lock:
            
            if(curr_level == 0):
                # turn on the relay
                self._Toggle_relay(device_name)
                
                curr_level = self.Get_device_level(device_name)
            try:
                # set D flip flop CLR# to low (cleared)
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_LOW)

                # if light is too bright
                if(curr_level > level):
                    
                    # set U/D# to low (down)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)
                    
                    num_tries = 0
                    
                    # while the light is too bright
                    while(level < self.Get_device_level(device_name)):
                        
                        # decrement the dpot
                        # set INC# high
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_HIGH)
                        # set INC# low
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                        
                        num_tries += 1
                        
                        if(num_tries >= LIGHT_SET_TRIES):
                            self.Log("could not set light to desired level, giving up.")
                            break
                        
                # light is too dim
                else:
                    # set U/D# to high (up)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_HIGH)
                    
                    num_tries = 0
                    
                    # while the light is too dim
                    while(self.Get_device_level(device_name) < level):
                        
                        # increment the dpot
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_HIGH)
                        # set INC# low
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                                                
                        num_tries += 1
                        
                        if(num_tries >= LIGHT_SET_TRIES):
                            self.Log("could not set light to desired level, giving up.")
                            break

            finally:
                # set D flip flop CLR# to high (not cleared)
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_HIGH)

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

            # acquire zigbee lock
            with self._zb_lock:
                # for outlets and lights, set up change detection for input button
                if(device_type in [SWITCH_TYPE, DIMMER_TYPE]):
                    # set RELAY_STATUS (D1) to input
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_STAT, parameter=XB_CONF_DINPUT)

                    # set CURRSENSE_OUT (D3) to analog input
                    #self._zb.remote_at(dest_addr_long=bytes_mac, command=CURRSENSE_OUT, parameter=XB_CONF_ADC)
                    
                    # set RELAY_TOGGLE (D0) to output low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

                if(device_type == DIMMER_TYPE):
                    # set DPOT_OUT (D2) to analog input
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_OUT, parameter=XB_CONF_ADC)
                    
                    # set D flip flop CLR# to high
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_HIGH)
                    
                    # DPOT INC# to low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                
                    # set U/D# to low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)

                # create node identifier
                node_identifier = device_type + "_" + device_mac[12:]

                # write node identifier to device
                self._zb.remote_at(dest_addr_long=bytes_mac, command='NI', parameter=node_identifier)

                # apply changes
                self._zb.remote_at(dest_addr_long=bytes_mac, command='AC')
                # save configuration
                self._zb.remote_at(dest_addr_long=bytes_mac, command='WR')

            with self._db_lock:
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

        # if could not get lock (other thread is receiving packets)
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
                        
                        if(len(split_ident) == 2):       
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
    def Add_task(self, params):
        
        if("task_type" not in params):
            self.Log("can't add task, no \"schedule_type\" in parameters")
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
        elif(task_type == "cron"):

            year = None
            month = None
            day = None
            hour = None
            minute = None
            second = None

            if("year" in params):
                year = int(params["year"])
            if("month" in params):
                month = params["month"]
            if("day" in params):
                day = params["day"]
            if("hour" in params):
                hour = int(params["hour"])
            if("minute" in params):
                minute = int(params["minute"])
            if("second" in params):
                second = int(params["second"])

            # add job
            self._sched.add_job(self._task_function, trigger='cron', year=year, month=month, day=day, hour=hour, minute=minute, second=second, args=[run_params], id=task_id, replace_existing=True)
            
        # if single occurance type
        elif(task_type == "once"):

            if(not("year" in params and "month" in params and "day" in params and "hour" in params
                   and "minute" in params and "seconds" in params)):
                self.Log("adding task failed, did not include one of these required params: year, month, day, hour, minute, second")
                return False

            year = int(params["year"])
            month = int(params["month"])
            day = int(params["day"])
            hour = int(params["hour"])
            minute = int(params["minute"])
            second = int(params["second"])

            self._sched.add_job(self._task_function, trigger='date',
                              run_date=time.datetime(year, month, day, hour, minute, second),
                                args=[task_command], id=task_id, replace_existing=True)

        else:
            self.Log("invalid task type \"" + task_type + "\"")
            return False

        self.Log("added task \"" + task_id + "\" to schedule")
        return True

    def Remove_task(self, task_id):
        self._sched.remove_job(task_id)
        self.Log("removed task \"" + task_id + "\" from schedule")

    def Get_tasks(self):
        return self._sched.get_jobs()

    """
    Function: Run_command
    recieves a dict of command to execute
    commands = test, get(level), set(level), add(name, mac, type), remove(name)
    """
    def Run_command(self, params):
        
        if("task_id" in params):
            self.Log("executing task \"" + params["task_id"] + "\"")

        # get the command
        if("cmd" in params):
            command = params["cmd"]
        elif("command" in params):
            command = params["commands"]
        else:
            command = "invalid"

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

            temp = int(params["temp"])
            
            # check if units are specified
            if("units" in params):
                units = params["units"][0].upper()
                success = self.Set_temp(temp, units=units)
            else:
                success = Set_temp(temp)

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
            
            # get wanted device level
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
                return(command + ":failed")
            
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
                device_list = device_list + "," + k

            return (device_list)

        elif(command == "list_devices_with_types"):
            device_list = ""

            if(len(self._device_db) == 0):
                return ("none")
            
            for k in self._device_db:
                device_list = device_list + "," + k

            return (device_list)

        # add a task
        elif(command == "add_task"):
            success = self.Add_task(params)

            if(success):
                return("ok")
            else:
                return("failed")

        else:
            self.Log("recieved invalid command")
            return("invalid")

    """
    Function: Log
    prints string to console and log file with a timestamp
    """
    def Log(self, logstr):
        self._log.info(logstr)
        print(time.strftime(LOG_TIMESTAMP) + ": " + logstr)

def Update_thermostat():
    global myhome
    myhome.Thermostat_update()
        
def Run_task(task):
    global myhome
    myhome.Run_command(task)

def Log_power_usages():
    global myhome
    myhome.Log_power_usages()

if(__name__ == "__main__"):
    print("this is a library. import it to use it")
    exit(0)

myhome = Home(thermostat_function=Update_thermostat, task_function=Run_task, power_usage_function=Log_power_usages)

