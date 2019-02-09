# coding=UTF-8
# Python Plugin for Xiaomi Miio Philips Bulb
#
# Author: Shainny xiaoyao9184
#
"""
<plugin 
    key="Xiaomi-Miio-Philips-Bulb" 
    name="Xiaomi Miio Philips Bulb" 
    author="Shainny&xiaoyao9184" 
    version="0.0.2" 
    wikilink="https://github.com/Shainny/DomoticzXiaomiPlugins">
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


class PhilipsBulbPlugin:

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
            if type(mapStatusValue) is int:
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
    
    def MapEnumCommandToMethodOrLevelToMethodParam(self, unit, command, level):
        # check command in map
        if command in unit["map_command_status"].keys():
            return self.MapEnumCommandToMethod(unit,command,level)
        else:
            return self.MapLevelToMethodParam(unit,command,level)



    __UNIT_BRIGHTNESS = 1
    __UNIT_COLOR_TEMPERATURE = 2
    __UNIT_SCENE = 3

    __UNITS = [
        {
            "_Name": "PhilipsBulb_Brightness", 
            "_Unit": __UNIT_BRIGHTNESS, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Dimmer
            "_Switchtype": 7,
            "_Options": None,
            "bindingStatusField": "brightness",
            "mapStatus": MapStatus,
            "map_status_value": 2, 
            "map_status_text": None,
            "mapCommand": MapEnumCommandToMethodOrLevelToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": {
                "On": "miio.on",
                "Off": "miio.off"
            },
            "map_level_status": None,
            "map_level_method": "miio.set_brightness",
            "map_level_param": None
        },
        {
            "_Name": "PhilipsBulb_Color_Temperature", 
            "_Unit": __UNIT_COLOR_TEMPERATURE, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Dimmer
            "_Switchtype": 7,
            "_Options": None,
            "bindingStatusField": "color_temperature",
            "mapStatus": MapStatus,
            "map_status_value": 2, 
            "map_status_text": None,
            "mapCommand": MapEnumCommandToMethodOrLevelToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": {
                "On": "miio.on",
                "Off": "miio.off"
            },
            "map_level_status": None,
            "map_level_method": "miio.set_color_temperature",
            "map_level_param": None
        },
        {
            "_Name": "PhilipsBulb_Scene", 
            "_Unit": __UNIT_SCENE, 
            "_TypeName": "Selector Switch", 
            "_Switchtype": 18,
            "_Options": {
                "LevelActions"  :"|||||" , 
                "LevelNames"    :"None|Bright|TV|Warm|Night" ,
                "LevelOffHidden":"true",
                "SelectorStyle" :"0"
            },
            "bindingStatusField": "scene",
            "mapStatus": MapStatus,
            "map_status_value": 2, 
            "map_status_text": { 0: "0", 1: "10", 2: "20", 3: "30", 4: "40" },
            "mapCommand": MapEnumLevelToMethodParam,
            "map_level_status": { 10: 1, 20: 2, 30: 3, 40: 4 },
            "map_level_method": "miio.set_scene",
            "map_level_param": { 10: 1, 20: 2, 30: 3, 40: 4 }
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
        self.miio = miio.philips_bulb.PhilipsBulb(ip, token, 0, debug, True)
        Domoticz.Debug("Xiaomi Miio Philips Bulb created with address '" + ip
            + "' and token '" + token + "'")

        # Create devices
        for unit in self.__UNITS:
            if unit["_Unit"] not in Devices:
                Domoticz.Device(
                    Name = unit["_Name"], 
                    Unit = unit["_Unit"],
                    TypeName = unit["_TypeName"], 
                    Switchtype = unit["_Switchtype"],
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

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)
        return

    def onDisconnect(self, Connection):
        Domoticz.Debug("onDisconnect called")
        return

    def onHeartbeat(self):
        self.heartbeat.beatHeartbeat()
        
    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called: Unit=" + str(Unit) + ", Parameter=" + str(Command) + ", Level=" + str(Level))

        unit = FindUnit(self.__UNITS, Unit)
        if unit is not None and "mapCommand" in unit.keys():
            status = unit["mapCommand"](self, unit, Command, Level)
            if status != None:
                if ("On" == Command):
                    UpdateDevice(self.__UNIT_BRIGHTNESS, 1, "On")
                    UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 1, "On")
                    UpdateDevice(self.__UNIT_SCENE, 1, "On")
                elif ("Off" == Command):
                    UpdateDevice(self.__UNIT_BRIGHTNESS, 0, "Off")
                    UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 0, "Off")
                    UpdateDevice(self.__UNIT_SCENE, 0, "Off")
                elif ("Set Level" == Command):
                    # Update device
                    field = unit["bindingStatusField"]
                    setattr(self.status, field, status)
                    vt = unit["mapStatus"](self, unit, status)
                    UpdateDevice(unit["_Unit"], vt["value"], vt["text"])
            return
        return


    def UpdateStatus(self):
        if not hasattr(self, 'miio'):
            return
        self.status = self.miio.status()
        self.status = CacheStatus(self.status)
        log = "Status : " + self.status.toString()
        Domoticz.Debug(log)

        # Shared `On` and `Off` for multiple devices
        # Data push will cause confusion

        # MUSE THIS ORDER
        # on image with level title
        # off image with 'Off' title

        # First 
        # set device on if need
        # change image and title
        if (self.status.is_on == True):
            UpdateDevice(self.__UNIT_BRIGHTNESS, 1, "On")
            UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 1, "On")
            UpdateDevice(self.__UNIT_SCENE, 1, "On")

        # Next
        # set device level
        # change dimmer and title

        # Update devices
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

        # level = self.status.brightness
        # UpdateDevice(self.__UNIT_BRIGHTNESS, 2, level)

        # level = self.status.color_temperature
        # UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 2, level)

        # if (self.status.scene != 0):
        #     level = GetLevelByValue(self.__UNITS, self.__UNIT_SCENE, self.status.scene)
        #     UpdateDevice(self.__UNIT_SCENE, 2, level)

        # Last
        # set device off if need
        # change image and title
        if (self.status.is_on == False):
            UpdateDevice(self.__UNIT_BRIGHTNESS, 0, "Off")
            UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 0, "Off")
            UpdateDevice(self.__UNIT_SCENE, 0, "Off")

        return


global _plugin
_plugin = PhilipsBulbPlugin()

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

def GetValueByLevel(units, unit_id, level, default = 0):
    for unit in units:
        if unit["_Unit"] == unit_id and 'map_level_value' in unit:
            map = unit['map_level_value']
            return map[level]
        elif unit["_Unit"] == unit_id and 'map_value_level' in unit:
            map = unit['map_value_level']
            return list(map.keys())[list(map.values()).index(level)]
    return default
    
def GetLevelByValue(units, unit_id, value, default = 0):
    for unit in units:
        if unit["_Unit"] == unit_id and 'map_value_level' in unit:
            map = unit['map_value_level']
            return map[value]
        elif unit["_Unit"] == unit_id and 'map_level_value' in unit:
            map = unit['map_level_value']
            return list(map.keys())[list(map.values()).index(value)]
    return default
