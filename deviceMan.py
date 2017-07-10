def openDB(dbFilename):
	if NOT (os.path.isfile(dbfile)): # check if need to create file
		conn, cur = createDB(dbfile) # create file
	else:
		conn = sqlite3.connect(dbfilename)
		cur = conn.cursor()
		
	return [conn, cur]
	

def createDB(dbfilename):
    conn = sqlite3.connect(dbfilename)
    cur = conn.cursor()

    # create empty table
    cur.execute('CREATE TABLE devices
                    (id integer primary key, type text, name text)')

    conn.commit()
    
    return [conn, cur]


def addDevice(cur, deviceName, deviceType, deviceID):
    cur.execute('INSERT INTO devices VALUES (?, ?, ?)', deviceID, deviceType, deviceName)
