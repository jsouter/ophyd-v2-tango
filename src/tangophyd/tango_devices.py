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

# from mockproxy import MockDeviceProxy


def _get_dtype(attribute) -> Dtype:
    # https://pytango.readthedocs.io/en/v9.3.4/data_types.html
    value_class = attribute.value.__class__
    if value_class is float:
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


async def _get_proxy_from_dict(device: str) -> AsyncDeviceProxy:
    if device not in _tango_dev_proxies:
        try:
            proxy_future = AsyncDeviceProxy(device)
            proxy = await proxy_future
        except DevFailed:
            raise DevFailed(f"Could not connect to DeviceProxy for {device}")
        _tango_dev_proxies[device] = proxy
    return _tango_dev_proxies[device]


class TangoSignal(Signal):
    @abstractmethod
    async def connect(self, dev_name: str, signal_name: str):
        pass
    
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
            # self.sync_proxy = DeviceProxy(self.dev_name)
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



class TangoAttrR(TangoAttr, SignalR):
    print('Need to implement observe_reading for TangoAttrR')
    print('Not happy with how observe_reading is implemented. '
    'supposed to return async generator but it returns a sub id')
    async def observe_reading(self, callback):
        print('in observe reading')
        sub_id = await self.proxy.subscribe_event(self.signal_name, EventType.CHANGE_EVENT, callback)
        return sub_id
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

    def sync_get_reading(self):
        attr_data = self.sync_proxy.read_attribute(self.signal_name)
        return {"value": attr_data.value, "timestamp": attr_data.time.totime()}

    def sync_get_descriptor(self):
        attr_data = self.sync_proxy.read_attribute(self.signal_name)
        return {"shape": self._get_shape(attr_data),
                "dtype": _get_dtype(attr_data),  # jsonschema types
                "source": self.source, }


class TangoAttrW(TangoAttr, SignalW):
    latest_quality = None

    async def put(self, value):
        await self.proxy.write_attribute(self.signal_name, value)

    async def get_quality(self):
        reading = await self.proxy.read_attribute(self.signal_name)
        return reading.quality

    def sync_wait_for_valid_quality(self):
        def record_quality(doc):
            self.latest_quality = doc.attr_value.quality
        sub = self.sync_proxy.subscribe_event(
            self.signal_name, EventType.CHANGE_EVENT, record_quality)
        while True:
            if self.latest_quality == AttrQuality.ATTR_VALID:
                self.sync_proxy.unsubscribe_event(sub)
                return
                
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
        self.__signals__ = make_tango_signals(self)
        self._connector = get_tango_connector(self)
        CommsConnector.schedule_connect(self)

    async def __connect__(self):
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
    def __new__(cls, arg: Optional[TangoComm] = None):
        instance = super().__new__(cls)
        if arg:
            return instance(arg)
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
        # self.sync_proxy = DeviceProxy(comm.dev_name)
        # print('Adding sync_proxy in ConnectTheRest')
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


# async def get_proxy(dev_name):
#     proxy = await AsyncDeviceProxy(dev_name)
#     await _get_proxy_from_dict(dev_name)
#     print(f'Adding dev name {dev_name} to proxy dict')
#     return proxy


class TangoDevice:
    def __init__(self, comm: TangoComm, name: Optional[str] = None):
        self.comm = comm
        self.parent = None
        self.name = name or re.sub(r'[^a-zA-Z\d]', '-', comm.dev_name) # replace non alphanumeric characters with dash if name not set manually

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

    def sync_read(self, *to_read):
        od = OrderedDict()
        for attr in to_read:
            reading = attr.sync_get_reading()
            name = self.name + ':' + attr.signal_name
            od[name] = reading
        return od

    def sync_describe(self, *to_desc):
        od = OrderedDict()
        for attr in to_desc:
            description = attr.sync_get_descriptor()
            name = self.name + ':' + attr.signal_name
            od[name] = description
        return od


class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW
    state: TangoAttrRW
    stop: TangoCommand


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

    async def set_config_value_async(self, attr_name: str, value):
        attr: TangoAttrRW = getattr(self.comm, attr_name)
        await attr.put(value)

    def set_config_value(self, attr_name: str, value):
        call_in_bluesky_event_loop(
            self.set_config_value_async(attr_name, value))

    def set(self, value, timeout: Optional[float] = None):


            # q = asyncio.Queue()

            # sub = self.comm.state.monitor_reading_value(q.put_nowait)
            # while True:
            #     _, val = await q.get()
            #     if val != DevState.MOVING:
            #         break
            # sub.close()

        async def write_and_wait():
            pos = self.comm.position
            state = self.comm.state
            await pos.put(value)
            q = asyncio.Queue()
            sub = await state.observe_reading(q.put_nowait)
            while True:
                state_reading= await q.get()
                if state_reading.attr_value.value != DevState.MOVING:
                    break
            state.proxy.unsubscribe_event(sub)
            print('kind of works but should be using Monitor object?')

        #     # await pos.wait_for_not_moving()
        #     event = asyncio.Event()
        #     async def set_event(reading):
        #         state_value = reading.attr_value.value
        #         if state_value != DevState.MOVING:
        #             event.set()
        #     sub_id = await state.observe_reading(set_event)
        #     await event.wait()
        #     state.proxy.unsubscribe_event(sub_id)

            # pos.sync_wait_for_valid_quality()
        status = AsyncStatus(asyncio.wait_for(
            write_and_wait(), timeout=timeout))
        return status


