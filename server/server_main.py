#!/usr/bin/env python3

import sys
import os
import json
from xbee import XBee, ZigBee
import serial
import time
import logging
from flask import Flask, request
from threading import RLock

#import RPi.GPIO as GPIO

DB_FILENAME = "devices.json" # path to DB file
LOG_FILENAME = "server.log" # log filename

# define XBee DIO constants
XBEE_OUTPUT_PIN = 'D0'
XBEE_DIO_HIGH = b'\x05'
XBEE_DIO_LOW = b'\x04'

# create device db
device_db = dict()

# create lock for accessing xbee and device_db
xbee_lock = RLock()

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
    ser.port = "/dev/ttyS0"
    ser.baudrate = 9600
    ser.timeout = 3
    ser.write_timeout = 3
    ser.exclusive = True
    ser.open()
    log("connected to xbee at " + ser.port)
    return ZigBee(ser, escaped=True, callback=input_handler)

def log(str):
    TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    printstr = time.strftime(TIME_FORMAT) + ": " + str + "\n"
    logging.debug(printstr)
    print(printstr)
    
def set_xbee_dio(addr, pin, stat):
    if(stat == 'high'):
        param = XBEE_DIO_HIGH
    elif(stat == 'low'):
        param = XBEE_DIO_LOW
    else:
        raise Exception("invalid option for setting DIO: " + str(stat))
    
    # send xbee command
    xbee.remote_at(dest_addr_long=id2xbee(addr), command=pin, parameter=param)
    
def input_handler(data):
    # get access to global db and xbee
    global device_db
    global xbee
    
    # ignore if not a input sample
    if('samples' not in data.keys()):
        return
    
    # get pin status
    stat = data['samples'][0]['dio-1']
    
    # ignore if on (only toggle on falling edge)
    if(stat == True):
        return
    
    # get source address
    source_addr = bytearray(data['source_addr_long'])

    print("input_handler getting lock")
    
    # acquire lock
    xbee_lock.acquire()
    print("input_handler got the lock")
    
    # check if device is in the database
    for device in device_db.values():
        # if found a match
        if(id2xbee(device['id']) == source_addr):
            device_name = device['name']
            device_id = device['id']
            # if status was on, turn it off
            if(device_db[device_name]['status'] == "on"):
                set_xbee_dio(device_id, XBEE_OUTPUT_PIN, "low") # set pin 0 to low
                # log
                log("toggled \"" + device_name + "\" to off")
                # update db
                device_db[device_name]['status'] = "off"
                write_db(device_db)
                # release lock
                xbee_lock.release()
                return
            # if status was off, turn it on
            else:
                set_xbee_dio(device_id, XBEE_OUTPUT_PIN, "high") # set pin 0 to high
                # log
                log("toggled \"" + device_name + "\" to on")
                # update db
                device_db[device_name]['status'] = "on"
                write_db(device_db)
                # release lock
                xbee_lock.release()
                return
    
    # release lock if no devices matched
    xbee_lock.release()

def add_device(name, device_id, device_type, status):
    # get access to global db
    global device_db
    
    device_db[name] = {'name':name, 'id':device_id, 'type':device_type, 'status':status}
    write_db(device_db)
    
def main(args):
    # make db and xbee global
    global device_db
    global xbee
    
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
    
    # add testing device
    add_device('testname', '0013A20041553731', 'off', 'outlet')

    print("main getting lock")
    # acquire lock
    xbee_lock.acquire()
    print("main got lock")
        
    # connect to xbee module
    xbee = xbeeConnect()
    
    xbee.at(frame_id='A', command='MY')
    
    # set DIO1 to input
    test_addr = id2xbee(device_db['testname']['id'])
    xbee.remote_at(dest_addr_long=test_addr, command='D1', parameter='\x03')
    # turn on DUI1 pull up resistor (30kOhm)
    xbee.remote_at(dest_addr_long=test_addr, command='PR', parameter='\x08')
    # set up change detection for DIO1
    xbee.remote_at(dest_addr_long=test_addr, command='IC', parameter=b'\x02')
    # save configuration
    xbee.remote_at(dest_addr_long=test_addr, command='WR');
    
    # release lock
    xbee_lock.release()
    print("main released lock")
    
    # example request: http://localhost:5000/?cmd=set&name=testname&to=off
    # valid commands: get, set, add, remove
    
    # setup http GET/POST request handler
    app = Flask(__name__)
    @app.route('/',methods=['GET', 'POST'])
    def get_handler():
        params = request.args
        
        log("GET request: " + str(params))
        
        command = params["cmd"]
        
        print("flask getting lock")
        # acquire lock
        xbee_lock.acquire()
        
        try:
            print("flask got lock")
        
            # test/ping
            if (command in ["test", "ping"]):
                log("test/ping received")
                return("OK")
            # check if in db and get ID
            if (command in ["set", "get", "toggle"]):
                if ("name" in params.keys()):
                    if (params["name"] in device_db.keys()):
                        device_id = device_db[params["name"]]['id']
                        device_name = params["name"]
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
                    set_xbee_dio(device_id, XBEE_OUTPUT_PIN, "high") # set pin 0 to high
                    log("turned \"" + device_name + "\" on")
                    # update db
                    device_db[device_name]['status'] =  "on"
                    write_db(device_db)
                    return("OK")
            
                # turn off
                elif (set_to == "off"):
                    set_xbee_dio(device_id, XBEE_OUTPUT_PIN, "low") # set pin 0 to low
                    log("turned \"" + device_name + "\" off")
                    device_db[device_name]['status'] = "off"
                    write_db(device_db)
                    return("OK")
                
                # unknown command
                else:
                    log("error:invalid set command")
                    return ("error:invalid set command")
            
            # toggle state
            elif(command == "toggle"):
                if(device_db[device_name][1] == "on"):
                    set_xbee_dio(device_id, XBEE_OUTPUT_PIN, "low") # set pin 0 to low
                    # log
                    log("toggled \"" + device_name + "\" to off")
                    # update db
                    device_db[device_name]['status'] = "off"
                    write_db(device_db)
                    return("OK")
                else:
                    set_xbee_dio(device_id, XBEE_OUTPUT_PIN, "high") # set pin 0 to high
                    # log
                    log("toggled \"" + device_name + "\" to on")
                    # update db
                    device_db[device_name]['status'] = "on"
                    write_db(device_db)
                    return("OK")
            
            # get status
            elif (cmd == "get"):
                if (device_name in device_db.keys()):
                    # log
                    log("status of \"" + device_name + "\" is " + device_db[device_name]['status'])
                    # return status of device
                    return(device_db[device_name]['status'])
                else:
                    log("error:get failed, device not in DB")
                    return("error:get failed, device not in DB")
                
                # get list of devices
            elif (cmd == "devices"):
                # log
                log("devices:\n" + str(device_db))
                # return device db
                return(str(device_db))
        
            # add a device
            elif cmd == "add":
                if("id" in params.keys() and "name" in params.keys() and "type" in params.keys()):
                    # add to db
                    add_device(params["name"], params["id"], params["type"], "off")
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
        
        finally:
            # release lock
            xbee_lock.release()
            print("flask released lock")
    
    # start http GET request handler
    app.run(host='0.0.0.0', port=5000)

if (__name__ == "__main__"):
    main(sys.argv)
