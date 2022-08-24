from PyTango.asyncio import AttributeProxy as AsyncAttributeProxy # type: ignore
from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy # type: ignore
from PyTango._tango import DevState, AttrQuality # type: ignore
import asyncio
import re
from ophyd.v2.core import AsyncStatus


from typing import get_type_hints, Dict, Protocol, Union, Type, Coroutine, List
from ophyd.v2.core import CommsConnector
from abc import ABC, abstractmethod
from collections import OrderedDict
from bluesky.run_engine import get_bluesky_event_loop
from bluesky.run_engine import call_in_bluesky_event_loop

def get_dtype(attribute) -> str:
    # print('Python has a json library, probably better to use that than do this')
    value_class = attribute.value.__class__
    json_type = None
    if value_class in (int, float):
        json_type = 'number'
    elif value_class is tuple:
        json_type = 'array'
    elif value_class in (str, DevState):
        json_type = 'string'
    elif value_class is bool:
        json_type = 'boolean'
    elif value_class is type(None):
        json_type = 'null'
        #print('Setting None to json type null, not sure if appropriate')
    if not json_type:
        raise NotImplementedError(f"dtype not implemented for {value_class} with attribute {attribute.name}")
    return json_type

_tango_dev_proxies: Dict[str, AsyncDeviceProxy] = {}

async def get_proxy_from_dict(device: str) -> AsyncDeviceProxy:
    if device not in _tango_dev_proxies:
        try:
            proxy_future = AsyncDeviceProxy(device)
            proxy = await proxy_future
        except:
            raise Exception(f"Could not connect to DeviceProxy for {device}")
        _tango_dev_proxies[device] = proxy
    return _tango_dev_proxies[device]

class TangoSignal(ABC):
    def __init__(self, dev_name):
        self.dev_name = dev_name
        self._connected = False
    
    @abstractmethod
    async def connect(self, signal_name: str): 
        pass


class TangoAttr(TangoSignal):
    async def connect(self, attr: str):
        '''Should set the member variables proxy and signal_name. May be called when no other connector used to connect signals'''
        if not self._connected:
            # print('Getting proxy from dict using dev name, better to use ophyd name')
            self.signal_name = attr
            self.proxy = await get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_attribute(attr)
            except:
                raise Exception(f"Could not read attribute {self.signal_name}")
            self._connected = True

class TangoAttrR(TangoAttr):
    def _get_shape(self, reading):
        shape = []
        if reading.dim_y: #For 2D arrays
            if reading.dim_x:
                shape.append(reading.dim_x)
            shape.append(reading.dim_y)
        elif reading.dim_x > 1: #for 1D arrays
            shape.append(reading.dim_x)
        return shape
    async def get_reading(self):
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return {"value": attr_data.value, "timestamp": attr_data.time.totime()}
    async def get_descriptor(self):
        attr_data = await self.proxy.read_attribute(self.signal_name)
        dtype = get_dtype(attr_data)
        source = 'tango://' + self.dev_name + '/' + attr_data.name
        return {"shape": self._get_shape(attr_data),
                "dtype": dtype,  # jsonschema types
                "source": source,}

class TangoAttrRW(TangoAttrR):
    async def write(self, value):
        await self.proxy.write_attribute(self.signal_name, value)
    async def get_quality(self):
        reading = await self.proxy.read_attribute(self.signal_name)
        return reading.quality

class TangoCommand(TangoSignal):
    async def connect(self, command: str):
        if not self._connected:
            self.signal_name = command
            self.proxy = await get_proxy_from_dict(self.dev_name)
            commands = self.proxy.command_list_query()
            cmd_names = [c.cmd_name for c in commands]
            assert self.signal_name in cmd_names, \
                f"Command {command} not in list of commands"
            self._connected = True
    async def execute(self, value = None):
        command_args = [ arg for arg in [self.signal_name, value] if arg ]
        #bit weird
        self.proxy.command_inout_asynch(*command_args)
        #is this async???
        print(f'Command {self.signal_name} executed')

class TangoPipe(TangoSignal):
    #need an R and W superclass etc
    async def connect(self, pipe):
        if not self._connected:
            self.signal_name = pipe
            self.proxy = await get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_pipe(self.signal_name)
            except:
                raise Exception(f"Couldn't read pipe {self.signal_name}")
            self._connected = True

