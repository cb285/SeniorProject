#! /usr/bin/python

import sys

from xbee import XBee
import serial
import time
import logging
import socket

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
    # setup serial connection (except port)
    ser = serial.Serial()
    ser.port = "/dev/ttyUSB0"
    ser.baudrate = 9600
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
    logging.debug(time.strftime(TIME_FORMAT) + ": " + str + "\n")
    
def main(args):    
    logging.basicConfig(filename=LOG_FILENAME, level=logging.DEBUG) # setup logging
    
    if not (os.path.isfile(DB_FILENAME)): # check if need to create file
        log(DB_FILENAME + " doesn't exist, creating it.")
	createDB(DB_FILENAME) # create file
    else:
	conn = sqlite3.connect(DB_FILENAME)
	cur = conn.cursor()
        log("opened existing db " + DB_FILENAME)
    
    # open serial port to xbee module
    ser = serialConnect()
    
    # connect to xbee module
    xbee = Xbee(ser) # callback=xbee_rx_handler)
    
    log("connected to xbee at " + ser.port)
    
    # setup socket
    HOST = "127.0.0.1"
    PORT = 50007
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, PORT))
    s.listen(1) # accept max of 1 connections
    conn, addr = s.accept()
    log("connected by " + addr)
    
    while True:
        try:
            #  wait for message from client
            data = conn.recv(1024)
            log("received: " + data)
            
            cmd_args = data.split(";")
            cmd = cmd_args[0]
            
            if cmd == "set":
                if cmd_args[1] == "on":
                    log("turning LED on")
                    xbee.at(command='D1', parameter='\x05') # turn LED on
                    resp = xbee.wait_read_frame()
                    log("xbee resp: " + str(resp))
                elif splitmgs[1] == "off":
                    log("turning LED off")
                    xbee.at(command='D1', parameter='\x04') # turn LED off
                    resp = xbee.wait_read_frame()
                    log("xbee resp: " + str(resp))
                else:
                    log("invalid command: " + data)
            elif cmd == "get":
                log("getting LED status")
                xbee.at(command='IS', frame_id='C')
                resp = xbee.wait_read_frame()
                print resp
            elif cmd == "add":
                pass
            elif cmd == "remove":
                pass
            else:
                print "invalid command: " + data
            
        except KeyboardInterrupt: # if ctrl+C is pressed
            socket.close() # close zmq socket
            conn.exit() # close db file
            exit(0) # exit program
            
        
