from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy  # type: ignore
from PyTango import DevFailed, EventData  # type: ignore
# from PyTango import DeviceProxy  # type: ignore
from PyTango._tango import (DevState, DevString,  # type: ignore
                            EventType, TimeVal)
import asyncio
import re
from ophyd.v2.core import AsyncStatus   # type: ignore
import logging

from typing import Callable, Generic, TypeVar, get_type_hints, Dict, Protocol,\
     Type, Coroutine, List, Optional
from ophyd.v2.core import CommsConnector
from bluesky.protocols import Reading, Descriptor, Movable, Readable,\
    Stageable, Triggerable, Configurable
from abc import ABC, abstractmethod
from collections import OrderedDict
from bluesky.protocols import Dtype
from ophyd.v2.core import Signal, SignalR, SignalW, Comm
from mockproxy import MockDeviceProxy
import numpy as np
from bluesky.run_engine import call_in_bluesky_event_loop
# from tango import set_green_mode, get_green_mode  # type: ignore
# from tango import GreenMode  # type: ignore

from ophyd.v2.core import Monitor


def _get_dtype(attribute) -> Dtype:
    '''Returns the appropriate JSON type for the value of a Tango signal
    reading from "string", "number", "array", "boolean" or "integer".'''
    value_class = type(attribute.value)
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
        raise NotImplementedError(
            f"dtype not implemented for type {value_class}"
            f" with attribute {attribute.name}"
            )


_tango_dev_proxies: Dict[str, AsyncDeviceProxy] = {}
_device_proxy_class = AsyncDeviceProxy


def set_device_proxy_class(
        klass: Type,
        proxy_dict: Dict[str, AsyncDeviceProxy] = _tango_dev_proxies):
    '''Sets the global variable _device_proxy_class which sets which class is
    used to instantiate proxy objects to the Tango device signals. Can be set
    to AsyncDeviceProxy or MockDeviceProxy for testing purposes. Calling this
    will also delete the dictionary proxy_dict which maps the Tango device
    names to proxy objects, by default this dictionary is the global
    _tango_dev_proxies. This should only be called once. '''
    # if hasattr(set_device_proxy_class, 'called'):
    #     print('has attr indeed')
    #     raise RuntimeError(
    #         "Function set_device_proxy_class should only be called once")
    # set_device_proxy_class.called = True  # type: ignore
    logging.warning('mypy doesn\'t like set_device_proxy_class.called')
    global _device_proxy_class
    logging.info('Resetting dev proxy dictionary')
    proxy_dict.clear()
    if klass == AsyncDeviceProxy or MockDeviceProxy:
        _device_proxy_class = klass
    else:
        raise ValueError(
            "Device proxy class must be one of"
            "AsyncDeviceProxy or MockDeviceProxy")


def get_device_proxy_class():
    global _device_proxy_class
    return _device_proxy_class


class TangoDeviceNotFoundError(KeyError):
    ...


async def _get_proxy_from_dict(
            dev_name: str,
            proxy_dict=_tango_dev_proxies) -> AsyncDeviceProxy:
    if dev_name not in proxy_dict:
        try:
            proxy_class = get_device_proxy_class()
            proxy_future = proxy_class(dev_name)
            proxy = await proxy_future
            proxy_dict[dev_name] = proxy
        except DevFailed:
            raise TangoDeviceNotFoundError(
                f"Could not connect to DeviceProxy for {dev_name}")
    return proxy_dict[dev_name]


class TangoSignalMonitor(Monitor):
    logging.warning('should we be able to use the same monitor twice?')

    def __init__(self, signal):
        self.proxy = signal.proxy
        self.signal_name = signal.signal_name
        self.sub_id = None

    async def __call__(self, callback=None):
        if not self.sub_id:
            self.sub_id = await self.proxy.subscribe_event(
                self.signal_name, EventType.CHANGE_EVENT, callback)

    def close(self):
        self.proxy.unsubscribe_event(self.sub_id)
        self.sub_id = None


