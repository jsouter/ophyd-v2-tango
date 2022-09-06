from multiprocessing.sharedctypes import Value
from PyTango import DeviceAttribute, TimeVal, AttributeInfoEx, EventData
from typing import List, Dict
from PyTango.asyncio import DeviceProxy
from PyTango._tango import AttrDataFormat, AttrQuality, EventType
import asyncio
import time
import os
import random
import multiprocessing
import threading




_global_sub_count = 0

class MockDeviceProxy:
    print('only works for scalar attr right now')
    #look into how "Mocks" work
    #how do we make it so that calling returns a coroutine?
    _name: str
    _class: str
    _port_num: int
    _host: str
    _dev_attrs: Dict[str, DeviceAttribute] = {}
    _attributes: List[str] = [] # lists accepted attributes. Do we need to specify behaviours for each of them?
    _attr_configs: Dict[str, AttributeInfoEx] = {}
    _active_subscriptions: List = []
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
        if self._name == "mock/device/name":
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
        return self._read_attribute_sync(attr_name)
    async def read_pipe(self, pipe: str):
        pass
    async def write_attribute(self, attribute: str, value):
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
    def get_attribute_list(self):
        return self._attributes
    def get_pipe_list(self):
        pass
    def get_command_list(self):
        pass
    def _read_attribute_sync(self, attr_name):
        # print('kind of janky but makes it easier to do background task in subscribe event??')
        if attr_name not in self._attributes:
            print('not an attribute in this device. also shouldnt just print here, use better exception')
            raise Exception
        if attr_name in self._dev_attrs:
            dev_attr = self._dev_attrs[attr_name]
        else:
            dev_attr = DeviceAttribute()
            self._dev_attrs[attr_name] = dev_attr
            dev_attr.name = attr_name
            dev_attr.value = 0 # kind of weird
            # dev_attr.nb_read = 1
        dev_attr.time = TimeVal().now()
        return dev_attr
    
    def create_event_data(self, reading):
        event = EventData()
        event.reception_data = TimeVal().now()
        event.event = 'change'
        event.attr_name = 'ADD THIS IN LATER'
        event.attr_value = reading
        return event

    async def subscribe_event(self, attr_name, event_type, callback):
        # print('Need to return an EventData object containing an attr_value= DeviceAttribute field. Easy enough!')
        #hasnt been tested yet, also need to make sure the sub is
        #running in a seperate process so that the function can return the sub id
        if event_type != EventType.CHANGE_EVENT:
            raise NotImplementedError("This mock only accepts EventType.CHANGE_EVENT as event_type")
        
        global _global_sub_count
        _global_sub_count += 1
        sub_id = _global_sub_count
        self._active_subscriptions.append(sub_id)
        async def sub_loop():
            # print('loop started')
            last_reading = self._read_attribute_sync(attr_name)
            callback(last_reading)
            while True:
                # print(sub_id, self._active_subscriptions)
                new_reading = self._read_attribute_sync(attr_name)
                if hasattr(new_reading, 'value'):
                    if not hasattr(last_reading, 'value'):
                        # print('new reading has value, last doesnt')
                        break
                    elif new_reading.value != last_reading.value:
                        callback(new_reading)
                        # print(f'callback run again for sub {sub_id}')
                if sub_id not in self._active_subscriptions:
                    break
                last_reading = new_reading
            # print("while loop broken")
        def sub_loop_sync(proxy):
            # print('loop started')
            last_reading = proxy._read_attribute_sync(attr_name)
            if not hasattr(last_reading, 'value'):
                last_reading.value = None
            last_value = last_reading.value
            callback(self.create_event_data(last_reading))
            # print(f"event_data is {self.create_event_data(last_reading)}")
            # print(f'callback run for first time for sub {sub_id}')
            while True:
                new_reading = proxy._read_attribute_sync(attr_name)
                if not hasattr(new_reading, 'value'):
                    new_reading.value = None
                if new_reading.value != last_value:
                    # print('Different!')
                    # callback(new_reading)
                    # print(f"reading is {new_reading}")
                    callback(self.create_event_data(new_reading))
                    # print(f"event_data is {self.create_event_data(new_reading)}")
                elif sub_id not in proxy._active_subscriptions:
                    # print(f'sub_id {sub_id} gone.')
                    return
                last_reading = new_reading
                last_value = new_reading.value # janky but it stops caching error
            # print("while loop broken")
        # loop = asyncio.get_event_loop()
        loop = asyncio.new_event_loop()
        loop.run_in_executor(None, sub_loop_sync, self)
        # loop.create_task(sub_loop())
        # p = threading.Thread(target=sub_loop_sync)
        # p.start()
        # print(f"sub_id is {sub_id} in fn")
        #for some reason using await in the task breaks the loop, so we have avoided it using sync methods. bit dodgy
        return sub_id
    def unsubscribe_event(self, sub_id):
        # print('Doing a dodgy sync thing to keep the sub going but maybe thats fine')
        self._active_subscriptions.remove(sub_id)
        # print(self._active_subscriptions)
    def __repr__(self):
        return self._class+"("+self.name()+")"
    def __str__(self):
        return self.__repr__()


