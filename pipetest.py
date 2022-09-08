from PyTango import DeviceProxy
import asyncio
b = DeviceProxy("tango/example/device")

print(b.command_inout("doubler", 4))

from PyTango.asyncio import DeviceProxy as adp
async def doit():
    c = await adp("tango/example/device")
    doubled = await c.command_inout("doubler", 4)
    print(doubled)

asyncio.run(doit())

# pipedata = b.read_pipe("my_pipe")
# pipedata[1][0]['value'] = 'how are you'
# b.write_pipe("my_pipe", pipedata)
# print(b.read_pipe("my_pipe"))
# pipedata[1][0]['value'] = 'yeah cant complain'
# b.write_pipe("my_pipe", pipedata)
# print(b.read_pipe("my_pipe"))