class TangoSignal(Signal, ABC):
    @abstractmethod
    async def connect(
            self, dev_name: str, signal_name: str,
            proxy: Optional[AsyncDeviceProxy] = None):
        self.proxy: AsyncDeviceProxy
        self.dev_name: str
        self.signal_name: str
        ...
    _connected: bool = False
    _source: Optional[str] = None
    name: str  # set in make_tango_signals

    @property
    def connected(self):
        return self._connected

    @property
    def source(self) -> str:
        if not self._source:
            prefix = (f'tango://{self.proxy.get_db_host()}:'
                      f'{self.proxy.get_db_port()}/{self.dev_name}')
            if isinstance(self, TangoAttr):
                self._source = prefix + f'/{self.signal_name}'
            elif isinstance(self, TangoPipe):
                self._source = prefix + \
                    f':{self.signal_name}(Pipe)'
            elif isinstance(self, TangoCommand):
                self._source = prefix + \
                    f':{self.signal_name}(Command)'
            else:
                raise TypeError(f'Can\'t determine source of TangoSignal'
                                f'object of class {self.__class__}')
        return self._source


class TangoAttrReadError(KeyError):
    ...


class TangoAttr(TangoSignal):
    async def connect(self, dev_name: str, attr: str,
                      proxy: Optional[AsyncDeviceProxy] = None):
        '''Should set the member variables proxy, dev_name and signal_name.
         May be called when no other connector used to connect signals'''
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = attr
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_attribute(attr)
            except DevFailed:
                raise TangoAttrReadError(
                    f"Could not read attribute {self.signal_name}")
            self._connected = True


class _TangoMonitorableSignal:
    logging.warning("We should check that callbacks only run if there is a new"
                    "value. CHANGE_EVENT could be anything")

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


class TangoAttrR(TangoAttr, _TangoMonitorableSignal, SignalR):

    def _get_shape(self, reading):
        shape = []
        if reading.dim_y:  # For 2D arrays
            if reading.dim_x:
                shape.append(reading.dim_x)
            shape.append(reading.dim_y)
        elif reading.dim_x > 1:  # for 1D arrays
            # scalars should be returned as [], not [1]
            shape.append(reading.dim_x)
        return shape

    async def get_reading(self) -> Reading:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Reading({"value": attr_data.value,
                        "timestamp": attr_data.time.totime()})

    async def get_descriptor(self) -> Descriptor:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Descriptor({"shape": self._get_shape(attr_data),
                           "dtype": _get_dtype(attr_data),  # jsonschema types
                           "source": self.source, })

    async def get_value(self):
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return attr_data.value


class TangoAttrW(TangoAttr, SignalW):
    async def put(self, value):
        await self.proxy.write_attribute(self.signal_name, value)

    async def get_quality(self):
        reading = await self.proxy.read_attribute(self.signal_name)
        return reading.quality


class TangoAttrRW(TangoAttrR, TangoAttrW):
    ...


class TangoCommand(TangoSignal):
    async def connect(
            self, dev_name: str, command: str,
            proxy: Optional[AsyncDeviceProxy] = None):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = command
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            commands = self.proxy.get_command_list()
            assert self.signal_name in commands, \
                f"Command {command} not in list of commands"
            self._connected = True

    def execute(self, value=None):
        command_args = [arg for arg in [self.signal_name, value] if arg]
        return self.proxy.command_inout(*command_args)


class TangoPipeReadError(KeyError):
    ...


class TangoPipe(TangoSignal):
    async def connect(
            self, dev_name: str, pipe: str,
            proxy: Optional[AsyncDeviceProxy] = None):
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = pipe
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_pipe(self.signal_name)
            except DevFailed:
                raise TangoPipeReadError(
                    f"Couldn't read pipe {self.signal_name}")
            self._connected = True


