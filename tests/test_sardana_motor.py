from typing import OrderedDict
# import sys
# sys.path.append('../src/')
from ophyd_tango_devices.tango_devices import *
from ophyd_tango_devices.signals import *

import unittest
import asyncio
from PyTango import DeviceProxy, DevFailed  # type: ignore
from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy
from ophyd.v2.core import CommsConnector
from bluesky import RunEngine
from bluesky.run_engine import call_in_bluesky_event_loop
from typing import OrderedDict
import random
import bluesky.plan_stubs as bps
from bluesky.plans import count, scan
from bluesky.callbacks import LiveTable, LivePlot
import bluesky.utils


RE = RunEngine()

# @unittest.skip
class MotorTestReliesOnSardanaDemo(unittest.IsolatedAsyncioTestCase):
    #how do we ensure the run engine stops after this test case?
    #should we do setUp to instantiate motor or not?
    def setUp(self):
        self.dev_name = "motor/motctrl01/1"
        with CommsConnector():
            self.test_motor = motor(self.dev_name)

    def test_instantiate_motor(self):
        pass

    def test_motor_readable(self):
        reading = call_in_bluesky_event_loop(self.test_motor.read())
        assert isinstance(reading, dict)

    def test_motor_bluesky_movable(self):
        rand_number = random.random() + 1.0
        call_in_bluesky_event_loop(self.test_motor.configure('velocity', 1000))
        RE(bps.mv(self.test_motor, rand_number))

    async def test_motor_configurable(self):
        call_in_bluesky_event_loop(self.test_motor.configure('velocity', 1000))

    async def test_motor_scannable(self):
        call_in_bluesky_event_loop(self.test_motor.configure('velocity', 1000))
        RE(scan([], self.test_motor, 0, 5, 6))

    async def test_motor_timeout(self):
        async def move_to_zero_then_reduce_velocity():
            await self.test_motor.configure('velocity', 1000)
            await self.test_motor.set(0)
            self.test_motor.set_timeout(0.0000001)
            await self.test_motor.configure('velocity', 0.1)
        call_in_bluesky_event_loop(move_to_zero_then_reduce_velocity())
        with self.assertRaises(bluesky.utils.FailedStatus):
            rand_number = random.random() + 1.0
            RE(bps.mv(self.test_motor, rand_number))
        call_in_bluesky_event_loop(self.test_motor.configure('velocity', 1000))

        # need to find a better way to specify what exception
