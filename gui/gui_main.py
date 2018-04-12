#!/usr/bin/env python2

import sys
import time
import requests
from threading import RLock, Timer

from kivy.app import App
from kivy.uix.widget import Widget
from kivy.uix.gridlayout import GridLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.tabbedpanel import *
from kivy.uix.button import Button
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.lang import Builder
from kivy.clock import Clock
from kivy.properties import *
from kivy.uix.dropdown import DropDown
from kivy.uix.slider import Slider

from kivy.config import Config
Config.set('kivy', 'keyboard_mode', 'systemandmulti')

USER = "clayton"
PASS = "clayton"
SERVER_IP = "127.0.0.1"
PORT = 58000
SERVER_URL = "https://" + USER + ":" + PASS + "@" + SERVER_IP + ":" + str(PORT)
VERIFY_SSL = False
TIME_FORMAT = "%A %m-%d %I:%M %p" # clock time/date format

REQUEST_TIMEOUT = 3               # seconds to wait for server response

CLOCK_UPDATE = 10                 # seconds between clock updates
THERMOSTAT_UPDATE = 10            # seconds between thermostat updates

DEVICE_UPDATE_INTERVAL = 10       # seconds between device state updates

LARGE_FONT_SIZE = 35
MEDIUM_FONT_SIZE = LARGE_FONT_SIZE - 5
SMALL_FONT_SIZE = MEDIUM_FONT_SIZE - 5

RESPONSE_OK = "ok"
RESPONSE_FAILED = "failed"
LEVEL_UNK = -1

SWITCH_TYPE = "switch"
DIMMER_TYPE = "dimmer"
CUSTOM_SWITCH = "cust-switch"
CUSTOM_PULSE = "cust-pulse"
CUSTOM_INPUT = "cust-input"

request_lock = RLock()

REQUEST_WAIT = 0
last_request_time = 0

LIGHT_CHANGE_WAIT = 4
last_light_change_time = 0

def Server_request(payload):

    with request_lock:
        global last_request_time
        while((time.time() - last_request_time) <= REQUEST_WAIT):
            print("waiting")
            time.sleep(0.5)

        last_request_time = time.time()

        if("name" in payload):
            payload["name"] = payload["name"].encode("utf-8")
            
        print("sending payload : ", payload)
        
        try:
            r = requests.get(SERVER_URL, params=payload, verify=VERIFY_SSL, timeout=REQUEST_TIMEOUT)
        except:
            print("error connecting to server")
            return False
            
        resp = r.text
    
        if(resp == RESPONSE_FAILED):
            return False
        elif(resp == RESPONSE_OK):
            return True
        elif(resp == "unk"):
            return False
    
        if(resp == "invalid"):
            raise Exception("invalid command sent to server: " + str(payload))
        
        return r.text

def Get_devices():
    resp = Server_request({'cmd':'list_devices_with_types'})

    if((not resp) or (resp == "none")):
        return list()
    
    device_list = resp.split(",")

    devices = dict()

    print("devices = " + str(resp))
    
    for device in device_list:
        name_type = device.split(":")
        devices[name_type[0]] = name_type[1]

    sorted_devices = list()

    # sort alphabetically by device name
    for key in sorted(devices.iterkeys()):
        sorted_devices.append({'name':key, 'type':devices[key]})

    return sorted_devices

def Discover_devices():

    resp = Server_request({'cmd':'discover_devices'})

    return resp

def Change_device_name(device_name, new_name):
    
    resp = Server_request({'cmd':'change_device_name', 'name':device_name, 'new_name':new_name})

    return resp
    
def Set_device_level(device_name, level):

    resp = Server_request({'cmd':'set_device_level', 'name':device_name, 'level':level})
    return resp

def Get_device_level(device_name):

    resp = Server_request({'cmd':'get_device_level', 'name':device_name})

    if(not resp):
        return LEVEL_UNK
    
    return int(resp)

