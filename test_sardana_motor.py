from typing import OrderedDict
# import sys
# sys.path.append('../src/tangophyd')
from tango_devices import TangoSignal, TangoAttr, motor, set_device_proxy_class, TangoSinglePipeDevice

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
from mockproxy import MockDeviceProxy


RE = RunEngine()
set_device_proxy_class(AsyncDeviceProxy)

# @unittest.skip
class MotorTestReliesOnSardanaDemo(unittest.IsolatedAsyncioTestCase):
    #how do we ensure the run engine stops after this test case?
    #should we do setUp to instantiate motor or not?
    def setUp(self):
        self.dev_name = "motor/motctrl01/1"

    def test_instantiate_motor(self):
        with CommsConnector():
            test_motor = motor(self.dev_name)

    def test_motor_readable(self):
        with CommsConnector():
            test_motor = motor(self.dev_name)
        reading = call_in_bluesky_event_loop(test_motor.read())
        assert isinstance(reading, OrderedDict)

    def test_motor_bluesky_movable(self):
        rand_number = random.random() + 1.0
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        call_in_bluesky_event_loop(test_motor.configure('velocity', 1000))
        RE(bps.mv(test_motor, rand_number))

    async def test_motor_configurable(self):
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        call_in_bluesky_event_loop(test_motor.configure('velocity', 1000))

    async def test_motor_scannable(self):
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        call_in_bluesky_event_loop(test_motor.configure('velocity', 1000))
        RE(scan([], test_motor, 0, 5, 6))

    async def test_motor_timeout(self):
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        async def move_to_zero_then_reduce_velocity():
            await test_motor.configure('velocity', 1000)
            await test_motor.set(0)
            test_motor.set_timeout(0.0000001)
            await test_motor.configure('velocity', 0.1)
        call_in_bluesky_event_loop(move_to_zero_then_reduce_velocity())
        with self.assertRaises(bluesky.utils.FailedStatus):
            rand_number = random.random() + 1.0
            RE(bps.mv(test_motor,rand_number))
        call_in_bluesky_event_loop(test_motor.configure('velocity', 1000))

        #need to find a better way to specify what exception


# class ExampleDeviceTests(unittest.IsolatedAsyncioTestCase):
#     async def test_read_pipe(self):
#         with CommsConnector():
#             singlepipe = TangoSinglePipeDevice("tango/example/device", "my_pipe", "mypipe")
#         a = call_in_bluesky_event_loop(singlepipe.read())
#         print(a)