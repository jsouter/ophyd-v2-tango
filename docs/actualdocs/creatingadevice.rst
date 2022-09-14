One can create a new Ophyd implementation for a Tango device by inheriting from existing TangoDevice subclasses. `This page <https://nsls-ii.github.io/bluesky/hardware.html>`_ from the Bluesky documentation outlines the required methods needed to interact with the RunEngine. Firstly, consider the ReadableDevice class. The essential methods needed to be able to pass the device to a simple count plan in the RunEngine (which just reads designated values of attributes belonging to the device at a user defined rate) are read(), describe(), read_configuration() and describe_configuration().

The simplest way to implement these methods is to return the self._read() and self._describe() methods inherited from TangoDevice, each of which takes as arguments the Tango signals (attributes, pipes, commands) belong to the device's comm object which are designated as data (for read() and describe) and configuration metadata (for read_configuration() and describe_configuration())
e.g.
::

    class TangoMotor(TangoDevice, Movable):

        async def read(self):
            return await self._read(self.comm.position)

        async def describe(self):
            return await self._describe(self.comm.position)

        async def read_configuration(self):
            return await self._read(self.comm.velocity)

        async def describe_configuration(self):
            return await self._describe(self.comm.velocity)

_read() and _describe() can each take multiple arguments. 
The readings from the fields in read() and describe() are accessible to callbacks in the RunEngine, so if you wish to scan a motor over a range of positions and then collect the readings of position in a table, you must include the position signal in read(). 
**GO ON TO EXPLAIN SET ETC**

Like any TangoDevice, we must instantiate our device object with a TangoComm as its first argument. This object holds the required TangoSignals (attributes, pipes, commands) needed for our plans. **See the comm.rst section for more info**

We must instantiate all Comm objects inside of ophyd.v2.core's CommsConnector context manager in order that the signals are connected and accessible. 

Creation of a device object should look like
::

    with CommsConnector():
        motor_comm = MotorComm("motor/device/name")
        my_motor = TangoMotor(motor_comm)

**How do we best have a test that doesn't require running all the Sardana/tango stuff???**