import RPi.GPIO as GPIO
import sys
import sqlite3

dbfile = "mydb.sqlite" # path to db file

if NOT (os.path.isfile(dbfile)): # check if need to create file
    conn, cur = createDB(dbfile) # create file


conn.close() # close db file




def createDB(dbfilename):
    conn = sqlite3.connect(dbfilename)
    cur = conn.cursor()

    # create empty table
    cur.execute('CREATE TABLE devices
                    (id integer primary key, type text, name text)')

    conn.commit()
    
    return [conn, cur]
                
def addDevice(DBcur, deviceName, deviceType, deviceID):
    
    DBcur.execute('INSERT INTO devices VALUES (?, ?, ?)', deviceName, deviceType, deviceID)
