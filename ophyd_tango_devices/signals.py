from PyTango import DevFailed, EventData  # type: ignore
from PyTango._tango import (DevState,  # type: ignore
                            EventType, TimeVal)
import logging
from .proxy import TangoProxy, SimProxy, DeviceProxy
from typing import (Callable, Generic, TypeVar, get_type_hints, List,
                    Dict, Protocol, Type, Optional, Coroutine)
from ophyd.v2.core import CommsConnector  # type: ignore
from bluesky.protocols import Reading, Descriptor
from abc import ABC, abstractmethod
from bluesky.protocols import Dtype
from ophyd.v2.core import Signal, SignalR, SignalW, Comm
import numpy as np  # type: ignore
import asyncio
import re
from ophyd.v2.core import Monitor

_tango_dev_proxies: Dict[DeviceProxy, Dict[str, DeviceProxy]] = {}


class TangoDeviceNotFoundError(KeyError):
    ...


async def _get_device_proxy(
            dev_name: str,
            sim_mode: bool = False,
            proxy_dict=_tango_dev_proxies) -> DeviceProxy:
    proxy_class = TangoProxy if not sim_mode else SimProxy
    if proxy_class not in proxy_dict:
        proxy_dict[proxy_class] = {}
    if dev_name not in proxy_dict[proxy_class]:
        try:
            proxy_future = proxy_class(dev_name)
            proxy = await proxy_future
            proxy_dict[proxy_class][dev_name] = proxy
        except DevFailed or KeyError:
            raise TangoDeviceNotFoundError(
                f"Could not connect to {proxy_class} for {dev_name}")
    return proxy_dict[proxy_class][dev_name]


class TangoSignal(Signal, ABC):
    @abstractmethod
    async def connect(
            self, dev_name: str, signal_name: str,
            proxy: Optional[DeviceProxy] = None):
        self._proxy_: DeviceProxy
        self._dev_name: str
        self._signal_name: str
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
            self._source = (f'tango://{self._proxy_.get_db_host()}:'
                            f'{self._proxy_.get_db_port()}/{self._dev_name}'
                            f'/{self._signal_name}')
            if isinstance(self, TangoPipe):
                self._source += '(Pipe)'
            elif isinstance(self, TangoCommand):
                self._source += '(Command)'
            elif not isinstance(self, TangoAttr):
                raise TypeError(f'Can\'t determine source of TangoSignal'
                                f'object of class {self.__class__.__name__}')
        return self._source


class TangoSignalMonitor(Monitor):
    """
    TangoSignalMonitor(signal: TangoSignal)
    Callable with a single argument: callback, which gets called on the
    event data whenever there is an update to the Signal.
    close() is used to cancel the subscription and must be called manually
    when the desired end condition for monitoring is met.
    """
    def __init__(self, signal: TangoSignal):
        self.signal = signal
        self.sub_id = None

    async def __call__(self, callback=None):
        if not self.sub_id:
            self.sub_id = await self.signal._proxy_.subscribe_event(
                self.signal._signal_name, EventType.CHANGE_EVENT, callback)

    def close(self):
        self.signal._proxy_.unsubscribe_event(self.sub_id)
        self.sub_id = None


class TangoAttrReadError(KeyError):
    ...


class TangoAttr(TangoSignal):
    def __init__(self, *args, **kwargs):
        if self.__class__ is TangoAttr:
            raise TypeError(
                "Can not create instance of TangoAttr class")
    async def connect(self, dev_name: str, attr: str,
                      proxy: Optional[DeviceProxy] = None):
        '''Set the member variables proxy, dev_name and signal_name.
         May be called when no other connector used to connect signals'''
        if not self.connected:
            self._dev_name = dev_name
            self._signal_name = attr
            self._proxy_ = proxy or await _get_device_proxy(self._dev_name)
            try:
                await self._proxy_.read_attribute(attr)
            except DevFailed or KeyError:
                raise TangoAttrReadError(
                    f"Could not read attribute {self._signal_name}")
            self._connected = True


