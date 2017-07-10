import RPi.GPIO as GPIO
import sys
import sqlite3

import deviceMan



dbfile = "mydb.sqlite" # path to DB file

[conn, cur] = openDB(dbfile) # open DB



conn.close() # close db file