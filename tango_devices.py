from argparse import ArgumentError
from multiprocessing.sharedctypes import Value
from PyTango.asyncio import AttributeProxy as AsyncAttributeProxy  # type: ignore
from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy  # type: ignore
from PyTango import DeviceProxy, DevFailed, EventData  # type: ignore
from PyTango._tango import DevState, DevString, AttrQuality, EventType, TimeVal  # type: ignore
import asyncio
import re
import sys
from ophyd.v2.core import AsyncStatus  # type: ignore
import logging

from typing import Callable, Generic, TypeVar, get_type_hints, Dict, Protocol, Union, Type, Coroutine, List, Any, Optional
from ophyd.v2.core import CommsConnector
from bluesky.protocols import Reading, Descriptor
from abc import ABC, abstractmethod
from collections import OrderedDict
from bluesky.run_engine import get_bluesky_event_loop
from bluesky.run_engine import call_in_bluesky_event_loop
from bluesky.protocols import Dtype
from ophyd.v2.core import Signal, SignalR, SignalW, Comm, observe_monitor
from mockproxy import MockDeviceProxy
import numpy as np
from tango import set_green_mode, get_green_mode # type: ignore
from tango import GreenMode # type: ignore

from ophyd.v2.core import Monitor


def _get_dtype(attribute) -> Dtype:
    value_class = attribute.value.__class__
    if value_class in (float, np.float64):
        return 'number'
    elif value_class is int:
        return 'integer'
    elif value_class is tuple:
        return 'array'
    elif value_class in (str, DevState):
        return 'string'
    elif value_class is bool:
        return 'boolean'
    else:
        raise NotImplementedError(f"dtype not implemented for {value_class} with attribute {attribute.name}")

# set_green_mode(GreenMode.Asyncio)

_tango_dev_proxies: Dict[str, AsyncDeviceProxy] = {}

_device_proxy_class = AsyncDeviceProxy
def set_device_proxy_class(klass, proxy_dict = _tango_dev_proxies):
    global _device_proxy_class
    print('Resetting dev proxy dictionary')
    proxy_dict.clear()
    if klass == AsyncDeviceProxy or MockDeviceProxy:
        _device_proxy_class = klass
    else:
        raise ValueError

def get_device_proxy_class():
    global _device_proxy_class
    return _device_proxy_class

class TangoDeviceNotFoundError(KeyError):
    ...

async def _get_proxy_from_dict(dev_name: str, proxy_dict = _tango_dev_proxies) -> AsyncDeviceProxy:
    if dev_name not in proxy_dict:
        try:
            proxy_class = get_device_proxy_class()
            proxy_future = proxy_class(dev_name)
            proxy = await proxy_future
            proxy_dict[dev_name] = proxy
        except DevFailed:
            raise TangoDeviceNotFoundError(f"Could not connect to DeviceProxy for {dev_name}")
    return proxy_dict[dev_name]



class TangoSignalMonitor(Monitor):
    logging.warning("implement TangoSignalMonitor")
    logging.warning("May be doing redundant putting to queues..")
    def __init__(self, signal):
        self.proxy = signal.proxy
        self.signal_name = signal.signal_name
        self.sub_id = None
    async def __call__(self, callback = None):
        if not self.sub_id:
            self.sub_id = await self.proxy.subscribe_event(self.signal_name, EventType.CHANGE_EVENT, callback)
    def close(self):
        self.proxy.unsubscribe_event(self.sub_id)
        self.sub_id = None


class TangoSignal(Signal):
    @abstractmethod
    async def connect(self, dev_name: str, signal_name: str, proxy: Optional[AsyncDeviceProxy] = None):
        self.proxy: AsyncDeviceProxy
        self.dev_name: str
        self.signal_name: str
        ...
        
    _connected: bool = False
    _source: Optional[str] = None

    @property
    def connected(self):
        return self._connected

    @property
    def source(self) -> str:
        if not self._source:
            prefix = (f'tango://{self.proxy.get_db_host()}:'
                            f'{self.proxy.get_db_port()}/')
            if isinstance(self, TangoAttr):
                self._source = prefix + f'{self.dev_name}/{self.signal_name}'
            elif isinstance(self, TangoPipe):
                self._source = prefix + f'{self.dev_name}:{self.signal_name}(Pipe)'
            elif isinstance(self, TangoCommand):
                self._source = prefix + f'{self.dev_name}:{self.signal_name}(Command)'
            else:
                raise TypeError(f'Can\'t determine source of TangoSignal object of class {self.__class__}')
        return self._source


