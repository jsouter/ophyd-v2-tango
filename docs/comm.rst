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

    @tango_connector
    async def motor_connector(comm: TangoMotorComm, proxy: DeviceProxyProtocol):
        ...

When called, the connector's decorator function will store the TangoComm class and connector object as a key value pair in a dictionary that is accessed by the TangoComm's init method. 

CommsConnector() should be called as context manager whenever a TangoComm (or higher level device containing a TangoComm object) is instantiated; upon exit from the CM the Comm's connect method gets called. If no connector is specified then the default is the callable class ConnectSimilarlyNamed. See connectors.rst 