class _TangoMonitorableSignal(TangoSignal):
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

    def _get_dtype(self, attr_data) -> Dtype:
        '''Returns the appropriate JSON type for the value of a Tango signal
        reading from "string", "number", "array", "boolean" or "integer".'''
        value_class = type(attr_data.value)
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
                f"Descriptor dtype not implemented for attribute"
                f" {self._dev_name}/{self._signal_name}, type: {value_class}")

    async def get_reading(self) -> Reading:
        attr_data = await self._proxy_.read_attribute(self._signal_name)
        return Reading({"value": attr_data.value,
                        "timestamp": attr_data.time.totime()})

    async def get_descriptor(self) -> Descriptor:
        attr_data = await self._proxy_.read_attribute(self._signal_name)
        return Descriptor({"shape": self._get_shape(attr_data),
                           "dtype": self._get_dtype(attr_data),
                           "source": self.source, })

    async def get_value(self):
        attr_data = await self._proxy_.read_attribute(self._signal_name)
        return attr_data.value


class TangoAttrW(TangoAttr, SignalW):
    async def put(self, value):
        await self._proxy_.write_attribute(self._signal_name, value)

    async def get_quality(self):
        reading = await self._proxy_.read_attribute(self._signal_name)
        return reading.quality


class TangoAttrRW(TangoAttrR, TangoAttrW):
    ...


class TangoCommand(TangoSignal):
    async def connect(
            self, dev_name: str, command: str,
            proxy: Optional[DeviceProxy] = None):
        if not self.connected:
            self._dev_name = dev_name
            self._signal_name = command
            self._proxy_ = proxy or await _get_device_proxy(self._dev_name)
            commands = self._proxy_.get_command_list()
            assert self._signal_name in commands, \
                f"Command {command} not in list of commands"
            self._connected = True

    def execute(self, value=None):
        command_args = [arg for arg in [self._signal_name, value] if arg]
        return self._proxy_.command_inout(*command_args)


class TangoPipeReadError(KeyError):
    ...


class TangoPipe(TangoSignal):
    def __init__(self, *args, **kwargs):
        if self.__class__ is TangoPipe:
            raise TypeError(
                "Can not create instance of TangoPipe class")

    async def connect(
            self, dev_name: str, pipe: str,
            proxy: Optional[DeviceProxy] = None):
        if not self.connected:
            self._dev_name = dev_name
            self._signal_name = pipe
            self._proxy_ = proxy or await _get_device_proxy(self._dev_name)
            try:
                await self._proxy_.read_pipe(self._signal_name)
            except DevFailed or KeyError:
                raise TangoPipeReadError(
                    f"Couldn't read pipe {self._signal_name}")
            self._connected = True


class TangoPipeR(TangoPipe, _TangoMonitorableSignal, SignalR):
    async def get_reading(self) -> Reading:
        pipe_data = await self.get_value()
        return Reading({"value": pipe_data, "timestamp": TimeVal().now()})

    async def get_descriptor(self) -> Descriptor:
        # if we are returning the pipe it is a tuple with string
        # and list of dicts, so dimensionality 2
        return Descriptor({"shape": [2],
                           "dtype": "array",  # more accurately, "object"
                           "source": self.source, })

    async def get_value(self):
        pipe_data_or_future = self._proxy_.read_pipe(self._signal_name)
        if type(pipe_data_or_future) is tuple:
            return pipe_data_or_future
        else:
            return await pipe_data_or_future


class TangoPipeW(TangoPipe, SignalW):

    async def put(self, value):
        try:
            await self._proxy_.write_pipe(self._signal_name, value)
        except TypeError:
            self._proxy_.write_pipe(self._signal_name, value)


class TangoPipeRW(TangoPipeR, TangoPipeW):
    ...


class TangoComm(Comm):
    def __init__(self, dev_name: str):
        if self.__class__ is TangoComm:
            raise TypeError(
                "Can not create instance of TangoComm class")
        self._dev_name = dev_name
        self._signals_ = make_tango_signals(self)
        self._sim_mode = CommsConnector.in_sim_mode()
        self._connector = get_tango_connector(self)
        CommsConnector.schedule_connect(self)

    async def _connect_(self):
        proxy = await _get_device_proxy(
            self._dev_name, sim_mode=self._sim_mode)
        await self._connector(self, proxy)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(dev_name={self._dev_name!r})"


Signals = Dict[str, TangoSignal]


