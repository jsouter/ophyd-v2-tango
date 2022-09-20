from src.ophyd_tango_devices.mockproxy import *

async def mockproxymain1():
    global m
    m = await MockDeviceProxy("mock/device/name")
    # print(await d.read_attribute("Position"))
    # print(await d.read_attribute("Position"))

    # sub1 = await m.subscribe_event("State", EventType.CHANGE_EVENT, q1.put_nowait)
    # print(f"sub={sub1}")
    # sub2 = await m.subscribe_event("Velocity", EventType.CHANGE_EVENT, q2.put_nowait)
    # print(f"sub={sub2}")
    # # m.unsubscribe_event(sub2)
    # reading1 = await q1.get()
    # reading2 = await q2.get()
    # m.unsubscribe_event(sub1)
    # print(reading1, reading2)

    q1 = asyncio.Queue()
    q2 = asyncio.Queue()
    sub1 = await m.subscribe_event("Velocity", EventType.CHANGE_EVENT, q1.put_nowait)
    sub2 = await m.subscribe_event("Position", EventType.CHANGE_EVENT, q2.put_nowait)
    while True:
        await m.write_attribute("Velocity", random.random())
        await m.write_attribute("Position", random.random())
        await asyncio.sleep(0.5)
        val1 = (await q1.get()).value
        val2 = (await q2.get()).value
        print(val1,val2)
        if val2 > 0.7:
            print('too far, lets break this loop!')
            m.unsubscribe_event(sub1)
            m.unsubscribe_event(sub2)
            break # is there a command to check "if subscription active?"


        # b = m._read_attribute_sync("Velocity")
        # print(b)

    #dont think _active_subscriptions is thread safe? doesnt seem to update in the process loop
    #threads maybe work better
    #sub_id gets successfully returned but only the first loop actually starts
    #with multiprocessing both loops start but the q1.get() never finishes waiting. idk why...


def mockproxymain2():
    from ophyd_tango_devices.tango_devices import motor
    from ophyd_tango_devices.signals import get_device_proxy_class, set_device_proxy_class
    from ophyd.v2.core import CommsConnector
    from bluesky import RunEngine
    import bluesky.plan_stubs as bps
    from bluesky.plans import count, scan
    from bluesky.callbacks import LiveTable
    from bluesky.run_engine import call_in_bluesky_event_loop
    from PyTango import DeviceProxy as TestDeviceProxy
    RE=RunEngine()

    
    set_device_proxy_class(MockDeviceProxy)
    print(f"device proxy class is set to : {get_device_proxy_class()}")

    with CommsConnector():
        b = motor("mock/device/name", "b")
    # print(call_in_bluesky_event_loop(b.describe()))
    #dev_attr is getting set but maybe ophyd doesn't know what to do with dev_attrs? it should do!
    # RE(bps.rd(b), LiveTable(["b:Position"]))

    # print(TestDeviceProxy("motor/motctrl01/1").read_attribute("Position"))
    RE(count([b],1), LiveTable(["b-position"]))
    def print2(doc):
        print(f"printing the thing: {doc}")

    # call_in_bluesky_event_loop(b.comm.position.proxy.subscribe_event("Position", EventType.CHANGE_EVENT, print2))
    RE(bps.mv(b, 5))
    #why cant we use bluesky mv on the device using mock device proxy?
    RE(scan([],b,0,1,3), LiveTable(["b-position"]))

def mockproxymain3():
    from ophyd_tango_devices.tango_devices import motor
    from ophyd_tango_devices.signals import get_device_proxy_class, set_device_proxy_class
    from ophyd.v2.core import CommsConnector
    from bluesky import RunEngine
    import bluesky.plan_stubs as bps
    from bluesky.plans import count, scan
    from bluesky.callbacks import LiveTable
    from bluesky.run_engine import call_in_bluesky_event_loop
    from PyTango import DeviceProxy as TestDeviceProxy
    RE=RunEngine()    
    set_device_proxy_class(MockDeviceProxy)
    print(f"device proxy class is set to : {get_device_proxy_class()}")

    with CommsConnector():
        b = motor("mock/device/name", "b")



if __name__ in "__main__":

    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(mockproxymain1())
    mockproxymain2()
    # print(d)
    # print(m)