class TangoAttr(TangoSignal):
    logging.warning('Have only tested attributes with scalar data so far')
    async def connect(self, dev_name: str, attr: str, proxy: Optional[AsyncDeviceProxy] = None):
        '''Should set the member variables proxy, dev_name and signal_name. May be called when no other connector used to connect signals'''
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = attr
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_attribute(attr)
            except:
                raise Exception(f"Could not read attribute {self.signal_name}")
            self._connected = True


class TangoMonitorable:
    async def monitor_reading(self, callback: Callable[[EventData], None]):
        monitor = TangoSignalMonitor(self)
        await monitor(callback)
        return monitor

    async def monitor_value(self, callback: Callable[[EventData], None]):
        monitor = TangoSignalMonitor(self)
        def value_callback(doc, callback=callback):
            callback(doc.attr_value.value)
        await monitor(value_callback)
        return monitor

class TangoAttrR(TangoAttr, TangoMonitorable, SignalR):

    def _get_shape(self, reading):
        shape = []
        if reading.dim_y:  # For 2D arrays
            if reading.dim_x:
                shape.append(reading.dim_x)
            shape.append(reading.dim_y)
        elif reading.dim_x > 1:  # for 1D arrays
            shape.append(reading.dim_x)
        return shape

    async def get_reading(self) -> Reading:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Reading({"value": attr_data.value, "timestamp": attr_data.time.totime()})

    async def get_descriptor(self) -> Descriptor:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Descriptor({"shape": self._get_shape(attr_data),
                "dtype": _get_dtype(attr_data),  # jsonschema types
                "source": self.source, })

    async def get_value(self):
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return attr_data.value


class TangoAttrW(TangoAttr, SignalW):
    latest_quality = None
    logging.warning('wait_for_not_moving may be deprecated')
    async def put(self, value):
        await self.proxy.write_attribute(self.signal_name, value)

    async def get_quality(self):
        reading = await self.proxy.read_attribute(self.signal_name)
        return reading.quality
               
    async def wait_for_not_moving(self):
        event = asyncio.Event()
        def set_event(reading):
            state = reading.attr_value.value
            if state != DevState.MOVING:
                event.set()
        sub = await self.proxy.subscribe_event('State', EventType.CHANGE_EVENT, set_event)
        await event.wait()
        self.proxy.unsubscribe_event(sub)

class TangoAttrRW(TangoAttrR, TangoAttrW):
    ...


class TangoCommand(TangoSignal):
    async def connect(self, dev_name: str, command: str, proxy: Optional[AsyncDeviceProxy] = None):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = command
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            commands = self.proxy.get_command_list()
            assert self.signal_name in commands, \
                f"Command {command} not in list of commands"
            self._connected = True

    async def execute(self, value=None):
        command_args = [arg for arg in [self.signal_name, value] if arg]
        # bit weird
        self.proxy.command_inout_asynch(*command_args)
        # is this async???
        print(f'Command {self.signal_name} executed')


class TangoPipe(TangoSignal):
    async def connect(self, dev_name: str, pipe: str, proxy: Optional[AsyncDeviceProxy] = None):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = pipe
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_pipe(self.signal_name)
            except:
                raise Exception(f"Couldn't read pipe {self.signal_name}")
            self._connected = True

