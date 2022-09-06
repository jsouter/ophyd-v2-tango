from multiprocessing.sharedctypes import Value
from PyTango.asyncio import AttributeProxy as AsyncAttributeProxy  # type: ignore
from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy  # type: ignore
from PyTango import DeviceProxy, DevFailed  # type: ignore
from PyTango._tango import DevState, AttrQuality, EventType  # type: ignore
import asyncio
import re
import sys
from ophyd.v2.core import AsyncStatus  # type: ignore

from typing import Callable, Generic, TypeVar, get_type_hints, Dict, Protocol, Union, Type, Coroutine, List, Any, Optional
from ophyd.v2.core import CommsConnector
from bluesky.protocols import Reading, Descriptor
from abc import ABC, abstractmethod
from collections import OrderedDict
from bluesky.run_engine import get_bluesky_event_loop
from bluesky.run_engine import call_in_bluesky_event_loop
from bluesky.protocols import Dtype
from ophyd.v2.core import Signal, SignalR, SignalW, Comm
from mockproxy import MockDeviceProxy
import numpy as np

# from mockproxy import MockDeviceProxy


def _get_dtype(attribute) -> Dtype:
    # https://pytango.readthedocs.io/en/v9.3.4/data_types.html
    value_class = attribute.value.__class__
    if value_class in (float, np.float64): # float64 needed to get mockproxy example working
        return 'number'
    elif value_class is int:
        return 'integer'
    elif value_class is tuple:
        return 'array'
    elif value_class in (str, DevState):
        return 'string'
    elif value_class is bool:
        return 'boolean'
    # elif value_class is type(None):
    #     return 'null'
        #print('Setting None to json type null, not sure if appropriate')
    else:
        raise NotImplementedError(f"dtype not implemented for {value_class} with attribute {attribute.name}")


_tango_dev_proxies: Dict[str, AsyncDeviceProxy] = {}
# print('need to make a proxy dict singleton class so that we can swap out AsyncDeviceProxy for MockDeviceProxy')
# print('or maybe its sufficient to just change the value of self.proxy')

_device_proxy_class = AsyncDeviceProxy
def set_device_proxy_class(klass):
    global _device_proxy_class
    if klass == AsyncDeviceProxy or MockDeviceProxy:
        _device_proxy_class = klass
    else:
        raise ValueError

def get_device_proxy_class():
    global _device_proxy_class
    return _device_proxy_class


async def _get_proxy_from_dict(device: str) -> AsyncDeviceProxy:
    if device not in _tango_dev_proxies:
        try:
            proxy_class = get_device_proxy_class()
            proxy_future = proxy_class(device)
            proxy = await proxy_future
        except DevFailed:
            raise DevFailed(f"Could not connect to DeviceProxy for {device}")
        _tango_dev_proxies[device] = proxy
    return _tango_dev_proxies[device]


class TangoSignal(Signal):
    @abstractmethod
    async def connect(self, dev_name: str, signal_name: str):
        self.proxy: AsyncDeviceProxy
        self.dev_name: str
        self.signal_name: str
        ...
        
    _connected = False
    _source = None

    @property
    def connected(self):
        return self._connected

    @property
    def source(self) -> str:
        # print(f"source called for {self.dev_name}:{self.signal_name}")
        if not self._source:
            self._source = (f'tango://{self.proxy.get_db_host()}:'
                            f'{self.proxy.get_db_port()}/'
                            f'{self.dev_name}/{self.signal_name}')
            if isinstance(self, TangoPipe):
                self._source += '(Pipe)'
            elif isinstance(self, TangoCommand):
                self._source += '(Command)'
        return self._source


class TangoAttr(TangoSignal):
    async def connect(self, dev_name: str, attr: str):
        '''Should set the member variables proxy and signal_name. May be called when no other connector used to connect signals'''
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = attr
            self.proxy = await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_attribute(attr)
            except:
                raise Exception(f"Could not read attribute {self.signal_name}")
            self._connected = True



# def tango_observe_monitor(subscription_id):

# class TangoMonitor: # this should probably inherit from Monitor Protocol but that is namespaced behind epics
#     async def __call__(self, signal: TangoSignal, callback):
#         self.sub_id = await signal.proxy.subscribe_event(signal.signal_name, EventType.CHANGE_EVENT, callback)
#         self.unsub_coro = signal.proxy.unsubscribe_event(self.sub_id)
#     async def close(self):
#         await self.unsub_coro


class TangoMonitor: # need to type hint this, inherit properly etc
    def __init__(self, callback):
        self.callback = callback
    



class TangoAttrR(TangoAttr, SignalR):
    print('Need to rewrite monitor_reading to use Monitor objects')
    async def monitor_reading(self, callback):
        # print('in observe reading')
        sub_id = await self.proxy.subscribe_event(self.signal_name, EventType.CHANGE_EVENT, callback)
        return sub_id


    _queues: Dict[asyncio.Queue, str] = {}
    async def monitor_reading_2(self, q: asyncio.Queue):
        if q not in self._queues:
            sub_id = await self.proxy.subscribe_event(self.signal_name, EventType.CHANGE_EVENT, q.put_nowait)
            self._queues[q] = sub_id
        return await q.get()
    
    async def monitor_value_2(self, q: asyncio.Queue):
        if q not in self._queues:
            sub_id = await self.proxy.subscribe_event(self.signal_name, EventType.CHANGE_EVENT, q.put_nowait)
            self._queues[q] = sub_id
        reading = await q.get()
        # print(reading)
        return reading.attr_value.value
    
    async def monitor_value(self, *args, **kwargs):
        return await self.monitor_value_2(*args, **kwargs)

    def close_monitor_2(self, q: asyncio.Queue):
        if q in self._queues:
            self.proxy.unsubscribe_event(self._queues[q])
            del self._queues[q]
    

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
        return {"value": attr_data.value, "timestamp": attr_data.time.totime()}

    async def get_descriptor(self) -> Descriptor:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return {"shape": self._get_shape(attr_data),
                "dtype": _get_dtype(attr_data),  # jsonschema types
                "source": self.source, }

    async def get_value(self):
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return attr_data.value


