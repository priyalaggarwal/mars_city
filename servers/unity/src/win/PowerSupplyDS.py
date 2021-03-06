#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Demo power supply tango device server"""

import time
import numpy
import PyTango
from PyTango import AttrQuality, AttrWriteType, DispLevel, DevState, DebugIt
from PyTango.server import Device, DeviceMeta, attribute, command, run
from PyTango.server import device_property

import time


class PowerSupply(Device):
    __metaclass__ = DeviceMeta

    voltage = attribute(label="Voltage", dtype=float,
                        display_level=DispLevel.OPERATOR,
                        access=AttrWriteType.READ,
                        unit="V", format="8.4f",
                        doc="the power supply voltage")

    current = attribute(label="Current", dtype=float,
                        display_level=DispLevel.EXPERT,
                        access=AttrWriteType.READ_WRITE,
                        unit="A", format="8.4f",
                        min_value=0.0, max_value=8.5,
                        min_alarm=0.1, max_alarm=8.4,
                        min_warning=0.5, max_warning=8.0,
                        fget="get_current",
                        fset="set_current",
                        doc="the power supply current")

    noise = attribute(label="Noise",
                      dtype=[[numpy.float64,
                             PyTango.IMAGE,
                             PyTango.READ, 100, 100],],
                      max_dim_x=1024, max_dim_y=1024)

    host = device_property(dtype=str)
    port = device_property(dtype=int, default_value=9788)

    def init_device(self):
        Device.init_device(self)
        self.__current = 0.0
        self.noise = numpy.random.random_integers(1000, size=(100, 100))
        self.set_state(DevState.STANDBY)

    def read_voltage(self):
        self.info_stream("read_voltage(%s, %d)", self.host, self.port)
        return 9.99, time.time(), AttrQuality.ATTR_WARNING

    def get_current(self):
        return self.__current

    def set_current(self, current):

        # should set the power supply current
        self.__current = current

    def set_noise(self, noise):
        self.noise = noise

    @DebugIt()
    def read_noise(self):
        end_time = time.time() + 10
        while time.time() < end_time:
            self.set_noise(numpy.random.random_integers(100, size=(100, 100)))
            # self.get_noise()
            self.push_change_event('noise', self.noise, 100, 100)
            return self.noise
    @command
    def get_noise(self):
        #print self.noise
        return self.noise

    @command
    def generate_noise(self):
        end_time = time.time() + 10
        while time.time() < end_time:
            yield self.set_noise(numpy.random.random_integers(100, size=(100, 100)))

            #self.get_noise()
        #self.push_change_event('noise', self.noise, 100, 100)

    @command
    def publish(self):
        self.push_change_event('noise', self.generate_noise() , 100, 100)

    @command
    def TurnOn(self):
        # turn on the actual power supply here
        self.set_state(DevState.ON)

    @command
    def TurnOff(self):
        # turn off the actual power supply here
        self.set_state(DevState.OFF)

    @command(dtype_in=float, doc_in="Ramp target current",
             dtype_out=bool, doc_out="True if ramping went well, False otherwise")
    def Ramp(self, target_current):
        # should do the ramping
        return True


if __name__ == "__main__":
    run([PowerSupply])
