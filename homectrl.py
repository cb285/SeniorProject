#! /usr/bin/python

import sys

from xbee import XBee, ZigBee
import serial

#import RPi.GPIO as GPIO

from Modules import deviceMan

def main(args):
    # Defaults:
    dbFilename = "mydb.sqlite" # path to DB file
    
    for i in range(args):
        cmd = args[i].lower()
        if cmd == "db":
            i += 1
            dbFilename = args[i]            
        elif cmd == "add":
            i += 1
            deviceMan.addDevice(cur, args[i])
            deviceMan.testComm(cur, args[i])
        elif cmd == "remove":
            i += 1
            deviceMan.removeDevice(cur, args[i])
        elif cmd == "status":
            deviceMan.deviceStat(cur, args[i])

    # open/create database
    [conn, cur] = deviceMan.openDB(dbFilename)

    #deviceMan.addDevice(conn, cur, 0x0, 0xFFFF)
    
    conn.close() # close db file
