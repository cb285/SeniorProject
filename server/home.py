#!/usr/bin/env python3

import sys
import os
import json
from xbee import ZigBee
import serial
import logging
import time
from threading import RLock
from apscheduler.schedulers.background import BackgroundScheduler

DEVICE_DB_FILENAME = "devices.json"        # path to device db file
TASKS_DB_FILENAME = "sqlite:///tasks.db"   # path to task db file
LOG_FILENAME = "server.log"                # log filename
LOG_TIMESTAMP = "%Y-%m-%d %H:%M:%S"        # timestamp format for logging

DIO_SIG_PERIOD = 0.05                      # period in seconds of square wave to trigger change

SETUP_WAIT = 5                             # time in seconds to wait for samples to be received on server startup
DISCOVERY_INTERVAL = 5                     # time in minutes between network discovery packet sends
DISCOVERY_TASKID = "_discovery_task"       # task id to use for network discovery task

LEVEL_UNK = -1                             # special device level used to mean level is unknown

OUTLET_TYPE = "outlet"
LIGHT_TYPE = "light"
DEVICE_TYPES = [OUTLET_TYPE, LIGHT_TYPE]   # valid device types

DEFAULT_FRAME_ID = b'\x01'

"""
-----------------------------------
           IO CONSTANTS
-----------------------------------
"""

XB_CONF_HIGH = b'\x05'
XB_CONF_LOW = b'\x04'
XB_CONF_DINPUT = b'\x03'
XB_CONF_ADC = b'\x02'

XB_FORCE_SAMPLE_OUT = 'D10'
XB_FORCE_SAMPLE_IN = 'D11'

# relay toggle (toggles relay on a rising edge)
RELAY_TOGGLE = 'D0'

# relay status
RELAY_STAT = 'D1'
RELAY_STAT_SAMPLE_IDENT = 'dio-1'

# number of DPOT positions
DPOT_NUM_POS = 32
# DPOT CS# pin
DPOT_CS_N = 'D2'
# DPOT U/D# pin
DPOT_UD_N = 'D4'
# D flip flop clear (clears CS#)
DFLIPCLR_N = 'D5'

# DPOT output pin
DPOT_OUT = 'D3'
DPOT_OUT_SAMPLE_IDENT = 'dio-3'

"""
-----------------------------------
         END IO CONSTANTS
-----------------------------------
"""