def make_tango_signals(comm: TangoComm):
    '''
    make_tango_signals(comm: TangoComm)
    Loops over type hinted signals in comm, sets attributes with the same
    name as the type hint as a member of comm, of the hinted type. Assigns the
    member variable "name" for each of these signals, to be accessed by the
    device for the purpose of generating globally unique signal names of the
    form "device_name:attr_name" to be passed to RunEngine callbacks.
    '''
    hints = get_type_hints(comm)  # dictionary of names and types
    signals: Signals = {}
    for name in hints:
        signal = hints[name]()
        setattr(comm, name, signal)
        signals[name] = signal
    return signals


TangoCommT = TypeVar("TangoCommT", bound=TangoComm, contravariant=True)


class TangoConnector(Protocol, Generic[TangoCommT]):

    async def __call__(self, comm: TangoCommT, proxy: DeviceProxy):
        ...


_tango_connectors: Dict[Type[TangoComm], TangoConnector] = {}


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


class ConnectSimilarlyNamed:
    '''
    ConnectSimilarlyNamed(comm: TangoComm, proxy: Optional[DeviceProxy])
    Connector class that checks DeviceProxy for similarly named signals to
    those unconnected in the comm object.
    The connector connects to attributes/pipes/commands that have identical
    names to the hinted signal name when lowercased and non alphanumeric
    characters are removed. e.g. the type hint "comm._position: TangoAttrRW"
    matches with the attribute "Position" on the DeviceProxy.
    Can be called like a function.
    '''
    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        return instance(*args, **kwargs)

    def __await__(self):
        ...

    async def __call__(self, comm: TangoComm,
                       proxy: Optional[DeviceProxy] = None):
        self.comm = comm
        self.unconnected: Dict[str, TangoSignal] = {}
        for signal_name in get_type_hints(comm):
            signal = getattr(self.comm, signal_name)
            if not signal.connected:
                self.unconnected[signal_name] = signal
        if not self.unconnected:  # if dict empty
            return
        self._proxy_ = proxy or await _get_device_proxy(comm._dev_name)
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
                signals = self._proxy_.get_attribute_list()
            elif isinstance(signal, TangoPipe):
                signals = self._proxy_.get_pipe_list()
            elif isinstance(signal, TangoCommand):
                signals = self._proxy_.get_command_list()
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
            coro = signal.connect(self.comm._dev_name,
                                  self.guesses[signal_type][name_guess],
                                  self._proxy_)
            self.coros.append(coro)
        else:
            raise ValueError(
                f"No named Tango signal found resembling '{name_guess}'"
                f" for type {signal_type.__name__}")


class ConnectWithoutReading:
    """
    ConnectWithoutReading(comm, proxy)
    Connects without reading any signals belonging the passed comm object, if
    a signal of the same signal_name is found in the Device Proxy's signal
    lists. Callable with keyword arguments where the keys are the names of the
    signals in the comm object and the values are the signal names as exported
    by the Tango device server. If not specified, the default signal name will
    be the object's Pythonic name.
    """
    def __init__(self, comm: TangoComm,
                 proxy: Optional[DeviceProxy] = None):
        self.comm = comm
        self._proxy_ = proxy
        self._attributes: List[str] = []
        self._commands: List[str] = []
        self._pipes: List[str] = []

    def __call__(self, **signal_names):
        connect = False
        hint_names = get_type_hints(self.comm).keys()
        for name in hint_names:
            if name not in signal_names:
                signal_names[name] = name
        for ophyd_name, signal_name in signal_names.items():
            signal = getattr(self.comm, ophyd_name)
            if isinstance(signal, TangoAttr):
                if not self._attributes:
                    self._attributes = self._proxy_.get_attribute_list()
                if signal_name in self._attributes:
                    connect = True
            elif isinstance(signal, TangoPipe):
                if not self._attributes:
                    self._pipes = self._proxy_.get_pipe_list()
                if signal_name in self._pipes:
                    connect = True
            elif isinstance(signal, TangoCommand):
                if not self._commands:
                    self._commands = self._proxy_.get_command_list()
                if signal_name in self._attributes:
                    connect = True
            if connect:
                signal._dev_name = self.comm._dev_name
                signal._signal_name = signal_name
                signal._proxy_ = self._proxy_
                signal._connected = True
            else:
                raise KeyError(f"{signal.__class__.__name__}"
                               f" {signal_name} not found")
