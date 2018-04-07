#!/usr/bin/env python

import sys
from flask import Flask, request
from flask_basicauth import BasicAuth
from home import myhome

PORT = 58000

USER = 'clayton'
PASS = 'clayton'

def main(args):
    # get instance of home server
    global myhome
    
    # setup http request handler
    app = Flask(__name__)

    app.config['BASIC_AUTH_USERNAME'] = USER
    app.config['BASIC_AUTH_PASSWORD'] = PASS
    app.config['BASIC_AUTH_FORCE'] = True
    basic_auth = BasicAuth(app)
    
    @app.route('/',methods=['GET', 'POST'])
    @basic_auth.required
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
    app.run(host='0.0.0.0', port=PORT, ssl_context=('cert.pem', 'key.pem'), debug=True, use_reloader=False)

if(__name__ == "__main__"):
    main(sys.argv)
