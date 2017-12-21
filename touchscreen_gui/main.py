#!/usr/bin/env python

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

SERVER_URL = "http://localhost:5000/"
TIME_FORMAT = "%A %m-%d %I:%M %p"

class ThermTab(TabbedPanelItem):
    def __init__(self,**kwargs):
        super(ThermTab,self).__init__(**kwargs)
        
        self.text="Thermostat"
        self.content = FloatLayout(background_normal="test.jpeg")
        #background_normal = '', background_color=(1,0,0,1)
        
        #self.myclock = MyClock()
        #self.content.add_widget(self.myclock)
        
        self.timelabel = Label(text=time.strftime(TIME_FORMAT), font_size=72, size_hint=(0.5, 0.2), pos_hint={'center_x': 0.5, 'center_y': 0.8})
        Clock.schedule_interval(self.update_timelabel, 3)
        
        self.content.add_widget(self.timelabel)
        
        self.curr_temp = 70
        self.set_temp = 70
        
        self.curr_temp_label = Label(text="Current: 70 F", font_size=42, size_hint=(0.5, 0.1), pos_hint={'center_x': 0.45, 'center_y': 0.6}, text_size=(350, None))
        self.content.add_widget(self.curr_temp_label)
                
        self.set_temp_label = Label(text= "Set: 70 F", font_size=42, size_hint=(0.5, 0.1), pos_hint={'center_x': 0.45, 'center_y': 0.5}, text_size=(350, None))
        self.content.add_widget(self.set_temp_label)
        
        self.increase_temp_button = Button(text="+", font_size=48, size_hint=(0.1, 0.1), pos_hint={'center_x': 0.6, 'center_y': 0.55}, on_release=self.increase_temp)
        self.content.add_widget(self.increase_temp_button)
        self.decrease_temp_button = Button(text="-", font_size=48, size_hint=(0.1, 0.1), pos_hint={'center_x': 0.6, 'center_y': 0.45}, on_release=self.decrease_temp)
        self.content.add_widget(self.decrease_temp_button)

        self.current_mode_label = Label(text="Mode: Heat", font_size=26, size_hint=(0.5, 0.1), pos_hint={'center_x': 0.45, 'center_y': 0.4}, text_size=(350, None))
        self.content.add_widget(self.current_mode_label)
        
        self.heat_mode_button = Button(text="Heat", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.35, 'center_y': 0.2}, on_release=self.set_heat_mode)
        self.content.add_widget(self.heat_mode_button)
        self.cool_mode_button = Button(text="Cool", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.45, 'center_y': 0.2}, on_release=self.set_cool_mode)
        self.content.add_widget(self.cool_mode_button)
        self.auto_mode_button = Button(text="Auto", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.55, 'center_y': 0.2}, on_release=self.set_auto_mode)
        self.content.add_widget(self.auto_mode_button)
        self.off_mode_button = Button(text="Off", size_hint=(0.1, 0.1), pos_hint={'center_x': 0.65, 'center_y': 0.2}, on_release=self.set_off_mode)
        self.content.add_widget(self.off_mode_button)

        Clock.schedule_interval(self.update_therm, 3)
        
    def update_timelabel(self, event):
        self.timelabel.text = time.strftime(TIME_FORMAT)

    def update_therm(self, event):
        pass

    def decrease_temp(self, event):
        if (self.set_temp > 32):
            self.set_temp -= 1
            self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"

    def increase_temp(self, event):
        if (self.set_temp < 100):
            self.set_temp += 1
            self.set_temp_label.text = "Set: " + str(self.set_temp) + " F"

    def set_heat_mode(self, event):
        self.current_mode_label.text = "Mode: Heat"

    def set_cool_mode(self, event):
        self.current_mode_label.text = "Mode: Cool"

    def set_auto_mode(self, event):
        self.current_mode_label.text = "Mode: Auto"
        
    def set_off_mode(self, event):
        self.current_mode_label.text = "Mode: Off"
        
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
        #self.content.remove_widget(self.add_button)
        self.gridlayout.add_widget(DeviceTile())
        #self.content.add_widget(self.add_button)
        
