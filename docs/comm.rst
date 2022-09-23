As in the EPICS implementation in ophyd.v2, groups of Ophyd signals are collected in Comm classes (here, TangoComm).
Subclasses of TangoComm made for specific devices (such as for a simulated motor device) need only contain type hints for the signals that are required to interact with Bluesky plans.
::

    class TangoMotorComm(TangoComm):
        position: TangoAttrRW
        velocity: TangoAttrRW
        state: TangoAttrRW
        stop: TangoCommand


At initialisation, the TangoComm inherits self.dev_name (`"domain/family/member" <https://tango-controls.readthedocs.io/en/latest/development/general-guidelines/naming.html>`_) from the sole argument passed to it. A function make_tango_signals loops over the type hints, and instantiates an unconnected Signal of that hinted class as a member variable. So, motor_comm = TangoMotorComm() would have an attribute motor_comm.position of type TangoAttrRW. 

::

    def make_tango_signals(comm: TangoComm):
    hints = get_type_hints(comm)
    for name in hints:
        signal = hints[name]()
        setattr(comm, name, signal)


Then, the TangoComm initialisation method finds the connector method needed to connect all the signals belonging to the Comm and schedules the connection with the CommsConnector from ophyd.v2.core. Connectors are callables that take two arguments:

* comm: an instance of a TangoComm subclass holding the required TangoSignal hints
* proxy: an instance of a DeviceProxyProtocol type class which has been instantiated with the required device name

Connectors should be decorated with the **tango_connector** function, which extracts the class name of the TangoComm subclass it is designed to accept, which is given by the type hint class of the comm parameter in the connector's call method. e.g.
::

    async def motor_connector(comm: TangoMotorComm, proxy: DeviceProxyProtocol):
        ...

When called, the connector's decorator function will store the TangoComm class and connector object as a key value pair in a dictionary that is accessed by the TangoComm's init method. 

CommsConnector() should be called as context manager whenever a TangoComm (or higher level device containing a TangoComm object) is instantiated; upon exit from the CM the Comm's connect method gets called. If no connector is specified then the default is the callable class ConnectSimilarlyNamed. See connectors.rst This method loops over the names in the type hints of the Comm object and gets the attributes from the Comm instance that were constructed during make_tango_signals, checks which ones have not been connected by another connect method and then calls the class method schedule_signal on them, returning immediately if all signals are connected. 

schedule_signal takes the hinted signal name, makes it lowercase and removes all non-alphanumeric characters. For instance, a hint like "PoSItIoN: TangoAttrRW" would reduce to "position". As position is hinted as a Tango attribute, this string is checked against all the exported attributes belonging to the device as given by the DeviceProxy's get_attribute_list() method; if the string matches any of the attribute names after they have also been modified in the same way, the signal's connect method coroutine is scheduled with the matching attribute name being given as the signal name argument. So if the exported Tango attribute name "Position" is found, then we schedule, effectively, 
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
        proxy = await _get_device_proxy(comm.dev_name)
        await asyncio.gather(
            comm.pos.connect(comm.dev_name, "Position", proxy),
            comm.vel.connect(comm.dev_name, "Velocity", proxy),
            comm.state.connect(comm.dev_name, "State", proxy),
        )
        await ConnectSimilarlyNamed(comm, proxy)

Each of the signal names are specified as an argument of the connect method. We may also choose to call ConnectSimilarlyNamed() to connect all the remaining signals not connected in the asyncio.gather() method, in this case it will connect the hinted "stop: TangoCommand" listed in the MotorComm above.