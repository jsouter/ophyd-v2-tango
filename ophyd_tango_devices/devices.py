import re
from typing import Optional
from bluesky.protocols import Readable, Configurable
from ophyd.v2.core import SignalCollection  # type: ignore
from .signals import (TangoAttrRW, TangoPipeRW, TangoCommand,
                      TangoComm, tango_connector)


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
        self.parent = None
        self._name = name
        self._read_signals = SignalCollection(**{name: self.comm.attribute})


class TangoSingleCommandDevice(TangoDevice):
    _signal_prefix = ""

    def __init__(self, dev_name, attr_name: str, name: Optional[str] = None):
        name = name or attr_name

        class SingleCommandComm(TangoComm):
            command: TangoCommand

        @tango_connector
        async def connectcommand(comm: SingleCommandComm, proxy):
            await comm.command.connect(dev_name, attr_name, proxy)

        self.comm = SingleCommandComm(dev_name)
        self.parent = None
        self._name = name
        self._read_signals = SignalCollection(**{name: self.comm.command})

    def execute(self, value=None):
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
        self.parent = None
        self._name = name
        self._conf_signals = SignalCollection(**{name: self.comm.pipe})

    async def configure(self, value):
        '''Returns old result of read_configuration and new result of
           read_configuration. Pass a single argument, the new value for
           the Pipe.'''

        old_reading = await self.read_configuration()  # type: ignore
        await self.comm.pipe.put(value)
        new_reading = await self.read_configuration()  # type: ignore
        return (old_reading, new_reading)