async def mockproxymain1():
    global m
    m = await MockDeviceProxy("mock/device/name")
    # print(await d.read_attribute("Position"))
    # print(await d.read_attribute("Position"))

    # sub1 = await m.subscribe_event("State", EventType.CHANGE_EVENT, q1.put_nowait)
    # print(f"sub={sub1}")
    # sub2 = await m.subscribe_event("Velocity", EventType.CHANGE_EVENT, q2.put_nowait)
    # print(f"sub={sub2}")
    # # m.unsubscribe_event(sub2)
    # reading1 = await q1.get()
    # reading2 = await q2.get()
    # m.unsubscribe_event(sub1)
    # print(reading1, reading2)

    q1 = asyncio.Queue()
    q2 = asyncio.Queue()
    sub1 = await m.subscribe_event("Velocity", EventType.CHANGE_EVENT, q1.put_nowait)
    sub2 = await m.subscribe_event("Position", EventType.CHANGE_EVENT, q2.put_nowait)
    while True:
        await m.write_attribute("Velocity", random.random())
        await m.write_attribute("Position", random.random())
        await asyncio.sleep(0.5)
        val1 = (await q1.get()).value
        val2 = (await q2.get()).value
        print(val1,val2)
        if val2 > 0.7:
            print('too far, lets break this loop!')
            m.unsubscribe_event(sub1)
            m.unsubscribe_event(sub2)
            break # is there a command to check "if subscription active?"


        # b = m._read_attribute_sync("Velocity")
        # print(b)

    #dont think _active_subscriptions is thread safe? doesnt seem to update in the process loop
    #threads maybe work better
    #sub_id gets successfully returned but only the first loop actually starts
    #with multiprocessing both loops start but the q1.get() never finishes waiting. idk why...


def mockproxymain2():
    from tango_devices import motor, get_device_proxy_class, set_device_proxy_class
    from ophyd.v2.core import CommsConnector
    from bluesky import RunEngine
    import bluesky.plan_stubs as bps
    from bluesky.plans import count, scan
    from bluesky.callbacks import LiveTable
    from bluesky.run_engine import call_in_bluesky_event_loop
    from PyTango import DeviceProxy as TestDeviceProxy
    RE=RunEngine()

    
    set_device_proxy_class(MockDeviceProxy)
    print(f"device proxy class is set to : {get_device_proxy_class()}")

    with CommsConnector():
        b = motor("mock/device/name", "b")
    # print(call_in_bluesky_event_loop(b.describe()))
    #dev_attr is getting set but maybe ophyd doesn't know what to do with dev_attrs? it should do!
    # RE(bps.rd(b), LiveTable(["b:Position"]))

    # print(TestDeviceProxy("motor/motctrl01/1").read_attribute("Position"))
    RE(count([b],1), LiveTable(["b:Position"]))
    def print2(doc):
        print(f"printing the thing: {doc}")
        
    # call_in_bluesky_event_loop(b.comm.position.proxy.subscribe_event("Position", EventType.CHANGE_EVENT, print2))
    RE(bps.mv(b, 5))
    #why cant we use bluesky mv on the device using mock device proxy?
    RE(scan([],b,0,1,3), LiveTable(["b:Position"]))


    

if __name__ in "__main__":

    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(mockproxymain1())
    mockproxymain2()
    # print(d)
    # print(m)