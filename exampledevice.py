from tango import Database, DbDevInfo
import time
from tango.server import Device, attribute, command, pipe
from tango import Util, Attr, AttrWriteType, AttrQuality, AttributeProxy, \
    PipeWriteType
import numpy as np
import random
import sys
import multiprocessing
import random
from PyTango import CmdArgType
import numpy as np

if len(sys.argv) < 2:
    sys.argv.append('default')
#  A reference on the DataBase
db = Database()

# Define the Tango Class served by this  DServer
new_device_info = DbDevInfo()
new_device_info._class = "ExampleDevice"
new_device_info.server = "ExampleDevice/"+sys.argv[1]

new_devices = ['tango/example/device']

for dev in new_devices:
    print("Creating device: %s" % dev)
    new_device_info.name = dev
    db.add_device(new_device_info)

new_device_info._class = "Detector"
new_device_info.server = "Detector/"+sys.argv[1]

class ExampleDevice(Device):

    _array = np.array([[1, 2], [3, 4]])
    randomvalue = attribute(label="randomvalue", dtype=float,
                            access=AttrWriteType.READ,
                            min_value=0, max_value=1,
                            fget="get_random_value")

    def get_random_value(self):
        return random.random()

    array = attribute(label="array", dtype=((float,),),
                            max_dim_x=2, max_dim_y=2,
                            # access=AttrWriteType.READ_WRITE,
                            fget="get_array",
                            fset="set_array")

    def get_array(self):
        return self._array

    def set_array(self, value):
        self._array = value

    _pipe = ('hello', dict(test='test', test2='test2'))
    my_pipe = pipe(access=PipeWriteType.PIPE_READ_WRITE)

    def read_my_pipe(self):
        return self._pipe

    def write_my_pipe(self, value):
        self._pipe = value 

    @command(dtype_in=float, dtype_out=float)
    def doubler(self, value):
        print(f"2 times {value} is {2*value}")
        return 2*value


if __name__ == "__main__":
    ExampleDevice.run_server()
