from requests import *
import string
from word2number import w2n

SERVER_URL = "https://clayton:clayton@192.195.228.50:58000"
VERIFY_SSL = False

# create translator for removing punctuation
translator=str.maketrans('','',string.punctuation)

def remove_punct(s):
    return s.translate(translator).lower()

def parse_level(s):

    s = remove_punct(s)

    # on
    if(s == "on"):
        return 100
    # dim or dimmed
    elif(s in ["dim", "dimmed"]):
        return 50
    # off
    elif(s == "off"):
        return 0
    
    try:
        # number or number words
        number = w2n.word_to_num(s)
    except ValueError:
        return -1

    return number

def parse_name(s):
    # remove punctuation
    s = remove_punct(s)

    # split by spaces
    words = s.split(" ")
    
    print("words: " + str(words))

    was_num = False

    # combine words to underscore separated string
    device_name = ""
    for word in words:
        if(word != " "):
            try:
                # check if number or number words
                number = w2n.word_to_num(word)
            except ValueError:
                if(was_num):
                    device_name = device_name + "_" + word + "_"
                else:
                    device_name = device_name + word + "_"
                was_num = False
                continue
            print("num = " + str(number))
            if(was_num):
                device_name = device_name + str(number)
            else:
                device_name = device_name + "_" + str(number)
            was_num = True

    # remove extra "_"
    if(not was_num):
        device_name = device_name[:-1]

    # return
    return device_name

def lambda_handler(event, context):

    if('request' in event):
        if('intent' in event['request']):
            if('name' in event['request']['intent']):
                
                intent = event['request']['intent']
                intent_name = intent['name']
                
                if(intent_name != "discover_devices"):
                    slots = intent['slots']

                if(intent_name == "test"):

                    split_str = slots["test_name"]["value"].split(" to ")
                    device_name = parse_name(split_str[0])
                    level = parse_level(split_str[1])

                    return build_response("device name is " + device_name + " and level is " + str(level))

                # discover_devices intent
                elif(intent_name == "discover_devices"):

                    cmd = "discover_devices"
                    
                    payload = {"cmd":cmd}
                    
                    stat = server_request(payload)
                    
                    if(stat):
                        
                        return build_response("okay, trying to discover new devices")
                    else:
                        return build_response("sorry, something went wrong. please try again")
                
                # set_device_level intent
                elif(intent_name == "set_device_level"):
                    if("value" in slots["name_to_level"]):

                        split_str = s.split(" to ")

                        if(len(split_str) != 2):
                            return build_response("sorry, I couldn't hear the device name or level. please try again.")

                        cmd = "set_device_level"
                        device_name = parse_name(split_str[0])
                        level = parse_level(split_str[1])

                        # if couldn't parse level
                        if(level == -1):
                            return build_response("sorry, I couldn't understand the level you wanted to set it to. please try again.")
                        
                        payload = {"cmd":cmd, 'name':device_name, 'level':level}
                        stat = server_request(payload)

                        if(stat):
                            return build_response("okay, I set " + device_name + " to " + str(level) + ".")
                            
                        else:
                            return build_response("sorry, I couldn't do that. check that the device is turned on and in the database.")

                    else:
                        return build_response("sorry, I couldn't understand that. here's an example: set light to 30.")

                # get_device_level intent
                elif(intent_name == "get_device_level"):
                    if("value" in slots["device_name"]):

                        cmd = "get_device_level"
                        device_name = parse_name(slots["device_name"]["value"])

                        payload = {"cmd":cmd, 'name':device_name}

                        level = server_request(payload)

                        if(level != -1):
                            if(level == 100):
                                return build_response("your device called " + device_name + " is on")
                            elif(level == 0):
                                return build_response("your device called " + device_name + " is off")
                            else:
                                return build_response("your device called " + device_name + " is set to " + str(level))
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
                            return build_response("sorry, something went wrong when I tried to set the temperature. check the server log for details.")

                    elif(intent_name == "change_device_name"):
                        if("old_to_new" in slots):

                            split_str = slots["old_to_new"]["value"].split(" to ")

                            if(len(split_str) != 2):
                                return build_response("sorry, I couldn't get the name or new name. please try again.")

                            old_name = parse_name(split_str[0])
                            new_name = parse_name(split_str[1])

                            payload = {'cmd':'change_device_name', 'name':old_name, 'new_name':new_name}

                            stat = server_request(payload)

                            if(stat):
                                return build_response("okay, I changed " + device_name + " to " + new_device_name + ".")
                            else:
                                return build_response("sorry, I couldn't do that. make sure there is a device in the database called " + device_name + ".")

                    else:
                        return build_response("sorry, I couldn't understand that. here's an example: set the temperature to 70 degrees")
                
                    
    return build_response("sorry, I couldn't understand that. please try again. here's an example: set my light to 84.")

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

    r = get(SERVER_URL, params=payload, verify=False)
    
    response = r.text
    
    print("response = " + str(r))
    
    if(response.isdigit()):
        return (int(response))
    else:
        if(response == "ok"):
            return True
        else:
            return False
