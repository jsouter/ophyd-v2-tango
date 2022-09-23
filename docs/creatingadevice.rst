One can create a new Ophyd implementation for a Tango device by inheriting from existing TangoDevice subclasses. `This page <https://nsls-ii.github.io/bluesky/hardware.html>`_ from the Bluesky documentation outlines the required methods needed to interact with the RunEngine. Firstly, consider the ReadableDevice class. The essential methods needed to be able to pass the device to a simple count plan in the RunEngine (which just reads designated values of attributes belonging to the device at a user defined rate) are read(), describe(), read_configuration() and describe_configuration().

We must instantiate any TangoDevice subclass with a TangoComm as its first argument. This object holds the required TangoSignals (attributes, pipes, commands) needed for our plans. See the comm.rst section for more info.

If we construct a subclass of TangoDevice it inherits the following methods:

::
    
    async def read(self):
        return await self.read_signals.read(self.signal_prefix)

    async def describe(self):
        return await self.read_signals.describe(self.signal_prefix)

    async def read_configuration(self):
        return await self.conf_signals.read(self.signal_prefix)

    async def describe_configuration(self):
        return await self.conf_signals.describe(self.signal_prefix)

Where self.read_signals and self.conf_signals are instances of the SignalCollection class from ophyd.v2.core. If unset, these will be empty of Signals. 
self.read_signals represents signals intended to be read by the Bluesky RunEngine during a plan and represent data. The signals in self.conf_signals should be configuration metadata that only need to be read once per run. 

Subclasses may set these like so:

::

    class TangoMotor(TangoDevice, Movable):
        @property
        def read_signals(self):
            return SignalCollection(position=self.comm.position)

        @property
        def conf_signals(self):
            return SignalCollection(velocity=self.comm.velocity)

Note that the SignalCollection class' read() and describe() method simply calls asyncio.gather() on each of the Signals' get_reading() or get_descriptor() method and packages the results together in a dictionary as required by the Bluesky API, with the keys being unique identifiers for each of the signals that may consist of the user specified device name and signal name separated by a hyphen. 


We must instantiate all Comm objects inside of ophyd.v2.core's CommsConnector context manager in order that the signals are connected and accessible. 

Creation of a device object should look like
::

    with CommsConnector():
        motor_comm = MotorComm("motor/device/name")
        my_motor = TangoMotor(motor_comm)

Though to simplify, we may define a single function that instantiates and passes the comm to the device:

::

    def tango_motor(dev_name: str, name: str):
        c = TangoMotorComm(dev_name)
        return TangoMotor(c, name)

    with CommsConnector():
        my_motor = tango_motor("motor/device/name")

The name parameter for the Device represents the unique name of the device that is seen by Bluesky, which may be optionally provided in preference to the default value which is the device name with the slashes replaced with dashes. Readable attributes can be accessed as callbacks in the Bluesky RunEngine by hyphenating the name of the device with the hinted name of the attribute as given in the TangoComm: e.g.

::

    from bluesky import RunEngine
    from bluesky.plans import count
    from bluesky.callbacks import LiveTable
    from ophyd.v2.core import CommsConnector

    with CommsConnector():
        my_motor = tango_motor("motor/device/name", name="my_named_motor")
    RE = RunEngine()
    RE(count([my_motor]), LiveTable(["my_named_motor-position"]))


If instead you need Bluesky to interact with only a single attribute, pipe or command of a given Tango device, you may create an instance of the TangoSingleAttributeDevice, TangoSinglePipeDevice or TangoSingleCommandDevice. Each of these takes three arguments:
    + The proper name of the Tango device
    + The proper name of the signal as exported by the Tango device server (string)
    + (Optionally) The unique identifier name that may be passed to the RunEngine callbacks (string).

e.g. 
::

    with CommsConnector():
        position_device = TangoSingleAttributeDevice("motor/motctrl01/1", "Position", "my_position")

    RE = RunEngine()
    RE(count([position_device], 1), LiveTable(["my_position"]))

Each of these classes defines a single signal TangoComm class in place, so each must still be instantiated inside a CommsConnector() context manager.