class DeviceTile(FloatLayout):
    def __init__(self,**kwargs):
        super(DeviceTile,self).__init__(**kwargs)
        
        self.setup_window = DeviceSetupWindow(self, size_hint=(0.5 , 0.5), pos_hit={'x_center': 0.5, 'y_center': 0.5}, on_dismiss=self.setup_tile, title="Device Setup", auto_dismiss=False)
        self.is_setup = BooleanProperty(False)
        self.device_name = StringProperty("null")
        self.device_id = StringProperty("null")
        self.device_type = StringProperty("null")
        
        self.setup_window.open()
        #self.add_widget(self.setup_window)
        
    def setup_tile(self, event):
        if(not self.is_setup):
            self.parent.remove_widget(self)
            return
        
        self.label = Label(text=self.device_name, font_size=36, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.65})
        self.add_widget(self.label)
        
        self.switch = Switch(on_press=self.toggle, active=False, size_hint=(0.5, 0.5), pos_hint={'center_x': 0.5, 'center_y': 0.5})
        self.add_widget(self.switch)
        
        self.close_button = Button(background_normal = '', background_color=(1,0,0,1), text="x", font_size=26, pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(.1, .1), on_press=self.close_tile)
        self.add_widget(self.close_button)
        
        payload = {'cmd':'add', 'id': self.device_id, 'name': self.device_name, 'type': self.device_type}
        r = requests.get(SERVER_URL, params=payload)
        
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
        
        # add buttons for choosing device type
        self.outlet_button = ToggleButton(text="Outlet", group="type", on_press=self.toggle_outlet_button, pos_hint={'x': 0, 'y': .75}, size_hint=(.3, .25))
        self.outlet_active = False
        self.content.add_widget(self.outlet_button)
        self.lightswitch_button = ToggleButton(text="Lightswitch", group="type", on_press=self.toggle_lightswitch_button, pos_hint={'x': .3, 'y': .75}, size_hint=(0.3, 0.25))
        self.lightswitch_active = False
        self.content.add_widget(self.lightswitch_button)
        
        # add entry boxes for device ID and Name
        self.id_entry = TextInput(hint_text="Device ID", pos_hint={'x': 0, 'y': .5}, size_hint=(.6, .15), )
        self.content.add_widget(self.id_entry)
        self.name_entry = TextInput(hint_text="Name", pos_hint={'x': 0, 'y': .3}, size_hint=(.6, .15))
        self.content.add_widget(self.name_entry)
        
        # add save button
        self.save_button = Button(text="Save", background_normal="", background_color=(0,0,.7,1), on_press=self.save_setup, pos_hint={'x': 0, 'y': 0}, size_hint=(.4, .2))
        self.content.add_widget(self.save_button)
        
    def close_setupwindow(self, event):
        self.caller.is_setup = False
        self.dismiss()
        
    def toggle_outlet_button(self, event):
        self.outlet_active = not self.outlet_active
        
    def toggle_lightswitch_button(self, event):
        self.lightswitch_active = not self.lightswitch_active
        
    def save_setup(self, event):
        if(self.outlet_active):
            self.caller.device_type = "outlet"
        elif(self.lightswitch_active):
            self.caller.device_type = "lightswitch"
        else:
            return
        
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

class TestApp(App):
    
    title = "Control Panel"
    
    def build(self):
        return MainWindow()

def main(args):
    # test connection to server
    payload = {'cmd':'test'}
    r = requests.get(SERVER_URL, params=payload)
    
    if (r.text != "OK"):
        print("ERROR: could not connect to server")
        return
    
    TestApp().run()
    
if (__name__ == "__main__"):
    main(sys.argv)
