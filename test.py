from PyTango.asyncio import DeviceProxy
from PyTango._tango import EventType, AttrQuality
import time
import asyncio
from bluesky.run_engine import call_in_bluesky_event_loop
from bluesky import RunEngine as RE

RE()

async def get_proxy():
    return await DeviceProxy("motor/motctrl01/1")

b = asyncio.run(get_proxy())
print(b)
moving = True
def do(doc):
    global moving
    if doc.attr_value.quality == AttrQuality.ATTR_VALID:
        moving = False
    else:
        moving = True

async def createsub(proxy):
    return proxy.subscribe_event('Position', EventType.CHANGE_EVENT, do)


c = call_in_bluesky_event_loop(createsub(b))

# c = asyncio.run(b.subscribe_event('Position', EventType.CHANGE_EVENT, do))
# while True:
#     time.sleep(1)
#     if moving:
#         print(moving)
#     else:
#         pass
