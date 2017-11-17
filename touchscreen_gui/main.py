#!/usr/bin/env python

import time

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

TIME_FORMAT = "%A %m-%d %I:%M %p"

class ThermTab(TabbedPanelItem):
    def __init__(self,**kwargs):
        super(ThermTab,self).__init__(**kwargs)
        
        self.text="Thermostat"
        self.content = FloatLayout()
        
        #self.myclock = MyClock()
        #self.content.add_widget(self.myclock)
        
        self.timelabel = Label(text=time.strftime(TIME_FORMAT), font_size=48, size_hint=(0.5, 0.2), pos_hint={'x': 0.1, 'y': 0.8})
        Clock.schedule_interval(self.update_timelabel, 3)
        
        self.content.add_widget(self.timelabel)

        self.curr_temp = NumericProperty(70)
        self.set_temp = NumericProperty(70)
        
        self.curr_temp_label = Label(text="Current: 70 F", font_size=36, size_hint=(0.5, 0.1), pos_hint={'x': 0.1, 'y': 0.6})
        self.content.add_widget(self.curr_temp_label)
        
        Clock.schedule_interval(self.update_therm, 3)
        
        self.set_temp_label = Label(text="Set: 70 F", font_size=36, size_hint=(0.5, 0.1), pos_hint={'x': 0.1, 'y': 0.5})
        self.content.add_widget(self.set_temp_label)
        
        self.increase_temp_button = Button(text="+", font_size=36, size_hint=(0.1, 0.1), pos_hint={'x': 0.5, 'y': 0.5}, on_press=self.increase_temp)
        self.content.add_widget(self.increase_temp_button)
        self.decrease_temp_button = Button(text="-", font_size=36, size_hint=(0.1, 0.1), pos_hint={'x': 0.5, 'y': 0.4}, on_press=self.decrease_temp)
        self.content.add_widget(self.decrease_temp_button)
        
    def update_timelabel(self, event):
        self.timelabel.text = time.strftime(TIME_FORMAT)

    def update_therm(self, event):
        pass

    def decrease_temp(self, event):
        if (self.set_temp > 32):
            self.set_temp -= 1
            self.set_temp_label.text = str(self.set_temp)

    def increase_temp(self, event):
        if (self.set_temp < 100):
            self.set_temp += 1
            self.set_temp_label.text = str(self.set_temp)
        
class DeviceTab(TabbedPanelItem):
    def __init__(self,**kwargs):
        super(DeviceTab,self).__init__(**kwargs)
        
        self.text="Devices"
        self.content = GridLayout(cols=3, rows=5)
        
        self.add_button = Button(text="+", font_size=24, on_press=self.add_device, size_hint=(0.1, 0.1), pos_hint={'x': 0.9, 'y': 0.9})
        self.content.add_widget(self.add_button)
        
    def add_device(self, event):
        self.content.remove_widget(self.add_button)
        self.content.add_widget(DeviceTile())
        self.content.add_widget(self.add_button)
        
class DeviceTile(FloatLayout):
    def __init__(self,**kwargs):
        super(DeviceTile,self).__init__(**kwargs)
        
        self.setup_window = DeviceSetupWindow(self, size_hint=(0.75 , 0.75), pos_hit={'x_center': 0.5, 'y_center': 0.5}, on_dismiss=self.setup_tile, title="Device Setup", )
        self.is_setup = BooleanProperty(False)
        self.device_name = StringProperty("null")
        self.device_id = StringProperty("null")
        self.device_type = StringProperty("null")
        
        self.setup_window.open()
        #self.add_widget(self.setup_window)
        
    def setup_tile(self, event):
        print("in setup_tile")
        
        if(not self.is_setup):
            print("tile is not setup")
            self.parent.remove_widget(self)
            return
        
        self.label = Label(text=self.device_name, size_hint=(0.25, 0.25), pos_hint={'center_x': 0.5, 'center_y': 0.6})
        self.add_widget(self.label)
        
        self.switch = Switch(on_press=self.toggle, active=False, size_hint=(1, 1), pos_hint={'center_x': 0.5, 'center_y': 0.5})
        self.add_widget(self.switch)
        
        self.close_button = Button(background_normal = '', background_color=(1,0,0,1), text="x", pos_hint={'x': 0.9, 'y': 0.9}, size_hint=(.1, .1), on_press=self.close_tile)
        self.add_widget(self.close_button)

    def toggle(self, event):
        pass
        
    def close_tile(self, event):
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
        self.outlet_button = ToggleButton(text="Outlet", group="type", on_press=self.toggle_outlet_button, pos_hint={'x': 0, 'y': .8}, size_hint=(.2, .2))
        self.outlet_active = False
        self.content.add_widget(self.outlet_button)
        self.lightswitch_button = ToggleButton(text="LightSwitch", group="type", on_press=self.toggle_lightswitch_button, pos_hint={'x': .2, 'y': .8}, size_hint=(0.2, 0.2))
        self.lightswitch_active = False
        self.content.add_widget(self.lightswitch_button)
        
        # add entry boxes for device ID and Name
        self.id_entry = TextInput(text="Device ID", pos_hint={'x': 0, 'y': .5}, size_hint=(.8, .1))
        self.content.add_widget(self.id_entry)
        self.name_entry = TextInput(text="Name", pos_hint={'x': 0, 'y': .3}, size_hint=(.8, .1))
        self.content.add_widget(self.name_entry)
        
        # add save button
        self.save_button = Button(text="Save", on_press=self.save_setup, pos_hint={'x': 0, 'y': 0}, size_hint=(.4, .1))
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
        
        print("closing setup window")
        
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

if __name__ == '__main__':
    TestApp().run()
