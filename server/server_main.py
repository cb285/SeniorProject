#!/usr/bin/env python3

import sys
from flask import Flask, request
from flask_basicauth import BasicAuth
from home import *

PORT = 5000

def discover():
    global myhome
    myhome.Discover_devices()

def run_task(params):
    global myhome
    myhome.Run_command(params)
    
myhome = Home(discover_function=discover, task_function=run_task)

def main(args):
    # get instance of home server
    global myhome
    
    # setup http request handler
    app = Flask(__name__)
    #app.config['BASIC_AUTH_USERNAME'] = 'admin'
    #app.config['BASIC_AUTH_PASSWORD'] = 'admin'
    #app.config['BASIC_AUTH_FORCE'] = True
    #basic_auth = BasicAuth(app)
    @app.route('/',methods=['GET', 'POST'])
    #@basic_auth.required
    def req_handler():
        # check if json format
        if(request.is_json):
            params = request.get_json()
        else:
            params = request.args

        print("received http request:\n" + str(params))

        # execute command
        ret = myhome.Run_command(params)
        
        return(ret)

    # start http server
    app.run(host='0.0.0.0', port=PORT) #, ssl_context='adhoc')

if(__name__ == "__main__"):
    main(sys.argv)
