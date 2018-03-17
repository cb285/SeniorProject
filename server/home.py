#!/usr/bin/env python3

import sys
import os
import json
from xbee import ZigBee
import serial
import logging
from systemd.journal import JournalHandler
import time
from threading import *
from apscheduler.schedulers.background import BackgroundScheduler
from queue import *

DEVICE_DB_FILENAME = "devices.json"               # path to device db file
TASKS_DB_FILENAME = "sqlite:///tasks.db"          # path to task db file
LOG_FILENAME = "home_server.log" # log filename
LOG_FORMAT = '%(asctime)s : %(name)s : %(message)s'
LOG_TIMESTAMP = "%Y-%m-%d %H:%M:%S"
POWER_TIMESTAMP = LOG_TIMESTAMP

POWER_LOG_FILENAME = "power_usage_log.csv"
POWER_LOG_INTERVAL = 10 # interval in minutes

SETUP_WAIT = 5                             # time in seconds to wait for samples to be received on server startup
DISCOVERY_INTERVAL = 5                     # time in minutes between network discovery packet sends
DISCOVERY_TASKID = "_discovery_task"       # task id to use for network discovery task

LEVEL_UNK = -1                             # special device level used to mean level is unknown

OUTLET_TYPE = "outlet"
LIGHT_TYPE = "light"
DEVICE_TYPES = [OUTLET_TYPE, LIGHT_TYPE]   # valid device types

DEFAULT_TIMEOUT = 2 # seconds

LIGHT_SET_TRIES = 200

WAIT_TIME = 0.1

XB_CONF_HIGH = b'\x05'
XB_CONF_LOW = b'\x04'
XB_CONF_DINPUT = b'\x03'
XB_CONF_ADC = b'\x02'

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

