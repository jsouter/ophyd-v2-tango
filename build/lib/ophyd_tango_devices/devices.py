from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy  # type: ignore
from PyTango import DevFailed, EventData  # type: ignore
# from PyTango import DeviceProxy  # type: ignore
from PyTango._tango import (DevState, DevString,  # type: ignore
                            EventType, TimeVal)
import asyncio
import re
import logging
from typing import Callable, Generic, TypeVar, get_type_hints, Dict, Protocol,\
     Type, Coroutine, List, Optional
from bluesky.protocols import (Reading, Descriptor, Movable, Readable,
                            #    Stageable, Triggerable,
                               Configurable)
# from collections import OrderedDict
from bluesky.run_engine import call_in_bluesky_event_loop
from ophyd.v2.core import SignalCollection, AsyncStatus
from .signals import (_get_proxy_from_dict, TangoAttr,  # type: ignore
                      TangoAttrR, TangoAttrW,
                      TangoAttrRW, TangoPipe, TangoPipeR, TangoPipeW,
                      TangoPipeRW, TangoCommand, TangoComm, tango_connector,
                      TangoSignal, ConnectSimilarlyNamed)
# from tango import set_green_mode, get_green_mode  # type: ignore
# from tango import GreenMode  # type: ignore


class WrongNumberOfArgumentsError(TypeError):
    ...


class TangoConfigurable(Configurable):
    async def configure(self, *args):
        '''Returns old result of read_configuration and new result of
        read_configuration. Pass an arbitrary number of pairs of args where the
        first arg is the attribute name as a string and the second arg is the
        new value of the attribute'''
        if len(args) % 2:  # != 0
            raise WrongNumberOfArgumentsError(
                "configure() can not parse an odd number of arguments")
        old_reading = await self.read_configuration()  # type: ignore
        for attr_name, value in zip(args[0::2], args[1::2]):
            attr = getattr(self.comm, attr_name)
            unique_name = self._get_unique_name(attr_name)
            if unique_name not in old_reading:
                raise KeyError(
                    f"The attribute {unique_name} is not "
                    "designated as configurable"
                    )
            await attr.put(value)
        new_reading = await self.read_configuration()  # type: ignore
        return (old_reading, new_reading)


class TangoDevice(Readable, TangoConfigurable):

    def __init__(self, comm: TangoComm, name: Optional[str] = None):
        self._name = name
        # replace non alphanumeric characters with dash
        # if name not set manually
        self.comm = comm
        self.parent = None
        if self.__class__ is TangoDevice:
            raise TypeError(
                "Can not create instance of abstract TangoComm class")

    @property
    def signal_prefix(self):
        return getattr(self, '_signal_prefix', self.name + "-")

    @property
    def conf_signals(self):
        return getattr(self, '_conf_signals', SignalCollection())

    @property
    def read_signals(self):
        return getattr(self, '_read_signals', SignalCollection())

    @property
    def name(self):
        if not self._name:
            self._name = re.sub(r'[^a-zA-Z\d]', '-', self.comm._dev_name)
        return self._name

    async def read(self):
        return await self.read_signals.read(self.signal_prefix)

    async def describe(self):
        return await self.read_signals.describe(self.signal_prefix)

    async def read_configuration(self):
        return await self.conf_signals.read(self.signal_prefix)

    async def describe_configuration(self):
        return await self.conf_signals.describe(self.signal_prefix)

    def _get_unique_name(self, signal_name):
        return self.signal_prefix + signal_name


class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW
    state: TangoAttrRW
    stop: TangoCommand


class TangoSingleAttributeDevice(TangoDevice):
    _signal_prefix = ""

    def __init__(self, dev_name, attr_name: str, name: Optional[str] = None):
        name = name or attr_name

        class SingleComm(TangoComm):
            attribute: TangoAttrRW

        @tango_connector
        async def connectattribute(comm: SingleComm, proxy):
            await comm.attribute.connect(dev_name, attr_name, proxy)

        self.comm = SingleComm(dev_name)
        self._read_signals = SignalCollection(**{name: self.comm.attribute})
        super().__init__(self.comm, name)


class TangoSingleCommandDevice(TangoDevice):
    _signal_prefix = ""

    def __init__(self, dev_name, attr_name: str, name: Optional[str] = None):
        name = name or attr_name

        class SingleComm(TangoComm):
            command: TangoCommand

        @tango_connector
        async def connectcommand(comm: SingleComm, proxy):
            await comm.command.connect(dev_name, attr_name, proxy)

        self.comm = SingleComm(dev_name)
        self._read_signals = SignalCollection(**{name: self.comm.command})
        super().__init__(self.comm, name)

    def execute_command(self, value=None):
        return self.comm.command.execute(value)


class TangoSinglePipeDevice(TangoDevice, Configurable):

    _signal_prefix = ""

    def __init__(self, dev_name, pipe_name: str, name: Optional[str] = None):
        name = name or pipe_name

        class SinglePipeComm(TangoComm):
            pipe: TangoPipeRW

        @tango_connector
        async def connectpipe(comm: SinglePipeComm, proxy):
            await comm.pipe.connect(dev_name, pipe_name, proxy)

        self.comm = SinglePipeComm(dev_name)
        self._conf_signals = SignalCollection(**{name: self.comm.pipe})
        super().__init__(self.comm, name)

    async def configure(self, value):
        '''Returns old result of read_configuration and new result of
           read_configuration. Pass a single argument, the new value for
           the Pipe.'''

        old_reading = await self.read_configuration()  # type: ignore
        await self.comm.pipe.put(value)
        new_reading = await self.read_configuration()  # type: ignore
        return (old_reading, new_reading)


class TangoMotor(TangoDevice, Movable):

    comm: TangoMotorComm

    @property
    def read_signals(self):
        return SignalCollection(position=self.comm.position)

    @property
    def conf_signals(self):
        return SignalCollection(velocity=self.comm.velocity)

    logging.warning('write_and_wait should have stricter requirements than'
                    ' the value not being DevState.MOVING')

    async def check_value(self, value):
        # should this include timeout even if it does nothing?
        # how do we check it's not a string
        config = await self.comm.position._proxy_.get_attribute_config(
            self.comm.position.name)
        if not isinstance(config.min_value, str):
            assert value >= config.min_value, f"Value {value} is less than"\
                                              f" min value {config.min_value}"
        if not isinstance(config.max_value, str):
            assert value <= config.max_value, f"Value {value} is greater than"\
                                              f" max value {config.max_value}"

    @property
    def timeout(self):
        return getattr(self, '_timeout', None)

    def set_timeout(self, timeout):
        self._timeout = timeout

    def set(self, value, timeout: Optional[float] = None):
        timeout = timeout or self.timeout

        async def write_and_wait():
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


@tango_connector
async def motor_connector(comm: TangoMotorComm, proxy):
    proxy = proxy or await _get_proxy_from_dict(comm._dev_name)
    await asyncio.gather(
        comm.position.connect(comm._dev_name, "Position", proxy),
        comm.velocity.connect(comm._dev_name, "Velocity", proxy),
        comm.state.connect(comm._dev_name, "State", proxy),
    )
    await ConnectSimilarlyNamed(comm, proxy)


def motor(dev_name: str, name: Optional[str] = None):
    name = name or re.sub(r'[^a-zA-Z\d]', '-', dev_name)
    c = TangoMotorComm(dev_name)
    return TangoMotor(c, name)