class TangoPipeR(TangoPipe, _TangoMonitorableSignal, SignalR):
    logging.warning("manual timestamp for read_pipe")

    async def get_reading(self) -> Reading:
        pipe_data = self.proxy.read_pipe(self.signal_name)
        return Reading({"value": pipe_data, "timestamp": TimeVal().now()})

    async def get_descriptor(self) -> Descriptor:
        # pipe_data = self.proxy.read_pipe(self.signal_name)
        logging.warning("Reading is a list of dictionaries."
                        " Setting json dtype to array, though"
                        " 'object' is more appropriate")
        # if we are returning the pipe it is a name and list of blobs,
        # so dimensionality 2
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


class ConnectIfFound:
    # idea is to immediately set connected any signals that are found in
    # get_attribute_list etc even without trying to read them first
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        return instance(*args, **kwargs)

    def __await__(self):
        ...

    async def __call__(self, comm: TangoComm,
                       proxy: Optional[AsyncDeviceProxy] = None):
        self.proxy = proxy or await _get_proxy_from_dict(comm.dev_name)
        attributes = None
        pipes = None
        commands = None
        signals_list: List[str] = []
        for signal_name, signal_type in get_type_hints(comm).items():
            signal = getattr(comm, signal_name)
            if issubclass(signal_type, TangoAttr):
                if not attributes:
                    attributes = self.proxy.get_attribute_list()
                signals_list += attributes
            elif issubclass(signal_type, TangoPipe):
                if not pipes:
                    pipes = self.proxy.get_pipe_list()
                signals_list += pipes
            elif issubclass(signal_type, TangoCommand):
                if not commands:
                    commands = self.proxy.get_command_list()
                signals_list += commands
            else:
                raise TypeError(f"Type {signal_type} is not appropriate")
            if signal_name in signals_list:
                signal.signal_name = signal_name
                signal.proxy = self.proxy
                signal._connected = True
                signal.dev_name = comm.dev_name
            else:
                raise TypeError(f"Signal with name {signal_name} not found"
                                f" for type {signal_type}")


class ConnectSimilarlyNamed:
    '''
    ConnectSimilarlyNamed(comm: TangoComm, proxy: Optional[AsyncDeviceProxy])
    Connector class that checks DeviceProxy for similarly named signals to
    those unconnected in the comm object.
    The connector connects to attributes/pipes/commands that have identical
    names to the hinted signal name when lowercased and non alphanumeric
    characters are removed. e.g. the type hint "comm._position: TangoAttrRW"
    matches with the attribute "Position" on the DeviceProxy.
    Can be called like a function.
    '''
    logging.warning("does not work with mock device proxy")

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        return instance(*args, **kwargs)

    def __await__(self):
        ...

    async def __call__(self, comm: TangoComm,
                       proxy: Optional[AsyncDeviceProxy] = None):
        self.comm = comm
        self.unconnected: Dict[str, TangoSignal] = {}
        for signal_name in get_type_hints(comm):
            signal = getattr(self.comm, signal_name)
            if not signal.connected:
                self.unconnected[signal_name] = signal
        if not self.unconnected:  # if dict empty
            return
        self.proxy = proxy or await _get_proxy_from_dict(comm.dev_name)
        self.coros: List[Coroutine] = []
        self.guesses: Dict[str, Dict[str, str]] = {}
        for name, signal in self.unconnected.items():
            self.schedule_signal(signal, name)
        if self.coros:
            await asyncio.gather(*self.coros)

    @staticmethod
    def guess_string(signal_name):
        return re.sub(r'\W+', '', signal_name).lower()

    def make_guesses(self, signal):
        signal_type = type(signal)
        if signal_type not in self.guesses:
            self.guesses[signal_type] = {}
            # attribute (or pipe or command) names
            if isinstance(signal, TangoAttr):
                signals = self.proxy.get_attribute_list()
            elif isinstance(signal, TangoPipe):
                signals = self.proxy.get_pipe_list()
            elif isinstance(signal, TangoCommand):
                signals = self.proxy.get_command_list()
            else:
                return
            for sig in signals:
                name_guess = self.guess_string(sig)
                self.guesses[signal_type][name_guess] = sig
                # lowercased-alphanumeric names are keys,
                # actual attribute names are values

    def schedule_signal(self, signal, signal_name):
        signal_type = type(signal)
        self.make_guesses(signal)
        name_guess = self.guess_string(signal_name)
        if name_guess in self.guesses[signal_type]:  # if key exists
            attr_proper_name = self.guesses[signal_type][name_guess]
            coro = signal.connect(self.comm.dev_name, attr_proper_name)
            self.coros.append(coro)
        else:
            raise ValueError(
                f"No named Tango signal found resembling '{name_guess}'"
                f" for type {signal_type.__name__}")