class SyncTangoMotor(TangoMotor):
    def read(self):
        return self.sync_read(self.comm.position)

    def describe(self):
        return self.sync_describe(self.comm.position)



# def get_attrs_from_hints(comm: TangoComm):
#     hints = get_type_hints(comm)
#     return {signal_name: getattr(comm, signal_name) for signal_name in hints}


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
    )
    await ConnectTheRest(comm)


def motor(dev_name: str, ophyd_name: Optional[str] = None):
    ophyd_name = ophyd_name or re.sub(r'[^a-zA-Z\d]', '-', dev_name)
    c = TangoMotorComm(dev_name)
    return TangoMotor(c, ophyd_name)


def syncmotor(dev_name: str, ophyd_name: str):
    c = TangoMotorComm(dev_name)
    return SyncTangoMotor(c, ophyd_name)


# if __name__ == "__main__":
def main():
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
        # motor1 = syncmotor("motor/motctrl01/1", "motor1")
        # motor2 = syncmotor("motor/motctrl01/2", "motor2")
        # motor3 = syncmotor("motor/motctrl01/3", "motor3")
        # motor4 = syncmotor("motor/motctrl01/4", "motor4")
        motor1 = motor("motor/motctrl01/1", "motor1")
        motor2 = motor("motor/motctrl01/2", "motor2")
        motor3 = motor("motor/motctrl01/3", "motor3")
        motor4 = motor("motor/motctrl01/4", "motor4")
        motors = [motor1, motor2, motor3, motor4]
    # print(call_in_bluesky_event_loop(motor1.describe()))
    # RE(count([motor1],num=10,delay=None), LiveTable(['motor1:Position']))
    # print(call_in_bluesky_event_loop(motor1.describe()))
    # print(call_in_bluesky_event_loop(motor1.set(0)))
    print(sys.path)
    from cbtest import mycallback

    velocity = 1000
    for m in motors:
        m.set_config_value('velocity', velocity)
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

    # print('with 2 motors:')
    # for i in range(10):
    #     thetime = time.time()
    #     RE(scan([],motor1,0,1,motor2,0,1,10*i+1))
    #     print('steps' +str(10*i+1),time.time() - thetime)
    # print('with 4 motors:')
    # for i in range(10):
    #     thetime = time.time()
    #     RE(scan([],motor1,0,1,motor2,0,1,motor3,0,1,motor4,0,1,10*i+1))
    #     print('steps' +str(10*i+1),time.time() - thetime)
    # for i in range(4):
    #     scan_args = []
    #     table_args = []
    #     for j in range(i+1):
    #         scan_args += [motors[j]]
    #         table_args += ['motor'+str(j+1)+':Position']
    #     thetime = time.time()
    #     # RE(count(scan_args,11), LiveTable(table_args))
    #     RE(count(scan_args,11))
    #     print('count' +str(i+1),time.time() - thetime)

    # RE(scan([],motor1,0,1,motor2,10,101,11), mycallback(['motor1:Position', 'motor2:Position']))


# def main2():
#     from bluesky.run_engine import get_bluesky_event_loop
#     from bluesky.run_engine import RunEngine
#     from bluesky.plans import count, scan
#     import time
#     from tango import set_green_mode, get_green_mode # type: ignore
#     from tango import GreenMode # type: ignore
#     import bluesky.plan_stubs as bps
#     from bluesky.callbacks import LiveTable, LivePlot
#     from bluesky.run_engine import call_in_bluesky_event_loop
#     import timeit

#     RE = RunEngine()
#     global _get_proxy_from_dict
#     _true_proxy_dict = _get_proxy_from_dict
#     async def _get_mock_proxy(device: str) -> MockDeviceProxy:
#         if device not in _tango_dev_proxies:
#             try:
#                 mock_proxy_future = MockDeviceProxy(device)
#                 proxy = await mock_proxy_future
#                 # print(proxy)
#             except DevFailed:
#                 raise Exception(f"Could not connect to DeviceProxy for {device}")
#             _tango_dev_proxies[device] = proxy
#         return _tango_dev_proxies[device]
#     _get_proxy_from_dict = _get_mock_proxy
#     with CommsConnector():
#         device = motor("my/device/name", "device")
#         print('ConnectTheRest messes things up somehow')
#     print(device.comm.position.proxy)
#     # loop = asyncio.new_event_loop()
#     # print(get_bluesky_event_loop())
#     # print(loop.run_until_complete(device.comm.position.proxy.write_attribute("Position",5)))
#     # print(loop.run_until_complete(device.comm.position.proxy.read_attribute("Position")))
#     # print(get_bluesky_event_loop())

#     RE(count([device],11))
    

if __name__ in "__main__":
    main()
    # python3 -m cProfile -o test.prof tango_devices.py
    # snakeviz test.prof
    # import cProfile
    # cProfile.run('main()', sort='cumtime')
    # cProfile.run('main()', sort='tottime')
