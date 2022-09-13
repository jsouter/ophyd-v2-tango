from typing import OrderedDict
# import sys
# sys.path.append('../src/tangophyd')
from tango_devices import TangoComm, TangoDeviceNotFoundError, TangoPipeRW,TangoAttrRW, TangoAttrR, TangoCommand, TangoSignal, \
    TangoAttr, motor, set_device_proxy_class, TangoSinglePipeDevice, TangoDevice

import unittest
import asyncio
from PyTango import DeviceProxy, DevFailed  # type: ignore
from PyTango.asyncio import DeviceProxy as AsyncDeviceProxy
from ophyd.v2.core import CommsConnector
from bluesky import RunEngine 
from bluesky.run_engine import call_in_bluesky_event_loop
import random
import bluesky.plan_stubs as bps
from bluesky.plans import count, scan
from PyTango._tango import AttrQuality



RE = RunEngine()
set_device_proxy_class(AsyncDeviceProxy)
# should do some tests that operate on the Comm level etc too
# defaults to ConnectTheRest without connector


class ExampleComm(TangoComm):
    my_pipe: TangoPipeRW
    doubler: TangoCommand
    randomvalue: TangoAttrR
    array: TangoAttrRW
    limitedvalue: TangoAttrRW


class ExampleDevice(TangoDevice):
    comm: ExampleComm  # satisfies type checker

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
    
    # @unittest.skip("breaks lower tests for some reason")
    def test_cant_connect_tango_attr_without_db(self):
        attr = TangoAttr()
        with self.assertRaises(TangoDeviceNotFoundError):
            call_in_bluesky_event_loop(attr.connect("non/existing/device", "attribute_name"))


    def test_connect_without_CM(self):
        attr = TangoAttr()
        assert attr.connected == False
        assert not hasattr(attr, 'proxy')
        assert not hasattr(attr, 'dev_name')
        assert not hasattr(attr, 'signal_name')
        call_in_bluesky_event_loop(attr.connect("tango/example/device", "randomvalue"))
        assert attr.connected == True
        assert hasattr(attr, 'proxy')
        assert hasattr(attr, 'dev_name')
        assert hasattr(attr, 'signal_name')

    def test_connected_only_after_CM(self):
        dev_name = "tango/example/device"
        with CommsConnector():
            device = example_device(dev_name)
            assert device.comm.randomvalue.connected == False
        assert device.comm.randomvalue.connected == True

    async def test_get_reading(self):
        dev_name = "tango/example/device"
        with CommsConnector():
            device = example_device(dev_name)
        call_in_bluesky_event_loop(device.comm.randomvalue.get_reading())

    def test_get_descriptor(self):
        dev_name = "tango/example/device"
        with CommsConnector():
            device = example_device(dev_name)
        call_in_bluesky_event_loop(device.comm.randomvalue.get_descriptor())


class ExampleDeviceTest(unittest.IsolatedAsyncioTestCase):
    # how do we ensure the run engine stops after this test case?
    # should we do setUp to instantiate motor or not?
    def setUp(self):
        self.dev_name = "tango/example/device"
        with CommsConnector():
            self.device = example_device(self.dev_name)

    def test_instantiate_device(self):
        pass

    def test_count(self):
        RE(count([self.device], 1))
        # RE(count([self.device],1),print)

    async def test_read_pipe(self):
        await self.device.comm.my_pipe.get_value()

    async def test_write_pipe(self):
        pipedata = await self.device.comm.my_pipe.get_value()
        pipedata[1][0]['value'] = "how are you"
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

    async def test_read_array(self):
        call_in_bluesky_event_loop(self.device.comm.array.get_value())
        # not sure why its now failing to read attributes for this device.
        # something about cant await  device attribute or something

    def test_read_write_array(self):
        async def read_write():
            array = await self.device.comm.array.get_value()
            print("array: ", array)
            array = [[random.random(), random.random()],
                     [random.random(), random.random()]]
            await self.device.comm.array.put(array)
            array = await self.device.comm.array.get_value()
            # print("array: ", array)
        call_in_bluesky_event_loop(read_write())

    def test_valid_quality(self):
        async def do_move_get_quality():
            config = await self.device.comm.limitedvalue.proxy.get_attribute_config("limitedvalue")
            alarms = config.alarms
            await self.device.comm.limitedvalue.put(0.5*(float(alarms.min_warning)+float(alarms.max_warning)))
            quality = await self.device.comm.limitedvalue.get_quality()
            assert quality == AttrQuality.ATTR_VALID

    def test_warning_quality(self):
        async def do_move_get_quality():
            config = await self.device.comm.limitedvalue.proxy.get_attribute_config("limitedvalue")
            alarms = config.alarms
            await self.device.comm.limitedvalue.put(0.5*(float(alarms.min_alarm)+float(alarms.min_warning)))
            quality = await self.device.comm.limitedvalue.get_quality()
            assert quality == AttrQuality.ATTR_WARNING
            call_in_bluesky_event_loop(do_move_get_quality())

    def test_alarm_quality(self):
        async def do_move_get_quality():
            config = await self.device.comm.limitedvalue.proxy.get_attribute_config("limitedvalue")
            alarms = config.alarms
            await self.device.comm.limitedvalue.put(0.5*(float(config.min_value)+float(alarms.min_alarm)))
            quality = await self.device.comm.limitedvalue.get_quality()
            assert quality == AttrQuality.ATTR_ALARM
            call_in_bluesky_event_loop(do_move_get_quality())

    def test_cant_move_out_of_bounds(self):
        async def do_move_get_quality():
            config = await self.device.comm.limitedvalue.proxy.get_attribute_config("limitedvalue")
            with self.assertRaises(DevFailed):
                await self.device.comm.limitedvalue.put(float(config.min_value) - 1)
        call_in_bluesky_event_loop(do_move_get_quality())
