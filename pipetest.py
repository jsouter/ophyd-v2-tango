from src.ophyd_tango_devices.signals import *
from src.ophyd_tango_devices.tango_devices import *
from bluesky import RunEngine
from bluesky.run_engine import call_in_bluesky_event_loop
RE = RunEngine()

with CommsConnector():
    pipey = TangoSinglePipeDevice("tango/example/device", "my_pipe")

async def do():
    reading = await pipey.read()
    print(reading)
    reading = await pipey.read_configuration()
    print(reading)
    readpipedirectly = await pipey.comm.pipe.get_reading()
    print(readpipedirectly)
    readpipeindirectly = await pipey.comm.pipe.proxy.read_pipe("my_pipe")
    print(readpipeindirectly)

#whyyy does it work here but not in the unit tests

call_in_bluesky_event_loop(do())