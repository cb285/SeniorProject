#!/usr/bin/env python3

import sys
import os
import json
from xbee import ZigBee
import serial
import logging
import time
from flask import Flask, request
from threading import Lock

DB_FILENAME = "devices.json"   # path to DB file
LOG_FILENAME = "server.log"    # log filename
LOG_TIME = "%Y-%m-%d %H:%M:%S" # time format for logging

class Home():
    def __init__(self):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)
        log("starting server")
        
        # create lock for xbee / db access
        self._lock = Lock()
        
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
            
            self._zb = ZigBee(self._ser, escaped=True, callback=self.Recv_handler)
            
            # load/create db file
            if not (os.path.isfile(DB_FILENAME)): # check if need to create db file
                log(DB_FILENAME + " doesn't exist, creating it.")
                self._device_db = dict()
                with open(DB_FILENAME, 'w') as f:
                    json.dump(device_db, f)
            else:
                with open(DB_FILENAME) as f:
                    self._device_db = json.load(f)
                    log("opened existing db " + DB_FILENAME)
        
        # release lock when done
        finally:
            # release lock
            self._lock.release()
    
    """
    Function: mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    def _Mac2bytes(mac):
        return bytearray.fromhex(mac)
    
    """
    Function: set_device
    receives a device name and a level to set it to
    returns True if successful, False otherwise
    
    level is an integer in the range [0, 100] from off to on
    
    valid levels for device types:
    outlet     : 0,  100 (off, on)
    light      : 0 - 100 (off, on)
    thermostat : 0 - 100 (0 - 100 degrees fahrenheit)
    """
    def Set_device(device_name, level):
        # check if level is valid
        if(type(level) is int):
            if(0 <= level and level <= 100):
                # check if device is in db
                if(self.Name_in_db(device_name))
    """
    Function: Name_in_db
    given device name
    returns true if device with that name is in db, false otherwise
    """
    def Name_in_db(device_name):
        # get lock
        self._lock.acquire()

        try:
            for(device in device_db.keys()):
                if(device == device_name):
                    return True

            return False

        # release lock when done
        finally:
            self._lock.release()

    """
    Function: Mac_in_db
    given device mac address
    returns true if device with that mac address is in db, false otherwise
    """
    def Mac_in_db(device_mac):
        # get lock
        self._lock.acquire()
        
        try:
            for(device in device_db.keys()):
                if(device_db['mac'] == device_mac):
                    return True

             return False

        # release lock when done
        finally:
            self._lock.release()
                
    """
    Function: Add_device
    attempts to add a device to the db, returns True if successful, false otherwise
    """
    def Add_device(device_name, device_mac, device_type):
        # get lock
        self._lock.acquire()
        
        try:
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name):
               log("there is already a device with name \"" + device_name + "\" in the db")
               return False
            elif(self.Mac_in_db(device_mac)):
               log("there is already a device with mac address \"" + device_mac + "\" in the db")
               return False
               
            # add to db dict
            device_db[device_name] = {'name':device_name, 'id':device_mac, 'type':device_type, 'status':'unk'}
            
            # update db file
            with open(DB_FILENAME, "w") as f:
                json.dump(device_db, f)
            
            # for outlets and lights, set up change detection
            if(device_type in ["outlet", "light"]):
               # get mac as bytes
               bytes_mac = self._Mac2bytes(device_mac)
               # set DIO1 to input
               self._zb.remote_at(dest_addr_long=bytes_mac, command='D1', parameter='\x03')
               # turn on DIO1 pull up resistor (30kOhm)
               self._zb.remote_at(dest_addr_long=bytes_mac, command='PR', parameter='\x08')
               # set up change detection for DIO1
               self._zb.remote_at(dest_addr_long=bytes_mac, command='IC', parameter=b'\x02')
               # save configuration
               self._zb.remote_at(dest_addr_long=bytes_mac, command='WR');
            
            return True
        
        # release lock when done
        finally:
            self._lock.release()
    
    """
    Function: Remove_device
    attempts to remove a device from the db, returns True if successful, false otherwise
    """
    def Remove_device(device_name, device_mac, device_type):
        # get lock
        self._lock.acquire()
        
        try:
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name)):
               # remove from db
               del(device_db[device_name])
               
               # update db file
               with open(DB_FILENAME, "w") as f:
                  json.dump(device_db, f)

               # for outlets and lights, disable change detection
               if(device_type in ["outlet", "light"]):
                  # get mac as bytes
                  bytes_mac = self._Mac2bytes(device_mac)
                  # set DIO1 to disabled
                  self._zb.remote_at(dest_addr_long=bytes_mac, command='D1', parameter='\x00')
                  # save configuration
                  self._zb.remote_at(dest_addr_long=bytes_mac, command='WR');
               
               Log("removed device called \"" + device_name + "\" from the db")
               return True

            Log("could not remove device called \"" + device_name + "\" from the db, no device with that name exists")
            return False
        
        # release lock when done
        finally:
            self._lock.release()
    
    def Recv_handler(data):
        # check if from a change detection
        if('samples' in data.keys()):
            pass
        
    def Log(self, s):
        logstr = time.strftime(TIME_FORMAT) + ": " + s + "\n"
        logging.debug(logstr)
        print(logstr, end="")
