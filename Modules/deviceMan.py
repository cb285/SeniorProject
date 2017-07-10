import sqlite3
import os

# Function: openDB
# opens the DB if it exists, otherwise it creates one
def openDB(dbFilename):
	if not (os.path.isfile(dbFilename)): # check if need to create file
		return createDB(dbFilename) # create file
	else:
		conn = sqlite3.connect(dbFilename)
		cur = conn.cursor()
		return [conn, cur]
	
# Function: createDB
# creates a DB file and creates an empty device table
def createDB(dbfilename):
    conn = sqlite3.connect(dbfilename)
    cur = conn.cursor()

    # create empty table
    cur.execute("CREATE TABLE devices (id integer primary key, type integer, name text)")
    conn.commit()
    
    return [conn, cur]

# Function: addDevice
def addDevice(conn, cur, deviceName, deviceType, deviceID):
	cur.execute("INSERT INTO devices VALUES (?, ?, ?)", (deviceID, deviceType, deviceName))
	conn.commit()
	
# Function: removeDeviceByName
def removeDeviceByName(conn, cur, deviceName):
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
