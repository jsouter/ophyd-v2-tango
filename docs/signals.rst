Attributes are one of `three types of signals provided by Tango devices <https://tango-controls.readthedocs.io/en/latest/development/device-api/device-server-model.html#the-device>`_. To extract readings of attributes attached to exported devices, one can use the PyTango API's DeviceProxy read_attribute() method, or the AttributeProxy's read() method, which returns a DeviceAttribute object containg data and metadata as member variables. This includes the current readback value (if set), set value, the dimensionality, attribute name, timestamp and so on.

    DeviceAttribute(data_format = tango._tango.AttrDataFormat.SCALAR, dim_x = 1, dim_y = 0, has_failed = False, is_empty = False, name = 'Position', nb_read = 1, nb_written = 1, quality = tango._tango.AttrQuality.ATTR_VALID, r_dimension = AttributeDimension(dim_x = 1, dim_y = 0), time = TimeVal(tv_nsec = 0, tv_sec = 1662970421, tv_usec = 567493), type = tango._tango.CmdArgType.DevDouble, value = 0.0, w_dim_x = 1, w_dim_y = 0, w_dimension = AttributeDimension(dim_x = 1, dim_y = 0), w_value = 0.0)

Tango pipes are length 2 sequences whose first value is a string: the pipe name. 
The second value is a list of dictionaries representing data elements, each of which contains keys for a Tango datatype, name and value. The number of data elements is not fixed and the list can hold an arbitrary combination of data types, making it useful for user-defined configuration. 

Commands are executable Tango signals. They are able to take in a single value of a set datatype as an input and return a single value of another set datatype. 

ophyd_tango_devices provides Ophyd devices access to attributes, pipes and commands via subclasses of TangoSignal.
At creation all TangoSignals are unconnected, in the sense that no verifiable connection to the Tango Device Server has been established for that particular signal. 

There are several different connect methods for each type of Signal, ultimately what these methods need to provide is
    + setting the member variable *dev_name* to the Tango device's proper exported name as a string, of the format "domain/family/member"
    + setting the member variable *signal_name* to the proper name of the signal, as exported by the Tango device
    + setting the member variable *proxy* to point to an instance of the PyTango DeviceProxy class, through which most communication with the Tango Device Server occurs
    + (Optionally) some test to see if the named attribute is accessible, such as by attempting to read its current value

Higher level Ophyd objects contain collections of TangoSignals as a `TangoComm <comm.rst>`_.
The types of signals that may be instantiated are:

    TangoAttrR,
    TangoAttrW,
    TangoAttrRW,
    TangoPipeR,
    TangoPipeW,
    TangoPipeRW,
    TangoCommand

The TangoSignals are designed not to require an init method, all necessary information is passed to the TangoSignal during connect().

::

    class TangoAttr(TangoSignal):
    async def connect(self, dev_name: str, attr: str,
                      proxy: Optional[DeviceProxy] = None):
        if not self.connected:
            self._dev_name = dev_name
            self._signal_name = attr
            self._proxy_ = proxy or await _get_device_proxy(self._dev_name)
            try:
                await self._proxy_.read_attribute(attr)
            except DevFailed or KeyError:
                raise TangoAttrReadError(
                    f"Could not read attribute {self._signal_name}")
            self._connected = True


    class TangoCommand(TangoSignal):
        async def connect(
                self, dev_name: str, command: str,
                proxy: Optional[DeviceProxy] = None):
            if not self.connected:
                self._dev_name = dev_name
                self._signal_name = command
                self._proxy_ = proxy or await _get_device_proxy(self._dev_name)
                commands = self._proxy_.get_command_list()
                assert self._signal_name in commands, \
                    f"Command {command} not in list of commands"
                self._connected = True

Each of the three major subclasses of TangoSignal have a connect() method that takes the device name, signal name (attribute name, for example) and proxy object as parameters. For TangoAttr and TangoPipe, the signal is verified by confirming that no exception is raised on reading the signal's value. For TangoCommand, since we can't read the output of a command without executing it, we instead check to see that a command of the given name is reported by the Tango device as existing. 

If it is deemed sufficient to check if the attributes, pipes and commands are listed by the Tango device and not to read the values to confirm connection, you may bypass the TangoSignals' connect method and call the ConnectWithoutReading connector: see connectors.rst.

The readable subclasses TangoAttrR and TangoPipeR contain the async methods get_reading() and get_descriptor(). These are called by higher level Ophyd device objects that implement the required read() and describe() methods needed by the Bluesky API to communicate with (real or simulated) hardware. 

::

    async def get_reading(self) -> Reading:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Reading({"value": attr_data.value,
                        "timestamp": attr_data.time.totime()})

Reading is a TypedDict subclass, and must contain at minimum the read value and timestamp of the reading, both can be obtained from the DeviceProxy's read_attribute method

::

    async def get_descriptor(self) -> Descriptor:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Descriptor({"shape": self._get_shape(attr_data),
                           "dtype": _get_dtype(attr_data),  # jsonschema types
                           "source": self.source, })

The source is a string describing the origin of the signal, it is given by the TangoSignal source property

::

    @property
    def source(self) -> str:
        if not self._source:
            prefix = (f'tango://{self.proxy.get_db_host()}:'
                      f'{self.proxy.get_db_port()}/')
            if isinstance(self, TangoAttr):
                self._source = prefix + f'{self.dev_name}/{self.signal_name}'
            elif isinstance(self, TangoPipe):
                self._source = prefix + \
                    f'{self.dev_name}:{self.signal_name}(Pipe)'
            elif isinstance(self, TangoCommand):
                self._source = prefix + \
                    f'{self.dev_name}:{self.signal_name}(Command)'
            else:
                raise TypeError(f'Can\'t determine source of TangoSignal'
                                f'object of class {self.__class__}')
        return self._source

returning, for an attribute, a string of the type e.g. 

**tango://<hostname of Tango device server>:10000/motor/motctrl01/1/Position**

Attribute names are separated from the device name with a slash following Tango naming conventions. Since it is in some cases possible to have a command and attribute which share the same name, pipes and commands are specified in parentheses to differentiate then from similarly named attributes.

There appears to be some inconsistency with the PyTango.asyncio DeviceProxy read_pipe() and write_pipe() methods to the point where they may either return an awaitable Future or immediately return the reading. Whenever these methods are called throughout ophyd_tango_devices the reading is performed and then awaited if it is found to be a Future, otherwise returned directly.