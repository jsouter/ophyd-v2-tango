Essentially all communication between Ophyd and Tango occurs through a "device proxy." In this implementation, this means the use of the DeviceProxy class imported from the PyTango.asyncio module; this is an alternative mode that implements, at least partially, asynchronous methods for the I/O operations. To generalise, the async Tango DeviceProxy class has been renamed TangoProxy inside ophyd_tango_devices, and DeviceProxy is the name of the Protocol which alternative proxy classes must implement.
proxy.py contains then this definition of TangoProxy and a limited implementation of a simulated proxy called SimProxy, which implements all the methods called by other parts of the ophyd_tango_devices, returning dummy values and which makes no actual calls to the Tango device server.

The SimProxy hold the attributes Position, State and Velocity, and the command Stop, resembling the signals of the Sardana style TangoMotor in ophyd_tango_devices.motor. It must be instantiated with the device name "mock/device/name" or a KeyError will be raised. 

Each TangoSignal subclass instance belonging to an Ophyd device's TangoComm has a member variable "proxy" which points to the same instance of the DeviceProxy instantiated with the single argument for the Tango device name of the form "domain/family/member." The major methods for reading and writing to the various Tango signals are:

+ read_attribute
+ write_attribute
+ read_pipe
+ write_pipe
+ command_inout_asynch
+ command_inout

each of which returns a Future that must be awaited. Each method takes as its first argument the name of the signal to interact with, meaning that technically, if misconfigured, each signal's DeviceProxy can be used to read or write with any other signal on the same device, though this should not happen if using ophyd_tango_devices' existing get_reading() and get_value() methods directly on the TangoSignal objects, or by writing a device that inherits the read(), describe(), read_configuration() and describe_configuration() from the ophyd_tango_devices.devices.TangoDevice class.

Which class is used depends on whether the Ophyd Tango devices are instantiated inside a CommsConnector with sim_mode = True or False. By default, TangoProxy is used, e.g.

::

    with CommsConnector():
        motor = tango_motor("motor/motctrl01/1")

and for SimProxy:

::

    with CommsConnector(sim_mode=True):
        sim_motor = tango_motor("mock/device/name")
