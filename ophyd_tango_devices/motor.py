from .signals import (TangoAttrRW, TangoCommand, TangoComm,
                      tango_connector, ConnectWithoutReading)
from .devices import TangoDevice
from .proxy import DeviceProxy
from PyTango._tango import DevState  # type: ignore
from ophyd.v2.core import SignalCollection, AsyncStatus  # type: ignore
from bluesky.protocols import Movable
import re
import asyncio
from typing import Optional


class TangoMotorComm(TangoComm):
    position: TangoAttrRW
    velocity: TangoAttrRW
    state: TangoAttrRW
    stop: TangoCommand


class TangoMotor(TangoDevice, Movable):

    comm: TangoMotorComm

    @property
    def read_signals(self):
        return SignalCollection(position=self.comm.position)

    @property
    def conf_signals(self):
        return SignalCollection(velocity=self.comm.velocity)

    async def check_value(self, value):
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
def motor_connector(comm: TangoMotorComm, proxy: DeviceProxy):
    connector = ConnectWithoutReading(comm, proxy)
    connector(position="Position", velocity="Velocity",
              state="State", stop="Stop")


def tango_motor(dev_name: str, name: Optional[str] = None):
    name = name or re.sub(r'[^a-zA-Z\d]', '-', dev_name)
    c = TangoMotorComm(dev_name)
    return TangoMotor(c, name)
