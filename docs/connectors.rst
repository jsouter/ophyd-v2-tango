There are a few methods for connecting signals in a TangoComm. The first, and most explicit, is to define a new connector class and manually call the asynchronous connect method on each required signal, passing the device name and signal name manually. For the TangoMotorComm seen in comm.rst:

::
    
    @tango_connector
    async def motor_connector(comm: TangoMotorComm, proxy: DeviceProxy):
        await asyncio.gather(
            comm.position.connect(comm._dev_name, "Position", proxy),
            comm.velocity.connect(comm._dev_name, "Velocity", proxy),
            comm.state.connect(comm._dev_name, "State", proxy),
            comm.stop.connect(comm._dev_name, "Stop", proxy))

If all the hinted signals in the TangoComm are named similarly to their actual names as exported by the TangoDevice it would be simpler to call the ConnectSimilarlyNamed connector:

::

    @tango_connector
    async def motor_connector(comm: TangoMotorComm, proxy: DeviceProxy):
        await ConnectSimilarlyNamed(comm, proxy)


This method loops over the names in the type hints of the Comm object and gets the attributes from the Comm instance that were constructed during make_tango_signals, checks which ones have not been connected by another connect method and then calls the class method schedule_signal on them, returning immediately if all signals are connected. 

schedule_signal takes the hinted signal name, makes it lowercase and removes all non-alphanumeric characters. For instance, a hint like "PoSItIoN: TangoAttrRW" would reduce to "position". As position is hinted as a Tango attribute, this string is checked against all the exported attributes belonging to the device as given by the DeviceProxy's get_attribute_list() method; if the string matches any of the attribute names after they have also been modified in the same way, the signal's connect method coroutine is scheduled with the matching attribute name being given as the signal name argument. So if the exported Tango attribute name "Position" is found, then we schedule, effectively, 
self.comm.position.connect(self.comm.dev_name, "Position")
Once all the unconnected signals have found matching Tango attributes (or pipes or commands) then the TangoSignals' connect methods are awaited. This will cause all the attributes and pipes to be read to confirm they can be connected to.

ConnectSimilarlyNamed is the default connector if no @tango_connector decorated connector exists for the hinted TangoComm subclass.

If it is preferred not to attempt to read the signals, perhaps if you are instantiating a large number of signals and do not wish to make so many network calls, the ConnectWithoutReading connector will set to connected any signals that are found in the reported attributes, pipes and commands list of the Tango device.

::

    @tango_connector
    def motor_connector(comm: TangoMotorComm, proxy: DeviceProxy):
        connector = ConnectWithoutReading(comm, proxy)
        connector(position="Position", velocity="Velocity",
                state="State", stop="Stop")

First, the ConnectWithoutReading class is instantiated with the normal parameters, then it must be called. As the DeviceProxy's get_attribute_list(), get_command_list() and get_pipe_list() methods are synchronous we need not await the connector. 
The arguments of the connector call should be a set of keyword arguments, where the key is the name of the Comm's attributes in Python and the value is the proper string of the signal name reported by the Tango device server. If a hinted signal in the TangoComm is not specified as a kwarg, the connector will assume that the value should be the same as its Pythonic name, so comm.position would have a value of "position". If any signal can not be found, a KeyError is raised.
 