class TangoPipeR(TangoPipe, TangoMonitorable, SignalR):
    #need to implement observe_reading and observe_monitor. should I just copy paste?
    logging.warning("read_pipe command does not return timeval, so may have to timestamp manually")
    logging.warning("it seems that read_pipe is not an awaitable function unlike read_attribute")
    
    async def get_reading(self) -> Reading:
        pipe_data = self.proxy.read_pipe(self.signal_name)
        return Reading({"value": pipe_data, "timestamp": TimeVal().now()})

    async def get_descriptor(self) -> Descriptor:
        # pipe_data = self.proxy.read_pipe(self.signal_name)
        logging.warning("Reading is a list of dictionaries. Setting json dtype to array, though 'object' is more appropriate")
        #if we are returning the pipe it is a name and list of blobs, so dimensionality 2
        return Descriptor({"shape": [2],
                "dtype": "array",  # jsonschema types
                "source": self.source, })

    async def get_value(self):
        pipe_data = self.proxy.read_pipe(self.signal_name)
        return pipe_data

    

class TangoPipeW(TangoPipe, SignalW):
    async def put(self, value):
        logging.warning('no longer needs to be async')
        # await self.proxy.write_pipe(self.signal_name, value)
        self.proxy.write_pipe(self.signal_name, value)


class TangoPipeRW(TangoPipeR, TangoPipeW):
    ...


class TangoComm(Comm):
    def __init__(self, dev_name: str):
        self.proxy: AsyncDeviceProxy  # should be set by a tangoconnector
        if self.__class__ is TangoComm:
            raise TypeError(
                "Can not create instance of abstract TangoComm class")
        self.dev_name = dev_name
        self._signals_ = make_tango_signals(self)
        self._connector = get_tango_connector(self)
        CommsConnector.schedule_connect(self)

    async def _connect_(self):
        await self._connector(self)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(dev_name={self.dev_name!r})"


TangoCommT = TypeVar("TangoCommT", bound=TangoComm, contravariant=True)

class TangoConnector(Protocol, Generic[TangoCommT]):
    async def __call__(self, comm: TangoCommT):
        ...

_tango_connectors: Dict[Type[TangoComm], TangoConnector] = {}

class ConnectTheRest:
    '''
    ConnectTheRest(comm: TangoComm)
    Connector class that checks DeviceProxy for similarly named signals to those unconnected in the comm object. 
    The connector connects to attributes/pipes/commands that have identical names to the hinted signal name when 
    lowercased and non alphanumeric characters are removed.
    e.g. the type hint "comm._position: TangoAttrRW" matches with the attribute "Position" on the DeviceProxy. 
    Can be called like a function.
    '''
    logging.warning("does not work with mock device proxy")
    def __new__(cls, comm):
        instance = super().__new__(cls)
        return instance(comm)

    def __await__(self):
        ...
  
    async def __call__(self, comm: TangoComm, proxy: Optional[AsyncDeviceProxy] = None):
        self.comm = comm
        self.signals: Dict[str, TangoSignal] = {}
        for signal_name in get_type_hints(comm):
            signal = getattr(self.comm, signal_name)
            if not signal.connected:
                self.signals[signal_name] = signal
        if not self.signals:  # if dict empty
            return
        self.proxy = proxy or await _get_proxy_from_dict(comm.dev_name)
        self.coros: List[Coroutine] = []
        self.guesses: Dict[str, Dict[str, str]] = {}
        self.signal_types = {'attribute':   {'baseclass': TangoAttr,
                                             'listcommand': self.proxy.get_attribute_list},
                             'pipe':         {'baseclass': TangoPipe,
                                              'listcommand': self.proxy.get_pipe_list},
                             'command':      {'baseclass': TangoCommand,
                                              'listcommand': self.proxy.get_command_list}}
        for signal_name in self.signals:
            self.schedule_signal(self.signals[signal_name], signal_name)
        if self.coros:
            await asyncio.gather(*self.coros)

    @staticmethod
    def guess_string(signal_name):
        return re.sub(r'\W+', '', signal_name).lower()

    def make_guesses(self, signal_type):
        if signal_type not in self.guesses:  # if key exists
            # self.guesses contains lowercased-alphanumeric attribute/pipe/command names
            # only populated when attribute/pipe/command found in unconnected signals
            self.guesses[signal_type] = {}
            # attribute (or pipe or command) names
            attributes = self.signal_types[signal_type]['listcommand']()
            for attr in attributes:
                name_guess = self.guess_string(attr)
                self.guesses[signal_type][name_guess] = attr
                # lowercased-alphanumeric names are keys, actual attribute names are values

    def schedule_signal(self, signal, signal_name):
        for signal_type in self.signal_types:
            if isinstance(signal, self.signal_types[signal_type]['baseclass']):
                self.make_guesses(signal_type)
                name_guess = self.guess_string(signal_name)
                if name_guess in self.guesses[signal_type]:  # if key exists
                    attr_proper_name = self.guesses[signal_type][name_guess]
                    coro = signal.connect(self.comm.dev_name, attr_proper_name)
                    self.coros.append(coro)
                else:
                    raise ValueError(f"No {signal_type} found resembling '{name_guess}'")
                break  # prevents unnecessary checks: e.g. if attribute, dont check for pipe


