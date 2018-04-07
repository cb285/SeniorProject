#!/usr/bin/env python3

import sys
import time
import requests

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

USER="clayton"
PASS="clayton"
SERVER_URL = "https://USER:PASS@10.10.1.251:58000"
VERIFY_SSL = False
TIME_FORMAT = "%A %m-%d %I:%M %p" # clock time/date format

REQUEST_TIMEOUT = 1 # seconds to wait for server response

CLOCK_UPDATE = 10 # seconds between clock updates
THERMOSTAT_UPDATE = 60 # seconds between thermostat updates

LARGE_FONT_SIZE = 48
MEDIUM_FONT_SIZE = LARGE_FONT_SIZE - 10
SMALL_FONT_SIZE = MEDIUM_FONT_SIZE - 10

RESPONSE_OK = "ok"
RESPONSE_FAILED = "failed"
LEVEL_UNK = -1

def Server_request(payload):
    try:
        r = requests.get(SERVER_URL, params=payload, verify=VERIFY_SSL, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.Timeout:
        return False

    resp = r.text
    
    if(resp == RESPONSE_FAILED):
        return False
    elif(resp == RESPONSE_OK):
        return True

    if(resp == "invalid"):
        raise Exception("invalid command sent to server: " + payload["cmd"])

    return r.text

def Get_devices():
    resp = Server_request({'cmd':'list_devices_with_types'})

    if(not resp):
        return [['none', 'none']]
    
    device_list = resp.split(",")

    devices = dict()
    
    for device in device_list:
        name_type = device.split(":")
        devices[name_type[0]] = name_type[1]

    # sort alphabetically by device name
    for key in sorted(devices.iterkeys()):
        sorted_devices.append([key, mydict[key]])

    return sorted_devices

def Discover_devices():
    resp = Server_request({'cmd':'discover_devices'})

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

    resp = Server_request({'cmd':'get_curr_temperature'})

    if(not resp):
        return LEVEL_UNK
    
    return int(resp)

def Get_set_temp():
    
    resp = Server_request({'cmd':'get_set_temperature'})

    if(not resp):
        return LEVEL_UNK

    return int(resp)

def Set_temp(temp):

    return Server_request({'cmd':'set_temperature', 'temperature':temp})

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
        self.curr_temp_label = Label(text="Current: ? F", font_size=LARGE_FONT_SIZE - 6, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.6}, text_size=(350, None))
        self.content.add_widget(self.curr_temp_label)

        self.set_temp_label = Label(text="Set: ? F", font_size=MEDIUM_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.5}, text_size=(350, None))
        self.content.add_widget(self.set_temp_label)
        
        self.increase_temp_button = Button(text="+", font_size=LARGE_FONT_SIZE, size_hint=(0.1, 0.1), pos_hint={'center_x': 0.6, 'center_y': 0.55}, on_release=self.change_set_temp)
        self.content.add_widget(self.increase_temp_button)
        self.decrease_temp_button = Button(text="-", font_size=LARGE_FONT_SIZE, size_hint=(0.1, 0.1), pos_hint={'center_x': 0.6, 'center_y': 0.45}, on_release=self.change_set_temp)
        self.content.add_widget(self.decrease_temp_button)

        # temperature mode label
        self.temp_mode_label = Label(text="Mode: ?", font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.4}, text_size=(350, None))
        self.content.add_widget(self.temp_mode_label)

        # fan mode label
        self.fan_mode_label = Label(text="Fan: ?", font_size=SMALL_FONT_SIZE, size_hint=(0.5, 0.1), pos_hint={'x': 0.2, 'center_y': 0.35}, text_size=(350, None))
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
        self.refresh_button = Button(text="#", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.2, 'center_y': 0.9}, on_release=self.update_therm)
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
        self.temp_mode_label.text = "Mode: " + temp_mode
        
        # get fan mode
        fan_mode = Get_temp_mode()
        
        # update fan mode label
        self.fan_mode_label.text = "Fan: " + fan_mode

    def change_set_temp(self, event):
        # increase
        if(event.text == "+"):

            if(self.set_temp == LEVEL_UNK):
                self.update_therm()
                return
                
            resp = Set_temperature(self.set_temp + 1)

            # update set temperature label
            if(not resp):
                self.set_temp = LEVEL_UNK
                self.set_temp_label.text = "Set: ? F"
            else:
                self.set_temp = resp
                self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"                
                return
        # decrease
        else:
            if(self.set_temp == LEVEL_UNK):
                self.update_therm()
                return
            
            resp = Set_temperature(self.set_temp - 1)

            # update set temperature label
            if(not resp):
                self.set_temp = LEVEL_UNK
                self.set_temp_label.text = "Set: ? F"
            else:
                self.set_temp = resp
                self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"                
                return

    def set_temp_mode(self, event):

        # get desired mode setting
        mode = event.text

        if(mode == "Heat"):
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Heat"
            else:
                self.temp_mode_label.text = "Mode: ?"

        elif(mode == "Cool"):
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Cool"
            else:
                self.temp_mode_label.text = "Mode: ?"

        else:
            success = Set_temp_mode(mode.lower())

            if(success):
                self.temp_mode_label.text = "Mode: Auto"
            else:
                self.temp_mode_label.text = "Mode: ?"

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
        self.add_button = Button(text="+", font_size=48, background_normal="", background_color=(0,0,1,.7), on_press=self.add_device, size_hint=(0.1, 0.2), pos_hint={'x': 0.9, 'y': 0})
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
        
        self.label = Label(text=self.device_name, font_size=36, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.65})
        self.add_widget(self.label)

        if(self.device_type == "outlet"):
            self.switch = Switch(on_press=self.toggle, active=False, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.5})
            self.add_widget(self.switch)
        elif(self.device_type == "light"):
            self.switch = Switch(on_press=self.toggle, active=False, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.5})
            self.add_widget(self.switch)
        
        self.close_button = Button(background_normal = '', background_color=(1,0,0,1), text="x", font_size=26, pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(.1, .1), on_press=self.close_tile)
        self.add_widget(self.close_button)
        
        payload = {'cmd':'get', 'name': self.device_name}
        r = requests.get(SERVER_URL, params=payload)
        if (r.text == "on"):
           self.current_state = "on"
           self.switch.active = True
        else:
            self.current_state = "off"
            self.switch.active = False
            
        # schedule status update
        Clock.schedule_interval(self.update_status, 3)

    def update_status(self, event):
        payload = {'cmd':'get', 'name': self.device_name}
        r = requests.get(SERVER_URL, params=payload)
        if (r.text == "on"):
           self.current_state = "on"
           self.switch.active = True
        else:
            self.current_state = "off"
            self.switch.active = False
        
    def toggle(self, event):
        if(self.current_state == "off"):
            self.current_state == "on"
        else:
            self.current_state = "off"
        
        payload = {'cmd':'set', 'name': self.device_name, 'to': self.current_state}
        r = requests.get(SERVER_URL, params=payload)
        
    def close_tile(self, event):
        # send remove command to server
        payload = {'cmd':'remove', 'name':self.device_name}
        r = requests.get(SERVER_URL, params=payload)

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
        self.close_button = Button(text="x", background_normal = '', background_color=(1,0,0,1), pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(0.1, 0.1), on_press=self.close_setupwindow)
        self.content.add_widget(self.close_button)

        # add drop down list
        self.device_dropdown = DropDown()
        self.content.add_widget(self.device_dropdown)

        # add devices to drop down list
        self.refresh_device_list()

        # add save button
        self.save_button = Button(text="Save", background_normal="", background_color=(0,0,.7,1), on_press=self.save_setup, pos_hint={'x': 0, 'y': 0}, size_hint=(.4, .2))
        self.content.add_widget(self.save_button)

    def refresh_device_list(self, event=0):

        # clear list
        self.device_dropdown.clearwidgets()
        
        # get list of devices in database
        devices = Get_devices()
        
        # add each device in db to drop down list
        for device in devices:
            btn = Button(text=device[0] + " : " + device[1], size_hint=(None, .05))
            btn.bind(on_release=lambda btn: self.device_dropdown.select(btn.text))
            self.device_dropdown.add_widget(widget=btn, index=len(self.device_dropdown.children))

    def close_setupwindow(self, event):
        self.caller.is_setup = False
        self.dismiss()
        
    def toggle_outlet_button(self, event):
        self.outlet_active = not self.outlet_active
        
    def toggle_lightswitch_button(self, event):
        self.lightswitch_active = not self.lightswitch_active
        
    def save_setup(self, event):

        
        
        
        self.caller.device_id = self.id_entry.text
        self.caller.device_name = self.name_entry.text
        self.caller.is_setup = True
        
        # close setup window
        #self.parent.remove_widget(self)
        self.dismiss()

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

    if (Server_request(payload)):
        App().run()
    else:
        print("ERROR: could not connect to server")
        return
 
if (__name__ == "__main__"):
    main(sys.argv)
