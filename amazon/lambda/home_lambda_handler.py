from requests import *

SERVER_URL = "https://clayton:clayton@192.195.228.50:58000"
VERIFY_SSL = False

def lambda_handler(event, context):
    
    print(event)
    
    if('request' in event):
        if('intent' in event['request']):
            if('name' in event['request']['intent']):
                
                intent = event['request']['intent']
                intent_name = intent['name']
                slots = intent['slots']

                # discover_devices intent
                if(intent_name == "discover_devices"):

                    cmd = "discover_devices"
                    
                    payload = {"cmd":cmd}
                    
                    stat = server_request(payload)
                    
                    if(stat):
                        
                        return build_response("okay, trying to discover new devices")
                    else:
                        return build_response("sorry, something went wrong. please try again")
                
                # set_device_level intent
                elif(intent_name == "set_device_level"):
                    if("value" in slots["device_level"] and "value" in slots["device_name"]):
                        
                        cmd = "set_device_level"
                        level = int(slots["device_level"]["value"])
                        device_name = slots["device_name"]["value"]

                        payload = {"cmd":cmd, 'name':device_name, 'level':level}
                        
                        stat = server_request(payload)
                        
                        if(stat):
                            return build_response("okay, I set " + device_name + " to " + str(level) + ".")
                            
                        else:
                            return build_response("sorry, I couldn't do that. check that the device is turned on and in the database.")

                    else:
                        return build_response("sorry, I couldn't understand that. here's an example: set light to 30.")

                # set_device_on_off intent
                elif(intent_name == "set_device_on_off"):
                    if("value" in slots["on_off"] and "value" in slots["device_name"]):
                        
                        cmd = "set_device_level"
                        on_off = int(slots["on_off"]["value"])
                        device_name = slots["device_name"]["value"]

                        if(on_off == "on"):
                            level = 100
                        else:
                            level = 0

                        payload = {"cmd":cmd, 'name':device_name, 'level':level}
                        
                        stat = server_request(payload)
                        
                        if(stat):
                            if(level == 100):
                                return build_response("okay, I turned " + device_name + " on.")
                            else:
                                return build_response("okay, I turned " + device_name + " off.")
                        else:
                            return build_response("sorry, I couldn't do that. check that the device is turned on and in the database.")
                    else:
                        return build_response("sorry, I couldn't understand that. here's an example: turn the light off.")

                # get_device_level intent
                elif(intent_name == "get_device_level"):
                    if("value" in slots["device_name"]):

                        cmd = "get_device_level"
                        device_name = slots["device_name"]["value"]
                        
                        payload = {"cmd":cmd, 'name':device_name}
                        
                        level = server_request(payload)
                        
                        if(level != -1):
                            if(level == 100):
                                return build_response(device_name + " is currently on")
                            elif(level == 0):
                                return build_response(device_name + " is currently off")
                            else:
                                return build_response(device_name + " is currently set to " + str(level) + " percent")
                                
                        else:
                            return build_response("sorry, I couldn't reach that device. please check that it is turned on and in the database.")
                            
                    else:
                        return build_response("sorry, I couldn't understand that. here's an example: is the light on?")

                elif(intent_name == "set_temperature"):
                    if("value" in slots["temperature"]):

                        cmd = "set_temperature"
                        temp = int(slots["temperature"]["value"])

                        payload = {"cmd":cmd, 'temp':temp}
                        
                        stat = server_request(payload)
                        
                        if(stat):
                            return build_response("okay, I set the temperature to " + str(temperature))
                        else:
                            return build_response("sorry, something went wrong.")

                    else:
                        return build_response("sorry, I couldn't understand that. here's an example: set the temperature to 70 degrees")
                
                    
    return build_response("sorry, I couldn't understand that. please try again. here's an example: set my light to 84.")

import requests

def build_response(resp_str):
    
    return {
        "version": "1.0",
        "sessionAttributes": {},
        "response": {
            "outputSpeech": {
                "type": "PlainText",
                "text": resp_str
            },
            "shouldEndSession": True
        }
    }
    
def server_request(payload):

    payload['alexa'] = "alexa"

    r = requests.get(SERVER_URL, params=payload, verify=False)
    
    response = r.text
    
    print("response = " + str(r))
    
    if(response.isdigit()):
        return (int(response))
    else:
        if(response == "ok"):
            return True
        else:
            return False

