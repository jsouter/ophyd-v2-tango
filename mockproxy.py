from multiprocessing.sharedctypes import Value
from re import M
from this import d
from PyTango import DeviceAttribute, TimeVal, AttributeInfoEx
from typing import List, Dict
from PyTango.asyncio import DeviceProxy
from PyTango._tango import AttrDataFormat, AttrQuality
import asyncio
import os


class MockDeviceProxy:
    #look into how "Mocks" work
    #how do we make it so that calling returns a coroutine?
    _name: str
    _class: str
    _port_num: int
    _host: str
    _dev_attrs: Dict[str, DeviceAttribute] = {}
    _attributes: List[str] = [] # lists accepted attributes. Do we need to specify behaviours for each of them?
    _attr_configs: Dict[str, AttributeInfoEx] = {}
    def __new__(cls, obj: str):
        print('Future should be pending, this returns it as done. close enough??')
        self = super().__new__(cls)
        self._name = obj
        self._class = 'MockClass'
        self._port_num = 10000
        self._attributes += ['Position', 'Velocity', 'State']
        print('setting to 10000 to test. prob a better way to do this')
        self._host = os.uname().nodename
        future = asyncio.Future()
        if self._name == "my/device/name":
            future.set_result(self)
        else:
            print(f"No Device named {self._name} found. Must be a better way to do this than printing")
            future.set_exception(ValueError)
        #we should want the future to raise exception when awaited if the obj string is not one of an existing device
        return future
        # return asyncio.Future(self)
        #need to have this check a simple database that contains attribute, command, pipe info etc and the logic?
        #or should it just be all included and use if to check if name is correct
    def name(self) -> str:
        return self._name
    def _get_info_(self):
        #should return dev_class, dev_type etc as a "DeviceInfo" object
        pass
    async def read_attribute(self, attr_name: str):
        await asyncio.sleep(0) #to make async?
        if attr_name not in self._attributes:
            print('not an attribute in this device. also shouldnt just print here, use better exception')
            raise Exception
        if attr_name in self._dev_attrs:
            dev_attr = self._dev_attrs[attr_name]
        else:
            dev_attr = DeviceAttribute()
            self._dev_attrs[attr_name] = dev_attr
            dev_attr.name = attr_name
            # dev_attr.nb_read = 1
        dev_attr.time = TimeVal().now()
        return dev_attr
    async def read_pipe(self, pipe: str):
        pass
    async def write_attribute(self, attribute: str, value):
        print('only works for scalar attr right now')
        config = self.get_attribute_config(attribute)
        if config.min_value not in ('', 'Not specified'):
            if value < float(config.min_value):
                raise ValueError
        if config.max_value not in ('', 'Not specified'):
            if value > float(config.max_value):
                raise ValueError
        dev_attr = await self.read_attribute(attribute)
        dev_attr.value = value
        
    def get_attribute_config(self, attr_name: str):
        if attr_name in self._attr_configs:
            config = self._attr_configs[attr_name]
        else:
            config = AttributeInfoEx()
            self._attr_configs[attr_name] = config
            config.name = attr_name
        return config
    async def write_pipe(self, pipe: str):
        pass    
    def get_db_port(self):
        return str(self._port_num)
    def get_db_port_num(self):
        return self._port_num
    def get_db_host(self):
        return self._host
    async def get_attribute_list(self):
        return self._attributes
    async def get_pipe_list(self):
        pass
    async def get_command_list(self):
        pass
    async def subscribe_event(self, event_type, callback):
        pass
    async def unsubscribe_event(self, sub_id):
        pass
    def __repr__(self):
        return self._class+"("+self.name()+")"
    def __str__(self):
        return self.__repr__()

_m = MockDeviceProxy("my/device/name")
print(_m)


_d = DeviceProxy("motor/motctrl01/1")
print(_d)

async def main():
    global m
    m = await _m
    global d
    d = await _d
    print(await d.read_attribute("Position"))
    print(await d.read_attribute("Position"))
    print(await m.read_attribute("Position"))
    print(await m.write_attribute("Position", 100))
    print(await m.read_attribute("Position"))
    # await asyncio.sleep(0)
    

if __name__ in "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    print(d)
    print(m)