def get_tango_connector(comm: TangoComm) -> TangoConnector:
    if type(comm) in _tango_connectors:  # .keys()
        return _tango_connectors[type(comm)]
    else:
        print('Defaulting to "ConnectTheRest()"')
        return ConnectTheRest


def tango_connector(connector, comm_cls=None):
    if comm_cls is None:
        comm_cls = get_type_hints(connector)["comm"]
    _tango_connectors[comm_cls] = connector

class WrongNumberOfArgumentsError(TypeError):
    ...

class TangoDevice:
    logging.warning("get_unique_name should probably belong to attr. Maybe we should use a setter or something idk")
    def __init__(self, comm: TangoComm, name: Optional[str] = None):
        self.name = name or re.sub(r'[^a-zA-Z\d]', '-', comm.dev_name) 
        # replace non alphanumeric characters with dash if name not set manually           
        self.comm = comm
        self.parent = None
        if self.__class__ is TangoDevice:
            raise TypeError(
                "Can not create instance of abstract TangoComm class")

    async def _read(self, *to_read):
        od = OrderedDict()
        for attr in to_read:
            reading = await attr.get_reading()
            name = self.get_unique_name(attr)
            od[name] = reading
        return od

    async def _describe(self, *to_desc):
        od = OrderedDict()
        for attr in to_desc:
            description = await attr.get_descriptor()
            name = self.name + ':' + attr.signal_name
            od[name] = description
        return od

    @abstractmethod
    async def read(self):
        ...

    @abstractmethod
    async def describe(self):
        ...

    @abstractmethod
    async def read_configuration(self):
        ...

    @abstractmethod
    async def describe_configuration(self):
        ...

    def get_unique_name(self, attr):
        return self.name + ':' + attr.signal_name

    async def configure(self, *args):
    
        '''Returns old result of read_configuration and new result of read_configuration. Pass an arbitrary number of pairs of args
        where the first arg is the attribute name as a string and the second arg is the new value of the attribute'''
        logging.warning('Need to decide whether we look for the Python attribute name or Tango attribute name')
        logging.warning('single pipe returns empty ordereddicts because we are counting the pipe as a read field not a read_config field')

        if len(args) % 2: # != 0
            raise WrongNumberOfArgumentsError("configure can not parse an odd number of arguments")
        old_reading = await self.read_configuration()
        for attr_name, value in zip(args[0::2], args[1::2]):
            attr = getattr(self.comm, attr_name)
            unique_name = self.get_unique_name(attr)
            if unique_name not in old_reading:
                raise KeyError(f"The attribute {unique_name} is not designated as configurable")
            await attr.put(value)
        new_reading = await self.read_configuration()
        return old_reading, new_reading

class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW
    state: TangoAttrRW
    stop: TangoCommand

