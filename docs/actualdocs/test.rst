===================
Ophyd Tango Devices
===================

TODO
    + Explain about inconsistency of async vs sync read_attribute etc
    + explain about things that need to be called in call_in_bluesky_event_loop vs awaiting
    + Explanation: overview of bluesky API requirements for talking to hardware

This repo contains some examples of how to write Tango devices that can be used by plans in the Bluesky run engine, implementing mainly just the necessary methods required by the Bluesky API for interacting with hardware, such as read(), describe(), and for movable devices: set(). These are written using nominally asynchronous methods, utilising PyTango's Asyncio "green mode." Almost all of the interaction with the (simulated) Tango hardware is through the PyTango DeviceProxy class, or more accurately, the PyTango.asyncio DeviceProxy.
I had considered using the AttributeProxy class for communicating with Tango attributes, and this may have been more straightforward, but the DeviceProxy class provides easier access to certain information required by the Bluesky API, such as the hostname and port of the Tango Device Server that the device is hosted on, which is required for the "source" field of each entry in the TangoDevice describe() method dictionary. It also appears that AttributeProxy is a higher level object that contains a DeviceProxy as a member variable, so using the DeviceProxy may be more lightweight even if it's weirder syntactically. 

Tango provides attributes, commands and pipes, which are a tuple containing a string name and a mutable list of dictionaries holding data of arbitrary data types.

Each of the attributes, pipes and commands are implemented as Ophyd Signals. Each Signal object contains the necessary methods to get from and put to the signal, or execute it in the case of commands. The Signals must be connected before Bluesky plans can interact with them. The connect method for TangoAttr, TangoPipe and TangoCommand should set the member variables/attributes self.proxy (pointing to a PyTango.asyncio.DeviceProxy instance), self.dev_name (the "domain/family/member" formatted name of the Tango device) and self.signal_name (the name of the signal as defined by the Tango device.)

The TangoAttr and TangoPipe connect method verifies that the signal is available by attempting to read from it via the DeviceProxy, discarding the result. The TangoCommand connect method simply checks to see if a command with the name self.signal_name exists in the list of the commands belonging to the device, provided by the self.proxy.get_command_list() method.



