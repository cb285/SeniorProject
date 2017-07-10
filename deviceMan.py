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
		
		colNames = list(map(lambda x: x[0], cur.description))
		if colNames is not ["id", "type", "name"]:
			print("Not a valid dataBase")
			exit(-1)
		
	return [conn, cur]
	
# Function: createDB
# creates a DB file and creates an empty device table
def createDB(dbfilename):
    conn = sqlite3.connect(dbfilename)
    cur = conn.cursor()

    # create empty table
    cur.execute("CREATE TABLE devices (id integer primary key, type text, name text)")
    conn.commit()
    
    return [conn, cur]

# Function: addDevice
def addDevice(cur, deviceName, deviceType, deviceID):
	cur.execute("INSERT INTO devices VALUES (?, ?, ?)", (deviceID, deviceType, deviceName))
	cur.commit()
	
# Function: removeDeviceByName
def removeDeviceByName(cur, deviceName):
	cur.execute("DELETE FROM devices WHERE name=?", (deviceName,))
	cur.commit()

# Function: removeDeviceByID
def removeDeviceByID(cur, deviceID):
	cur.execute("DELETE FROM devices WHERE id=?", (deviceID,))
	cur.commit()

# Function: clearDB
# deletes all devices from table
def clearDB(cur):
	cur.execute("DELETE FROM devices")
	cur.commit()
