#!/usr/bin/env python3

import sys
from flask import Flask, request
from flask_basicauth import BasicAuth
from home import myhome

PORT = 5002

def main(args):
    # get instance of home server
    global myhome
    
    # setup http request handler
    app = Flask(__name__)
    @app.route('/',methods=['GET', 'POST'])
    def req_handler():
        # check if json format
        if(request.is_json):
            params = request.get_json()
        else:
            params = request.args

        print("received http request:\n" + str(params))

        # execute command
        return(myhome.Run_command(params))

    # start http server
    app.run(host='0.0.0.0', port=PORT) #, ssl_context='adhoc')

if(__name__ == "__main__"):
    main(sys.argv)
