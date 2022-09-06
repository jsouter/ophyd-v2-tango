from PyTango import DeviceProxy
b = DeviceProxy("tango/example/device")
pipedata = b.read_pipe("my_pipe")
pipedata[1][0]['value'] = 'how are you'
b.write_pipe("my_pipe", pipedata)
print(b.read_pipe("my_pipe"))
pipedata[1][0]['value'] = 'yeah cant complain'
b.write_pipe("my_pipe", pipedata)
print(b.read_pipe("my_pipe"))
