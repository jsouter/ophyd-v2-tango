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
set_device_proxy_class(MockDeviceProxy)

class MotorTestMockDeviceProxy(unittest.IsolatedAsyncioTestCase):
    '''Replaces the (Async)DeviceProxy object with the MockDeviceProxy class, so makes no outside calls to the network for Tango commands'''
    #may be a complication in creating a new RunEngine. Have to close the first one perhaps?
    def setUp(self):
        self.dev_name = "mock/device/name"
        with CommsConnector():
            self.test_motor = motor(self.dev_name)
    def test_instantiate_motor(self):
        pass

    def test_motor_readable(self):
        with CommsConnector():
            test_motor = motor(self.dev_name)
        reading = call_in_bluesky_event_loop(test_motor.read())
        assert isinstance(reading, OrderedDict)

    def test_motor_config_writable(self):
        rand_number = random.random()
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")       
        _, new_reading = call_in_bluesky_event_loop(test_motor.configure("velocity", rand_number))
        assert new_reading["test_motor:velocity"]['value'] == rand_number
    
    async def test_cant_set_non_config_attributes(self):
        rand_number = random.random()
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        with self.assertRaises(KeyError):
            await test_motor.configure("position", rand_number)
        #this should complain, can't set slow settable (like a motor) attributes like this

    def test_read_in_RE(self):
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        RE(bps.rd(test_motor))

    def test_count_in_RE(self):
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        RE(count([test_motor],1), print)

    def test_count_in_RE_with_callback_named_attribute(self):
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        RE(count([test_motor],1), LiveTable(["test_motor:position"]))

    def test_motor_bluesky_movable(self):
        rand_number = random.random() + 1.0
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        call_in_bluesky_event_loop(test_motor.configure('velocity', 1000))
        RE(bps.mv(test_motor, rand_number))
    
    async def test_motor_scans(self):
        rand_number = random.random() + 1.0
        with CommsConnector():
            test_motor = motor(self.dev_name, "test_motor")
        RE(scan([],test_motor,0,rand_number,2), LiveTable(["test_motor:position"]))
        currentPos = await test_motor.read()
        assert currentPos['test_motor:position']['value'] == rand_number, "Final position does not equal set number"
    
#not sure what the deal is with "1 comm not connected ... NoneType object is not iterable"
#think it's to do with connecttherest