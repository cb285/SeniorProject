import RPi.GPIO as GPIO
import sys
import sqlite3

dbfile = "mydb.sqlite" # path to db file

if NOT (os.path.isfile(dbfile)): # check if need to create file
    conn, cur = createDB(dbfile) # create file


conn.close() # close db file