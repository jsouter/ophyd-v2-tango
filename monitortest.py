from tango_devices import TangoSignalMonitor, motor
from ophyd.v2.core import CommsConnector
from bluesky import RunEngine
from bluesky.run_engine import call_in_bluesky_event_loop
from bluesky.plans import count
from bluesky.callbacks import LiveTable

RE=RunEngine()
with CommsConnector():
    m = motor("motor/motctrl01/1", "m")
# a = TangoSignalMonitor(m.comm.position)

the_value = call_in_bluesky_event_loop(m.comm.position.monitor_value())
# the_value = call_in_bluesky_event_loop(m.comm.position.monitor_reading_3())
print(f"the value is {the_value}")

RE(count([m], 1), LiveTable(["m:Position"]))