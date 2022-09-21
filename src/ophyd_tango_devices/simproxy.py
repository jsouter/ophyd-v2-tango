import time
import os
import logging
import asyncio

_sim_sub_count = 0


class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

class _SimDeviceAttribute(dotdict):
    def __init__(self, attr_name):
        self.name = attr_name
        self.value = 0
        self.time = TangoTimestamp()
        self.dim_x = 1
        self.dim_y = 0
    def __repr__(self):
        repr = 'DeviceAttribute['
        for k, v in self.items():
            string = '\n' + k + ' = ' + str(v)
            repr += string
        repr += ']'
        return repr

class _SimEventData(dotdict):
    def __init__(self, attr_name, dev_name, hostname):
        self.attr_name = 'tango://' + hostname + ':10000/' + 'dev_name' + '/' + attr_name.lower()
        self.attr_value = _SimDeviceAttribute(attr_name)
        self.reception_date = TangoTimestamp()
        self.event = 'change'
    def __repr__(self):
        repr = 'EventData['
        for k, v in self.items():
            string = '\n' + k + ' = '
            if type(v) is str:
                string += f"'{v}'"
            else:
                string += str(v)
            repr += string
        repr += ']'
        return repr


class TangoTimestamp:
    def __init__(self):
        thetime = time.time()
        self.tv_sec = int(thetime)
        self.tv_usec = int(round(1e6 * (thetime - int(thetime)), 6))
        self.tv_nsec = 0

    def totime(self):
        return self.tv_sec + 1e-6 * self.tv_usec
    @property
    def time(self):
        return time.time()
    def __repr__(self):
        return f"TimeVal(tv_nsec: {self.tv_nsec}, tv_sec: {self.tv_sec}, tv_usec: {self.tv_usec})"


# import asyncio
async def SimProxy(name):
    return _SimProxyClass(name)


class _SimProxyClass:
    def __init__(self, name):
        if name != "mock/device/name":
            raise ValueError("SimProxy must be instantiated with 'mock/device/name'")
        self._name = name
        self._attributes = ['Position', 'Velocity', 'State']
        self._attribute_values = {}
        self._commands = ['Stop']
        self._pipes = []
        self._port_num = 10000  # magic number for ease of testing
        self._host = os.uname().nodename
        self._active_subs = []

    async def read_attribute(self, attr_name: str):
        return self._read_attribute_sync(attr_name)

    def _read_attribute_sync(self, attr_name: str):
        if attr_name not in self._attributes:
            raise Exception() # what kind of exception should I raise?
        attr = getattr(self, attr_name, _SimDeviceAttribute(attr_name))
        if attr_name in self._attribute_values:
            attr.value = self._attribute_values[attr_name]
        return attr

    async def write_attribute(self, attr_name: str, value):
        logging.warning("Need to check if value is of right type and within bounds")
        if attr_name not in self._attributes:
            raise Exception() # what kind of exception should I raise?
        self._attribute_values[attr_name] = value

    def unsubscribe_event(self, sub_id):
        self._active_subs.remove(sub_id)

    async def subscribe_event(self, attr_name, event_type, callback):
        #need to add in loop..
        global _sim_sub_count
        _sim_sub_count += 1

        sub_id = _sim_sub_count
        self._active_subs.append(sub_id)
        def sub_loop():
            last_reading = self._read_attribute_sync(attr_name)
            last_value = last_reading.value
            event = _SimEventData(attr_name, self._name, self._host)
            if callback:
                callback(event)
            while True:
                new_reading = self._read_attribute_sync(attr_name)
                new_value = new_reading.value
                if new_value != last_value:
                    event = _SimEventData(attr_name, self._name, self._host)
                    if callback:
                        callback(event)
                elif sub_id not in self._active_subs:
                    return
        loop = asyncio.new_event_loop()
        loop.run_in_executor(None, sub_loop)
        return sub_id

    def get_db_port(self):
        return str(self._port_num)

    def get_db_port_num(self):
        return self._port_num

    def get_db_host(self):
        return self._host

    def get_attribute_list(self):
        return self._attributes

    def get_pipe_list(self):
        return self._pipes

    def get_command_list(self):
        return self._commands

    def __repr__(self):
        return "SimProxy("+self._name+")"

    def __str__(self):
        return self.__repr__()