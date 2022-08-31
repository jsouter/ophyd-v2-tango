from matplotlib.pyplot import connect
from PyTango.asyncio import AttributeProxy as AsyncAttributeProxy  # type: ignore
from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy  # type: ignore
from PyTango import DeviceProxy  # type: ignore
from PyTango._tango import DevState, AttrQuality, EventType  # type: ignore
import asyncio
import re
from ophyd.v2.core import AsyncStatus  # type: ignore

from typing import Callable, get_type_hints, Dict, Protocol, Union, Type, Coroutine, List, Any, Optional
from ophyd.v2.core import CommsConnector
from abc import ABC, abstractmethod
from collections import OrderedDict
from bluesky.run_engine import get_bluesky_event_loop
from bluesky.run_engine import call_in_bluesky_event_loop


def _get_dtype(attribute) -> str:
    # https://pytango.readthedocs.io/en/v9.3.4/data_types.html
    # see above for examples of what the dtypes are expected to be. e.g. "int32" -> this fn needs work
    # or is that just on the server end?? bluesky doesnt need this level of information
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
        raise NotImplementedError(
            f"dtype not implemented for {value_class} with attribute {attribute.name}")
    return json_type


_tango_dev_proxies: Dict[str, AsyncDeviceProxy] = {}


async def _get_proxy_from_dict(device: str) -> AsyncDeviceProxy:
    if device not in _tango_dev_proxies:
        try:
            proxy_future = AsyncDeviceProxy(device)
            proxy = await proxy_future
        except:
            raise Exception(f"Could not connect to DeviceProxy for {device}")
        _tango_dev_proxies[device] = proxy
    return _tango_dev_proxies[device]


class TangoSignal(ABC):
    @abstractmethod
    async def connect(self, dev_name: str, signal_name: str):
        pass

    @property
    def connected(self):
        if not hasattr(self, '_connected'):
            self._connected = False
        return self._connected


class TangoAttr(TangoSignal):
    async def connect(self, dev_name: str, attr: str):
        '''Should set the member variables proxy and signal_name. May be called when no other connector used to connect signals'''
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = attr
            self.proxy = await _get_proxy_from_dict(self.dev_name)
            self.sync_proxy = DeviceProxy(self.dev_name)
            try:
                await self.proxy.read_attribute(attr)
            except:
                raise Exception(f"Could not read attribute {self.signal_name}")
            self._connected = True


class TangoAttrR(TangoAttr):
    def _get_shape(self, reading):
        shape = []
        if reading.dim_y:  # For 2D arrays
            if reading.dim_x:
                shape.append(reading.dim_x)
            shape.append(reading.dim_y)
        elif reading.dim_x > 1:  # for 1D arrays
            shape.append(reading.dim_x)
        return shape

    @property
    def source(self):
        if not hasattr(self, '_source'):
            self._source = (f'tango://{self.proxy.get_db_host()}:'
                            f'{self.proxy.get_db_port()}/'
                            f'{self.dev_name}/{self.signal_name}')
        return self._source

    async def get_reading(self):
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return {"value": attr_data.value, "timestamp": attr_data.time.totime()}

    async def get_descriptor(self):
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


def passer(*args, **kwargs):
    pass


class TangoAttrRW(TangoAttrR):
    latest_quality = None

    async def write(self, value):
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

class TangoCommand(TangoSignal):
    async def connect(self, dev_name: str, command: str):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = command
            self.proxy = await _get_proxy_from_dict(self.dev_name)
            commands = self.proxy.command_list_query()
            cmd_names = [c.cmd_name for c in commands]
            assert self.signal_name in cmd_names, \
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


class TangoComm(ABC):
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


# _tango_connectors: Dict[Type[TangoComm], TangoConnector]  = {}
_tango_connectors: Dict[Type[TangoComm], Callable] = {}
print('fix type hint for _tango_connectors')

class ConnectTheRest:
    print('rewrite so that we can call as we instantiate and have type checker be happy.')
    # def __new__(cls, arg=None):
    #     print('doing a weird thing in __new__ to make the class act like a function')
    #     instance = super().__new__(cls)
    #     if arg is None:
    #         return instance
    #     else:
    #         return instance(arg)

    async def __call__(self, comm: TangoComm):
        self.comm = comm

        # signals = get_attrs_from_hints(self.comm)
        # self.signals2 = {signal: signals[signal] for signal in signals if signals[signal].connected}
        # above is single line but maybe less clear

        self.signals = get_attrs_from_hints(self.comm)
        for signal in self.signals.copy():
            if self.signals[signal].connected:
                del self.signals[signal]
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
            if issubclass(signal.__class__, self.signal_types[signal_type]['baseclass']):
                self.make_guesses(signal_type)
                name_guess = self.guess_string(signal_name)
                if name_guess in self.guesses[signal_type]:  # if key exists
                    attr_proper_name = self.guesses[signal_type][name_guess]
                    # print(f'Connecting unconnected signal "{signal_name}" to {self.comm.dev_name}:{attr_proper_name}')
                    coro = signal.connect(self.comm.dev_name, attr_proper_name)
                    self.coros.append(coro)
                break  # prevents unnecessary checks: e.g. if attribute, dont check for pipe


def get_tango_connector(comm: TangoComm) -> Callable:
    if type(comm) in _tango_connectors:  # .keys()
        return _tango_connectors[type(comm)]
    else:
        print('Defaulting to "ConnectTheRest()"')
        return ConnectTheRest()


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
        await attr.write(value)

    def set_config_value(self, attr_name: str, value):
        call_in_bluesky_event_loop(
            self.set_config_value_async(attr_name, value))

    def set(self, value, timeout: Optional[float] = None):
        async def write_and_wait():
            pos = self.comm.position
            await pos.write(value)
            # q = asyncio.Queue()

            # sub = self.comm.state.monitor_reading_value(q.put_nowait)
            # while True:
            #     _, val = await q.get()
            #     if val != DevState.MOVING:
            #         break
            # sub.close()

            await pos.wait_for_not_moving()
            # pos.sync_wait_for_valid_quality()
            # await pos.wait_for_status()
            # quality = await pos.get_quality()
            # while quality != AttrQuality.ATTR_VALID:
            # quality = await pos.get_quality()
        status = AsyncStatus(asyncio.wait_for(
            write_and_wait(), timeout=timeout))
        return status


class SyncTangoMotor(TangoMotor):
    def read(self):
        return self.sync_read(self.comm.position)

    def describe(self):
        return self.sync_describe(self.comm.position)



def get_attrs_from_hints(comm: TangoComm):
    hints = get_type_hints(comm)
    return {signal_name: getattr(comm, signal_name) for signal_name in hints}


def make_tango_signals(comm: TangoComm):
    hints = get_type_hints(comm)  # dictionary of names and types
    for signal_name in hints:
        signal = hints[signal_name]()
        setattr(comm, signal_name, signal)


# @tango_connector
async def motorconnector(comm: TangoMotorComm):
    await asyncio.gather(
        comm.position.connect(comm.dev_name, "Position"),
        comm.velocity.connect(comm.dev_name, "Velocity"),
    )
    await ConnectTheRest()(comm)


def motor(dev_name: str, ophyd_name: str):
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
    from tango import set_green_mode, get_green_mode
    from tango import GreenMode
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


if __name__ in "__main__":
    main()
    # python3 -m cProfile -o test.prof tango_devices.py
    # snakeviz test.prof
    # import cProfile
    # cProfile.run('main()', sort='cumtime')
    # cProfile.run('main()', sort='tottime')
