#!/usr/bin/env python

import sys
import os
import json
from xbee import XBee, ZigBee
import serial
import time
import logging
from flask import Flask, request

#import RPi.GPIO as GPIO

DB_FILENAME = "homectrldb.json" # path to DB file
LOG_FILENAME = "homectrl_server.log" # log filename

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
# converts xbee device ID of form "0x0013A20041553731" to "\x00\x13\xA2\x00\x41\x55\x37\x31" (usable by xbee API)
def id2xbee(a):
    b = a.split("x")[1] # remove "0x" part
    return('\\x' + '\\x'.join(i+j for i,j in zip(b[::2], b[1::2]))) # insert "\x" before each byte

def serialConnect():
    # setup serial connection
    ser = serial.Serial()
    ser.port = "/dev/ttyS0"
    ser.baudrate = 115200
    ser.timeout = 10
    ser.write_timeout = 10
    ser.exclusive = True
    ser.open()    
    return ser

def log(str):
    TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    printstr = time.strftime(TIME_FORMAT) + ": " + str + "\n"
    logging.debug(printstr)
    print(printstr)

def main(args):

    logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG) # setup logging
    
    if not (os.path.isfile(DB_FILENAME)): # check if need to create db file
        log(DB_FILENAME + " doesn't exist, creating it.")
        device_dict = dict()
        with open(DB_FILENAME, 'w') as f:
            json.dump(device_dict, f)
    else:
        device_dict = read_db() # open existing file
        log("opened existing db " + DB_FILENAME)
        log("devices:\n" + str(device_dict))
    
    # add xbee module addresses (temporary)
    device_db['test'] = ("0x0013A20041553731", "outlet")
    write_db(device_db)
    
    # open serial port to xbee module
    ser = serialConnect()
    
    # connect to xbee module
    xbee = ZigBee(ser) #, callback=xbee_rx_handler)
    
    log("connected to xbee at " + ser.port)
    
    xbee.at(frame_id='A', command='MY')
    reply = xbee.wait_read_frame()
    log("local xbee: " + str(reply))
    
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
        if (command == "test" or command == "ping"):
            log("test/ping received")
            return("OK")
        # check if in db and get ID
        if (command == "set" or command == "get"):
            if ("name" in params.keys()):
                if (params["name"] in device_db.keys()):
                    device_id = id2xbee(device_db[params["name"]][0])
                else:
                    log("invalid device name")
                    return ("invalid device name")
            else:
                log("must specify device name")
                return("must specify device name")
        
        # set status
        if (command == "set"):
            # get requested setting
            set_to = params["to"]
            device_name = params["name"]
            
            # turn on
            if (set_to == "on"):
                xbee.remote_at(dest_addr_long=device_id, command='D0', parameter='\x05') # set pin 0 to high
                log("turned \"" + device_name + "\" off")
                return("OK")
            
            # turn off
            elif (set_to == "off"):
                xbee.remote_at(dest_addr_long=device_id, command='D0', parameter='\x04') # set pin 0 to low
                log("turned \"" + device_name + "\" off")
                return("OK")
            
            # unknown command
            else:
                log("invalid set command")
                return ("INVALID COMMAND")
        
        # get status
        elif (cmd == "get"):
            pass
            """
            log("getting " + device_name + " status")
            xb.remote_at(command='IS', frame_id='C')
            """
        
        # get list of devices
        elif (cmd == "devices"):
            log(str(device_db))
            return(str(device_db))
        
        # add a device
        elif cmd == "add":
            if("id" in params.keys() and "name" in params.keys() and "type" in params.keys()):
                # add to dict
                device_db[params["name"]] = (params["id"], params["type"])
                # save to file
                write_db(device_db)
                
            else:
                log("must specify name, id, and type")
                return("must specify name, id, and type")

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
                    return("not in db, cannot remove")
            else:
                log("name must be specified")
                return("name must be specified")

        # invalid
        else:
            log("invalid command")
            return("invalid command")
        
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