def get_tango_connector(comm: TangoComm) -> TangoConnector:
    if type(comm) in _tango_connectors:  # .keys()
        return _tango_connectors[type(comm)]
    else:
        logging.info('Defaulting to "ConnectSimilarlyNamed()"')
        return ConnectSimilarlyNamed


def tango_connector(connector, comm_cls=None):
    if comm_cls is None:
        comm_cls = get_type_hints(connector)["comm"]
    _tango_connectors[comm_cls] = connector


class WrongNumberOfArgumentsError(TypeError):
    ...


class TangoDevice(Readable, Configurable):
    logging.warning("get_unique_name should probably belong to attr."
                    " Maybe we should use a setter or something")

    def __init__(self, comm: TangoComm, name: Optional[str] = None):
        self._name = name or re.sub(r'[^a-zA-Z\d]', '-', comm.dev_name)
        # replace non alphanumeric characters with dash
        # if name not set manually
        self.comm = comm
        self.parent = None
        if self.__class__ is TangoDevice:
            raise TypeError(
                "Can not create instance of abstract TangoComm class")

    @property
    def name(self):
        return self._name

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
            name = self.get_unique_name(attr)
            od[name] = description
        return od

    def get_unique_name(self, attr):
        # return self.name + ':' + attr.signal_name
        return self.name + ':' + attr.name

    async def configure(self, *args):
        '''Returns old result of read_configuration and new result of
        read_configuration. Pass an arbitrary number of pairs of args where the
        first arg is the attribute name as a string and the second arg is the
        new value of the attribute'''
        logging.warning('Need to decide whether we look for the Python'
                        'attribute name or Tango attribute name')
        logging.warning('single pipe returns empty ordereddicts because'
                        ' we are counting the pipe as a read field not a'
                        ' read_config field')

        if len(args) % 2:  # != 0
            raise WrongNumberOfArgumentsError(
                "configure can not parse an odd number of arguments")
        old_reading = await self.read_configuration()  # type: ignore
        for attr_name, value in zip(args[0::2], args[1::2]):
            attr = getattr(self.comm, attr_name)
            unique_name = self.get_unique_name(attr)
            if unique_name not in old_reading:
                raise KeyError(
                    f"The attribute {unique_name} is not "
                    "designated as configurable"
                    )
            await attr.put(value)
        new_reading = await self.read_configuration()  # type: ignore
        return (old_reading, new_reading)


class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW
    state: TangoAttrRW
    stop: TangoCommand


class TangoSingleAttributeDevice(TangoDevice):
    def __init__(self, dev_name, attr_name, name: Optional[str] = None):
        name = name or attr_name

        class SingleComm(TangoComm):
            attribute: TangoAttrRW
            # replace Position with attribute when done testing
        logging.warning("TangoSingle__Device maybe shouldnt have"
                        " SingleComm defined inside class, not sure"
                        " how this namespaces with the dictionary")

        @tango_connector
        async def connectattribute(comm: SingleComm):
            await comm.attribute.connect(dev_name, attr_name)

        self.comm = SingleComm(dev_name)
        super().__init__(self.comm, name)

    async def read(self):
        reading = await self.comm.attribute.get_reading()
        return OrderedDict({self.name: reading})

    async def describe(self):
        descriptor = await self.comm.attribute.get_descriptor()
        return OrderedDict({self.name: descriptor})

    async def read_configuration(self):
        return await self._read()

    async def describe_configuration(self):
        return await self._describe()