class TangoComm(ABC):
    def __init__(self, dev_name: str,):
        self.proxy: AsyncDeviceProxy # should be set by a tangoconnector
        if self.__class__ is TangoComm:
            raise TypeError("Can not create instance of abstract TangoComm class")
        self.dev_name = dev_name
        self.__signals__ = make_tango_signals(self)
        self._connector = get_tango_connector(self)
        CommsConnector.schedule_connect(self)

    async def __connect__(self):
        await self._connector(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(dev_name={self.dev_name!r})"



_tango_connectors = {}



def get_tango_connector(comm: TangoComm):
    if type(comm) in _tango_connectors.keys():
        return _tango_connectors[type(comm)]
    else:
        print('Defaulting to "ConnectTheRest()", only works with v1 objects (using proxy of signals not comm)')
        return ConnectTheRest()

def tango_connector(connector, comm_cls = None):
    if comm_cls is None:
        comm_cls = get_type_hints(connector)["comm"]
    _tango_connectors[comm_cls] = connector

async def get_proxy(dev_name):
    proxy = await AsyncDeviceProxy(dev_name)
    await get_proxy_from_dict(dev_name)
    print(f'Adding dev name {dev_name} to proxy dict')
    return proxy

class TangoDevice:
    def __init__(self, comm: TangoComm, name: Union[str, None] = None):
        print('attr._get_shape is weird. change it')
        self.comm = comm
        self.parent = None
        self.name = name or comm.dev_name.replace("/", "-")#if name not set, remove slashes from dev_name to satisfy regex
        # if not get_bluesky_event_loop().is_running():
        #     raise Exception("Can't instantiate Device when bluesky event loop not running")
        # self.proxy = call_in_bluesky_event_loop(get_proxy(comm.dev_name))
        # print('calling proxy in event loop. is that appropriate?')
    # async def _read(self, *to_read):
    #     od = OrderedDict()
    #     for attr in to_read:
    #         attr_data = await self.proxy.read_attribute(attr.signal_name)
    #         reading = {"value": attr_data.value, "timestamp": attr_data.time.totime()}
    #         name = self.name + ':' + attr.signal_name
    #         od[name] = reading
    #     return od
    # async def _describe(self, *to_desc):
    #     od = OrderedDict()
    #     for attr in to_desc:
    #         attr_data = await self.proxy.read_attribute(attr.signal_name)
    #         dtype = get_dtype(attr_data)
    #         source = 'tango://' + self.comm.dev_name + '/' + attr_data.name
    #         description =  {"shape": attr._get_shape(attr_data),
    #                 "dtype": dtype,  # jsonschema types
    #                 "source": source,}
    #         name = self.name + ':' + attr.signal_name
    #         od[name] = description
    #     return od
    # async def write(self, attr, value):
    #     await self.proxy.write_attribute(attr.signal_name, value)
    # async def get_quality(self, attr):
    #     reading = await self.proxy.read_attribute(attr.signal_name)
    #     return reading.quality
    async def _read(self, *to_read):
        od = OrderedDict()
        for attr in to_read:
            reading = await attr.get_reading()
            name = self.name + ':' + attr.signal_name
            od[name] = reading
        return od
    async def _describe(self, *to_desc):
        od = OrderedDict()
        for attr in to_desc:
            description = await attr.get_descriptor()
            name = self.name + ':' + attr.signal_name
            od[name] = description
        return od

class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW

class TangoMotor(TangoDevice):
    comm: TangoMotorComm # kind of weird but this prevents the type hints issue for comm.position
    # @property
    # def pos(self):
    #     return self.comm.position
    async def read(self):
        return await self._read(self.comm.position)#could remove this red line by passing TangoMotorCommv2 as an arg, but would have to write redundant init
    async def describe(self):
        return await self._describe(self.comm.position)
    async def read_configuration(self):
        return await self._read(self.comm.velocity)
    async def describe_configuration(self):
        return await self._describe(self.comm.velocity)
    async def set_config_value_async(self, attr_name: str, value):
        attr: TangoAttrRW = getattr(self.comm, attr_name)
        await attr.write(value)
    def set_config_value(self, attr_name: str, value):
        call_in_bluesky_event_loop(self.set_config_value_async(attr_name, value))
    def set(self, value, timeout: Union[float, None] = None):
        async def write_and_wait():
            pos = self.comm.position
            try:
                # await self.write(pos, value)
                await pos.write(value)
            except Exception:
                raise Exception("Something went wrong in write_and_wait")
            # quality = await self.get_quality(pos)
            quality = await pos.get_quality()
            while quality != AttrQuality.ATTR_VALID:
                # quality = await self.get_quality(pos)
                quality = await pos.get_quality()
        status = AsyncStatus(asyncio.wait_for(write_and_wait(), timeout=timeout))
        return status


def get_attrs_from_hints(comm: TangoComm):
    hints = get_type_hints(comm)
    return {signal_name: getattr(comm, signal_name) for signal_name in hints}

def make_tango_signals(comm: TangoComm):
    hints = get_type_hints(comm)#dictionary of names and types
    dev_name = comm.dev_name
    for signal_name in hints:
        signal = hints[signal_name](dev_name)
        setattr(comm, signal_name, signal)



@tango_connector
async def motorconnector(comm: TangoMotorComm):
    await asyncio.gather(
        comm.position.connect("Position"),
        comm.velocity.connect("Velocity"),
    )

def motor(dev_name: str, ophyd_name: str):
    c = TangoMotorComm(dev_name)
    return TangoMotor(c, ophyd_name)


if __name__ == "__main__":
       
    from bluesky.run_engine import get_bluesky_event_loop
    from bluesky.run_engine import RunEngine
    from bluesky.plans import count, scan
    import time
    from tango import set_green_mode, get_green_mode
    from tango import GreenMode
    import bluesky.plan_stubs as bps
    from bluesky.callbacks import LiveTable, LivePlot
    from bluesky.run_engine import call_in_bluesky_event_loop
    # set_green_mode(GreenMode.Asyncio)
    # set_green_mode(GreenMode.Gevent)

    RE = RunEngine({})
    with CommsConnector():
        motor1 = motor("motor/motctrl01/1", "motor1")
        motor2 = motor("motor/motctrl01/2", "motor2")
    motor2.set_config_value('velocity', 10000)
    # print(call_in_bluesky_event_loop(motor1.read()))
    # RE(count([motor1],num=10,delay=None), LiveTable(['motor1:Position']))

    from cbtest import mycallback
    RE(scan([],motor1,0,1,11), LiveTable(['motor1:Position']))
    RE(scan([],motor1,1,2,motor2,5,10,11), LiveTable(['motor1:Position', 'motor2:Position']))
    # RE(scan([],motor1,0,1000,motor2,0,1000,2), LiveTable(['motor1:Position', 'motor2:Position']))
    # RE(scan([],motor1,0,1,motor2,10,101,11), mycallback(['motor1:Position', 'motor2:Position']))