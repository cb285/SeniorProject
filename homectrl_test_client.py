import socket

s = socket.socket()
host = "127.0.0.1"
port = 50007
s.connect((host, port))

while True:
    cmd = raw_input(">> ")
    if cmd == "exit":
        s.close()
        exit(0)
    else:
        s.send(cmd.encode('utf-8'))