def Get_device_type(device_name):

    resp = Server_request({'cmd':'get_device_type', 'name':device_name})

    if(not resp):
        return "?"

    return resp

def Get_curr_temp():

    resp = Server_request({'cmd':'get_curr_temp'})

    if(not resp):
        return LEVEL_UNK
    
    return int(round(float(resp)))

def Get_set_temp():
    
    resp = Server_request({'cmd':'get_set_temp'})

    if(not resp):
        return LEVEL_UNK

    return int(round(float(resp)))

def Set_temp(temp):

    return Server_request({'cmd':'set_temp', 'temp':temp})

def Set_temp_mode(mode):

    return Server_request({'cmd':'set_temp_mode', 'temp_mode':mode})

def Set_fan_mode(mode):

    return Server_request({'cmd':'set_fan_mode', 'fan_mode':mode})

def Get_temp_mode():

    return Server_request({'cmd':'get_temp_mode'})

def Get_fan_mode():

    resp = Server_request({'cmd':'get_fan_mode'})

    if(not resp):
        return "?"
    return resp

# Thermostat / Clock Tab
class ThermTab(TabbedPanelItem):
    def __init__(self,**kwargs):
        super(ThermTab,self).__init__(**kwargs)

        # set displayed tab name
        self.text="Thermostat"

        # make tab a float layout
        self.content = FloatLayout()

        # create clock
        self.clock_label = Label(text=time.strftime(TIME_FORMAT), font_size=LARGE_FONT_SIZE, size_hint=(0.5, 0.2), pos_hint={'center_x': 0.5, 'center_y': 0.8})

        # schedule clock updates
        Clock.schedule_interval(self.update_clock, CLOCK_UPDATE)
        self.content.add_widget(self.clock_label)

        # create temperature labels and buttons
        self.curr_temp_label = Label(text="Current: ? F", font_size=MEDIUM_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.6}, text_size=(350, None))
        self.content.add_widget(self.curr_temp_label)

        self.set_temp_label = Label(text="Set: ? F", font_size=MEDIUM_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.5}, text_size=(350, None))
        self.content.add_widget(self.set_temp_label)
        
        self.increase_temp_button = Button(text="+", font_size=MEDIUM_FONT_SIZE, size_hint=(0.1, 0.1), pos_hint={'center_x': 0.6, 'center_y': 0.55}, on_release=self.change_set_temp)
        self.content.add_widget(self.increase_temp_button)
        self.decrease_temp_button = Button(text="-", font_size=MEDIUM_FONT_SIZE, size_hint=(0.1, 0.1), pos_hint={'center_x': 0.6, 'center_y': 0.45}, on_release=self.change_set_temp)
        self.content.add_widget(self.decrease_temp_button)

        # temperature mode label
        self.temp_mode_label = Label(text="Mode: ?", font_size=MEDIUM_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.4}, text_size=(350, None))
        self.content.add_widget(self.temp_mode_label)

        # fan mode label
        self.fan_mode_label = Label(text="Fan: ?", font_size=MEDIUM_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.32}, text_size=(350, None))
        self.content.add_widget(self.fan_mode_label)

        # temperature mode buttons
        self.temp_button_label = Label(text="Temp:", font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.1, 'center_y': 0.2}, text_size=(350, None))
        self.content.add_widget(self.temp_button_label)

        self.heat_temp_mode_button = Button(text="Heat", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.35, 'center_y': 0.2}, on_release=self.set_temp_mode)
        self.content.add_widget(self.heat_temp_mode_button)
        self.cool_temp_mode_button = Button(text="Cool", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.45, 'center_y': 0.2}, on_release=self.set_temp_mode)
        self.content.add_widget(self.cool_temp_mode_button)
        self.auto_temp_mode_button = Button(text="Auto", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.55, 'center_y': 0.2}, on_release=self.set_temp_mode)
        self.content.add_widget(self.auto_temp_mode_button)
        self.off_temp_mode_button = Button(text="Off", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.65, 'center_y': 0.2}, on_release=self.set_temp_mode)
        self.content.add_widget(self.off_temp_mode_button)

        # fan mode buttons
        self.fan_button_label = Label(text="Fan:", font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.1, 'center_y': 0.1}, text_size=(350, None))
        self.content.add_widget(self.fan_button_label)
        
        self.auto_fan_mode_button = Button(text="Auto", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.35, 'center_y': 0.1}, on_release=self.set_fan_mode)
        self.content.add_widget(self.auto_fan_mode_button)
        self.on_fan_mode_button = Button(text="On", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.45, 'center_y': 0.1}, on_release=self.set_fan_mode)
        self.content.add_widget(self.on_fan_mode_button)
        self.off_fan_mode_button = Button(text="Off", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.55, 'center_y': 0.1}, on_release=self.set_fan_mode)
        self.content.add_widget(self.off_fan_mode_button)

        self.update_clock()

        self.update_therm()
        
        # schedule thermostat updates
        Clock.schedule_interval(self.update_therm, THERMOSTAT_UPDATE)

        # add refresh button
        self.refresh_button = Button(text="refresh", size_hint=(0.1, 0.1), pos_hint={'x': 0.9, 'y': 0}, on_release=self.update_therm)
        self.content.add_widget(self.refresh_button)
        
    def update_clock(self, event=0):
        self.clock_label.text = time.strftime(TIME_FORMAT)

    def update_therm(self, event=0):
        # get current temperature
        curr_temp = Get_curr_temp()

        # update current temperature label
        if(curr_temp == LEVEL_UNK):
            self.curr_temp_label.text = "Current: ? F"
        else:
            self.curr_temp_label.text = "Current: " + str(curr_temp) + " F"
        
        # get set temperature
        self.set_temp = Get_set_temp()

        # update set temperature label
        if(self.set_temp == LEVEL_UNK):
            self.set_temp_label.text = "Set: ? F"
        else:
            self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"
        
        # get temp mode
        temp_mode = Get_temp_mode()

        # update temperature mode label
        if(not temp_mode):
            self.temp_mode_label.text = "Mode: ?"
        else:
            self.temp_mode_label.text = "Mode: " + temp_mode
        
        # get fan mode
        fan_mode = Get_fan_mode()

        # update fan mode label
        if(not fan_mode):
            self.fan_mode_label.text = "Fan: ?"
        else:
            self.fan_mode_label.text = "Fan: " + fan_mode

    def change_set_temp(self, event):

        # if set temperature is unknown
        if(self.set_temp == LEVEL_UNK):
            self.update_therm()
            if(self.set_temp == LEVEL_UNK):
                self.set_temp_label.text = "Set: ? F"
                return
            return
        
        # increase
        if(event.text == "+"):

            resp = Set_temp(self.set_temp + 1)

            # update set temperature label
            if(not resp):
                self.set_temp = LEVEL_UNK
                self.set_temp_label.text = "Set: ? F"
            else:
                self.set_temp = self.set_temp + 1
                self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"                
                return
        # decrease
        else:
            resp = Set_temp(self.set_temp - 1)

            # update set temperature label
            if(not resp):
                self.set_temp = LEVEL_UNK
                self.set_temp_label.text = "Set: ? F"
            else:
                self.set_temp = self.set_temp - 1
                self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"                
                return

    def set_temp_mode(self, event):

        # get desired mode setting
        mode = event.text.lower()

        if(mode == "heat"):
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Heat"
            else:
                self.temp_mode_label.text = "Mode: ?"

        elif(mode == "cool"):
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Cool"
            else:
                self.temp_mode_label.text = "Mode: ?"

        elif(mode == "auto"):
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Auto"
            else:
                self.temp_mode_label.text = "Mode: ?"

        elif(mode == "off"):
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Auto"
            else:
                self.temp_mode_label.text = "Mode: ?"
        else:
            raise Exception("invalid temp mode : " + str(mode))

    def set_fan_mode(self, event):

        # get desired mode setting
        mode = event.text
        
        if(mode == "On"):
            success = Set_fan_mode(mode.lower())

            if(success):
                self.fan_mode_label.text = "Fan: On"
            else:
                self.fan_mode_label.text = "Fan: ?"

        elif(mode == "Off"):
            success = Set_fan_mode(mode.lower())

            if(success):
                self.fan_mode_label.text = "Fan: Off"
            else:
                self.fan_mode_label.text = "Fan: ?"

        else:
            success = Set_fan_mode(mode.lower())

            if(success):
                self.fan_mode_label.text = "Fan: Auto"
            else:
                self.fan_mode_label.text = "Fan: ?"

