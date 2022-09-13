Attributes are one of three types of "**Signal**"s provided by Tango devices. To extract readings of attributes attached to export devices, one can use the PyTango API's DeviceProxy read_attribute method, or the AttributeProxy's read method, which returns a DeviceAttribute object with key value pairs resembling a dictionary of data and metadata fields for the reading. This includes the current readback value (if set), set value, the dimensionality, attribute name, timestamp and so on.

    DeviceAttribute(data_format = tango._tango.AttrDataFormat.SCALAR, dim_x = 1, dim_y = 0, has_failed = False, is_empty = False, name = 'Position', nb_read = 1, nb_written = 1, quality = tango._tango.AttrQuality.ATTR_VALID, r_dimension = AttributeDimension(dim_x = 1, dim_y = 0), time = TimeVal(tv_nsec = 0, tv_sec = 1662970421, tv_usec = 567493), type = tango._tango.CmdArgType.DevDouble, value = 0.0, w_dim_x = 1, w_dim_y = 0, w_dimension = AttributeDimension(dim_x = 1, dim_y = 0), w_value = 0.0)

ophyd_tango_devices provides Ophyd devices access to attributes, along with the other two types of "signal" (pipes and commands) via subclasses of TangoSignal.
At creation all TangoSignals are unconnected, in the sense that no verifiable connection to the Tango Device Server has been established for that particular signal. 

There are several different connect methods for each type of Signal, ultimately what these methods need to provide is
    + setting the member variable *dev_name* to the Tango device's proper exported name as a string, of the format "domain/family/member"
    + setting the member variable *signal_name* to the proper name of the signal, as exported by the Tango device
    + setting the member variable *proxy* to point to an instance of the PyTango DeviceProxy class, through which most communication with the Tango Device Server occurs
    + (Optionally) some test to see if the named attribute is accessible, such as by attempting to read its current value

Higher level Ophyd objects contain collections of Signals, which may be of the type TangoAttrR, TangoAttrW, depending on the required read/write requirements.

::

    class TangoAttr(TangoSignal):
    async def connect(self, dev_name: str, attr: str,
                      proxy: Optional[AsyncDeviceProxy] = None):
        '''Should set the member variables proxy, dev_name and signal_name.
         May be called when no other connector used to connect signals'''
        if not self.connected:
            self.dev_name = dev_name
            self.signal_name = attr
            self.proxy = proxy or await _get_proxy_from_dict(self.dev_name)
            try:
                await self.proxy.read_attribute(attr)
            except DevFailed:
                raise TangoAttrReadError(
                    f"Could not read attribute {self.signal_name}")
            self._connected = True

The first way of setting an attribute to connected is by awaiting the TangoAttr class' (or subclass') connect method. The device and attribute names are passed in as required arguments, with the DeviceProxy instance passed in optionally. If the proxy is not given, it is found via _get_proxy_from_dict() which returns a DeviceProxy object for the given device name and adds it to a dictionary structued like {dev_name: DeviceProxy(dev_name),}
and if the dev_name is already in the dictionary keys returns the existing DeviceProxy object to prevent creating redundant unique objects. 
The connect method then attempts to read the attribute to confirm communication is possible. Note the use of the await keyword; the DeviceProxy class is from PyTango's Asyncio "green mode" which implements Python asynchronicity for some, though not all, of its I/O operations.

The readable subclass, TangoAttrR contains the async methods get_reading() and get_descriptor. These are called by higher level Ophyd device objects that implement the required read() and describe() methods needed by the Bluesky API to communicate with (real or simulated) hardware. 

::

    async def get_reading(self) -> Reading:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Reading({"value": attr_data.value,
                        "timestamp": attr_data.time.totime()})

Reading is a TypedDict, and must contain at minimum the read value and timestamp of the reading, both can be obtained from the DeviceProxy's read_attribute method

::

    async def get_descriptor(self) -> Descriptor:
        attr_data = await self.proxy.read_attribute(self.signal_name)
        return Descriptor({"shape": self._get_shape(attr_data),
                           "dtype": _get_dtype(attr_data),  # jsonschema types
                           "source": self.source, })

The source is a string describing the origin of the signal, it is given by the TangoSignal method

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

*tango://<hostname of Tango device server>:10000/motor/motctrl01/1/Position*