class Home():
    def __init__(self, discover_function, task_function):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)
        self.Log("starting server")

        # save startup time
        self._start_time = time.time()

        # setup task scheduler
        self._sched = BackgroundScheduler()
        self._sched.add_jobstore('sqlalchemy', url=TASKS_DB_FILENAME)
        logging.getLogger('apscheduler') #.setLevel(logging.DEBUG)

        # save task running function
        self._task_function = task_function

        # create lock for xbee / db access
        self._lock = RLock()

        # acquire lock
        self._lock.acquire()
        locked = True

        try:
            # setup connection to zigbee module
            ser = serial.Serial()
            ser.port = "/dev/ttyS0"
            ser.baudrate = 9600
            ser.timeout = 3
            ser.write_timeout = 3
            ser.exclusive = True
            ser.open()
            
            self._ser = ser
            
            self._zb = ZigBee(ser, escaped=True,
                              callback=self.Recv_handler)

            # load/create db file
            if not (os.path.isfile(DEVICE_DB_FILENAME)):  # check if need to create db file
                self.Log(DEVICE_DB_FILENAME + " file doesn't exist, creating it.")
                self._device_db = dict()
                with open(DEVICE_DB_FILENAME, 'w') as f:
                    json.dump(self._device_db, f)
            else:
                with open(DEVICE_DB_FILENAME) as f:
                    self._device_db = json.load(f)
                self.Log("opened existing db " + DEVICE_DB_FILENAME)

            # sample all devices in db
            self.Force_sample_all()

            # send discovery packet
            self.Discover_devices()
            
            # release lock
            self._lock.release()
            locked = False

            self.Log("sampling devices...")
            # sleep to allow samples to be processed
            time.sleep(SETUP_WAIT)
            
            # start scheduler
            self._sched.start()
            self.Log("started scheduler")

            # add network discovery task (self.Discover_devices)
            self._sched.add_job(discover_function, trigger='interval', minutes=DISCOVERY_INTERVAL, replace_existing=True, id=DISCOVERY_TASKID)

            self.Log("jobs: " + str(self.Get_tasks()))
            
            self.Log("server ready!")

        # release lock when done
        finally:
            if(locked):
                # release lock
                self._lock.release()

    """
    Function: Mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    def Mac2bytes(self, mac):
        return bytearray.fromhex(mac)

    def Force_sample_device(self, device_name):

        # get lock
        self._lock.acquire()

        # check if device in db
        if(not self.Name_in_db(device_name)):
            self.Log("cannot force sample of device \"" + device_name + "\", no device with that name in db")
            return False

        try:
            bytes_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

            # set XB_FORCE_SAMPLE_OUT to high
            self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_OUT, parameter=XB_CONF_HIGH)
            # set XB_FORCE_SAMPLE_OUT to low
            self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_OUT, parameter=XB_CONF_LOW)

            self.Log("forced sample of device \"" + device_name + "\"")

            return True
            
        # release lock when done
        finally:
            self._lock.release()

    """ Function: Force_sample_all
    requests input sample from all devices in db
    """
    def Force_sample_all(self):       
        # get lock
        self._lock.acquire()

        try:
            # for each device in db
            for device_name in self._device_db:

                bytes_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

                # set XB_FORCE_SAMPLE_OUT pin to high
                self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_OUT, parameter=XB_CONF_LOW)
                # set XB_FORCE_SAMPLE_OUT pin to low
                self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_OUT, parameter=XB_CONF_HIGH)

        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Get_device_level
    get current device level (polls device if sample is past TTL)
    returns the current level if successful, returns -1 if failed to get level
    """
    def Get_device_level(self, device_name, silent=False):
        # get lock
        self._lock.acquire()

        try:
            # check if device with that name is in db
            if(self.Name_in_db(device_name)):

                # get device type
                device_type = self._device_db[device_name]['type']

                # check if current sample is valid
                if(self._device_db[device_name]['sample_time'] >= self._start_time):
                    # get level
                    curr_level = self._device_db[device_name]['level']

                    if(not silent):
                        self.Log("current level of \"" + device_name + "\" is " + str(curr_level))

                    # return level
                    return(curr_level)

                # if sample is not valid
                else:
                    # force sample of input
                    self.Force_sample_device(device_name)

                    if(not silent):
                        self.Log("current level of \"" + device_name + "\" is unknown. trying to resample, please check if the device is turned on")
                    return LEVEL_UNK
            
        # release lock when done
        finally:
            self._lock.release()

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
        # get lock
        self._lock.acquire()

        try:
            # check if level is valid
            if(not (0 <= level and level <= 100)):
                self.Log("could not set level of \"" + device_name + "\" to " + str(level) + ", level is invalid")
                return False

            # check if device is in db
            if(not self.Name_in_db(device_name)):
                self.Log("could not change level of device \"" + device_name + "\", device not in db")
                return False

            # get current level
            curr_level = self.Get_device_level(device_name)

            # if could not get current level
            if(curr_level == LEVEL_UNK):
                self.Force_sample_device(device_name)
                self.Log("could not set \"" + device_name + "\" to " + str(level) + ". current level is unknown. trying to resample. please check if device is on")
                return False

            # get type
            device_type = self._device_db[device_name]['type']
            # get mac addr
            bytes_mac = self.Mac2bytes(self._device_db[device_name]['mac'])

            # if do not need to change level
            if(curr_level == level):
                self.Log("did not change device \"" + device_name + "\" to " + str(level) + ", was already set")
                return True

            # if not a valid device type
            if(device_type not in DEVICE_TYPES):
                self.Log("could not change device \"" + device_name + "\" to " + str(level) + ", not a valid device type")
                return False

            # if an outlet
            if(device_type == OUTLET_TYPE):
                # if valid level for an outlet
                if(level in [0, 100]):
                    # set relay toggle pin high
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_HIGH)
                    # make relay toggle pin low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)
                    # update db
                    self._device_db[device_name]['level'] = level
                    self._device_db[device_name]['sample_time'] = time.time()
                    with open(DEVICE_DB_FILENAME, 'w') as f:
                        json.dump(self._device_db, f)
                    self.Log("changed device \"" +
                             device_name + "\" level to " + str(level))
                    return True
                else:
                    self.Log("invalid level value for outlet type devices")
                    return False
            elif(device_type == LIGHT_TYPE):
                # turn off relay
                if(level == 0):
                    # set relay toggle pin high
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_HIGH)
                    # make relay toggle pin low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

                    # update db
                    self._device_db[device_name]['level'] = level
                    self._device_db[device_name]['sample_time'] = time.time()
                    with open(DEVICE_DB_FILENAME, 'w') as f:
                        json.dump(self._device_db, f)
                    self.Log("changed device \"" +
                             device_name + "\" level to " + str(level))
                    return True
                else:
                    # check if need to turn relay on
                    if(curr_level == 0):
                        # set relay toggle pin high
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_HIGH)
                        # make relay toggle pin low
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)
                        
                        # set DPOT to 0:
                        # set D flip flop CLR# to low (cleared)
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_LOW)
                        
                        # set U/D# to low (down)
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)

                        # decrement pot all the way
                        for i in range(DPOT_NUM_POS):
                            # set INC# low
                            self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                            # set INC# high
                            self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_HIGH)

                        # (can now set to desired level)

                    # calculate DPOT position increase
                    dpot_change = int(round(DPOT_NUM_POS*((level - curr_level) / 100.0)))

                    # set U/D# to high (up)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_HIGH)

                    # increment pot to desired level
                    for i in range(dpot_change):
                        # set INC# low
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_LOW)
                        # set INC# high
                        self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_INC_N, parameter=XB_CONF_HIGH)

                    # undo changes to allow encoder to change values
                    # set U/D# to low
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_UD_N, parameter=XB_CONF_LOW)    
                    # set D flip flop CLR# to high (not cleared)
                    self._zb.remote_at(dest_addr_long=bytes_mac, command=DFLIPCLR_N, parameter=XB_CONF_HIGH)

                    # update db
                    self._device_db[device_name]['level'] = level
                    self._device_db[device_name]['sample_time'] = time.time()
                    with open(DEVICE_DB_FILENAME, 'w') as f:
                        json.dump(self._device_db, f)
                    self.Log("changed device \"" +
                             device_name + "\" level to " + str(level))
                    return True

        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Name_in_db
    given device name
    returns true if device with that name is in db, false otherwise
    """
    def Name_in_db(self, device_name):
        # get lock
        self._lock.acquire()
        try:
            for device in self._device_db:
                if(device == device_name):
                    return True
                
            return False

        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Mac_in_db
    given device mac address (hex string or bytearray)
    returns true if device with that mac address is in db, false otherwise
    """
    def Mac_in_db(self, device_mac):
        # get lock
        self._lock.acquire()
        
        if(type(device_mac) is bytearray):
            byte_format = True
        else:
            byte_format = False
        
        try:
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
            
        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Mac2name
    given device mac address (hex string or bytearray)
    returns name of device if in db, empty string ("") otherwise
    """
    def Mac2name(self, device_mac):
        # get lock
        self._lock.acquire()

        if(type(device_mac) is bytearray):
            byte_format=True
        else:
            byte_format=False

        try:
            if(byte_format):
                for device in self._device_db:
                    if(self.Mac2bytes(self._device_db[device]['mac']) == device_mac):
                        return device

                return ""

            else:
                for device in self._device_db:
                    if(self._device_db[device]['mac'] == device_mac):
                        return device

                return ""
            
        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Add_device
    attempts to add a device to the db, returns True if successful, false otherwise
    """
    def Add_device(self, device_name, device_mac, device_type):
        
        # get lock
        self._lock.acquire()

        try:
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
               self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_STAT, parameter=XB_CONF_INPUT)
               # set FORCE_SAMPLE_IN (D12 to input)
               self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_IN, parameter=XB_CONF_INPUT)
               
               # set up change detection for RELAY_CTRL (D1) and FORCE_SAMPLE_IN (D12)
               self._zb.remote_at(dest_addr_long=bytes_mac, command='IC', parameter=b'\x01002')

               # set RELAY_TOGGLE (D0) to output low
               self._zb.remote_at(dest_addr_long=bytes_mac, command=RELAY_TOGGLE, parameter=XB_CONF_LOW)

               # force sample of input
               # set FORCE_SAMPLE_OUT (D12) to high
               self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_OUT, parameter=XB_CONF_HIGH)
               # set FORCE_SAMPLE_OUT (D12) to low
               self._zb.remote_at(dest_addr_long=bytes_mac, command=XB_FORCE_SAMPLE_OUT, parameter=XB_CONF_LOW)

            if(device_type == LIGHT_TYPE):
                # set DPOT_OUT (D2) to analog input
                self._zb.remote_at(dest_addr_long=bytes_mac, command=DPOT_OUT, parameter=XB_CONF_ADC)

            # create node identifier
            node_identifier = device_type + ":" + device_mac[12:]

            # write node identifier to device
            self._zb.remote_at(dest_addr_long=bytes_mac, command='NI', parameter=node_identifier)

            # apply changes
            self._zb.remote_at(dest_addr_long=bytes_mac, command='AC')
            # save configuration
            self._zb.remote_at(dest_addr_long=bytes_mac, command='WR')

            # add to db dict
            self._device_db[device_name] = {'name':device_name, 'mac':device_mac, 'type':device_type, 'level':LEVEL_UNK, 'sample_time':0}

            # update db file
            with open(DEVICE_DB_FILENAME, "w") as f:
               json.dump(self._device_db, f)

            self.Log("added device \"" + device_name + "\" of type \"" + device_type + "\" to db")
            self.Log("device identifer is set to \"" + node_identifier + "\"")
            return True

        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Remove_device
    attempts to remove a device from the db, returns True if successful, false otherwise
    """
    def Remove_device(self, device_name):
        # get lock
        self._lock.acquire()
        
        try:
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name)):

                # get mac from db
                device_mac = self._device_db[device_name]['mac']
                # get type from db
                device_type = self._device_db[device_name]['type']
                
                # remove from db
                del(self._device_db[device_name])
                
                # update db file
                with open(DEVICE_DB_FILENAME, "w") as f:
                    json.dump(self._device_db, f)

                self.Log("removed device called \"" + device_name + "\" from the db")
                return True

            else:
                self.Log("could not remove device called \"" + device_name + "\" from the db, no device with that name exists")
                return False
            
        # release lock when done
        finally:
            self._lock.release()


    """
    Function: Change_device_name
    given old name and new name, changes device name
    returns True if successful, false otherwise
    """
    def Change_device_name(self, orig_name, new_name):
        # get lock
        self._lock.acquire()
        
        try:
            # check if device with that name is in db
            if(self.Name_in_db(orig_name)):

                # check if new name already in db
                if(self.Name_in_db(new_name)):
                    self.Log("could not change name to \"" + new_name + "\", device with name already in db")
                    return False
                
                # save device
                saved_device = self._device_db[orig_name]
                
                # remove old device name from db
                del(self._device_db[device_name])

                # add new device name to db
                self._device_db[new_name] = saved_device

                # update db file
                with open(DEVICE_DB_FILENAME, "w") as f:
                    json.dump(self._device_db, f)

                self.Log("changed device name \"" + orig_name + "\" to \"" + new_name)
                return True

            else:
                self.Log("could not rename device called \"" + orig_name + "\" from the db, no device with that name exists")
                return False

        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Recv_handler
    receives all packets from ZigBee modules (runs on separate thread)
    handles packets containing change detection samples
    """
    def Recv_handler(self, data):        

        self.Log("received zigbee packet:\n" + str(data))
        
        # if network discovery or node identification packet
        if("parameter" in data):
            
            discover_data = data["parameter"]
            
            if("node_identifier" in discover_data):

                # ignore if device already in db
                device_mac = bytearray(discover_data['source_addr_long']).hex()
                if(self.Mac2name(device_mac) != ""):
                    return

                # get node identifier
                node_identifier = discover_data["node_identifier"].decode("utf-8")

                # check if is a valid device
                split_ident = node_identifier.split(":")

                #self.Log(str(split_ident))

                # if node identifier has correct form
                if(len(split_ident) == 2):             
                    # get needed values
                    device_type = split_ident[0]
                    device_ident = split_ident[1]
                    
                    # attempt to add to db
                    success = self.Add_device(node_identifier, device_mac, device_type)

                    if(success):
                        self.Log("discovered device with mac \"" + device_mac + "\" of type \"" + device_type + "\"")
                        self.Log("device named \"" + node_identifier + "\", use change_name command to change it to a better name")
                        return
                    else:
                        self.Log("failed to add discovered device to db")
                        return

                else:
                    self.Log("couldn't add discovered device, node identifier not recognized")
                    return

        # if it's a sample packet
        if("samples" in data):
            # get source address
            source_mac = bytearray(data['source_addr_long'])

            # get lock
            self._lock.acquire()

            try:
                # check if device in db (and get name)
                device_name = self.Mac2name(source_mac)
                if(device_name != ""):

                    # get device type
                    device_type = self._device_db[device_name]['type']

                    # if outlet
                    if(device_type == OUTLET_TYPE):
                        # get relay status
                        stat = data['samples'][0]['dio-1']

                        curr_level = self.Get_device_level(device_name, silent=True)

                        # update status in db
                        if(stat):
                           
                            # check if no actual change
                            if(curr_level == 100):
                                return
                           
                            self._device_db[device_name]['level'] = 100
                            self.Log("device called \"" + device_name + "\" level changed to 100")
                        else:
                            # check if no actual change
                            if(curr_level == 0):
                                return

                            self._device_db[device_name]['level'] = 0
                            self.Log("device called \"" + + device_name + "\" level changed to 0")

                        # record sample time
                        self._device_db[device_name]['sample_time'] = time.time()

                        # update db file
                        with open(DEVICE_DB_FILENAME, "w") as f:
                            json.dump(self._device_db, f)

                    elif(device_type == LIGHT_TYPE):
                        # get relay status
                        stat = data['samples'][0][RELAY_STAT_SAMPLE_IDENT]

                        # get current level
                        curr_level = self.Get_device_level(device_name, silent=True)
                        
                        # check if relay off
                        if(not stat):
                            # if different from current sample
                            if(curr_level != 0):
                                level = 0

                        else:
                            # get dpot ADC
                            dpot_val = data['samples'][0][DPOT_OUT_SAMPLE_IDENT]
                            
                            # convert to voltage
                            dpot_voltage = (dpot_val / 1023.0) * 1.2

                            if(dpot_voltage > 1.0):
                                dpot_voltage = 1.0
                            
                            level = 100*dpot_voltage

                        # update db
                        self._device_db[device_name]['level'] = level
                        self.Log("device called \"" + + device_name + "\" level changed to " + str(level))
                        
                        # record sample time
                        self._device_db[device_name]['sample_time'] = time.time()
                        # update db file
                        with open(DEVICE_DB_FILENAME, "w") as f:
                            json.dump(self._device_db, f)
                    else:
                        raise ValueError("device type \"" + device_type + "\" sampling not supported")

                # if device not in db
                else:
                    self.Log("received packet from device not in db")
            
            # release lock when done
            finally:
                self._lock.release()

    """
    Function: Discover_devices
    sends network discovery command to local zigbee.
    discovered devices are handled in Recv_handler
    """
    def Discover_devices(self):
        self.Log("sending device discovery packet")

        # get lock
        self._lock.acquire()
        
        try:
            # tell local zigbee to discover devices on network
            self._zb.at(command='ND', frame=DEFAULT_FRAME_ID)

        finally:
            self._lock.release()

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

        self.Log("running command: " + str(params))
        
        #if("task_id" in params):
            #self.Log("executing task \"" + params["task_id"] + "\"")

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
            return("test:ok")

        elif(command == "forcesample"):
            self.Force_sample_all()
            return("Forced sample")
        
        # set level
        elif (command == "set"):
            # get device name
            device_name = params['name']
            
            # get wanted device level
            level = params['level']
            
            success = self.Set_device_level(device_name, int(level))
            
            if(not success):
                return(device_name + ":set:unk")
            else:
                return(device_name + ":set:" + str(level))

        # get level
        elif(command == "get"):
            # get device name
            device_name = params['name']
            
            curr_level = self.Get_device_level(device_name)

            if(curr_level == LEVEL_UNK):
                return(device_name + ":get:unk")
            else:
                return(device_name + ":get:" + str(curr_level))
        
        # add a device
        elif(command == "add"):
            # get device name, mac addr, and type
            device_name = params['name']
            mac = params['mac']
            device_type = params['type']
            
            success = self.Add_device(device_name, mac, device_type)
            
            if(success):
                return(device_name + ":add:ok")
            else:
                return(device_name + ":add:failed")
        
        # remove a device
        elif(command == "remove"):
            device_name = params['name']
            
            success = self.Remove_device(device_name)
            
            if(success):
                return(device_name + ":remove:ok")
            else:
                return(device_name + ":remove:failed")

        # change a device name
        elif(command == "change_name"):

            if("device_name" not in params or "new_name" not in params):
                self.Log("change name failed, device_name or new_name not specified")
                return("no_name:change_name:failed")

            orig_name = params["device_name"]
            new_name = params["new_name"]
            
            success = self.Change_device_name(orig_nam, new_name)

            if(success):
                return(device_name + ":change_name:ok")
            else:
                return(device_name + ":change_name:failed")

        # add a task
        elif(command == "add_task"):
            success = self.Add_task(params)

            if(success):
                return(task_id + ":add_task:ok")
            else:
                return(task_id + ":add_task:failed")
            
        else:
            self.Log("recieved invalid command")
            return("invalid command")

    """
    Function: Log
    prints string to console and log file with a timestamp
    """
    def Log(self, s):
        logstr = time.strftime(LOG_TIMESTAMP) + ": " + s + "\n"
        logging.debug(logstr)
        print(logstr, end="")

if(__name__ == "__main__"):
    print("this is a library. import it to use it")
    exit(0)