class TangoSingleAttributeDevice(TangoDevice):
    def __init__(self, dev_name, attr_name, name: Optional[str] = None):
        name = name or dev_name

        class SingleComm(TangoComm):
            attribute: TangoAttrRW

        @tango_connector
        async def connectattribute(comm: SingleComm):
            await comm.attribute.connect(dev_name, attr_name)

        self.comm = SingleComm(dev_name)
        super().__init__(self.comm, name)

    async def read(self):
        reading = await self.comm.attribute.get_reading()
        return OrderedDict({self.name:reading})

    async def describe(self):
        descriptor = await self.comm.attribute.get_descriptor()
        return OrderedDict({self.name:descriptor})

    async def read_configuration(self):
        return await self._read()

    async def describe_configuration(self):
        return await self._describe()

class TangoSinglePipeDevice(TangoDevice):
    def __init__(self, dev_name, attr_name, name: Optional[str] = None):
        name = name or dev_name

        class SinglePipeComm(TangoComm):
            pipe: TangoPipeRW

        @tango_connector
        async def connectpipe(comm: SinglePipeComm):
            await comm.pipe.connect(dev_name, attr_name)

        self.comm = SinglePipeComm(dev_name)
        super().__init__(self.comm, name)

    async def read(self):
        reading = await self.comm.pipe.get_reading()
        return OrderedDict({self.name:reading})

    async def describe(self):
        descriptor = await self.comm.pipe.get_descriptor()
        return OrderedDict({self.name:descriptor})

    async def read_configuration(self):
        return await self._read()

    async def describe_configuration(self):
        return await self._describe()

class TangoMotor(TangoDevice):
    comm: TangoMotorComm # satisfies type checker
    async def read(self):
        return await self._read(self.comm.position)

    async def describe(self):
        return await self._describe(self.comm.position)

    async def read_configuration(self):
        return await self._read(self.comm.velocity)

    async def describe_configuration(self):
        return await self._describe(self.comm.velocity)

    #this should probably be changed, use a @timeout.setter
    def set_timeout(self, timeout):
        self._timeout = timeout
    
    @property
    def timeout(self):
        if hasattr(self, '_timeout'):
            return self._timeout
        else:
            return None

    def set(self, value, timeout: Optional[float] = None):
        timeout = timeout or self.timeout
        async def write_and_wait():
            pos = self.comm.position
            state = self.comm.state
            await pos.put(value)
            q = asyncio.Queue()
            monitor = await state.monitor_value(q.put_nowait)
            while True:
                state_value = await q.get()
                if state_value != DevState.MOVING:
                    monitor.close()
                    break
        status = AsyncStatus(asyncio.wait_for(
            write_and_wait(), timeout=timeout))
        return status


def make_tango_signals(comm: TangoComm):
    hints = get_type_hints(comm)  # dictionary of names and types
    for signal_name in hints:
        signal = hints[signal_name]()
        setattr(comm, signal_name, signal)


@tango_connector
async def motorconnector(comm: TangoMotorComm):
    proxy = await _get_proxy_from_dict(comm.dev_name)
    await asyncio.gather(
        comm.position.connect(comm.dev_name, "Position", proxy),
        comm.velocity.connect(comm.dev_name, "Velocity", proxy),
        comm.state.connect(comm.dev_name, "State", proxy),
    )
    await ConnectTheRest(comm)

def motor(dev_name: str, ophyd_name: Optional[str] = None):
    ophyd_name = ophyd_name or re.sub(r'[^a-zA-Z\d]', '-', dev_name)
    c = TangoMotorComm(dev_name)
    return TangoMotor(c, ophyd_name)




