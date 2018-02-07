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
TASKS_DB_FILENAME = "tasks.sqlite"         # path to task db file
LOG_FILENAME = "server.log"                # log filename
LOG_TIMESTAMP = "%Y-%m-%d %H:%M:%S"        # timestamp format for logging

DIO_SIG_PERIOD = 0.05                      # period in seconds of square wave to trigger change

SETUP_WAIT = 10                            # time in seconds to wait for samples to be received on server startup

LEVEL_UNK = -1

DEVICE_TYPES = ["outlet", "light", "auto"] # valid device types
DIN_DEVICES = ["outlet", "light"]          # devices that require digital input detection
DOUT_DEVICES = ["outlet"]                  # devices that require digital output (levels of 0, 100)

class Home():
    def __init__(self, callback_function):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)
        self.Log("starting server")

        # save startup time
        self._start_time = time.time()

        # setup task scheduler
        self._sched = BackgroundScheduler()
        self._sched.add_jobstore('sqlalchemy', url=TASKS_DB_FILENAME)
        logging.getLogger('apscheduler').setLevel(logging.DEBUG)
        
        # create lock for xbee / db access
        self._lock = RLock()
        
        # acquire lock
        self._lock.acquire()
        
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
                              callback=callback_function)

            # load/create db file
            if not (os.path.isfile(DEVICE_DB_FILENAME)):  # check if need to create db file
                self.Log(DEVICE_DB_FILENAME + " file doesn't exist, creating it.")
                self.device_db = dict()
                with open(DEVICE_DB_FILENAME, 'w') as f:
                    json.dump(self.device_db, f)
            else:
                with open(DEVICE_DB_FILENAME) as f:
                    self.device_db = json.load(f)
                self.Log("opened existing db " + DEVICE_DB_FILENAME)

            # sample all devices in db
            self.Force_sample_all(release=False)
            
        # release lock when done
        finally:
            # release lock
            self._lock.release()
            # sleep to allow samples to be processed
            time.sleep(SETUP_WAIT)
            # start scheduler
            self._sched.start()
            

    """
    Function: Mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    def Mac2bytes(self, mac):
        return bytearray.fromhex(mac)

    def Force_sample_all(self, release=True):

        # get lock
        self._lock.acquire()
        try:
            # for each device in db
            for device_name in device_db:
                # force sample
                self._zb.remote_at(dest_addr_long=self.Mac2bytes(device_db[device_name]['mac']), command='IS')

        # release lock when done
        finally:
            if(release):
                self._lock.release()
    
    """
    Function: Get_device_level
    get current device level (polls device if sample is past TTL)
    returns the current level if successful, returns -1 if failed to get level
    """
    def Get_device_level(self, device_name, release=True):
        # get lock
        self._lock.acquire()
        
        try:
            # check if device with that name is in db
            if(self.Name_in_db(device_name, release=False)):
                
                # get device type
                device_type = self.device_db[device_name]['type']
                
                # check if current sample is valid
                if(self.device_db[device_name]['sample_time'] >= self._start_time):
                    # get level
                    curr_level = self.device_db[device_name]['level']
                    # return level
                    self.Log("current level of \"" + device_name + "\" is " + str(curr_level))
                    return(curr_level)
                
                # if sample is not valid
                else:
                    self.Log("current level of \"" + device_name + "\" is unknown, check the device")
                    return LEVEL_UNK
        
        # release lock when done
        finally:
            if(release):
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
    def Set_device_level(self, device_name, level, release=True):
        # get lock
        self._lock.acquire()
        try:
            # check if level is valid
            if(0 <= level and level <= 100):
                # check if device is in db
                if(self.Name_in_db(device_name, release=False)):
                    # get type
                    device_type = self.device_db[device_name]['type']
                    # get current level
                    curr_level = self.Get_device_level(device_name, release=False)
                    # get mac addr
                    bytes_mac = self.Mac2bytes(self.device_db[device_name]['mac'])

                    # if could not get current level
                    if(curr_level == LEVEL_UNK):
                        self.Log("could not set \"" + device_name + "\" to " + level + ", could not get current level")
                        return False

                    # if a DOUT_DEVICE
                    if(device_type in DOUT_DEVICES):
                        # if valid level
                        if(level in [0, 100]):
                            # check if need to change device status
                            if(curr_level != level):
                                # set output pin high
                                self._zb.remote_at(dest_addr_long=bytes_mac, command='D0', parameter=b'\x05')
                                time.sleep(DIO_SIG_PERIOD)
                                # make output pin low
                                self._zb.remote_at(dest_addr_long=bytes_mac, command='D0', parameter=b'\x04')
                                # update db
                                self.device_db[device_name]['level'] = level
                                self.device_db[device_name]['sample_time'] = time.time()
                                with open(DEVICE_DB_FILENAME, 'w') as f:
                                    json.dump(self.device_db, f)
                                self.Log("changed device \"" +
                                         device_name + "\" level to " + str(level))
                                return True
                            else:
                                self.Log("did not change device \"" + device_name + "\" to " + str(level) + ", was already set")
                                return True
                        else:
                            self.Log("invalid level value for outlet type devices")
                            return False
                    else:
                        self.Log("setting levels of types other than DOUT_DEVICES is not yet supported")
                        return False
                else:
                    self.Log("could not change level of device \"" + device_name + "\", device not in db")
                    return False
        
        # release lock when done
        finally:
            if(release):
                self._lock.release()

    """
    Function: Name_in_db
    given device name
    returns true if device with that name is in db, false otherwise
    """
    def Name_in_db(self, device_name, release=True):
        # get lock
        self._lock.acquire()
        try:
            for device in self.device_db:
                if(device == device_name):
                    return True
                
            return False
        
        # release lock when done
        finally:
            if(release):
                self._lock.release()
    
    """
    Function: Mac_in_db
    given device mac address (hex string or bytearray)
    returns true if device with that mac address is in db, false otherwise
    """
    def Mac_in_db(self, device_mac, release=True):
        # get lock
        self._lock.acquire()
        
        if(type(device_mac) is bytearray):
            byte_format = True
        else:
            byte_format = False
        
        try:
            if(byte_format):
                for device in self.device_db:
                    if(self.Mac2bytes(self.device_db[device]['mac']) == device_mac):
                        return True

                return False

            else:
                for device in self.device_db:
                    if(self.device_db[device]['mac'] == device_mac):
                        return True
                    
                return False

        # release lock when done
        finally:
            if(release):
                self._lock.release()

    """
    Function: Mac2name
    given device mac address (hex string or bytearray)
    returns name of device if in db, empty string ("") otherwise
    """
    def Mac2name(self, device_mac, release=True):
        # get lock
        self._lock.acquire()

        if(type(device_mac) is bytearray):
            byte_format=True
        else:
            byte_format=False

        try:
            if(byte_format):
                for device in self.device_db:
                    if(self.Mac2bytes(self.device_db[device]['mac']) == device_mac):
                        return device

                return ""

            else:
                for device in self.device_db:
                    if(self.device_db[device]['mac'] == device_mac):
                        return device

                return ""

        # release lock when done
        finally:
            if(release):
                self._lock.release()

    """
    Function: Add_device
    attempts to add a device to the db, returns True if successful, false otherwise
    """
    def Add_device(self, device_name, device_mac, device_type, release=True):
        # get lock
        self._lock.acquire()

        try:
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name, release=False)):
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
            if(device_type in DIN_DEVICES):
               
               # set DIO1 to input
               self._zb.remote_at(dest_addr_long=bytes_mac, command='D1', parameter='\x03')
               # set up change detection for DIO1
               self._zb.remote_at(dest_addr_long=bytes_mac, command='IC', parameter=b'\x02')
               
               # force sample of input
               self._zb.remote_at(dest_addr_long=bytes_mac, command='IS')

            # if type is not auto
            if(device_type != "auto"):
                # write device type to node identifier
                self._zb.remote_at(dest_addr_long=bytes_mac, command='D1', parameter='\x03')

            # if type is auto
            else:
                # request node identifier string
                self._zb.remote_at(dest_addr_long=self.Mac2bytes(device_db[device_name]['mac']), command='IS')
            
            # apply changes
            self._zb.remote_at(dest_addr_long=bytes_mac, command='AC');
            # save configuration
            self._zb.remote_at(dest_addr_long=bytes_mac, command='WR');
            
            # add to db dict
            self.device_db[device_name] = {'name':device_name, 'mac':device_mac, 'type':device_type, 'level':-1, 'sample_time':0}
            
            # update db file
            with open(DEVICE_DB_FILENAME, "w") as f:
               json.dump(self.device_db, f)
            
            self.Log("added device \"" + device_name + "\" of type \"" + device_type + " to db")
            return True
        
        # release lock when done
        finally:
            if(release):
                self._lock.release()

    """
    Function: Remove_device
    attempts to remove a device from the db, returns True if successful, false otherwise
    """
    def Remove_device(self, device_name, release=True):
        # get lock
        self._lock.acquire()

        try:
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name, release=False)):

                # get mac from db
                device_mac = self.device_db[device_name]['mac']
                # get type from db
                device_type = self.device_db[device_name]['type']
                
                # remove from db
                del(self.device_db[device_name])
                
                # update db file
                with open(DEVICE_DB_FILENAME, "w") as f:
                    json.dump(self.device_db, f)

                self.Log("removed device called \"" + device_name + "\" from the db")
                return True

            else:
                self.Log("could not remove device called \"" + device_name + "\" from the db, no device with that name exists")
                return False

        # release lock when done
        finally:
            if(release):
                self._lock.release()

    """
    Function: Recv_handler
    receives all packets from ZigBee modules (runs on separate thread)
    handles packets containing change detection samples
    """
    def Recv_handler(self, data):
        
        self.Log("received zigbee packet:\n" + str(data))

        # if network discovery or node identification packet
        

        
        # if io sample packet
        if('samples' in data):
            # get source address
            source_mac = bytearray(data['source_addr_long'])

            # get lock
            self._lock.acquire()
            
            try:
               # check if device in db (and get name)
               device_name = self.Mac2name(source_mac, release=False)
               if(device_name != ""):
                  self.Log("status change for device called \"" + device_name + "\"")

                  # get device type
                  device_type = self.device_db[device_name]['type']

                  # if outlet
                  if(device_type == "outlet"):
                     # get pin status
                     stat = data['samples'][0]['dio-1']

                     # update status in db
                     if(stat):
                        self.device_db[device_name]['level'] = 100
                        self.Log("device called \"" + "\"" + device_name + " level changed to 100")
                     else:
                        self.device_db[device_name]['level'] = 0
                        self.Log("device called \"" + "\"" + device_name + " level changed to 0")
                        
                     # record sample time
                     self.device_db[device_name]['sample_time'] = time.time()
                     
                     # update db file
                     with open(DEVICE_DB_FILENAME, "w") as f:
                        json.dump(self.device_db, f)

                  else:
                      raise ValueError("device type \"" + device_type + "\" sampling not supported")

                # if device not in db
               else:
                   self.Log("received packet from device not in db")
            
            # release lock when done
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

        # if repeating type
        if(task_type == "repeating"):
            cron_dict = dict()

            for k in params:
                if(k in ["year", "month", "day", "hour", "minute", "second"]):
                    cron_dict[e] = int(params[k])

            # add job
            self._sched.add_job(self.Run_command, trigger='cron', cron_dict, args=[task_command], id=task_id, replace_existing=True)
            
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

            self._sched.add_job(self.Run_command, trigger='date',
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

        if(params["task_id"] != None):
            self.Log("executing task \"" + params["task_id"] + "\"")
        
        # get command
        if("cmd" in params):
            command = params['cmd']
        elif("command" in params):
            command = params['commands']
        else:
            command = "invalid"

        # test
        if (command == "test"):
            self.Log("receieved test command")
            return("test:ok")
        
        # set level
        if (command == "set"):
            # get device name
            device_name = params['name']
            
            # get wanted device level
            level = params['level']
            
            success = myhome.Set_device_level(device_name, int(level))
            
            if(success):
                return(device_name + ":set:unk")
            else:
                return(device_name + ":set:" + str(level))

        # get level
        elif(command == "get"):
            # get device name
            device_name = params['name']
            
            curr_level = myhome.Get_device_level(device_name)

            if(curr_level == LEVEL_UNK):
                return(device_name + ":get:unk")
            else:
                return(device_name + ":get:" + str(level))
        
        # add a device
        elif(command == "add"):
            # get device name, mac addr, and type
            device_name = params['name']
            mac = params['mac']
            device_type = params['type']
            
            success = myhome.Add_device(device_name, mac, device_type)
            
            if(success):
                return(device_name + ":add:ok")
            else:
                return(device_name + ":add:failed")
        
        # remove a device
        elif(command == "remove"):
            device_name = params['name']
            
            success = myhome.Remove_device(device_name)
            
            if(success):
                return(device_name + ":remove:ok")
            else:
                return(device_name + ":remove:failed")

        else:
            self.Log("recieved invalid command \"" + cmd + "\"")
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
