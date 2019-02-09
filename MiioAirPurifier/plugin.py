# coding=UTF-8
# Python Plugin for Xiaomi Miio AirPurifier
#
# Author: xiaoyao9184 
#
"""
<plugin 
    key="Xiaomi-Miio-AirPurifier" 
    name="Xiaomi Miio AirPurifier" 
    author="xiaoyao9184" 
    version="0.1" 
    externallink="https://github.com/xiaoyao9184/DomoticzXiaomiPlugins">
    <params>
        <param field="Mode1" label="Debug" width="200px">
            <options>
                <option label="None" value="none" default="none"/>
                <option label="Debug(Only Domoticz)" value="debug"/>
                <option label="Debug(Attach by ptvsd)" value="ptvsd"/>
                <option label="Debug(Attach by rpdb)" value="rpdb"/>
            </options>
        </param>
        <param field="Mode2" label="Repeat Time(s)" width="30px" required="true" default="30"/>
        <param field="Address" label="IP" width="100px" required="true"/>
        <param field="Mode3" label="Token" width="250px" required="true"/>
    </params>
</plugin>
"""

# Fix import of libs installed with pip as PluginSystem has a wierd pythonpath...
import os
import sys
import site
for mp in site.getsitepackages():
    sys.path.append(mp)

import Domoticz
import miio
import functools


class Heartbeat():

    def __init__(self, interval):
        self.callback = None
        self.count = 0
        # stage interval
        self.seek = 0
        self.interval = 10
        # real interval
        self.total = 10
        if (interval < 0):
            pass
        elif (0 < interval and interval < 30):
            self.interval = interval
            self.total = interval
        else:
            result = self.show_factor(interval, self.filter_factor, self.bast_factor)
            self.seek = result["repeat"]
            self.interval = result["factor"]
            self.total = result["number"]

    def setHeartbeat(self, func_callback):
        Domoticz.Heartbeat(self.interval)
        Domoticz.Log("Heartbeat total interval set to: " + str(self.total) + ".")
        self.callback = func_callback
            
    def beatHeartbeat(self):
        self.count += 1
        if (self.count >= self.seek):
            self.count = 0
            if self.callback is not None:
                Domoticz.Log("Calling heartbeat handler " + str(self.callback.__name__) + ".")
                self.callback()
        else:
            Domoticz.Log("Skip heartbeat handler bacause stage not enough " + str(self.count) + "/" + str(self.seek) + ".")

    def filter_factor(self, factor):
        return factor < 30 and factor > 5

    def show_factor(self, number, func_filter, func_prime):
        factor = number // 2
        while factor > 1:
            if number % factor == 0 and func_filter(factor):
                return {
                    "number": number,
                    "factor": factor,
                    "repeat": int(number / factor)
                }
            factor-=1
        else:
            return func_prime(number)

    def next_factor(self, number):
        return self.show_factor(number + 1, self.filter_factor, self.next_factor)

    def last_factor(self, number):
        return self.show_factor(number - 1, self.filter_factor, self.last_factor)

    def bast_factor(self, number):
        n = self.next_factor(number)
        l = self.last_factor(number)

        if n["factor"] >= l["factor"]:
            return n
        else:
            return l


class CacheStatus(object):
    def __init__(self, status):
      self.status = status
      self.cache = {}

    def __getattr__(self, name):
        if name not in self.cache:
            value = getattr(self.status, name)
            if value is not None:
                self.cache[name] = value
            else:
                return None
        return self.cache[name]

    def __setattr__(self, name, value):
        if(name == 'status' or name == 'cache'):
            super(CacheStatus, self).__setattr__(name, value)
            return
        self.cache[name] = value

    def toString(self):
        l = []
        for attr in dir(self.status):
            if(attr[:2] != "__" and attr != 'data'):
                value = getattr(self.status, attr)
                l.append(str(attr + ' = ' + str(value)) )
        return ', '.join(l)


