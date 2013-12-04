#!/usr/bin/env python

# Copyright 2012
# Adrian Alvarez <alvarez@ingen10.com>, Juan Menendez <juanmb@ingen10.com>
# and Armando Vincelle <armando@ingen10.com>
#
# This file is part of opendaq.
#
# opendaq is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# opendaq is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with opendaq.  If not, see <http://www.gnu.org/licenses/>.

import struct
import time
import serial

BAUDS = 115200
INPUT_MODES = ('ANALOG_INPUT', 'ANALOG_OUTPUT', 'DIGITAL_INPUT',
               'DIGITAL_OUTPUT', 'COUNTER_INPUT', 'CAPTURE_INPUT')
LED_OFF = 0
LED_GREEN = 1
LED_RED = 2


class LengthError(Exception):
    pass


class CRCError(Exception):
    pass


def crc(data):
    """
    Create cyclic redundancy check.
    """
    s = 0
    for c in data:
        s += ord(c)
    return struct.pack('>H', s)


def check_crc(data):
    """
    Cyclic redundancy check.

    Args:
        data: variable that saves the checksum.
    Raises:
        CRCError: Checksum incorrect.
    """
    csum = data[:2]
    payload = data[2:]
    if csum != crc(payload):
        raise CRCError
    return payload


def check_stream_crc(head, data):
    """
    Cyclic redundancy check for streaming.

    Args:
        head: variable that defines the header
        data: variable that defines the data
    """
    csum = (head[0] << 8) + head[1]
    return csum == sum(head[2:] + data)