class DeviceTab(TabbedPanelItem):
    def __init__(self,**kwargs):
        super(DeviceTab,self).__init__(**kwargs)
        
        self.text="Devices"
        self.content = FloatLayout()
        self.gridlayout = GridLayout(cols=3, rows=5)
        self.content.add_widget(self.gridlayout)
        self.add_button = Button(text="+", font_size=LARGE_FONT_SIZE, background_normal="", background_color=(0,0,1,.7), on_press=self.add_device, size_hint=(0.1, 0.2), pos_hint={'x': 0.9, 'y': 0})
        self.content.add_widget(self.add_button)
        
    def add_device(self, event):
        self.gridlayout.add_widget(DeviceTile())

class DeviceTile(FloatLayout):
    def __init__(self,**kwargs):
        super(DeviceTile,self).__init__(**kwargs)
        
        self.setup_window = DeviceSetupWindow(self, size_hint=(0.5 , 0.5), pos_hit={'x_center': 0.5, 'y_center': 0.5}, on_dismiss=self.setup_tile, title="Device Setup", auto_dismiss=False)
        self.is_setup = BooleanProperty(False)
        self.device_name = StringProperty("null")
        self.device_type = StringProperty("null")
        
        self.setup_window.open()
        
    def setup_tile(self, event):
        if(not self.is_setup):
            self.parent.remove_widget(self)
            return

        if(self.device_type in [SWITCH_TYPE, CUSTOM_SWITCH]):
            self.switch = Switch(on_touch_down=self.toggle_switch, active=False, size_hint=(0.05, 0.05), pos_hint={'center_x': 0.5, 'center_y': 0.5})
            self.add_widget(self.switch)

            self.label = Label(text=self.device_name, font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.6})
            self.add_widget(self.label)
            
        elif(self.device_type == DIMMER_TYPE):
            self.slider = Slider(orientation='vertical', min=0, max=100, value=0, value_track=True, value_track_color=[1, 0, 0, 1],
                                 on_touch_up=self.set_dimmer_level, size_hint=(0.1, 0.4), pos_hint={'center_x': 0.5, 'center_y': 0.5})
            self.add_widget(self.slider)

            self.label = Label(text=self.device_name, font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.3, 'center_y': 0.5})
            self.add_widget(self.label)

            self.last_set_level = -1
            
        elif(self.device_type == CUSTOM_PULSE):
            self.button = Button(text="", font_size=SMALL_FONT_SIZE, pos_hint={'center_x': 0.5, 'center_y': 0.5}, size_hint=(.1, .1), on_press=self.pulse)
            self.add_widget(self.button)

            self.label = Label(text=self.device_name, font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.6})
            self.add_widget(self.label)

        self.settings_button = Button(text="...", font_size=SMALL_FONT_SIZE, pos_hint={'x': 0, 'y': 0}, size_hint=(.1, .1), on_press=self.open_settings)
        self.add_widget(self.settings_button)
            
        self.close_button = Button(background_normal = '', background_color=(1,0,0,1), text="x", font_size=SMALL_FONT_SIZE, pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(.1, .1), on_press=self.close_tile)
        self.add_widget(self.close_button)

        if(self.device_type != CUSTOM_PULSE):
            self.update_status()

            # schedule status update
            Clock.schedule_interval(self.update_status, DEVICE_UPDATE_INTERVAL)

    def update_status(self, event=0):

        # update label in case name changed
        self.label.text = self.device_name
        
        level = Get_device_level(self.device_name)

        if(self.device_type in [SWITCH_TYPE, CUSTOM_SWITCH]):
            if(level == 100):
                self.switch.active = True
            else:
                self.switch.active = False
        elif(self.device_type == DIMMER_TYPE):
            self.slider.value = level
            
    def toggle_switch(self, event=0, touch=0):

        if not self.collide_point(*touch.pos):
            return
        
        if(self.switch.active):
            level = 0
        else:
            level = 100

        curr_level = Get_device_level(self.device_name)
            
        if(curr_level == level):
            print("not changing level")
            return
            
        success = Set_device_level(self.device_name, level)

        Timer(0.1, self.update_status).start()
        
    def set_dimmer_level(self, event=0, touch=0):

        level = int(round(self.slider.value))

        if(level > 100):
            level = 100
        elif(level < 0):
            level = 0

        curr_level = Get_device_level(self.device_name)

        if(curr_level == level):
            print("not changing level")
            return

        global last_light_change_time
        
        if((time.time() - last_light_change_time) < LIGHT_CHANGE_WAIT):
            print("ignoring slider input")
            return

        self.slider.disabled = True

        last_light_change_time = time.time()
            
        print("setting level to ", level)
        
        # send command to server
        success = Set_device_level(self.device_name, level)

        # if not successful
        if(not success):
            # set slider to 0
            self.slider.value = 0
            
        Timer(LIGHT_CHANGE_WAIT, self.enable_slider).start()
        Timer(LIGHT_CHANGE_WAIT, self.update_status).start()

    def enable_slider(self, event=0):
        self.slider.disabled = False

    def pulse(self, event=0):
        # send command to server
        success = Set_device_level(self.device_name, 100)

    def open_settings(self, event=0):
        self.settings_window = DeviceSettingsWindow(self, size_hint=(0.5 , 0.5), pos_hit={'x_center': 0.5, 'y_center': 0.5}, title="Device Settings", auto_dismiss=False)
        self.settings_window.open()
        
    def close_tile(self, event):
        
        # stop status updater
        Clock.unschedule(self.update_status)
        
        # delete tile widget
        self.parent.remove_widget(self)
        
