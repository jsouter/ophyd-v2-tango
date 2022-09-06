from tango import Database, DbDevInfo
import time
from tango.server import Device, attribute, command, pipe
from tango import Util, Attr, AttrWriteType, AttrQuality, AttributeProxy, PipeWriteType
import numpy as np
import random
import sys
import multiprocessing

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
    _position = 0.0
    _set_position = {'pos': 0.0, 'timestamp': None}
    _wavenumber = 1
    _offset = 0
    _amplitude = 1
    _speed = 10
    _pipe1 = ('hello',dict(test='test', test2='test2'))

    Speed = attribute(label = "Speed", dtype = float,
    access=AttrWriteType.READ_WRITE,
    min_value=0,
    fget="get_Speed", fset = "set_Speed")

    Value = attribute(label = "Value", dtype = float,
    access=AttrWriteType.READ,
    min_value=-1, max_value=1,
    fget="get_Value")

    def noise(self):
        return 0.05*self._amplitude*(2*random.random()-1)

    def get_Value(self):
        value = np.sin(2*np.pi*self._wavenumber*self._position)+self._offset+self.noise()
        # print(f"value is {value}")
        return value

    def get_Speed(self):
        return self._speed

    def set_Speed(self, speed):
        self._speed = speed
    
    _pipe = ('hello',dict(test='test', test2='test2'))
    my_pipe = pipe(access = PipeWriteType.PIPE_READ_WRITE)

    def read_my_pipe(self):
        return self._pipe
    
    def write_my_pipe(self, value):
        self._pipe = value 

    @command(dtype_in=float)
    def offset(self, value):
        self._offset = value
        print(f"offset of sin wave is now {self._offset}")
        
    @command(dtype_in=float)
    def wavenumber(self, value):
        self._wavenumber = value
        print(f"wavenumber of sin wave is now {self._wavenumber}")

if __name__ == "__main__":
    ExampleDevice.run_server()
