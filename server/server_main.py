#!/usr/bin/env python3

import sys
import os
import json
from xbee import XBee, ZigBee
import serial
import time
import logging
from flask import Flask, request
import codecs

#import RPi.GPIO as GPIO

DB_FILENAME = "homectrldb.json" # path to DB file
LOG_FILENAME = "homectrl_server.log" # log filename

# define XBee DIO constants
XBEE_DIO_PIN = 'D0'
XBEE_DIO_HIGH = b'\x05'
XBEE_DIO_LOW = b'\x04'

# Function: createDB
# open existing json device file
def read_db():
    with open(DB_FILENAME) as f:
        return json.load(f)

# Function: write_db
# writes devices to json file
def write_db(device_dict):
    with open(DB_FILENAME, "w") as f:
        json.dump(device_dict, f)

# Function: id2xbee
# converts xbee device ID of form "0013A20041553731" to address usable by xbee API
def id2xbee(a):
    return bytearray.fromhex(a)

def xbeeConnect():
    # setup serial connection
    ser = serial.Serial()
    ser.port = "/dev/ttyAMA0"
    ser.baudrate = 9600
    ser.timeout = 10
    ser.write_timeout = 10
    ser.exclusive = True
    ser.open()
    log("connected to xbee at " + ser.port)
    return ZigBee(ser, escaped=True)

def log(str):
    TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    printstr = time.strftime(TIME_FORMAT) + ": " + str + "\n"
    logging.debug(printstr)
    print(printstr)

def main(args):

    logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG) # setup logging
    
    if not (os.path.isfile(DB_FILENAME)): # check if need to create db file
        log(DB_FILENAME + " doesn't exist, creating it.")
        device_db = dict()
        with open(DB_FILENAME, 'w') as f:
            json.dump(device_db, f)
    else:
        device_db = read_db() # open existing file
        log("opened existing db " + DB_FILENAME)
        log("devices:\n" + str(device_db))
    
    # add xbee module addresses (temporary)
    device_db['testname'] = ("0013A20041553731", "off")
    write_db(device_db)
    
    # connect to xbee module
    xbee = ZigBeeConnect()
    
    xbee.at(frame_id='A', command='MY')
    
    #reply = xbee.wait_read_frame()
    #log("local xbee: " + str(reply))
    
    # example request: http://localhost:5000/?cmd=set&name=testname&to=off
    # valid commands: get, set, add, remove
    
    # setup http GET/POST request handler
    app = Flask(__name__)
    @app.route('/',methods=['GET', 'POST'])
    def get_handler():
        params = request.args
        
        log("GET request: " + str(params))
        
        command = params["cmd"]
        
        # test/ping
        if (command in ["test", "ping"]):
            log("test/ping received")
            return("OK")
        # check if in db and get ID
        if (command in ["set", "get", "toggle"]):
            if ("name" in params.keys()):
                if (params["name"] in device_db.keys()):
                    device_id = device_db[params["name"]][0]
                    device_name = params["name"]
                    print(device_id)
                else:
                    log("error:invalid device name")
                    return ("error:invalid device name")
            else:
                log("error:must specify device name")
                return("error:must specify device name")
        
        # set status
        if (command == "set"):
            # get requested setting
            set_to = params["to"]
            
            # turn on
            if (set_to == "on"):
                xbee.remote_at(dest_addr_long=id2xbee(device_id), command=XBEE_DIO_PIN, parameter=XBEE_DIO_HIGH) # set pin 0 to high
                log("turned \"" + device_name + "\" on")
                device_db[device_name] = (device_id, "on")
                write_db(device_db)
                return("OK")
            
            # turn off
            elif (set_to == "off"):
                xbee.remote_at(dest_addr_long=id2xbee(device_id), command=XBEE_DIO_PIN, parameter=XBEE_DIO_LOW) # set pin 0 to low
                log("turned \"" + device_name + "\" off")
                device_db[device_name] = (device_id, "off")
                write_db(device_db)
                return("OK")
            
            # unknown command
            else:
                log("error:invalid set command")
                return ("error:invalid set command")
        
        # toggle state
        elif(command == "toggle"):
            if(device_db[device_name][2] == "on"):
                xbee.remote_at(dest_addr_long=id2xbee(device_id), command=XBEE_DIO_PIN, parameter=XBEE_DIO_LOW) # set pin 0 to low
                log("toggled \"" + device_name + "\" to off")
                device_db[device_name] = (device_id, "off")
                write_db(device_db)
                return("OK")
            else:
                xbee.remote_at(dest_addr_long=id2xbee(device_id), command=XBEE_DIO_PIN, parameter=XBEE_DIO_HIGH) # set pin 0 to high
                log("toggled \"" + device_name + "\" to on")
                device_db[device_name] = (device_id, "on")
                write_db(device_db)
                return("OK")
        
        # get status
        elif (cmd == "get"):
            if (device_name in device_db.keys()):
                log("status of \"" + device_name + "\" is " + device_db[device_name][1])
                return(device_db[device_name][1])
            else:
                log("error:get failed, device not in DB")
                return("error:get failed, device not in DB")
        
        # get list of devices
        elif (cmd == "devices"):
            log("devices:\n" + str(device_db))
            return(str(device_db))
        
        # add a device
        elif cmd == "add":
            if("id" in params.keys() and "name" in params.keys() and "type" in params.keys()):
                # add to dict
                device_db[params["name"]] = (params["id"], "off")
                # save to file
                write_db(device_db)
                return("OK")
            else:
                log("error:must specify name, id, and type")
                return("error:must specify name, id, and type")

        # remove a device
        elif cmd == "remove":
            if("name" in params.keys()):
                if(params["name"] in device_db.keys()):
                    del device_db[params["name"]]
                    # write to file
                    write_db(device_db)
                    device_name = params["name"]                    
                    log("removed device \"" + params["name"] + "\" from db")
                    return("removed device \"" + params["name"] + "\" from db")
                else:
                    log("error:not in db, cannot remove")
                    return("error:not in db, cannot remove")
            else:
                log("error:name must be specified")
                return("error:name must be specified")
            
        # invalid
        else:
            log("error:invalid command")
            return("error:invalid command")
        
    # start http GET request handler
    app.run(host='0.0.0.0', port=5000)

"""
def xbee_rx_handler(xbee):
    #logging.basicConfig(filename=logFilename, level=logging.DEBUG) # setup logging

    if not (os.path.isfile(dbFilename)): # check if need to create file
        log(dbFilename + " doesn't exist, creating it.")
	createDB(dbFilename) # create file
    else:
	conn = sqlite3.connect(dbFilename)
	cur = conn.cursor()
        log("opened existing db " + dbFilename)
"""

if (__name__ == "__main__"):
    main(sys.argv)
