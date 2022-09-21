from src.ophyd_tango_devices.signals import *
from src.ophyd_tango_devices.tango_devices import *
from src.ophyd_tango_devices.mockproxy import *
from bluesky import RunEngine
from bluesky.run_engine import call_in_bluesky_event_loop
from bluesky.plans import count, scan
from src.ophyd_tango_devices.simproxy import *
from bluesky.callbacks import LiveTable
RE = RunEngine()
import random

with CommsConnector(sim_mode=True):
    sim_motor = motor("mock/device/name", "sim_motor")

RE(count([sim_motor]), LiveTable(["sim_motor-position"]))
RE(scan([], sim_motor, 0, 1, 3), LiveTable(["sim_motor-position"]))

async def get_sp():
    sp = await SimProxy("mock/device/name")
    await sp.write_attribute("Position", random.random())

    blah = await sp.read_attribute("Position")
    print(blah)


call_in_bluesky_event_loop(get_sp())

# with CommsConnector(sim_mode=False):
#     real_motor = motor("motor/motctrl01/1", "real_motor")
# RE(count([real_motor]), LiveTable(["real_motor-position"]))


# async def get_read():
#     blah = await real_motor.comm.position.proxy.read_attribute("Position")
#     print(blah)
# call_in_bluesky_event_loop(get_read())

# # RE(count([real_motor]), print)