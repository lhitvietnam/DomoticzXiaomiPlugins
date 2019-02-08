# coding=UTF-8
# Python Plugin for Xiaomi Miio Plug
#
# Author: xiaoyao9184 
#
"""
<plugin 
    key="Xiaomi-Miio-PowerStrip" 
    name="Xiaomi Miio PowerStrip" 
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
        <param field="Mode4" label="Mode" width="150px">
            <options>
                <option label="qmi.powerstrip.v1" value="qmi.powerstrip.v1" default="qmi.powerstrip.v1"/>
                <option label="zimi.powerstrip.v2" value="zimi.powerstrip.v2"/>
            </options>
        </param>
        <param field="Mode5" label="Unit Price" width="50px"/>
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
import time


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


class PowerStripPlugin:

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

    def MapStatusToWattText(self, unit, status):
        # https://www.domoticz.com/forum/viewtopic.php?t=21978
        # https://www.domoticz.com/wiki/Domoticz_API/JSON_URL%27s#Electricity_.28instant_and_counter.29
        avg = (self.lastWatt + status) / 2
        second = int(time.time()) - self.lastTime

        self.lastWatt = status
        self.lastTime = int(time.time())
        self.lastCount = self.lastCount + (avg / 1000) * (second / 60 / 60)
        return str(status) + ";" + "{:.9f}".format(self.lastCount)

    __UNIT_POWER = 1
    __UNIT_TEMPERATURE = 2
    __UNIT_ELECTRIC = 3
    __UNIT_VLOTAGE = 4
    __UNIT_POWER_FACTOR = 5
    __UNIT_POWER_PRICE = 6
    __UNIT_CURRENT = 7
    __UNIT_LEAKAGE_CURRENT = 8
    __UNIT_MODE = 9
    # __UNIT_REALTIME_POWER = 10
    __UNIT_LED = 11
    
    __UNITS = [
        {
            "_Name": "PowerStrip_Power", 
            "_Unit": __UNIT_POWER, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Options": None,
            "_Image": 1,
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
            "_Name": "PowerStrip_Temperature", 
            "_Unit": __UNIT_TEMPERATURE, 
            "_TypeName": "Temperature",
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "temperature"
        },
        {
            "_Name": "PowerStrip_Electric", 
            "_Unit": __UNIT_ELECTRIC, 
            "_TypeName": "kWh",
            # General / kWh
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "load_power",
            "mapStatus": MapStatus,
            "map_status_value": 0, 
            "map_status_text": MapStatusToWattText,
        },
        {
            "_Name": "PowerStrip_Voltage", 
            "_Unit": __UNIT_VLOTAGE, 
            "_TypeName": "Voltage",
            # General / Voltage
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "voltage",
            "mapStatus": MapStatus,
            "map_status_value": 0, 
            "map_status_text": None, 
        },
        {
            "_Name": "PowerStrip_Power_Factor", 
            "_Unit": __UNIT_POWER_FACTOR, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "0;"
            },
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "power_factor",
        },
        {
            "_Name": "PowerStrip_Power_Price", 
            "_Unit": __UNIT_POWER_PRICE, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "0;"
            },
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "power_price",
        },
        {
            "_Name": "PowerStrip_Current", 
            "_Unit": __UNIT_CURRENT, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "0;"
            },
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "current",
        },
        {
            "_Name": "PowerStrip_Leakage_Current", 
            "_Unit": __UNIT_LEAKAGE_CURRENT, 
            "_TypeName": "Custom",
            "_Options": {
                "Custom": "0;"
            },
            "_Switchtype": None,
            "_Options": None,
            "_Image": None,
            "bindingStatusField": "leakage_current",
        },
        {
            "_Name": "PowerStrip_Mode", 
            "_Unit": __UNIT_MODE, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Options": None,
            "_Image": 9,
            "bindingStatusField": "mode",
            "mapStatus": MapEnumStatus,
            "map_status_value": { miio.powerstrip.PowerMode.Eco: 1, miio.powerstrip.PowerMode.Normal: 0 }, 
            "map_status_text": { miio.powerstrip.PowerMode.Eco: "On", miio.powerstrip.PowerMode.Normal: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "set_power_mode",
            "map_command_method_param": { "On": miio.powerstrip.PowerMode.Eco, "Off": miio.powerstrip.PowerMode.Normal }
        },
        # I don't know which state is related to set_realtime_power.
        # {
        #     "_Name": "PowerStrip_Realtime_Power", 
        #     "_Unit": __UNIT_REALTIME_POWER, 
        #     "_TypeName": "Selector Switch", 
        #     # Selector Switch / On/Off
        #     "_Switchtype": 0,
        #     "_Options": None,
        #     "_Image": 0,
        #     "bindingStatusField": "?",
        #     "mapStatus": MapEnumStatus,
        #     "map_status_value": { True: 1, False: 0 }, 
        #     "map_status_text": { True: "On", False: "Off" },
        #     "mapCommand": MapEnumCommandToMethodParam,
        #     "map_command_status": { "On": True, "Off": False },
        #     "map_command_method": "miio.set_realtime_power",
        #     "map_command_method_param": { "On": True, "Off": False }
        # },
        {
            "_Name": "PowerStrip_LED", 
            "_Unit": __UNIT_LED, 
            "_TypeName": "Selector Switch", 
            # Selector Switch / On/Off
            "_Switchtype": 0,
            "_Options": None,
            "_Image": 0,
            "bindingStatusField": "wifi_led",
            "mapStatus": MapEnumStatus,
            "map_status_value": { True: 1, False: 0 }, 
            "map_status_text": { True: "On", False: "Off" },
            "mapCommand": MapEnumCommandToMethodParam,
            "map_command_status": { "On": True, "Off": False },
            "map_command_method": "miio.set_wifi_led",
            "map_command_method_param": { "On": True, "Off": False }
        }
    ]

    def __init__(self):
        self.miio = None
        self.status = None
        self.lastWatt = 0
        self.lastCount = 0
        self.lastTime = int(time.time())
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
            Domoticz.Log("Debugger rpdb started, use 'telnet 0.0.0.0 4444' to connect")
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
        mode = Parameters["Mode4"]
        price = Parameters["Mode5"]
        self.miio = miio.powerstrip.PowerStrip(ip, token, 0, debug, True, mode)
        Domoticz.Debug("Xiaomi Miio PowerStrip created with address '" + ip
            + "' and token '" + token
            + "' and mode '" + mode + "'")

        if (price != ''):
            self.miio.set_power_price(int(price))

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
            status = unit["mapCommand"](self, unit, Command, Level)
            if status != None:
                # Update device
                field = unit["bindingStatusField"]
                setattr(self.status, field, status)
                vt = unit["mapStatus"](self, unit, status)
                UpdateDevice(unit["_Unit"], vt["value"], vt["text"])
            return
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
                    UpdateDevice(unit["_Unit"], status, str(status))
        return


global _plugin
_plugin = PowerStripPlugin()

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