class TangoAttrW(TangoAttr, SignalW):
    latest_quality = None

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
    async def connect(self, dev_name: str, command: str):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = command
            self.proxy = await _get_proxy_from_dict(self.dev_name)
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
    # need an R and W superclass etc
    async def connect(self, dev_name: str, pipe: str):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = pipe
            self.proxy = await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_pipe(self.signal_name)
            except:
                raise Exception(f"Couldn't read pipe {self.signal_name}")
            self._connected = True


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
    def __new__(cls, comm: Optional[TangoComm] = None):
        instance = super().__new__(cls)
        if comm:
            return instance(comm)
        else:
            return instance
    def __await__(self):
        ...
  
    async def __call__(self, comm: TangoComm):
        self.comm = comm
        self.signals: Dict[str, TangoSignal] = {}
        for signal_name in get_type_hints(comm):
            signal = getattr(self.comm, signal_name)
            if not signal.connected:
                self.signals[signal_name] = signal
        if not self.signals:  # if dict empty
            return
        self.proxy = await _get_proxy_from_dict(comm.dev_name)
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
                    # print(f'Connecting unconnected signal "{signal_name}" to {self.comm.dev_name}:{attr_proper_name}')
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


class TangoDevice:
    # def __new__(cls, *args, **kwargs):
    #     if cls is TangoDevice:
    #         raise TypeError("Should not instantiate TangoDevice directly, use a non-generic subclass")
    #     instance = super().__new__(cls)
    #     return object.__new__(cls)
    def __init__(self, comm: TangoComm, name: Optional[str] = None):
        self.name = name or re.sub(r'[^a-zA-Z\d]', '-', comm.dev_name) # replace non alphanumeric characters with dash if name not set manually           
        self.comm = comm
        self.parent = None
        if self.__class__ is TangoDevice:
            raise TypeError(
                "Can not create instance of abstract TangoComm class")

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

    async def set_config_value_async(self, attr_name: str, value):
        attr: TangoAttrRW = getattr(self.comm, attr_name)
        await attr.put(value)

    def set_config_value(self, attr_name: str, value):
        call_in_bluesky_event_loop(
            self.set_config_value_async(attr_name, value))

class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW
    state: TangoAttrRW
    stop: TangoCommand

class TangoSingleAttributeDevice(TangoDevice):
    def __init__(self, dev_name, attr_name, name: Optional[str] = None):
        name = name or dev_name
        async def connectsingleattribute(comm):
            print('connectsingleattribute called')
            await comm.attribute.connect(dev_name, attr_name)
        class SingleComm(TangoComm):
            attribute: TangoAttrRW
            def __init__(self, dev_name: str):
                self.proxy: AsyncDeviceProxy  # should be set by a tangoconnector
                self.dev_name = dev_name
                self._signals_ = make_tango_signals(self)
                CommsConnector.schedule_connect(self)
            async def _connect_(self):
                await self.attribute.connect(dev_name, attr_name)

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


    def set_timeout(self, timeout):
        self._timeout = timeout
    
    @property
    def timeout(self):
        if hasattr(self, '_timeout'):
            return self._timeout
        else:
            return None

    def set(self, value, timeout: Optional[float] = None):
            # q = asyncio.Queue()

            # sub = self.comm.state.monitor_reading_value(q.put_nowait)
            # while True:
            #     _, val = await q.get()
            #     if val != DevState.MOVING:
            #         break
            # sub.close()
        timeout = timeout or self.timeout

        async def write_and_wait():
            pos = self.comm.position
            state = self.comm.state
            await pos.put(value)
            q = asyncio.Queue()
            sub = await state.monitor_reading(q.put_nowait)
            while True:
                state_reading= await q.get()
                if state_reading.attr_value.value != DevState.MOVING:
                    break
            state.proxy.unsubscribe_event(sub)

        async def write_and_wait_2():
            pos = self.comm.position
            state = self.comm.state
            await pos.put(value)
            q = asyncio.Queue()
            while True:
                state_value= await state.monitor_value_2(q)
                if state_value != DevState.MOVING:
                    break
            state.close_monitor_2(q)


        status = AsyncStatus(asyncio.wait_for(
            write_and_wait_2(), timeout=timeout))
        return status


def make_tango_signals(comm: TangoComm):
    hints = get_type_hints(comm)  # dictionary of names and types
    for signal_name in hints:
        signal = hints[signal_name]()
        setattr(comm, signal_name, signal)


@tango_connector
async def motorconnector(comm: TangoMotorComm):
    await asyncio.gather(
        comm.position.connect(comm.dev_name, "Position"),
        comm.velocity.connect(comm.dev_name, "Velocity"),
        comm.state.connect(comm.dev_name, "State"),
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

    def scan1():
        velocity = 1000
        for m in motors:
            m.set_config_value('velocity', velocity)
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
    

    with CommsConnector():
        single = TangoSingleAttributeDevice("motor/motctrl01/1", "Position", "mymotorposition")
    # print(dir(single.comm.attribute))
    RE(count([single]), LiveTable(["mymotorposition"]))
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