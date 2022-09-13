As in the EPICS implementation in ophyd.v2, groups of Ophyd signals are collected in Comm classes (here, TangoComm).
Subclasses of TangoComm made for specific devices (such as a simulated motor device) need only contain type hints for the signals that are required to interact with Bluesky plans.
::

    class TangoMotorComm(TangoComm):
        position: TangoAttrRW
        velocity: TangoAttrRW
        state: TangoAttrRW
        stop: TangoCommand


At initialisation, the TangoComm inherits self.dev_name ("domain/family/member") from an argument passed to it. A function make_tango_signals loops over the type hints, and instantiates (not connects) a member variable of that hinted class. So, motor_comm = TangoMotorComm() would have an attribute motor_comm.position of type TangoAttrRW. This method also adds the member variable name to to the signal which is a string representing the name of the signal object in Python as given by the type hint, i.e.
motor_comm.position.name = 'position' and motor_comm.stop.name = 'stop'. **This is needed to generate unique signal names that can be passed to the builtin callbacks of the Bluesky RunEngine.**

::

    def make_tango_signals(comm: TangoComm):
    hints = get_type_hints(comm)
    for name in hints:
        signal = hints[name]()
        signal.name = name
        setattr(comm, name, signal)

Then, the TangoComm initialisation method finds the connector method needed to connect all the signals belonging to the Comm and schedules the connection with the CommsConnector from ophyd.v2.core.

CommsConnector() should be called as context manager whenever a TangoComm (or higher level device containing a TangoComm object) is instantiated; upon exit from the CM the Comm's connect method gets called. If no connector is specified then the default is the callable class ConnectSimilarlyNamed. This method loops over the names in the type hints of the Comm object and gets the attributes from the Comm instance that were constructed during make_tango_signals, checks which ones have not been connected by another connect method and then calls the class method schedule_signal on them, returning immediately if all signals are connected. 

schedule_signal takes the hinted signal name, makes it lowercase and removes all non-alphanumeric characters. For instance, a hint like "PoSItIoN: TangoAttrRW" would reduce to "position". As position is hinted as a Tango attribute, this string is checked again all the exported attributes belonging to the device as given by the DeviceProxy's get_attribute_list() method; if the string matches any of the attribute names after they have also been modified in the same way, the signal's connect method coroutine is scheduled with the matching attribute name being given as the signal name argument. So if the exported Tango attribute name "Position" is found, then we schedule, effectively, 
self.comm.position.connect(self.comm.dev_name, "Position")
Once all the unconnected signals have found matching Tango attributes (or pipes or commands) then the connect methods are awaited.

If instead, we want more freedom with what we name the Python TangoSignal objects, we can manually call the connect method for specific signal names. 

::

    class TangoMotorComm(TangoComm):
        pos: TangoAttrRW
        vel: TangoAttrRW
        state: TangoAttrRW
        stop: TangoCommand


    @tango_connector
    async def motorconnector(comm: TangoMotorComm):
        proxy = await _get_proxy_from_dict(comm.dev_name)
        await asyncio.gather(
            comm.pos.connect(comm.dev_name, "Position", proxy),
            comm.vel.connect(comm.dev_name, "Velocity", proxy),
            comm.state.connect(comm.dev_name, "State", proxy),
        )
        await ConnectSimilarlyNamed(comm, proxy)

Each of the signal names are specified as an argument of the connect method. We may also choose to call ConnectSimilarlyNamed() to connect all the remaining signals, in this case it will connect the hinted "stop: TangoCommand" listed in the MotorComm above. The @tango_connector decorator will ensure that the connector is added to a global dictionary that matches the Comm subclass (type hinted in the arguments of the motorconnector function) to the connector function, which the Comm's init function looks for to determine what to call when the CommsConnector context manager exists.