class AirPurifierPlugin:

    def MapEnumStatus(self, unit, status):
        value = None
        text = None
        if "map_status_value" in unit.keys():
            value = unit["map_status_value"][status]
        else:
            value = status

        if "map_status_text" in unit.keys():
            text = unit["map_status_text"][status]
        else:
            text = status

        return {
            "value": value,
            "text": text
        }

    def MapStatus(self, unit, status):
        value = None
        text = None
        if "map_status_value" in unit.keys():
            mapStatusValue = unit["map_status_value"]
            if mapStatusValue == None:
                value = status
            elif type(mapStatusValue) is int:
                value = mapStatusValue
            else:
                value = mapStatusValue(self, unit, status)
        else:
            value = status

        if "map_status_text" in unit.keys():
            mapStatusText = unit["map_status_text"]
            if mapStatusText == None:
                text = str(status)
            elif type(mapStatusText) is str:
                text = mapStatusText
            elif type(mapStatusText) is dict:
                text = unit["map_status_text"][status]
            else:
                text = mapStatusText(self, unit, status)
        else:
            text = status

        return {
            "value": value,
            "text": text
        }

    def MapEnumCommandToMethod(self, unit, command, level):
        field = unit["bindingStatusField"]
        status_old = getattr(self.status, field)
        status_new = unit["map_command_status"][command]

        if status_old == status_new:
            Domoticz.Log("The command is consistent with the status:" + str(command))
            return None

        method = unit["map_command_method"][command]
        method = rgetattr(self, method)
        result = method()

        Domoticz.Log("Method call result:" + str(result))
        if (result == ["ok"] or result == [] or int(result) == 0):
            return status_new

        return None

    def MapEnumCommandToMethodParam(self, unit, command, level):
        field = unit["bindingStatusField"]
        status_old = getattr(self.status, field)
        status_new = unit["map_command_status"][command]

        if status_old == status_new:
            Domoticz.Log("The command is consistent with the status:" + str(command))
            return None

        method = unit["map_command_method"]
        method = rgetattr(self, method)
        param = unit["map_command_method_param"][command]

        result = method(param)
        Domoticz.Log("Method call result:" + str(result))
        if (result == ["ok"] or result == [] or int(result) == 0):
            return status_new

        return

    def MapEnumLevelToMethodParam(self, unit, command, level):
        field = unit["bindingStatusField"]
        status_old = getattr(self.status, field)
        status_new = unit["map_level_status"][level]

        if status_old == status_new:
            Domoticz.Log("The level is consistent with the status:" + str(command))
            return None

        method = unit["map_level_method"]
        method = rgetattr(self, method)
        param = unit["map_level_param"][level]
        
        result = method(param)
        Domoticz.Log("Method call result:" + str(result))
        if (result == ["ok"] or result == [] or int(result) == 0):
            return status_new

        return None

    def MapLevelToMethodParam(self, unit, command, level):
        field = unit["bindingStatusField"]
        status_old = getattr(self.status, field)
        status_new = level

        mapLevelStatus = unit["map_level_status"]
        if mapLevelStatus != None:
            status_new = mapLevelStatus(self, unit, level)
            if status_new == status_old:
                Domoticz.Log("The command is consistent with the status:" + str(command))
                return None

        method = unit["map_level_method"]
        method = rgetattr(self, method)
        param = level
        mapLevelParam = unit["map_level_param"]
        if mapLevelParam != None:
            param = mapLevelParam(self, unit, level)

        result = method(param)
        Domoticz.Log("Method call result:" + str(result))
        if (result == ["ok"] or result == [] or int(result) == 0):
            return status_new

        return None

    # fix humidity
    def MapTextHumidity(value):
        sValue = 0
        n = int(value)
        if n < 46:
            sValue = 2        #dry
        elif n > 70:
            sValue = 3        #wet
        else:
            sValue = 1        #comfortable
        return sValue

    __UNIT_AQI = 1
    __UNIT_AVG_AQI = 2
    __UNIT_FILTER_HOURS_USED = 3
    __UNIT_FILTER_LIFE_REMAINING = 4
    __UNIT_HUMIDITY = 5
    __UNIT_ILLUMINANCE = 6
    __UNIT_MOTOR_SPEED = 7
    __UNIT_MOTOR2_SPEED = 8
    __UNIT_PURIFY_VOLUME = 9
    __UNIT_SLEEP_MODE_LEARN_COUNT = 10
    __UNIT_SLEEP_TIME = 11
    __UNIT_TEMPERATURE = 12
    __UNIT_USED_TIME = 13

    __UNIT_POWER = 20
    __UNIT_RESET_FILTER = 21
    __UNIT_AUTO_DETECT = 22
    __UNIT_AUTO_DETECT = 23
    __UNIT_BUZZER = 24
    __UNIT_CHILD_LOCK = 25
    __UNIT_EXTRA_FEATURES = 26
    __UNIT_FAVORITE_LEVEL = 27
    __UNIT_LEARN_MODE = 28
    __UNIT_LED = 29
    __UNIT_BRIGHTNESS = 30
    __UNIT_MODE = 31
    __UNIT_VOLUME = 32
    
    __UNITS = [
        {
            "_Name": "AirPurifier_AQI", 
            "_Unit": __UNIT_AQI, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;μg/m³"
            },
            "bindingStatusField": "aqi",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Average_AQI", 
            "_Unit": __UNIT_AVG_AQI, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;μg/m³"
            }, 
            "bindingStatusField": "average_aqi",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Filter_Hours_Used", 
            "_Unit": __UNIT_FILTER_HOURS_USED, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;h"
            }, 
            "bindingStatusField": "filter_hours_used",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_filter_life_remaining", 
            "_Unit": __UNIT_FILTER_LIFE_REMAINING, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;h"
            }, 
            "bindingStatusField": "filter_life_remaining",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Humidity", 
            "_Unit": __UNIT_HUMIDITY, 
            "_TypeName": "Humidity",
            "_Options": None,
            "bindingStatusField": "humidity",
            "mapStatus": MapStatus,
            "map_status_value": None, 
            "map_status_text": MapTextHumidity
        },
        {
            "_Name": "AirPurifier_Illuminance", 
            "_Unit": __UNIT_ILLUMINANCE, 
            "_TypeName": "Lux", 
            "_Options": None,
            "bindingStatusField": "illuminance" 
        },
        {
            "_Name": "AirPurifier_Motor_speed", 
            "_Unit": __UNIT_MOTOR_SPEED, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;Speed"
            }, 
            "bindingStatusField": "motor_speed",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Motor2_speed", 
            "_Unit": __UNIT_MOTOR2_SPEED, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;Speed"
            }, 
            "bindingStatusField": "motor2_speed",
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Purify_Volume", 
            "_Unit": __UNIT_PURIFY_VOLUME, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;Speed"
            }, 
            "bindingStatusField": "purify_volume",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Sleep_Mode_Learn_Count", 
            "_Unit": __UNIT_SLEEP_MODE_LEARN_COUNT, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;Count"
            }, 
            "bindingStatusField": "sleep_mode_learn_count",
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Sleep_Time", 
            "_Unit": __UNIT_SLEEP_TIME, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;Count"
            }, 
            "bindingStatusField": "sleep_time",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        {
            "_Name": "AirPurifier_Temperature", 
            "_Unit": __UNIT_TEMPERATURE, 
            "_TypeName": "Temperature",
            "_Options": None,
            "bindingStatusField": "temperature"
        },
        {
            "_Name": "AirPurifier_Use_time", 
            "_Unit": __UNIT_USED_TIME, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "1;Seconds"
            }, 
            "bindingStatusField": "use_time",
            "mapStatus": MapStatus,
            "map_status_value": 1, 
            "map_status_text": None
        },
        # button_pressed
        # filter_rfid_product_id
        # filter_rfid_tag
        # filter_type
        # sleep_mode
        # turbo_mode_supported

        {
            "_Name": "AirPurifier_Power", 
            "_Unit": __UNIT_POWER, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Image": 7,
            "_Options": None,
            "bindingStatusField": "is_on",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethod,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": {
                "On": "miio.on",
                "Off": "miio.off"
            }
        },
        {
            "_Name": "AirPurifier_Reset_Filter", 
            "_Unit": __UNIT_RESET_FILTER, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Push On Button
            "_Switchtype": 9,
            "_Image": None,
            "_Options": None,
            "bindingStatusField": "is_on",
            "mapCommand": MapEnumCommandToMethod,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": {
                "On": "miio.reset_filter"
            },
        },
        {
            "_Name": "AirPurifier_Auto_Detect", 
            "_Unit": __UNIT_AUTO_DETECT, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Image": 9,
            "_Options": None,
            "bindingStatusField": "auto_detect",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "miio.set_auto_detect",
            "map_command_method_param": { "On": True, "Off": False }
        },
        {
            "_Name": "AirPurifier_Buzzer", 
            "_Unit": __UNIT_BUZZER, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Image": 9,
            "_Options": None,
            "bindingStatusField": "buzzer",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "miio.set_buzzer",
            "map_command_method_param": { "On": True, "Off": False }
        },
        {
            "_Name": "AirPurifier_Child_Lock", 
            "_Unit": __UNIT_CHILD_LOCK, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Image": 9,
            "_Options": None,
            "bindingStatusField": "child_lock",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "miio.set_child_lock",
            "map_command_method_param": { "On": True, "Off": False }
        },
        {
            "_Name": "AirPurifier_Extra_Features", 
            "_Unit": __UNIT_EXTRA_FEATURES, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Push On Button
            "_Switchtype": 9,
            "_Image": None,
            "_Options": None,
            "bindingStatusField": "extra_features"
        },
        {
            "_Name": "AirPurifier_Favorite_Level", 
            "_Unit": __UNIT_FAVORITE_LEVEL, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Dimmer
            "_Switchtype": 7,
            "_Image": None,
            "_Options": None,
            "bindingStatusField": "favorite_level",
            "mapStatus": MapStatus,
            "map_status_value": 2, 
            "map_status_text": None,
            "mapCommand": MapLevelToMethodParam,
            "map_level_status": None,
            "map_level_method": "miio.set_favorite_level",
            "map_level_param": None
        },
        {
            "_Name": "AirPurifier_Learn_Mode", 
            "_Unit": __UNIT_LEARN_MODE, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Image": 7,
            "_Options": None,
            "bindingStatusField": "learn_mode",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "miio.set_learn_mode",
            "map_command_method_param": { "On": True, "Off": False }
        },
        {
            "_Name": "AirPurifier_LED", 
            "_Unit": __UNIT_LED,
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Image": None,
            "_Options": None,
            "bindingStatusField": "led",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "miio.set_led",
            "map_command_method_param": { "On": True, "Off": False }
        },
        {
            "_Name": "AirPurifier_Brightness", 
            "_Unit": __UNIT_BRIGHTNESS, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Selector
            "_Switchtype": 18,
            "_Image": 7,
            "_Options": {
                "LevelActions"  :"|||" , 
                "LevelNames"    :"Off|Dim|Bright" ,
                "LevelOffHidden":"false",
                "SelectorStyle" :"0"
            },
            "bindingStatusField": "led_brightness",
            "mapStatus": MapEnumStatus,
            "map_status_value": { miio.airpurifier.LedBrightness.Off: 2, miio.airpurifier.LedBrightness.Dim: 2, miio.airpurifier.LedBrightness.Bright: 2 }, 
            "map_status_text": { miio.airpurifier.LedBrightness.Off: "0", miio.airpurifier.LedBrightness.Dim: "10", miio.airpurifier.LedBrightness.Bright: "20"},
            "mapCommand": MapEnumLevelToMethodParam,
            "map_level_status": { 0: miio.airpurifier.LedBrightness.Off, 10: miio.airpurifier.LedBrightness.Dim, 20: miio.airpurifier.LedBrightness.Bright },
            "map_level_method": "miio.set_led_brightness",
            "map_level_param": { 0: miio.airpurifier.LedBrightness.Off, 10: miio.airpurifier.LedBrightness.Dim, 20: miio.airpurifier.LedBrightness.Bright }
        },
        {
            "_Name": "AirPurifier_Mode", 
            "_Unit": __UNIT_MODE, 
            "_TypeName": "Selector Switch", 
            "_Switchtype": 18,
            "_Image": 7,
            "_Options": {
                "LevelActions"  :"|||||" , 
                "LevelNames"    :"None|Auto|Favorite|High|Idle|Medium|Silent|Strong" ,
                "LevelOffHidden":"true",
                "SelectorStyle" :"0"
            },
            "bindingStatusField": "mode",
            "mapStatus": MapEnumStatus,
            "map_status_value": { 
                miio.airpurifier.OperationMode.Auto: 2, 
                miio.airpurifier.OperationMode.Favorite: 2, 
                miio.airpurifier.OperationMode.High: 2, 
                miio.airpurifier.OperationMode.Idle: 2, 
                miio.airpurifier.OperationMode.Medium: 2, 
                miio.airpurifier.OperationMode.Silent: 2,
                miio.airpurifier.OperationMode.Strong: 2 }, 
            "map_status_text": { 
                miio.airpurifier.OperationMode.Auto: "10", 
                miio.airpurifier.OperationMode.Favorite: "20", 
                miio.airpurifier.OperationMode.High: "30", 
                miio.airpurifier.OperationMode.Idle: "40", 
                miio.airpurifier.OperationMode.Medium: "50", 
                miio.airpurifier.OperationMode.Silent: "60", 
                miio.airpurifier.OperationMode.Strong: "70" },
            "mapCommand": MapEnumLevelToMethodParam,
            "map_level_status": { 
                10: miio.airpurifier.OperationMode.Auto, 
                20: miio.airpurifier.OperationMode.Favorite, 
                30: miio.airpurifier.OperationMode.High, 
                40: miio.airpurifier.OperationMode.Idle, 
                50: miio.airpurifier.OperationMode.Medium, 
                60: miio.airpurifier.OperationMode.Silent, 
                70: miio.airpurifier.OperationMode.Strong },
            "map_level_method": "miio.set_mode",
            "map_level_param": { 
                10: miio.airpurifier.OperationMode.Auto, 
                20: miio.airpurifier.OperationMode.Favorite, 
                30: miio.airpurifier.OperationMode.High, 
                40: miio.airpurifier.OperationMode.Idle, 
                50: miio.airpurifier.OperationMode.Medium, 
                60: miio.airpurifier.OperationMode.Silent, 
                70: miio.airpurifier.OperationMode.Strong }
        },
        {
            "_Name": "AirPurifier_Volume", 
            "_Unit": __UNIT_VOLUME, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Dimmer
            "_Switchtype": 7,
            "_Image": None,
            "_Options": None,
            "bindingStatusField": "volume",
            "mapStatus": MapStatus,
            "map_status_value": 2, 
            "map_status_text": None,
            "mapCommand": MapLevelToMethodParam,
            "map_level_status": None,
            "map_level_method": "miio.set_volume",
            "map_level_param": None
        }
    ]

    def __init__(self):
        self.miio = None
        self.status = None
        return

    def onStart(self):
        # Debug
        debug = 0
        if (Parameters["Mode1"] != "none"):
            Domoticz.Debugging(1)
            debug = 1

        if (Parameters["Mode1"] == "ptvsd"):
            Domoticz.Log("Debugger ptvsd started, use 0.0.0.0:5678 to attach")
            import ptvsd
            # signal error on raspberry
            ptvsd.enable_attach()
            ptvsd.wait_for_attach()
        elif (Parameters["Mode1"] == "rpdb"):
            Domoticz.Log("Debugger rpdb started, use 'telnet 127.0.0.1 4444' on host to connect")
            import rpdb
            rpdb.set_trace()
            # signal error on raspberry
            # rpdb.handle_trap("0.0.0.0", 4444)

        # Heartbeat
        self.heartbeat = Heartbeat(int(Parameters["Mode2"]))
        self.heartbeat.setHeartbeat(self.UpdateStatus)

        # Create miio
        ip = Parameters["Address"]
        token = Parameters["Mode3"]
        self.miio = miio.airpurifier.AirPurifier(ip, token, 0, debug, True)
        Domoticz.Debug("Xiaomi AirPurifier created with address '" + ip
            + "' and token '" + token + "'")

        # Read function
        self.UpdateStatus(False)

        # Create devices
        for unit in self.__UNITS:
            field = unit["bindingStatusField"]
            value = getattr(self.status, field)
            if value is not None and unit["_Unit"] not in Devices:
                if "_Switchtype" in unit and unit["_Switchtype"] != None:
                    Domoticz.Device(
                        Name = unit["_Name"], 
                        Unit = unit["_Unit"],
                        TypeName = unit["_TypeName"], 
                        Switchtype = unit["_Switchtype"],
                        Image = unit["_Image"],
                        Options = unit["_Options"]).Create()
                else:
                    Domoticz.Device(
                        Name = unit["_Name"], 
                        Unit = unit["_Unit"],
                        TypeName = unit["_TypeName"], 
                        Options = unit["_Options"]).Create()

        # Read initial state
        self.UpdateStatus()

        DumpConfigToLog()

        return

    def onStop(self):
        Domoticz.Debug("onStop called")
        return

    def onConnect(self, Connection, Status, Description):
        Domoticz.Debug("onConnect called: Connection=" + str(Connection) + ", Status=" + str(Status) + ", Description=" + str(Description))
        return

    def onMessage(self, Connection, Data):
        Domoticz.Debug("onMessage called: Connection=" + str(Connection) + ", Data=" + str(Data))
        return

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called: Unit=" + str(Unit) + ", Parameter=" + str(Command) + ", Level=" + str(Level))

        unit = FindUnit(self.__UNITS, Unit)
        if unit is not None and "mapCommand" in unit.keys():
            status = unit["mapCommand"](self, Command, Level)
            if status != None:
                # Update device
                field = unit["bindingStatusField"]
                setattr(self.status, field, status)
                vt = unit["mapStatus"](self, unit, status)
                UpdateDevice(unit["_Unit"], vt["value"], vt["text"])
            return
        # TODO Update devices
        # self.UpdateStatus()
        return

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)
        return

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called")
        return

    def onHeartbeat(self):
        self.heartbeat.beatHeartbeat()
        return
        

    def UpdateStatus(self, updateDevice = True):
        if not hasattr(self, "miio"):
            return
        self.status = self.miio.status()
        self.status = CacheStatus(self.status)
        log = "Status : " + self.status.toString()
        Domoticz.Debug(log)

        # Update devices
        if (updateDevice):
            for unit in self.__UNITS:
                field = unit["bindingStatusField"]
                status = getattr(self.status, field)
                if status is None:
                    pass
                elif "mapStatus" in unit.keys():
                    vt = unit["mapStatus"](self, unit, status)
                    UpdateDevice(unit["_Unit"], vt["value"], vt["text"])
                else:
                    UpdateDevice(unit["_Unit"], status, status)
        return


