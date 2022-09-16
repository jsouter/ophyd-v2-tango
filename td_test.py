from ophyd_tango_devices.tango_devices import *
from ophyd_tango_devices.signals import *
from ophyd.v2.core import CommsConnector


def tango_devices_main():
    # from bluesky.run_engine import get_bluesky_event_loop
    from bluesky.run_engine import RunEngine
    from bluesky.plans import count, scan
    import time
    # from tango import set_green_mode, get_green_mode # type: ignore
    # from tango import GreenMode # type: ignore
    # import bluesky.plan_stubs as bps
    from bluesky.callbacks import LiveTable
    # from bluesky.callbacks import LivePlot
    from bluesky.run_engine import call_in_bluesky_event_loop

    # set_green_mode(GreenMode.Asyncio)
    # set_green_mode(GreenMode.Gevent)

    RE = RunEngine({})
    with CommsConnector():
        motor1 = motor("motor/motctrl01/1", "motor1")
        motor2 = motor("motor/motctrl01/2", "motor2")
        motor3 = motor("motor/motctrl01/3", "motor3")
        motor4 = motor("motor/motctrl01/4", "motor4")
        motors = [motor1, motor2, motor3, motor4]

    def scan1():
        velocity = 1000
        for m in motors:
            call_in_bluesky_event_loop(m.configure('velocity', velocity))

            # m.set_timeout(0.0001)
        for i in range(4):
            scan_args = []
            table_args = []
            for j in range(i+1):
                scan_args += [motors[j], 0, 1]
                table_args += ['motor'+str(j+1)+'-position']
            thetime = time.time()
            RE(scan([], *scan_args, 11), LiveTable(table_args))
            # RE(scan([], *scan_args, 11))
            print('scan' + str(i+1), time.time() - thetime)

    def scan2():
        print('with 2 motors:')
        for i in range(10):
            thetime = time.time()
            RE(scan([], motor1, 0, 1, motor2, 0, 1, 10*i+1))
            print('steps' + str(10*i+1), time.time() - thetime)
        print('with 4 motors:')
        for i in range(10):
            thetime = time.time()
            RE(scan([], motor1, 0, 1, motor2, 0, 1, motor3,
                    0, 1, motor4, 0, 1, 10*i+1))
            print('steps' + str(10*i+1), time.time() - thetime)
        for i in range(4):
            scan_args = []
            table_args = []
            for j in range(i+1):
                scan_args += [motors[j]]
                table_args += ['motor'+str(j+1)+'-position']
            thetime = time.time()
            # RE(count(scan_args,11), LiveTable(table_args))
            RE(count(scan_args, 11))
            print('count' + str(i+1), time.time() - thetime)

    scan1()
    # scan2()

    with CommsConnector():
        single = TangoSingleAttributeDevice("motor/motctrl01/1", "Position",
                                            "mymotorposition")
        singlepipe = TangoSinglePipeDevice("tango/example/device", "my_pipe",
                                           "mypipe")

    RE(count([single]), LiveTable(["mymotorposition"]))
    # RE(count([single, singlepipe]), print)
    # RE(count([singlepipe]), print)
    # reading = call_in_bluesky_event_loop(q.get())
    # print(reading)
    # print(call_in_bluesky_event_loop(motor1.configure('velocity',100)))

    async def check_single_attr():
        reading = await single.read()
        desc = await single.describe()
        print("reading: ", reading, "desc: ", desc)

    async def check_pipe_configured():
        await singlepipe.configure(
            ('hello',
             [{'name': 'test', 'dtype': DevString,
               'value': 'how are you'},
              {'name': 'test2', 'dtype': DevString,
               'value': 'test2'}]))
        old, new = await singlepipe.configure(
            ('hello',
             [{'name': 'test', 'dtype': DevString,
               'value': 'yeah cant complain'},
              {'name': 'test2', 'dtype': DevString,
               'value': 'test2'}]))
        print(old, new)
        # nonconfigreading = await singlepipe.read_configuration()
        # print(nonconfigreading)


    # call_in_bluesky_event_loop(check_single_attr())
    # call_in_bluesky_event_loop(check_pipe_configured())

    # print(get_green_mode())
    # monitor1 = call_in_bluesky_event_loop(
    # motor1.comm.position.monitor_reading(print))
    # monitor1.close()
    # monitor2 = call_in_bluesky_event_loop(
    # motor1.comm.position.monitor_value(print))
    # monitor2.close()

    # set_device_proxy_class(MockDeviceProxy)
    # set_device_proxy_class(MockDeviceProxy)
    print(id(motor1.comm.position.proxy), id(motor1.comm.velocity.proxy), id(motor1.comm.state.proxy), id(motor1.comm.stop.proxy))
    print(id(motor1.comm.position.proxy) == id(motor1.comm.velocity.proxy))
    # print(motor1.comm.position.source)
    # print(_tango_dev_proxies)
    with CommsConnector():
        my_doubler = TangoSingleCommandDevice("tango/example/device", "doubler", "doobler")
    my_doubler.execute_command(2)

if __name__ in "__main__":
    tango_devices_main()
