#!/usr/bin/env python3

import sys
import os
import json
from xbee import ZigBee
import serial
import logging
import time
from flask import Flask, request
from threading import RLock

DB_FILENAME = "devices.json"         # path to DB file
LOG_FILENAME = "server.log"          # log filename
LOG_TIMESTAMP = "%Y-%m-%d %H:%M:%S"  # timestamp format for logging

SAMPLE_TTL = 30        # time in seconds a device status sample is valid
DIO_SIG_PERIOD = 0.05  # period in seconds of square wave to trigger change


class Home():
    def __init__(self):
        # setup logging
        logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG)
        log("starting server")

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

            self._zb = ZigBee(self._ser, escaped=True,
                              callback=self.Recv_handler)

            # load/create db file
            if not (os.path.isfile(DB_FILENAME)):  # check if need to create db file
                log(DB_FILENAME + " doesn't exist, creating it.")
                self.device_db = dict()
                with open(DB_FILENAME, 'w') as f:
                    json.dump(device_db, f)
            else:
                with open(DB_FILENAME) as f:
                    self.device_db = json.load(f)
                log("opened existing db " + DB_FILENAME)

        # release lock when done
        finally:
            # release lock
            self._lock.release()

    """
    Function: Mac2bytes
    receives a string of 16 hex characters (mac address)
    returns a bytearray usable by ZigBee API
    """
    def Mac2bytes(self, mac):
        return bytearray.fromhex(mac)

    """
    Function: Get_device_level
    get current device level (polls device if sample is past TTL)
    returns the current level if successful, returns -1 if failed to get level
    """
    def Get_device_level(self, device_name):
        # get lock
        self._lock.acquire()

        try:
            # check if device with that name is in db
            if(self.Name_in_db(device_name)):
                # for outlets and lights, request sample
                if(device_type in ["outlet", "light"]):

                    # check if current sample is valid
                    if(self.device_db[device_name]['sample_time'] - time.gmtime() <= SAMPLE_TTL):
                        curr_level = self.device_db[device_name]['level']
                        # return level
                        log("current level of \"" + device_name + "\" is " + str(curr_level))
                        return(curr_level)
                    # if sample is expired, force a sample
                    else:
                        # get mac as bytes
                        bytes_mac = self.Mac2bytes(device_mac)

                        # force sample of inputs
                        self._zb.remote_at(dest_addr_long=bytes_mac, command='IS')
                        
                        # release lock so Recv_handler can access db
                        self._lock.release()

                        # wait for receipt of new sample or timeout
                        start_time = time.gmtime()
                        while(self.device_db[device_name]['sample_time'] - time.gmtime() > SAMPLE_TTL):
                            # check if timed out
                            if(time.gmtime() - start_time >= SAMPLE_TIMEOUT):
                                log("could not reach device \"" + device_name + "\", timed out while waiting for sample")
                                return -1

                        # if got sample
                        curr_level = self.device_db[device_name]['level']
                        log("current level of \"" + device_name + "\" is " + str(curr_level))
                        return curr_level
        
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
            if(0 <= level and level <= 100):
                # check if device is in db
                if(self.Name_in_db(device_name)):
                    # get device type
                    device_type = self.device_db[device_name]['type']
                    curr_level = self.Get_device_level(device_name)
                    
                    # if outlet
                    if(device_type == "outlet"):
                        # if turn off
                        if(level == 0):
                            # check if need to change device status
                            if(curr_level == 100):
                                # set output pin high
                                xbee.remote_at(dest_addr_long=self.Mac2bytes(self.device_db['mac']), command='D0', parameter=b'\x05')
                                time.sleep(DIO_SIG_PERIOD)
                                # make output pin low
                                xbee.remote_at(dest_addr_long=self.Mac2bytes(self.device_db['mac']), command='D0', parameter=b'\x04')
                                # update db
                                self.device_db[device_name]['level'] = 0
                                self.device_db[device_name]['sample_time'] = time.gmtime()
                                with open(DB_FILENAME, 'w') as f:
                                    json.dump(device_db, f)
                                log("changed device \"" +
                                    device_name + "\" level to " + level)
                                return True
                            else:
                                log("did not need to change device \"" + device_name + "\" level to " + level)
                                return True
                        elif(level == 100):
                            # check if need to change device status
                            if(curr_level == 0):
                                # make DIO0 high
                                xbee.remote_at(dest_addr_long=self.Mac2bytes(self.device_db['mac']), command='D0', parameter=b'\x05')
                                time.sleep(DIO_SIG_PERIOD)
                                # make DIO0 low
                                xbee.remote_at(dest_addr_long=self.Mac2bytes(self.device_db['mac']), command='D0', parameter=b'\x04')
                                # update db
                                self.device_db[device_name]['level'] = 100
                                self.device_db[device_name]['sample_time'] = time.gmtime()
                                with open(DB_FILENAME, 'w') as f:
                                    json.dump(self.device_db, f)
                                    
                                log("changed device \"" +
                                device_name + "\" level to " + level)
                                return True
                            else:
                                log("did not need to change device \"" +
                                    device_name + "\" level to " + level)
                                return True
                        else:
                            raise ValueError("invalid level value for outlet type devices")
                    else:
                        raise ValueError("setting levels of types other than \"outlet\" is not yet supported")
                else:
                    log("could not change level of device \"" + device_name + "\", device not in db")
                    return False

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
            for device in self.device_db:
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
               log("there is already a device with name \"" + device_name + "\" in the db")
               return False
            elif(self.Mac_in_db(device_mac)):
               log("there is already a device with mac address \"" + device_mac + "\" in the db")
               return False

            # add to db dict
            self.device_db[device_name] = {'name':device_name, 'id':device_mac, 'type':device_type, 'level':-1, 'sample_time':0}

            # update db file
            with open(DB_FILENAME, "w") as f:
               json.dump(self.device_db, f)
   
            # for outlets and lights, set up change detection
            if(device_type in ["outlet", "light"]):
               # get mac as bytes
               bytes_mac = self.Mac2bytes(device_mac)
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
    def Remove_device(self, device_name, device_mac, device_type):
        # get lock
        self._lock.acquire()

        try:
            # check if device with that name or mac is already in db
            if(self.Name_in_db(device_name)):
                # remove from db
                del(self.device_db[device_name])
            
                # update db file
                with open(DB_FILENAME, "w") as f:
                    json.dump(self.device_db, f)
               
                # for outlets and lights, disable change detection
                if(device_type in ["outlet", "light"]):
                    # get mac as bytes
                    bytes_mac = self.Mac2bytes(device_mac)
                    # disable DIO0
                    self._zb.remote_at(dest_addr_long=bytes_mac, command='D0', parameter='\x00')
                    # disable DIO1
                    self._zb.remote_at(dest_addr_long=bytes_mac, command='D1', parameter='\x00')
                    # save configuration
                    self._zb.remote_at(dest_addr_long=bytes_mac, command='WR');

                Log("removed device called \"" + device_name + "\" from the db")
                return True

            else:
                Log("could not remove device called \"" + device_name + "\" from the db, no device with that name exists")
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

        Log("received packet:\n" + str(data))

        # check if contains a sample
        # (could potentially use this to trigger other events)
        if('samples' in data.keys()):
            # get source address
            source_addr = bytearray(data['source_addr_long'])

            # get lock
            self._lock.acquire()

            try:
               # check if device in db (and get name)
               device_name = self.Mac2name(source_addr)
               if(device_name != ""):
                  Log("status change for device called \"" + device_name + "\"")

                  # get device type
                  device_type = self.device_db[device_name]['type']
            
                  # if outlet
                  if(device_type == "outlet"):
                     # get pin status
                     stat = data['samples'][0]['dio-1']

                     # update status in db
                     if(stat):
                        self.device_db[device_name]['level'] = 100
                     else:
                        self.device_db[device_name]['level'] = 0

                     # record sample time
                     self.device_db[device_name]['sample_time'] = time.gmtime()

                     # update db file
                     with open(DB_FILENAME, "w") as f:
                        json.dump(self.device_db, f)
                # if device not in db
               else:
                   Log("received packet from device not in db")
            
            # release lock when done
            finally:
                self._lock.release()

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