class DeviceSetupWindow(Popup):
    def __init__(self,caller,**kwargs):
        super(DeviceSetupWindow,self).__init__(**kwargs)

        self.caller = caller
        self.content = FloatLayout()
        
        # add close button
        self.close_button = Button(text="x", background_normal = '', background_color=(1,0,0,1), pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(0.1, 0.1), on_press=self.close_window)
        self.content.add_widget(self.close_button)

        # create drop down list
        self.device_dropdown = DropDown()
        self.content.add_widget(self.device_dropdown)

        # create main button
        self.device_dropdown_mainbutton = Button(text='Devices', size_hint=(.5, .2), pos_hint={'center_x':0.4, 'center_y':0.6})
        self.device_dropdown_mainbutton.bind(on_release=self.device_dropdown.open)

        self.content.add_widget(self.device_dropdown_mainbutton)
        
        # on select, change text of main button
        self.device_dropdown.bind(on_select=lambda instance, x: setattr(self.device_dropdown_mainbutton, 'text', x))

        ## add devices to drop down list
        self.refresh_device_list()

        # add refresh devices buttom
        self.refresh_devices_btn = Button(text='refresh', size_hint=(0.25, 0.2), pos_hint={'x':0, 'y':0.8}, on_press=self.refresh_device_list)
        self.content.add_widget(self.refresh_devices_btn)
        
        # add save button
        self.save_button = Button(text="Save", background_normal="", background_color=(0,0,.7,1), on_press=self.save_setup, pos_hint={'x': 0, 'y': 0}, size_hint=(.4, .2))
        self.content.add_widget(self.save_button)

    def refresh_device_list(self, event=0):

        # clear list
        self.device_dropdown.clear_widgets()
        
        # get list of devices in database
        devices = Get_devices()

        #devices = [{'name':'testdimmer', 'type':'dimmer'},{'name':'testswitch', 'type':'switch'},{'name':'testcustomsw', 'type':'custom-switch'},{'name':'testcustompulse', 'type':'custom-pulse'}]
        
        print("devices: ", devices)
        
        # add each device in db to drop down list
        for device in devices:
            btn = Button(text=device['name'] + " : " + device['type'], size_hint=(.05, None))
            btn.bind(on_release=lambda btn: self.device_dropdown.select(btn.text))
            self.device_dropdown.add_widget(btn)

    def close_window(self, event=0):
        self.caller.is_setup = False
        self.dismiss()

    def save_setup(self, event):

        if(self.device_dropdown_mainbutton.text == "Devices"):
            self.close_window()
            return
        
        split_btn_text = self.device_dropdown_mainbutton.text.split(" : ")

        # set device parameters
        self.caller.device_name = split_btn_text[0]
        self.caller.device_type = split_btn_text[1]
        self.caller.is_setup = True
        
        # close setup window
        self.dismiss()

