from typing import OrderedDict
import sys
sys.path.append('../src/tangophyd')
from .tango_devices import TangoSignal, TangoAttr, motor

import unittest
import asyncio
from PyTango import DeviceProxy, DevFailed  # type: ignore
from ophyd.v2.core import CommsConnector
from bluesky import RunEngine 
from bluesky.run_engine import call_in_bluesky_event_loop
from typing import OrderedDict
import random
import bluesky.plan_stubs as bps
from bluesky.plans import count, scan
from bluesky.callbacks import LiveTable, LivePlot


class SignalTest(unittest.IsolatedAsyncioTestCase):
    def test_cant_instantiate_abstract_tango_signal(self):
        self.assertRaises(TypeError, TangoSignal)
    async def test_cant_connect_tango_attr_without_db(self):
        attr = TangoAttr()
        try:
            await attr.connect("non/existing/device", "attribute_name")
            raise Exception
        except DevFailed:
            pass #only way I could think to get around async assertions quickly
        #what should the exception type be??

class MotorTestReliesOnSardanaDemo(unittest.IsolatedAsyncioTestCase):
    RE = RunEngine()
    #how do we ensure the run engine stops after this test case?
    #should we do setUp to instantiate motor or not?
    def test_instantiate_motor(self):
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1")

    async def test_motor_readable(self):
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1")
        reading = call_in_bluesky_event_loop(test_motor.read())
        assert isinstance(reading, OrderedDict)

    def test_motor_config_writable(self):
        rand_number = random.random()
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1", "test_motor")
        # call_in_bluesky_event_loop(test_motor.set_config_value_async("velocity", rand_number))
        test_motor.set_config_value("velocity", rand_number)
        #this calls the async version in the bluesky loop
        reading = call_in_bluesky_event_loop(test_motor.read_configuration())
        assert reading["test_motor:Velocity"]['value'] == rand_number
    
    @unittest.skip
    def test_cant_set_non_config_attributes(self):
        rand_number = random.random()
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1", "test_motor")
        self.assertRaises(KeyError, test_motor.set_config_value, "position", rand_number)
        #this should complain, can't set slow settable (like a motor) attributes like this
        

    def test_read_in_RE(self):
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1", "test_motor")
        self.RE(bps.rd(test_motor))

    def test_count_in_RE_with_callback_named_attribute(self):
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1", "test_motor")
        self.RE(count([test_motor],1), LiveTable("test_motor:Position"))

    def test_motor_scans(self):
        rand_number = random.random() + 1.0
        with CommsConnector():
            test_motor = motor("motor/motctrl01/1", "test_motor")
        self.RE(scan([],test_motor,0,rand_number,2), LiveTable("test_motor:Position"))
        currentPos = call_in_bluesky_event_loop(test_motor.read())
        assert currentPos['test_motor:Position']['value'] == rand_number, "Final position does not equal set number"