# if __name__ == "__main__":
def tango_devices_main():
    from bluesky.run_engine import get_bluesky_event_loop
    from bluesky.run_engine import RunEngine
    from bluesky.plans import count, scan
    import time
    from tango import set_green_mode, get_green_mode # type: ignore
    from tango import GreenMode # type: ignore
    import bluesky.plan_stubs as bps
    from bluesky.callbacks import LiveTable, LivePlot
    from bluesky.run_engine import call_in_bluesky_event_loop


    import timeit

    # set_green_mode(GreenMode.Asyncio)
    # set_green_mode(GreenMode.Gevent)

    RE = RunEngine({})
    with CommsConnector():
        motor1 = motor("motor/motctrl01/1", "motor1")
        motor2 = motor("motor/motctrl01/2", "motor2")
        motor3 = motor("motor/motctrl01/3", "motor3")
        motor4 = motor("motor/motctrl01/4", "motor4")
        motors = [motor1, motor2, motor3, motor4]

    from cbtest import mycallback
    print(call_in_bluesky_event_loop(motor1.read_configuration()))
    def scan1():
        velocity = 1000
        for m in motors:
            call_in_bluesky_event_loop(m.configure('velocity', velocity))
            # m.set_timeout(0.0001)
        for i in range(4):
            scan_args = []
            table_args = []
            for j in range(i+1):
                scan_args += [motors[j], 0, 1]
                table_args += ['motor'+str(j+1)+':Position']
            thetime = time.time()
            RE(scan([],*scan_args,11), LiveTable(table_args))
            # RE(scan([], *scan_args, 11))
            print('scan' + str(i+1), time.time() - thetime)
    def scan2():
        print('with 2 motors:')
        for i in range(10):
            thetime = time.time()
            RE(scan([],motor1,0,1,motor2,0,1,10*i+1))
            print('steps' +str(10*i+1),time.time() - thetime)
        print('with 4 motors:')
        for i in range(10):
            thetime = time.time()
            RE(scan([],motor1,0,1,motor2,0,1,motor3,0,1,motor4,0,1,10*i+1))
            print('steps' +str(10*i+1),time.time() - thetime)
        for i in range(4):
            scan_args = []
            table_args = []
            for j in range(i+1):
                scan_args += [motors[j]]
                table_args += ['motor'+str(j+1)+':Position']
            thetime = time.time()
            # RE(count(scan_args,11), LiveTable(table_args))
            RE(count(scan_args,11))
            print('count' +str(i+1),time.time() - thetime)
    
    # scan1()
    # scan2()

    with CommsConnector():
        single = TangoSingleAttributeDevice("motor/motctrl01/1", "Position", "mymotorposition")
        singlepipe = TangoSinglePipeDevice("tango/example/device", "my_pipe", "mypipe")


    # RE(count([single]), LiveTable(["mymotorposition"]))
    # RE(count([single, singlepipe]), print)
    # RE(count([singlepipe]), print)
    # reading = call_in_bluesky_event_loop(q.get())
    # print(reading)
    # print(call_in_bluesky_event_loop(motor1.configure('velocity',100)))

    async def check_pipe_configured():
        reading = await singlepipe.read()
        print(reading)
        await singlepipe.configure('pipe',('hello', [{'name': 'test', 'dtype': DevString, 'value': 'how are you'}, {'name': 'test2', 'dtype': DevString, 'value': 'test2'}]))
        reading = await singlepipe.read()
        print(reading)
        await singlepipe.configure('pipe',('hello', [{'name': 'test', 'dtype': DevString, 'value': 'yeah cant complain'}, {'name': 'test2', 'dtype': DevString, 'value': 'test2'}]))
        reading = await singlepipe.read()
        print(reading)
    # call_in_bluesky_event_loop(check_pipe_configured())
    print(get_green_mode())
    monitor1 = call_in_bluesky_event_loop(motor1.comm.position.monitor_reading(print))
    monitor1.close()
    monitor2 = call_in_bluesky_event_loop(motor1.comm.position.monitor_value(print))
    monitor2.close()




    print(id(motor1.comm.position.proxy) == id(motor1.comm.velocity.proxy))




    # single = tango_single_attribute_device("motor/motctrl01/1", "Velocity")

if __name__ in "__main__":
    tango_devices_main()
    from bluesky.plans import count
    from bluesky.callbacks import LiveTable
    from ophyd.v2.core import CommsConnector
    # python3 -m cProfile -o test.prof tango_devices.py
    # snakeviz test.prof
    # import cProfile
    # cProfile.run('main()', sort='cumtime')
    # cProfile.run('main()', sort='tottime')