class TangoSinglePipeDevice(TangoDevice):
    def __init__(self, dev_name, pipe_name, name: Optional[str] = None):
        name = name or pipe_name

        class SinglePipeComm(TangoComm):
            pipe: TangoPipeRW

        @tango_connector
        async def connectpipe(comm: SinglePipeComm):
            await comm.pipe.connect(dev_name, pipe_name)

        self.comm = SinglePipeComm(dev_name)
        super().__init__(self.comm, name)

    async def read(self):
        reading = await self.comm.pipe.get_reading()
        return OrderedDict({self.name: reading})

    async def describe(self):
        descriptor = await self.comm.pipe.get_descriptor()
        return OrderedDict({self.name: descriptor})

    async def read_configuration(self):
        return await self._read()

    async def describe_configuration(self):
        return await self._describe()


logging.warning("Should TangoMotor inherit from TangoMovableDevice?")


# class TangoMotor(TangoDevice, Movable, Stageable):
class TangoMotor(TangoDevice, Movable):
    comm: TangoMotorComm  # satisfies type checker
    logging.warning('can not use in event loop because it has to make an async'
                    'call itself')

    @property
    def position(self):
        reading = call_in_bluesky_event_loop(self.read())
        name = self.get_unique_name(self.comm.position)
        return reading[name]['value']
        # A heuristic that describes the current position of a device as a
        # single scalar, as opposed to the potentially multi-valued description
        # provided by read(). Optional: bluesky itself does not use the
        #  position attribute, but other parts of the ecosystem might.
        # Developers are encouraged to implement this attribute where possible.

    async def read(self):
        return await self._read(self.comm.position)

    async def describe(self):
        return await self._describe(self.comm.position)

    async def read_configuration(self):
        return await self._read(self.comm.velocity)

    async def describe_configuration(self):
        return await self._describe(self.comm.velocity)

    async def check_value(self, value):
        # should this include timeout even if it does nothing?
        # how do we check it's not a string
        config = await self.comm.position.proxy.get_attribute_config(
            self.comm.position.name)
        if not isinstance(config.min_value, str):
            assert value >= config.min_value, f"Value {value} is less than"\
                                              f" min value {config.min_value}"
        if not isinstance(config.max_value, str):
            assert value <= config.max_value, f"Value {value} is greater than"\
                                              f" max value {config.max_value}"

    # this should probably be changed, use a @timeout.setter
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
            await self.check_value(value)
            await self.comm.position.put(value)
            q = asyncio.Queue()
            monitor = await self.comm.state.monitor_value(q.put_nowait)
            while True:
                state_value = await q.get()
                if state_value != DevState.MOVING:
                    monitor.close()
                    break
        status = AsyncStatus(asyncio.wait_for(
            write_and_wait(), timeout=timeout))
        return status


def make_tango_signals(comm: TangoComm):
    '''
    make_tango_signals(comm: TangoComm)
    Loops over type hinted signals in comm, sets attributes with the same
    name as the type hint as a member of comm, of the hinted type. Assigns the
    member variable "name" for each of these signals, to be accessed by the
    device for the purpose of generating globally unique signal names of the
    form "device_name:attr_name" to be passed to RunEngine callbacks.
    '''
    logging.warning('setting name in make_tango_signals')
    hints = get_type_hints(comm)  # dictionary of names and types
    for name in hints:
        signal = hints[name]()
        signal.name = name
        setattr(comm, name, signal)


@tango_connector
async def motorconnector(comm: TangoMotorComm):
    proxy = await _get_proxy_from_dict(comm.dev_name)
    await asyncio.gather(
        comm.position.connect(comm.dev_name, "Position", proxy),
        comm.velocity.connect(comm.dev_name, "Velocity", proxy),
        comm.state.connect(comm.dev_name, "State", proxy),
    )
    await ConnectSimilarlyNamed(comm, proxy)


def motor(dev_name: str, name: Optional[str] = None):
    name = name or re.sub(r'[^a-zA-Z\d]', '-', dev_name)
    c = TangoMotorComm(dev_name)
    return TangoMotor(c, name)