global _plugin
_plugin = AirPurifierPlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Connection, Status, Description):
    global _plugin
    _plugin.onConnect(Connection, Status, Description)

def onMessage(Connection, Data):
    global _plugin
    _plugin.onMessage(Connection, Data)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect(Connection):
    global _plugin
    _plugin.onDisconnect(Connection)

def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Generic helper functions

def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return

def UpdateDevice(Unit, nValue, sValue):
    if (Unit not in Devices): return
    if (Devices[Unit].nValue != nValue) or (Devices[Unit].sValue != sValue):
        Domoticz.Debug("Update '" + Devices[Unit].Name + "' : " + str(nValue) + " - " + str(sValue))
        # Warning: The lastest beta does not completly support python 3.5
        # and for unknown reason crash if Update methode is called whitout explicit parameters
        Devices[Unit].Update(nValue = nValue, sValue = str(sValue))
    return

def FindUnit(Units, unit):
    for item in Units:
        if item["_Unit"] == unit:
            return item
    return None

def rsetattr(obj, attr, val):
    pre, _, post = attr.rpartition('.')
    return setattr(rgetattr(obj, pre) if pre else obj, post, val)

# using wonder's beautiful simplification: https://stackoverflow.com/questions/31174295/getattr-and-setattr-on-nested-objects/31174427?noredirect=1#comment86638618_31174427

def rgetattr(obj, attr, *args):
    def _getattr(obj, attr):
        return getattr(obj, attr, *args)
    return functools.reduce(_getattr, [obj] + attr.split('.'))