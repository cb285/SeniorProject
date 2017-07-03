import RPi.GPIO as GPIO
import sys
import sqlite3

dbfile = "mydb.sqlite" # path to db file

tablename = "devices"
col1 = "name"
col1_type = "TEXT"

col2 = "type"
col2_type = "TEXT"

col3 = "id"
col3_type = "INTEGER"


if os.path.isfile(dbfile): # check if need to create file
    conn = createdb(dbfile) # create file



conn.close() # close db file


def createdb(dbfilename):
    conn = sqlite3.connect(dbfilename)
    cur = conn.cursor()

    # create empty table with 
    cur.execute('CREATE TABLE {tn} ({nf} {ft} PRIMARY KEY)'\
        .format(tn=tablename, nf=col1, ft=field_type))

    conn.commit()
    
    return [conn, cur]
