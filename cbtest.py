from bluesky.callbacks.core import get_obj_fields

from bluesky.callbacks.core import CallbackBase
from numpy import argmin

import time
class mycallback(CallbackBase):
    def __init__(self, fields):
        self._fields = fields
        print(fields)
        pass
        self.start_time = time.time()
    def event(self, doc):
        timestamps = [(i, doc['timestamps'][i] - self.start_time) for i in self._fields]
        readings = [doc['data'][i] for i in self._fields]
        # print(readings)
        timediff = timestamps[0][1] - timestamps[1][1]
        print(timediff)