"""
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

class Home():
    def __init__(self, task_function, power_usage_function):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_TIMESTAMP)
        self._log = logging.getLogger('home')
        self._log.addHandler(JournalHandler())
        
        #formatter = logging.Formatter()
        #self._log.setFormatter(formatter)
        
        self.Log("starting server, please wait...")

        # setup task scheduler
        self._sched = BackgroundScheduler()
        self._sched.add_jobstore('sqlalchemy', url=TASKS_DB_FILENAME)

        # create lock for xbee access
        self._zb_lock = RLock()

        # create lock for device_db access
        self._db_lock = RLock()

        # create lock for permission to process packets
        self._process_packets_lock = RLock()

        # create queue for holding pending packets
        self._packet_queue = Queue(maxsize=10)

        # acquire locks
        with self._zb_lock:
            with self._db_lock:

                # setup connection to zigbee module
                ser = serial.Serial()
                ser.port = "/dev/ttyS0"
                ser.baudrate = 9600
                ser.timeout = 3
                ser.write_timeout = 3
                ser.exclusive = True
                ser.open()

                self._ser = ser

                self._zb = ZigBee(ser, escaped=True, callback=self.Recv_handler)
                
                # load/create db file
                if not (os.path.isfile(DEVICE_DB_FILENAME)):  # check if need to create db file
                    self.Log(DEVICE_DB_FILENAME + " file doesn't exist, creating it.")
                    self._device_db = dict()
                    # save db to file
                    self._Save_db()

                else:
                    with open(DEVICE_DB_FILENAME) as f:
                        self._device_db = json.load(f)
                    self.Log("opened existing db " + DEVICE_DB_FILENAME)

                # send discovery packet
                self.Send_discovery_packet()

                # start scheduler
                self._sched.start()

                # start power usage logger task
                #self._sched.add_job(power_usage_function, trigger='interval', minutes=POWER_LOG_INTERVAL, id=task_id, replace_existing=True)
                
                # store task_function for using when adding tasks
                self._task_function = task_function
                
                self.Log("server ready!")

    def _Save_db(self):

        # get db lock
        with self._db_lock:
            
            # dump db to file
            with open(DEVICE_DB_FILENAME, 'w') as f:
                json.dump(self._device_db, f)

    """
    Function: Mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    def Mac2bytes(self, mac):
        return bytearray.fromhex(mac)

    def Bytes2mac(self, mac):
        return mac.hex()

    def Get_power_usage(self, device_name):

        # sample device's current sense pin
        sample_val = Sample_device(device_name, get_current=True)

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
    
    def Sample_device(self, device_name, get_current=False, timeout=DEFAULT_TIMEOUT):

        # get db lock
        with self._db_lock:
        
            # check if device in db
            if(not self.Name_in_db(device_name)):
                self.Log("cannot sample device \"" + device_name + "\", no device with that name in db")
                # return unknown
                return LEVEL_UNK

            # get device type
            device_type = self._device_db[device_name]['type']
            # get device mac
            bytes_mac = self.Mac2bytes(self._device_db[device_name]['mac'])
            
            # get process packets lock
            with self._process_packets_lock:

                # clear the queue
                while(not self._packet_queue.empty()):
                    self._packet_queue.get(block=False)
                
                # request sample (periodic sampling every 255 ms)
                self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x0FF');

                for x in range(3):

                    try:
                        # wait for a packet
                        packet = self._packet_queue.get(block=True, timeout=timeout)

                    except Empty:
                        packet = False
                        
                    # check if didn't receive packet
                    if(not packet):
                        self.Log("could not get sample from device \"" + device_name + "\", check the device")
                        # turn off sampling
                        self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');
                        return LEVEL_UNK
                    
                    if("source_addr_long" not in packet):
                        self.Log("does not contain source addr")
                        continue
                    
                    # check if packet is from device of interest
                    if((bytearray(packet['source_addr_long'])) != bytes_mac):
                            self.Log("mac doesn't match device of interest")
                            continue

                    # check if sample packet
                    if("samples" in packet):                        
                        samples = packet["samples"][0]

                        # if current sense value is desired
                        if(get_current):
                            if(CURR_SENSE_SAMPLE_IDENT in samples):

                                # turn off sampling
                                self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');

                                # return current level
                                return samples[CURRSENSE_SAMPLE_IDENT]
                                
                        # if outlet device
                        if(device_type == OUTLET_TYPE):
                            # get relay status
                            stat = samples[RELAY_STAT_SAMPLE_IDENT]
                            if(stat):
                                # turn off sampling
                                self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');
                                return 100
                            else:
                                # turn off sampling
                                self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');
                                return 0

                        # if light device
                        elif(device_type == LIGHT_TYPE):

                            # if contains relay status
                            if(RELAY_STAT_SAMPLE_IDENT in samples):
                                # get relay status
                                stat = samples[RELAY_STAT_SAMPLE_IDENT]
                                
                                # if relay is off
                                if(not stat):
                                    # turn off sampling
                                    self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');
                                    return 0

                                # if relay is on
                                else:
                                    # if contains dpot analog out status
                                    if(DPOT_OUT_SAMPLE_IDENT in samples):
                                        
                                        # get level
                                        dpot_level = int(round(100*((samples[DPOT_OUT_SAMPLE_IDENT] / 1023.0) * 1.2)))
                                        
                                        # adjust the level
                                        if(dpot_level >= 95):
                                            dpot_level = 100
                                        elif(dpot_level <= 0):
                                            dpot_level = 1

                                        # return level
                                        # turn off sampling
                                        self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');
                                        return dpot_level

                # turn off sampling
                self._zb.remote_at(dest_addr_long=bytes_mac, command='IR', parameter=b'\x00');
                return LEVEL_UNK

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
        curr_level = self.Sample_device(device_name)
        
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
            if(device_type == OUTLET_TYPE):
                # toggle relay
                self._Toggle_relay(device_name)
                return True

            elif(device_type == LIGHT_TYPE):
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
                
                curr_level = self.Sample_device(device_name)
            try:
                # set D flip flop CLR# to low (cleared)
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_LOW)

                # if light is too bright
                if(curr_level > level):
                    
                    # set U/D# to low (down)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)
                    
                    num_tries = 0
                    
                    # while the light is too bright
                    while(level < self.Sample_device(device_name)):
                        
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
                    while(self.Sample_device(device_name) < level):
                        
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

        # get db lock
        with self._db_lock:

            self.Log("add device got lock")
            
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

            # for outlets and lights, set up change detection for input button
            if(device_type in [OUTLET_TYPE, LIGHT_TYPE]):
                # set RELAY_STATUS (D1) to input
                self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_STAT, parameter=XB_CONF_DINPUT)

                # set CURRSENSE_OUT (D3) to analog input
                #self._zb.remote_at(dest_addr_long=bytes_mac, command=CURRSENSE_OUT, parameter=XB_CONF_ADC)

                # set RELAY_TOGGLE (D0) to output low
            self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

            if(device_type == LIGHT_TYPE):
                # set DPOT_OUT (D2) to analog input
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_OUT, parameter=XB_CONF_ADC)
                
                # set D flip flop CLR# to high
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_HIGH)
                
                # DPOT INC# to low
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                
                # set U/D# to low
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)

            # create node identifier
            node_identifier = device_type + "-" + device_mac[12:]

            # write node identifier to device
            self._zb.remote_at(dest_addr_long=bytes_mac, command='NI', parameter=node_identifier)

            # apply changes
            self._zb.remote_at(dest_addr_long=bytes_mac, command='AC')
            # save configuration
            self._zb.remote_at(dest_addr_long=bytes_mac, command='WR')

            # add to db dict
            self._device_db[device_name] = {'name':device_name, 'mac':device_mac, 'type':device_type}

            # update db file
            self._Save_db()

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

            # update db file
            self._Save_db()

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
            
            # update db file
            self._Save_db()
                
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
                        
                        split_ident = node_identifier.split("-")
                        
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

            curr_level = self.Sample_device(device_name)

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
        elif(command == "ls_devices"):

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
        #print(time.strftime(LOG_TIMESTAMP) + ": " + logstr)

def Run_task(task):
    global myhome
    myhome.Run_command(task)

def Log_power_usages():
    global myhome
    myhome.Log_power_usages()

myhome = Home(task_function=Run_task, power_usage_function=Log_power_usages)

if(__name__ == "__main__"):
    print("this is a library. import it to use it")
    exit(0)
