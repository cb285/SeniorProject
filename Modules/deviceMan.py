import sqlite3
import os
import serial
import glob

# Constants:
OUTLET_TYPE = "outlet"
LIGHT_TYPE = "light"
THERMOSTAT_TYPE = "thermo"
        
class DeviceManager:
        
        def __init__(dbFilename):
                if not (os.path.isfile(dbFilename)): # check if need to create file
                        print "db doesn't exist, creating new one."
		        return createDB(dbFilename) # create file
	        else:
		        conn = sqlite3.connect(dbFilename)
		        cur = conn.cursor()
        
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

        def testComm(
                
        def xbeeConnect():
                PORT_NAME = "/dev/ttyACM*" # port name (with wildcard for scanning multiple ports)
                
                # setup serial connection (except port)
                ser = serial.Serial()
                ser.baudrate = 115200
                ser.timeout = 10
                ser.write_timeout = 10
                ser.exclusive = True
                
                for a_port in glob.glob(PORT_NAME):        
                        # set port
                        ser.port = a_port
                        
                        print "attempting connection on port " + ser.port
                        
                        try:
                                num_attempts += 1
                                ser.open()
                                print "connection successful."
                                ser.flushInput()	# flush buffers (just in case)
                                ser.flushOutput()
                                return ser		# return to main if connection succeeded
                        
                        except serial.SerialException: # if failed
                                # if have attempts left
                                if (num_attempts < CONN_ATTEMPTS):
                                        time.sleep(CONN_INTERVAL)	# wait CONN_INTERVAL between tries
                                continue    		# try again
                        # if no attempts left, try next port number
                                else:
                                        print "connection failed on port " + ser.port
                                        
                        except KeyboardInterrupt: # If CTRL+C is pressed
                                ser.close()
                                return False
                        
                        time.sleep(SCAN_INTERVAL) # wait between port scans
                        
                print "connection failed on all ports"
                ser.close()
                return False