def tango_devices_main():
    # from bluesky.run_engine import get_bluesky_event_loop
    from bluesky.run_engine import RunEngine
    from bluesky.plans import count, scan
    import time
    # from tango import set_green_mode, get_green_mode # type: ignore
    # from tango import GreenMode # type: ignore
    # import bluesky.plan_stubs as bps
    from bluesky.callbacks import LiveTable
    # from bluesky.callbacks import LivePlot
    from bluesky.run_engine import call_in_bluesky_event_loop

    # set_green_mode(GreenMode.Asyncio)
    # set_green_mode(GreenMode.Gevent)

    RE = RunEngine({})
    with CommsConnector():
        motor1 = motor("motor/motctrl01/1", "motor1")
        motor2 = motor("motor/motctrl01/2", "motor2")
        motor3 = motor("motor/motctrl01/3", "motor3")
        motor4 = motor("motor/motctrl01/4", "motor4")
        motors = [motor1, motor2, motor3, motor4]

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
                table_args += ['motor'+str(j+1)+':position']
            thetime = time.time()
            RE(scan([], *scan_args, 11), LiveTable(table_args))
            # RE(scan([], *scan_args, 11))
            print('scan' + str(i+1), time.time() - thetime)

    def scan2():
        print('with 2 motors:')
        for i in range(10):
            thetime = time.time()
            RE(scan([], motor1, 0, 1, motor2, 0, 1, 10*i+1))
            print('steps' + str(10*i+1), time.time() - thetime)
        print('with 4 motors:')
        for i in range(10):
            thetime = time.time()
            RE(scan([], motor1, 0, 1, motor2, 0, 1, motor3,
                    0, 1, motor4, 0, 1, 10*i+1))
            print('steps' + str(10*i+1), time.time() - thetime)
        for i in range(4):
            scan_args = []
            table_args = []
            for j in range(i+1):
                scan_args += [motors[j]]
                table_args += ['motor'+str(j+1)+':position']
            thetime = time.time()
            # RE(count(scan_args,11), LiveTable(table_args))
            RE(count(scan_args, 11))
            print('count' + str(i+1), time.time() - thetime)

    # scan1()
    # scan2()

    with CommsConnector():
        single = TangoSingleAttributeDevice("motor/motctrl01/1", "Position",
                                            "mymotorposition")
        singlepipe = TangoSinglePipeDevice("tango/example/device", "my_pipe",
                                           "mypipe")

    RE(count([single]), LiveTable(["mymotorposition"]))
    # RE(count([single, singlepipe]), print)
    # RE(count([singlepipe]), print)
    # reading = call_in_bluesky_event_loop(q.get())
    # print(reading)
    # print(call_in_bluesky_event_loop(motor1.configure('velocity',100)))

    async def check_pipe_configured():
        reading = await singlepipe.read()
        print(reading)
        await singlepipe.configure('pipe', ('hello',
                                   [{'name': 'test', 'dtype': DevString,
                                     'value': 'how are you'},
                                    {'name': 'test2', 'dtype': DevString,
                                     'value': 'test2'}]))
        reading = await singlepipe.read()
        print(reading)
        await singlepipe.configure('pipe', ('hello',
                                   [{'name': 'test', 'dtype': DevString,
                                     'value': 'yeah cant complain'},
                                    {'name': 'test2', 'dtype': DevString,
                                     'value': 'test2'}]))
        reading = await singlepipe.read()
        print(reading)

    # a =call_in_bluesky_event_loop(motor1.comm.position.get_reading())
    # print("position", a)
    # call_in_bluesky_event_loop(check_pipe_configured())
    # print(get_green_mode())
    # monitor1 = call_in_bluesky_event_loop(
    # motor1.comm.position.monitor_reading(print))
    # monitor1.close()
    # monitor2 = call_in_bluesky_event_loop(
    # motor1.comm.position.monitor_value(print))
    # monitor2.close()

    # set_device_proxy_class(MockDeviceProxy)
    # set_device_proxy_class(MockDeviceProxy)

    print(id(motor1.comm.position.proxy) == id(motor1.comm.velocity.proxy))
    print(motor1.comm.position.source)


if __name__ in "__main__":
    tango_devices_main()