class DeviceSettingsWindow(Popup):
    def __init__(self,caller,**kwargs):
        super(DeviceSettingsWindow,self).__init__(**kwargs)

        self.caller = caller
        self.content = FloatLayout()
        self.device_name = self.caller.device_name
        
        # add close button
        self.close_button = Button(text="x", background_normal = '', background_color=(1,0,0,1), pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(0.1, 0.1), on_press=self.close_window)
        self.content.add_widget(self.close_button)

        # add name text box
        self.device_name_input = TextInput(text=self.device_name, multiline=False, pos_hint={'x':0.02, 'center_y':0.5}, size_hint=(0.8, 0.25))
        self.content.add_widget(self.device_name_input)

        self.device_name_input.show_keyboard()

        # add name text box label
        self.device_name_input_label = Label(text="Change Device Name:", font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'center_x': 0.5, 'center_y': 0.7})
        self.content.add_widget(self.device_name_input_label)
            
        # add save button
        self.save_button = Button(text="Save", background_normal="", background_color=(0,0,.7,1), on_press=self.save_settings, pos_hint={'x': 0, 'y': 0}, size_hint=(.4, .2))
        self.content.add_widget(self.save_button)

    def close_window(self, event=0):
        self.dismiss()

    def save_settings(self, event=0):

        # if name didn't change
        if(self.device_name_input.text == self.device_name):
            self.close_window()
            return
        # if name did change
        else:
            success = Change_device_name(self.device_name, self.device_name_input.text.encode("utf-8"))
            if(success):
                self.caller.device_name = self.device_name_input.text

                if(self.caller.device_type != CUSTOM_PULSE):
                    self.caller.update_status()
            
            self.close_window()

class MainWindow(TabbedPanel):
    def __init__(self,**kwargs):
        super(MainWindow,self).__init__(**kwargs)
        
        self.do_default_tab = False
        
        self.therm_tab = ThermTab()
        self.default_tab = self.therm_tab
        
        self.add_widget(self.therm_tab)
        
        self.device_tab = DeviceTab()
        self.add_widget(self.device_tab)

class App(App):
    
    title = "Control Panel"
    
    def build(self):
        return MainWindow()

def main(args):
    # test connection to server
    payload = {'cmd':'test'}

    """
    if (Server_request(payload)):
        App().run()
    else:
        print("ERROR: could not connect to server")
        return
    """

    App().run()
 
if (__name__ == "__main__"):
    main(sys.argv)
