#!/usr/bin/env python

import sys
import os
import sqlite3
from xbee import XBee, ZigBee
import serial
import time
import logging
from flask import Flask, request

#import RPi.GPIO as GPIO

DB_FILENAME = "homectrldb.sqlite" # path to DB file
LOG_FILENAME = "homectrl_server.log" # log filename

# Function: createDB
# creates a DB file and creates an empty device table
def createDB(dbfilename):
    conn = sqlite3.connect(dbfilename)
    cur = conn.cursor()
    
    # create empty table
    cur.execute("CREATE TABLE devices (id integer primary key, type text, name text)")
    conn.commit()
    
# Function: addDevice
def addDevice(deviceName, deviceType, deviceID):
    cur.execute("INSERT INTO devices VALUES (?, ?, ?)", (deviceID, deviceType, deviceName))
    conn.commit()
    
# Function: getDevices
def getDevices():
    cur.execute("SELECT * from devices")
    return cur.fetchone() # return list of rows

# Function: removeDeviceByName
def removeDeviceByName(deviceName):
    cur.execute("DELETE FROM devices WHERE name=?", (deviceName,))
    conn.commit()
    
# Function: removeDeviceByID
def removeDeviceByID(conn, cur, deviceID):
    cur.execute("DELETE FROM devices WHERE id=?", (deviceID,))
    conn.commit()
    
# Function: clearDB
# deletes all devices from table
def clearDB(conn, cur):
    cur.execute("DELETE FROM devices")
    conn.commit()
    
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

def log(str):
    TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    printstr = time.strftime(TIME_FORMAT) + ": " + str + "\n"
    logging.debug(printstr)
    print(printstr)

def main(args):    
    logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG) # setup logging
    
    if not (os.path.isfile(DB_FILENAME)): # check if need to create file
        log(DB_FILENAME + " doesn't exist, creating it.")
        createDB(DB_FILENAME) # create file
    else:
        conn = sqlite3.connect(DB_FILENAME)
        cur = conn.cursor()
        log("opened existing db " + DB_FILENAME)
    
    # store xbee module addresses
    device_addrs = dict()
    device_addrs['outlet'] = '\x00\x13\xA2\x00\x41\x55\x37\x31'
    device_addrs['light'] = '\x00\x13\xA2\x00\x41\x55\x37\x31'
    
    # open serial port to xbee module
    ser = serialConnect()
    
    # connect to xbee module
    xbee = ZigBee(ser) #, callback=xbee_rx_handler)
    
    log("connected to xbee at " + ser.port)
    
    xbee.at(frame_id='A', command='MY')
    reply = xbee.wait_read_frame()
    log("local xbee resp: " + str(reply))
    
    while(True):
        xbee.remote_at(dest_addr_long=device_addrs['outlet'],command='D0',parameter='\x04')
        time.sleep(1)
        xbee.remote_at(dest_addr_long=device_addrs['outlet'],command='D0',parameter='\x05')
        time.sleep(1)
        
    reply = xbee.wait_read_frame()
    log("remote xbee resp: " + str(reply))
    
    return
    
    # http://localhost:5000/?cmd=set&name=testname&to=off
    
    # setup http GET request handler
    app = Flask(__name__)
    
    @app.route('/',methods=['GET'])
    def get_handler():
        params = request.args
        
        log("GET request: " + str(params))
        
        command = params["cmd"]
        device_name = params["name"]
        
        if (command == "set"):
            if (device_name in device_addrs.keys()):
                # get requested setting
                set_to = params["to"]
                dev_addr = device_addrs[device_name]
                
                # turn on
                if (set_to == "on"):
                    log("turning " + device_name + " on")
                    xbee.remote_at(frame_id='B', dest_addr_long=dev_addr, command='D0', parameter='\x05') # set pin 0 to high
                    resp = xbee.wait_read_frame()
                    log("remote xbee resp: " + str(resp))
                    if(resp["status"] == 0):
                        return("OK")
                    else:
                        return("FAILED")
                # turn off
                elif (set_to == "off"):
                    log("turning " + device_name + " off")
                    xbee.remote_at(frame_id='C', dest_addr_long=dev_addr, command='D0', parameter='\x04') # set pin 0 to low
                    resp = xbee.wait_read_frame()
                    log("remote xbee resp: " + str(resp))
                    if(resp["status"] == 0):
                        return("OK")
                    else:
                        return("FAILED")
                # unknown command
                else:
                    log("invalid set command")
                    return ("INVALID COMMAND")
            else:
                log("unknown device name")
                return("INVALID DEVICE")
        
        elif (cmd == "get"):
            pass
            """
            log("getting " + devname + " status")
            xb.remote_at(command='IS', frame_id='C')
            #resp = xbee.wait_read_frame()
            #log("xbee resp: " + str(resp))
            """
        elif (cmd == "devices"):
            pass
        elif cmd == "add":
            pass
        elif cmd == "remove":
            pass
        else:
            print ("invalid command")
            return("INVALID COMMAND")
        
        return ("OK")
    
    # start http GET request handler
    app.run(host='0.0.0.0', port=5000)

if (__name__ == "__main__"):
    main(sys.argv)
    
#except KeyboardInterrupt: # if ctrl+C is pressed
#   socket.close() # close zmq socket
#  conn.exit() # close db file
#  exit(0) # exit program
