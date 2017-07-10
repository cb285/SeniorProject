#! /usr/bin/python

#import RPi.GPIO as GPIO
import sys
import sqlite3

from xbee import XBee, ZigBee
import serial

from Modules import deviceMan

# Defaults:
dbFilename = "mydb.sqlite" # path to DB file

# Constants:
DOUT_TYPE = 0x1
DIN_TYPE = 0x2


# for i in range(sys.argc):
	# cmd = sys.argv[i].lower()
	# if cmd == "db":
		# i += 1
		# dbfile = sys.argv[i]
		# [conn, cur] = deviceMan.openDB(dbfile) # open DB

	# elif cmd == "add":
		# deviceMan.addDevice(cur, )


# open/create database
[conn, cur] = deviceMan.openDB(dbFilename)

deviceMan.addDevice(conn, cur, 0x0, 0xFFFF)

conn.close() # close db file