from typing import OrderedDict
# import sys
# sys.path.append('../src/tangophyd')
from tango_devices import TangoComm, TangoDeviceNotFoundError, TangoPipeRW, TangoAttrR, TangoCommand, TangoSignal, \
    TangoAttr, motor, set_device_proxy_class, TangoSinglePipeDevice, TangoDevice, TangoDeviceNotFoundError

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

#should do some tests that operate on the Comm level etc too

#defaults to ConnectTheRest without connector
class ExampleComm(TangoComm):
    my_pipe: TangoPipeRW
    doubler: TangoCommand
    randomvalue: TangoAttrR

class ExampleDevice(TangoDevice):
    comm: ExampleComm # satisfies type checker
    async def read(self):
        return await self._read(self.comm.randomvalue)

    async def describe(self):
        return await self._describe(self.comm.randomvalue)

    async def read_configuration(self):
        return await self._read(self.comm.my_pipe)

    async def describe_configuration(self):
        return await self._describe(self.comm.my_pipe)

def example_device(dev_name):
    c = ExampleComm(dev_name)
    return ExampleDevice(c)

class SignalTest(unittest.IsolatedAsyncioTestCase):
    def test_cant_instantiate_abstract_tango_signal(self):
        self.assertRaises(TypeError, TangoSignal)
    async def test_cant_connect_tango_attr_without_db(self):
        attr = TangoAttr()
        with self.assertRaises(TangoDeviceNotFoundError):
            await attr.connect("non/existing/device", "attribute_name")
            

class ExampleDeviceTest(unittest.IsolatedAsyncioTestCase):
    #how do we ensure the run engine stops after this test case?
    #should we do setUp to instantiate motor or not?
    def setUp(self):
        self.dev_name = "tango/example/device"
        with CommsConnector():
            self.device = example_device(self.dev_name)

    def test_instantiate_device(self):
        pass

    def test_count(self):
        RE(count([self.device],1),print)

    async def test_read_pipe(self):
        await self.device.comm.my_pipe.get_value()
    
    async def test_write_pipe(self):
        pipedata = await self.device.comm.my_pipe.get_value()
        pipedata[1][0]['value'] = "how are you"
        print(1, pipedata[1][0])
        await self.device.comm.my_pipe.put(pipedata)
        reading2 = await self.device.comm.my_pipe.get_value()
        assert reading2[1][0]['value'] == "how are you"

        pipedata[1][0]['value'] = "not too bad"
        await self.device.comm.my_pipe.put(pipedata)
        reading2 = await self.device.comm.my_pipe.get_value()
        assert reading2[1][0]['value'] == "not too bad"
    
    def test_command_executed(self):
        number = random.random()
        doubled = self.device.comm.doubler.execute(number)
        assert doubled == 2 * number

    def test_command_fails_wrong_type(self):
        with self.assertRaises(DevFailed):
            self.device.comm.doubler.execute(None)