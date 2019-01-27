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


class PhilipsBulbPlugin:

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
            "_Options": None
        },
        {
            "_Name": "PhilipsBulb_Color_Temperature", 
            "_Unit": __UNIT_COLOR_TEMPERATURE, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / Dimmer
            "_Switchtype": 7,
            "_Options": None
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
            "map_level_value": {'10': 1, '20': 2, '30': 3, '40': 4}
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

        if (Parameters["Mode1"] == 'ptvsd'):
            Domoticz.Log("Debugger ptvsd started, use 0.0.0.0:5678 to attach")
            import ptvsd
            # signal error on raspberry
            ptvsd.enable_attach()
            ptvsd.wait_for_attach()
        elif (Parameters["Mode1"] == 'rpdb'):
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

        # # Add main devices
        # if (self.__UNIT_BRIGHTNESS not in Devices):
        #     # Selector Switch / Dimmer
        #     # See https://github.com/domoticz/domoticz/blob/development/hardware/hardwaretypes.h for device types
        #     Domoticz.Device(
        #         Name = "PhilipsBulb_Brightness", 
        #         Unit = self.__UNIT_BRIGHTNESS, 
        #         # Type = 241, 
        #         # Subtype = 8,
        #         TypeName = "Selector Switch", 
        #         Switchtype = 7).Create()

        # if (self.__UNIT_COLOR_TEMPERATURE not in Devices):
        #     # Selector Switch / Dimmer
        #     # See https://github.com/domoticz/domoticz/blob/development/hardware/hardwaretypes.h for device types
        #     Domoticz.Device(
        #         Name = "PhilipsBulb_Color_Temperature", 
        #         Unit = self.__UNIT_COLOR_TEMPERATURE, 
        #         # Type = 241, 
        #         # Subtype = 8,
        #         TypeName = "Selector Switch", 
        #         Switchtype = 7).Create()

        # # Add scene device
        # Options =   {    
        #     "LevelActions"  :"|||||" , 
        #     "LevelNames"    :"None|Bright|TV|Warm|Night" ,
        #     "LevelOffHidden":"true",
        #     "SelectorStyle" :"0"
        # }
        # if (self.__UNIT_SCENE not in Devices):
        #     # Selector Switch / Selector
        #     Domoticz.Device(
        #         Name = "PhilipsBulb_Scene", 
        #         Unit = self.__UNIT_SCENE, 
        #         TypeName = "Selector Switch", 
        #         Switchtype = 18, 
        #         Options = Options).Create()

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

        if (self.__UNIT_BRIGHTNESS == Unit):
            if ("On" == Command):
                self.TurnOn()
            elif ("Off" == Command):
                self.TurnOff()
            else :
                self.ChangeBrightness(Level,Level)
        elif (self.__UNIT_COLOR_TEMPERATURE == Unit):
            if ("On" == Command):
                self.TurnOn()
            elif ("Off" == Command):
                self.TurnOff()
            else :
                self.ChangeColorTemperature(Level,Level)
        elif (self.__UNIT_SCENE == Unit):
            value = GetValueByLevel(self.__UNITS, self.__UNIT_SCENE, str(Level))
            self.ChangeScene(value, Level)
        else:
            Domoticz.Error("Unknown Unit number : " + str(Unit))

        # update status
        self.UpdateStatus()
        return

    def TurnOn(self):
        if (self.status.is_on == False):
            result = self.miio.on()
            Domoticz.Log("Turn on result:" + str(result))
            if (result == ["ok"] or result == []):
                self.status.is_on = True
                UpdateDevice(self.__UNIT_BRIGHTNESS, 1, "On")
                UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 1, "On")
            else:
                Domoticz.Log("Turn on failure:" + str(result))
        return

    def TurnOff(self):
        if (self.status.is_on == True):
            result = self.miio.off()
            Domoticz.Log("Turn off result:" + str(result))
            if (result == ["ok"] or result == []):
                self.status.is_on = False
                UpdateDevice(self.__UNIT_BRIGHTNESS, 0, "Off")
                UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 0, "Off")
            else:
                Domoticz.Log("Turn off failure:" + str(result))
        return

    def ChangeBrightness(self, brightness, level):
        result = self.miio.set_brightness(brightness)
        Domoticz.Log("Set brightness result:" + str(result))
        if (result == ["ok"] or result == []):
            self.status.brightness = brightness
            UpdateDevice(self.__UNIT_BRIGHTNESS, 2, level)
        else:
            Domoticz.Log("Set brightness failure:" + str(result))
        return
        
    def ChangeColorTemperature(self, color_temperature, level):
        result = self.miio.set_color_temperature(color_temperature)
        Domoticz.Log("Set color temperature result:" + str(result))
        if (result == ["ok"] or result == []):
            self.status.color_temperature = color_temperature
            UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 2, level)
        else:
            Domoticz.Log("Set color temperature failure:" + str(result))
        return

    def ChangeScene(self, scene, level):
        result = self.miio.set_scene(scene)
        Domoticz.Log("Set scene result:" + str(result))
        if (result == ["ok"] or result == []):
            self.status.scene = scene
            UpdateDevice(self.__UNIT_SCENE, 2, level)
        else:
            Domoticz.Log("Set scene failure:" + str(result))
        return

    def UpdateStatus(self):
        if not hasattr(self, 'miio'):
            return
        self.status = self.miio.status()
        Domoticz.Debug("Status : On = " + str(self.status.is_on) + \
                              ", Brightness = " + str(self.status.brightness) + \
                              ", ColorTemp = " + str(self.status.color_temperature) + \
                              ", DelayOff = " + str(self.status.delay_off_countdown) + \
                              ", Power = " + str(self.status.power) + \
                              ", Scene = " + str(self.status.scene))

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
        level = self.status.brightness
        UpdateDevice(self.__UNIT_BRIGHTNESS, 2, level)

        level = self.status.color_temperature
        UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 2, level)

        if (self.status.scene != 0):
            level = GetLevelByValue(self.__UNITS, self.__UNIT_SCENE, self.status.scene)
            UpdateDevice(self.__UNIT_SCENE, 2, level)

        # Last
        # set device off if need
        # change image and title
        if (self.status.is_on == False):
            UpdateDevice(self.__UNIT_BRIGHTNESS, 0, "Off")
            UpdateDevice(self.__UNIT_COLOR_TEMPERATURE, 0, "Off")
            UpdateDevice(self.__UNIT_SCENE, 0, "Off")

        self.status = CacheStatus(self.status)
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