class DAQ:
    def __init__(self, port):
        """
        Class constructor.
        """
        self.name = ""
        self.port = port
        self.open()
        info = self.get_info()
        self.vHW = "m" if info[0] == 1 else "s"
        self.gains, self.offset = self.get_cal()
        self.dacGain, self.dacOffset = self.get_dac_cal()

    def open(self):
        """
        Open serial port.

        Configure serial port to be opened.
        """
        self.ser = serial.Serial(self.port, BAUDS, timeout=1)
        self.ser.setRTS(0)
        time.sleep(2)

    def close(self):
        """
        Close serial port.

        Configure serial port to be closed.
        """
        self.ser.close()

    def send_command(self, cmd, ret_fmt, debug=False):
        """
        Send a command to openDAQ.

        Args:
            cmd: variable that defines the command
            ret_fmt: variable that defines the format
            debug: variable that defines the debug mode
        Returns:
            The command number into variable 'data'.
        Raises:
        LengthError: An error occurred.
        """
        # Add 'command' and 'length' fields to the format string
        fmt = '>bb' + ret_fmt
        ret_len = 2 + struct.calcsize(fmt)
        packet = crc(cmd) + cmd
        self.ser.write(packet)
        ret = self.ser.read(ret_len)
        if debug:
            print 'Command:  ',
            for c in packet:
                print '%02X' % ord(c),
            print
            print 'Response: ',
            for c in ret:
                print '%02X' % ord(c),
            print
        if len(ret) != ret_len:
            raise LengthError
        data = struct.unpack(fmt, check_crc(ret))
        if data[1] != ret_len-4:
            raise LengthError
        # Strip 'command' and 'length' values from returned data
        return data[2:]

    def get_info(self):
        """
        Read device configuration: serial number, firmware version
        and hardware version.
        """
        return self.send_command('\x27\x00', 'bbI')

    def get_vHW(self):
        """
        Get the hardware version.

        Recognize the hardware version.
        """
        return self.vHW

    def read_adc(self):
        """
        Read the analog-to-digital converter.

        Read data from adc and return it in 'value'.
        """
        value = self.send_command('\x01\x00', 'h')[0]
        return value

    def read_analog(self):
        """
        Read the analog data.

        Read raw data.
        """
        value = self.send_command('\x01\x00', 'h')[0]
        # Raw value to voltage->
        index = self.gain+1 if self.vHW == "m" else self.input
        value *= self.gains[index]
        value = value / -100000.0 if self.vHW == "m" else value / 10000.0
        value = (value+self.offset[index]) / 1000.0
        return value

    def conf_adc(self, pinput, ninput=0, gain=0, nsamples=20):
        """
        Configure the analog-to-digital converter.

        Get the parameters for configure the analog-to-digital converter.

        Args:
            pinput: variable that defines the input pin
            ninput: variable that defines the input number
            gain: variable that defines the gain
            nsamples: variable that defines the samples number
        """
        self.gain = gain
        self.input = pinput

        if self.vHW == "s" and ninput != 0:
            if pinput == 1 or pinput == 2:
                self.input = 9
            if pinput == 3 or pinput == 4:
                self.input = 10
            if pinput == 5 or pinput == 6:
                self.input = 11
            if pinput == 7 or pinput == 8:
                self.input = 12

        cmd = struct.pack('BBBBBB', 2, 4, pinput, ninput, gain, nsamples)
        return self.send_command(cmd, 'hBBBB')

    def enable_crc(self, on):
        """
        Enable/Disable cyclic redundancy check.

        Args:
            on: variable that defines the enable status.
        """
        cmd = struct.pack('BBB', 55, 1, on)
        return self.send_command(cmd, 'B')[0]

    def set_led(self, color):
        """
        Choose LED status.

        LED switch on (green, red or orange) or switch off.

        Args:
                color: variable that defines the led color (0=off, 1=green,
        2=red, 3=orange).

        Raises:
            ValueError: An error ocurred caused for invalid selecction,
            must be in [0,1,2,3] and print 'invalid color number'.
        """
        if not 0 <= color <= 3:
            raise ValueError('Invalid color number')
        cmd = struct.pack('BBB', 18, 1, color)
        return self.send_command(cmd, 'B')[0]

    def set_analog(self, volts):
        """
        Set DAC output voltage (milivolts value).

        Set the output between the voltage hardware limits.
        (-4.096V and +4.096V for openDAQ[M])
        (0V and +4.096V for openDAQ[S])

        Args:
            volts: variable that defines the output value.

        Raises:
            ValueError: An error ocurred when voltage is out of range
            and print 'DAQ voltage out of range'.
        """
        value = int(round(volts*1000))
        if (
            (self.vHW == "m" and not -4096 <= value < 4096) or
                (self.vHW == "s" and not 0 <= value < 4096)):
                    raise ValueError('DAQ potential out of range')
        data = (value * self.dacGain / 1000.0 + self.dacOffset + 4096) * 2
        if self.vHW == "s":
            if data < 0:
                data = 0
            if data > 32767:
                data = 32767
        cmd = struct.pack('>BBh', 24, 2, data)
        return self.send_command(cmd, 'h')[0]

    def set_dac(self, raw):
        """
        Set DAC with raw value.

        Set the raw value into DAC before conditioning the data.

        Args:
            raw: variable with the raw data.
        """
        value = int(round(raw))
        if not 0 < value < 16384:
            raise ValueError('DAQ voltage out of range')
        cmd = struct.pack('>BBH', 24, 2, value)
        return self.send_command(cmd, 'h')[0]

    def set_port_dir(self, output):
        """
        Configure/Read all PIOs directions.

        Args:
                output: variable that defines PIOs direction values
            (0 inputs, 1 outputs).
        """
        cmd = struct.pack('BBB', 9, 1, output)
        return self.send_command(cmd, 'B')[0]

    def set_port(self, value):
        """
        Write/Read all PIOs in a port.

        Args:
            value: variable that defines PIOs output value.
        """
        cmd = struct.pack('BBB', 7, 1, value)
        return self.send_command(cmd, 'B')[0]

    def set_pio_dir(self, number, output):
        """
        Configure PIO direction.

        Args:
            number: variable that defines the PIO number.
            output: variable that defines PIO direction
        (0 input, 1 output).
        Raises:
            ValueError: An error ocurred when the PIO number doesn´t exist,
            and print 'Invalid PIO number'.
        """
        if not 1 <= number <= 6:
            raise ValueError('Invalid PIO number')
        cmd = struct.pack('BBBB', 5, 2, number,  int(bool(output)))
        return self.send_command(cmd, 'BB')

    def set_pio(self, number, value):
        """
        Write/Read PIO output.

        Args:
            number: variable that defines the PIO number.
            value: variable that defines low or high voltage output (+5V)
        Raises:
            ValueError: An error ocurred when the PIO number doesn´t exist,
            and print 'Invalid PIO number'.
        """
        if not 1 <= number <= 6:
            raise ValueError('Invalid PIO number')
        cmd = struct.pack('BBBB', 3, 2, number, int(bool(value)))
        return self.send_command(cmd, 'BB')

    def init_counter(self, edge):
        """
        Initialize the edge counter.

        Configure which edge increments the count:
        Low-to-High or High-to-Low.

        Args:
            edge: variable that definess the increment mode
            (1 Low-to-High, 0  High-to-Low).
        """
        cmd = struct.pack('>BBB', 41, 1, 1)
        return self.send_command(cmd, 'B')[0]

    def get_counter(self, reset):
        """
        Get counter value.

        Args:
            reset: variable that reset the count (1 reset accumulator).
        """
        cmd = struct.pack('>BBB', 42, 1, reset)
        return self.send_command(cmd, 'H')[0]

    def init_capture(self, period):
        """
        Start capture mode arround a given period.

        Args:
            period: variable that definess the aproximate period of the
            wave (microseconds).
        """
        cmd = struct.pack('>BBH', 14, 2, period)
        return self.send_command(cmd, 'H')[0]

    def stop_capture(self):
        """
        Stop capture mode.
        """
        self.send_command('\x0F\x00', '')

    def get_capture(self, mode):
        """
        Get current period length.

        Low cycle, High cycle or Full period.

        Args:
            mode: variable that defines the period length.
            - 0 Low cycle
            - 1 High cycle
            - 2 Full period
        """
        cmd = struct.pack('>BBB', 16, 1, mode)
        return self.send_command(cmd, 'BH')

    def init_encoder(self, resolution):
        """
        Start encoder function.

        Args:
            resolution: variable that defines maximun number of ticks
            per round [0:255].
        """
        cmd = struct.pack('>BBB', 50, 1, resolution)
        return self.send_command(cmd, 'B')[0]

    def stop_encoder(self):
        """
        Stop encoder function.
        """
        self.send_command('\x33\x00', '')

    def get_encoder(self):
        """
        Get current encoder relative position.
        """
        return self.send_command('\x34\x00', 'H')

    def init_pwm(self, duty, period):
        """
        Start PWM whit a given period and duty.

        Args:
            duty: variable that defines the high time of the signal [0:1023]
            (0 always low, 1023 always high).
            period: variable that defines the frecuency of the signal
            (microseconds) [0:65535]
        """
        cmd = struct.pack('>BBHH', 10, 4, duty, period)
        return self.send_command(cmd, 'HH')

    def stop_pwm(self):
        """
        Stop PWM.
        """
        self.send_command('\x0b\x00', '')

    def __get_calibration(self, gain_id):
        """
        Read device calibration.

        Args:
            gain_id: variable that defines the gain multiplier [0:4]
            (0 x(1/2), 1 x(1), 2 x(2, 3 x(10), 4 x(100) default(1)).
        """
        cmd = struct.pack('>BBB', 36, 1, gain_id)
        return self.send_command(cmd, 'BHh')

    def get_cal(self):
        """
        Read device calibration.

        Returns:
            The gains and offsets values.
        """
        gains = []
        offsets = []
        _range = 6 if self.vHW == "m" else 17
        for i in range(_range):
            gain_id, gain, offset = self.__get_calibration(i)
            gains.append(gain)
            offsets.append(offset)
        return gains, offsets

    def get_dac_cal(self):
        """
        Read DAC calibration.

        Returns:
            The gain and offset value.
        """
        gain_id, gain, offset = self.__get_calibration(0)
        return gain, offset

    def __set_calibration(self, gain_id, gain, offset):
        """
        Set device calibration.

        Args:
            gain_id: variable that defines the gain multiplier [0:4]
            (0 x(1/2), 1 x(1), 2 x(2, 3 x(10), 4 x(100) default(1)).
            gain: variable that defines gain multiplied by 100000
            (m=Slope/100000, 0 to 0.65) [0:65535].
            offset: variable that defines the offset raw value.
            [-32768:32768].
        """
        cmd = struct.pack('>BBBHh', 37, 5, gain_id, gain, offset)
        return self.send_command(cmd, 'BHh')

    def set_cal(self, gains, offsets, flag):
        """
        Set device calibration.
        """
        if flag == "M":
            for i in range(1, 6):
                self.__set_calibration(i, gains[i-1], offsets[i-1])
        if flag == "SE":
            for i in range(1, 9):
                self.__set_calibration(i, gains[i-1], offsets[i-1])
        if flag == "DE":
            for i in range(9, 17):
                self.__set_calibration(i, gains[i-9], offsets[i-9])

    def set_DAC_cal(self, gain, offset):
        """
        Set DAC calibration.
        """
        self.__set_calibration(0, gain, offset)

    def conf_channel(self, number, mode, pinput, ninput=0, gain=1, nsamples=1):
        """
        Configure one of the experiments (ANALOG, +IN, -IN, GAIN).

        Args:
            number: variable that defines the number of DataChannel
            to assign.
            mode: variable that defines mode [0:5], 0 ANALOG_INPUT,
            1 ANALOG_OUTPUT, 2 DIGITAL_INPUT, 3 DIGITAL_OUTPUT,
            4 COUNTER_INPUT, 5 CAPTURE INPUT.
            pinput: variable that defines positive/SE analog input [1:8]
            (default 5).
            ninput: variable that defines negative analog input
            [0, 25, 5:8] (default 0).
            gain: variable that defines gain multiplier [0:4]
            (0 x(1/2), 1 x(1), 2 x(2, 3 x(10), 4 x(100) default(1)).
            nsamples: variable that defines number of samples per point
            [1:255].
        """
        if not 1 <= number <= 4:
            raise ValueError('Invalid number')
        if type(mode) == str and mode in INPUT_MODES:
            mode = INPUT_MODES.index(mode)
        cmd = struct.pack('>BBBBBBBB', 22, 6, number, mode,
                          pinput, ninput, gain, nsamples)
        return self.send_command(cmd, 'BBBBBB')

    def setup_channel(self, number, npoints, continuous=True):
        """
        Configure the experiment's number of points.

        Args:
            number: variable that defines the number of DataChannel
            to assign.
            npoints: variable that defines the number of total points
            [0:65536] (0 indicates continuous acquisition).
            continuous: variable that defines repetition mode [0:1]
            0 continuous, 1 run once.
        """
        if not 1 <= number <= 4:
            raise ValueError('Invalid number')
        cmd = struct.pack('>BBBHb', 32, 4, number, npoints, int(continuous))
        return self.send_command(cmd, 'BHB')

    def destroy_channel(self, number):
        """
        Delete Datachannel structure.

        Args:
            number: variable that defines the number of DataChannel to clear
            [0:4] 0 reset all DataChannel.
        """
        if not 1 <= number <= 4:
            raise ValueError('Invalid number')
        cmd = struct.pack('>BBB', 57, 1, number)
        return self.send_command(cmd, 'B')

    def create_stream(self, number, period):
        """
        Create stream experiment.

        Args:
            number: variable that defines the number of DataChannel to assign
            [1:4].
            period: variable that defines the period of the stream experiment
            [1:65536].
        """
        if not 1 <= number <= 4:
            raise ValueError('Invalid number')
        if not 1 <= period <= 65535:
            raise ValueError('Invalid period')
        cmd = struct.pack('>BBBH', 19, 3, number, period)
        return self.send_command(cmd, 'BH')

    def create_burst(self, period):
        """
        Create burst experiment.

        Args:
            period: variable that defines the period of the burst experiment
            (microseconds) [100:65535].
        """
        cmd = struct.pack('>BBH', 21, 2, period)
        return self.send_command(cmd, 'H')

    def create_external(self, number, edge):
        """
        Create external experiment.

        Args:
            number: variable that defines the number of DataChannel to assign
            [1:4].
            edge: [0:1].
        """
        if not 1 <= number <= 4:
            raise ValueError('Invalid number')
        cmd = struct.pack('>BBBB', 20, 2, number, edge)
        return self.send_command(cmd, 'BB')

    def load_signal(self, data, offset):
        """
        Load an array of values to preload DAC output.

        Args:
            data: variable that defines the data number [1:400].
            offset:
        """
        cmd = struct.pack(
            '>bBh%dh' % len(data), 23, len(data) * 2 + 2, offset, *data)
        return self.send_command(cmd, 'Bh')

    def start(self):
        """
        Start an automated measurement.
        """
        self.send_command('\x40\x00', '')

    def stop(self):
        """
        Stop actual measurement.
        """
        self.send_command('\x50\x00', '')
        time.sleep(1)
        self.flush()

    def flush(self):
        """
        Call ser.flushInput().
        """
        self.ser.flushInput()

    def flush_stream(self, data, channel):
        """
        Get stream from serial and reveive data in the buffer.

        Args:
           data: variable that defines the data
           channel: variable that defines the channel

        Returns:
            0 if there aren't any incoming data.
            1 if data stream was processed.
            2 if no data stream received. Useful for debuging.

        Raises:
           LengthError: An error ocurred.
        """
        # Receive all stream data in the in buffer
        while 1:
            ret = self.ser.read(1)
            if not ret:
                break
            else:
                cmd = struct.unpack('>b', ret)
                if cmd[0] == 0x7E:
                    self.header = []
                    self.data = []
                    while len(self.header) < 8:
                        ret = self.ser.read(1)
                        char = struct.unpack('>B', ret)
                        if char[0] == 0x7D:
                            ret = self.ser.read(1)
                        self.header.append(char[0])
                    length = self.header[3]
                    self.dataLength = length - 4
                    while len(self.data) < self.dataLength:
                        ret = self.ser.read(1)
                        char = struct.unpack('>B', ret)
                        if char[0] == 0x7D:
                            ret = self.ser.read(1)
                            char = struct.unpack('>B', ret)
                            tmp = char[0] | 0x20
                            self.data.append(tmp)
                        else:
                            self.data.append(char[0])
                    if check_stream_crc(self.header, self.data) != 1:
                        continue
                    for i in range(0, self.dataLength, 2):
                        value = (self.data[i] << 8) | self.data[i+1]
                        if value >= 32768:
                            value -= 65536
                        data.append(int(value))
                        channel.append(self.header[4]-1)
                else:
                    break
        ret = self.ser.read(3)
        ret += str(cmd[0])
        if len(ret) != 4:
            raise LengthError

    # This function reads a stream from serial connection.
    # Returns 0 if there is not incoming data
    # Returns 1 if data stream was precessed
    # Returns 2 if no data stream was received (useful for debugging)
    def get_stream(self, data, channel, callback=0):
        """
        Args:
            data: variable that defines the data
            channel: variable that defines the channel
            callback: variable that defines the callback mode

        Returns:
            0 ???
            1 ???
            2 ???
            3 ???
        """
        self.header = []
        self.data = []
        ret = self.ser.read(1)
        if not ret:
            return 0
        head = struct.unpack('>b', ret)
        if head[0] != 0x7E:
            data.append(head[0])
            return 2
        # Get header
        while len(self.header) < 8:
            ret = self.ser.read(1)
            char = struct.unpack('>B', ret)
            if char[0] == 0x7D:
                ret = self.ser.read(1)
                char = struct.unpack('>B', ret)
                tmp = char[0] | 0x20
                self.header.append(tmp)
            else:
                self.header.append(char[0])
            if len(self.header) == 3 and self.header[2] == 80:
                # openDAQ sent a stop command
                ret = self.ser.read(2)
                char, ch = struct.unpack('>BB', ret)
                channel.append(ch-1)
                return 3
        self.dataLength = self.header[3] - 4
        while len(self.data) < self.dataLength:
            ret = self.ser.read(1)
            char = struct.unpack('>B', ret)
            if char[0] == 0x7D:
                ret = self.ser.read(1)
                char = struct.unpack('>B', ret)
                tmp = char[0] | 0x20
                self.data.append(tmp)
            else:
                self.data.append(char[0])
        for i in range(0, self.dataLength, 2):
            value = (self.data[i] << 8) | self.data[i+1]
            if value >= 32768:
                value -= 65536
            data.append(int(value))
        check_stream_crc(self.header, self.data)
        channel.append(self.header[4]-1)
        return 1

    def setVHW(self, v):
        """
        Choose the hardware version.

        Args:
            v: variable that defines the hardware version (m openDAQ[M],
            s openDAQ[S]).
        """
        self.vHW = v

    def set_DAC_gain_offset(self, g, o):
        """
        Set DAC gain and offset.

        Args:
            g: variable that defines DAC gain.
            o: variable that defines DAC offset.
        """
        self.dacGain = g
        self.dacOffset = o

    def set_gains_offsets(self, g, o):
        """
        Set gains and offsets.

        Args:
            g: variable that defines gains.
            o: variable that defines offsets.
        """
        self.gains = g
        self.offset = o

    def set_id(self, id):
        """
        Identify openDAQ device.

        Args:
            id: variable that defines id number [000:999].
        """
        cmd = struct.pack('>BBI', 39, 4, id)
        return self.send_command(cmd, 'bbI')

    def spisw_config(self, cpol, cpha):
        if not 0 <= cpol <= 1 or not 0 <= cpha <= 1:
            raise ValueError('Invalid spisw_config values')
        cmd = struct.pack('>BBB', 26, 2, cpol, cpha)
        return self.send_command(cmd, 'BB')

    def spisw_setup(self, nbytes, bbsck=1, bbmosi=2, bbmiso=3):
        if not 0 <= nbytes <= 3:
            raise ValueError('Invalid number of bytes')
        if not 1 <= bbsck <= 6 or not 1 <= bbmosi <= 6 or not 1 <= bbmosi <= 6:
            raise ValueError('Invalid spisw_setup values')
        cmd = struct.pack('>BBBBB', 28, 3, bbsck, bbmosi, bbmiso)
        return self.send_command(cmd, 'BBB')

    def spisw_bytetransfer(self, value):
        cmd = struct.pack('>BBB', 29, 1, value)
        return self.send_command(cmd, 'B')[0]

    def spisw_wordtransfer(self, value):
        cmd = struct.pack('>BBH', 29, 2, value)
        return self.send_command(cmd, 'H')[0]


if __name__ == '__main__':
    daq = DAQ('COM4')
    daq.set_dac(3)
    daq.create_stream(1, 500)
    daq.conf_channel(1, 'ANALOG_INPUT', 8)
    daq.setup_channel(1, 20)
    daq.start()
    data = []
    channel = []
    for i in xrange(40):
        daq.get_stream(data, channel)
    daq.flush()
    daq.stop()