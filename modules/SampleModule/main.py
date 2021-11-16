# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.

import random
import time
import sys
import iothub_client
import json
import asyncio
# pylint: disable=E0611
from iothub_client import IoTHubModuleClient, IoTHubClientError, IoTHubTransportProvider
from iothub_client import IoTHubMessage, IoTHubMessageDispositionResult, IoTHubError
from pyModbusTCP.client import ModbusClient

# messageTimeout - the maximum time in milliseconds until a message times out.
# The timeout period starts at IoTHubModuleClient.send_event_async.
# By default, messages do not expire.
MESSAGE_TIMEOUT = 10000

# global counters
RECEIVE_CALLBACKS = 0
SEND_CALLBACKS = 0
THRESHOLD = 70.0

# Choose HTTP, AMQP or MQTT as transport protocol.  Currently only MQTT is supported.
PROTOCOL = IoTHubTransportProvider.MQTT

# Callback received when the message that we're forwarding is processed.
def send_confirmation_callback(message, result, user_context):
    global SEND_CALLBACKS
    print ( "Confirmation[%d] received for message with result = %s" % (user_context, result) )
    map_properties = message.properties()
    key_value_pair = map_properties.get_internals()
    print ( "    Properties: %s" % key_value_pair )
    SEND_CALLBACKS += 1
    print ( "    Total calls confirmed: %d" % SEND_CALLBACKS )


# receive_message_callback is invoked when an incoming message arrives on the specified 
# input queue (in the case of this sample, "input1").  Because this is a filter module, 
# we will forward this message onto the "output1" queue.
def receive_message_callback(message, hubManager):
    global RECEIVE_CALLBACKS
    message_buffer = message.get_bytearray()
    size = len(message_buffer)
    print ( "    Data: <<<%s>>> & Size=%d" % (message_buffer[:size].decode('utf-8'), size) )
    map_properties = message.properties()
    key_value_pair = map_properties.get_internals()
    print ( "    Properties: %s" % key_value_pair )
    RECEIVE_CALLBACKS += 1
    print ( "    Total calls received: %d" % RECEIVE_CALLBACKS )
    hubManager.forward_event_to_output("output1", message, 0)
    return IoTHubMessageDispositionResult.ACCEPTED

async def check_level(hubManager):
    # Customize this coroutine to do whatever tasks the module initiates
    # TCP auto connect on first modbus request
    iologik = ModbusClient(host="192.168.4.254", port=502, unit_id=1, auto_open=True)
    iologik.open()
    alert = False
    message = ""
    while True:    
        # request will get a list --> cast first element to int or float
        level = iologik.read_input_registers(513,1)
        # check if read successful
        if level:
            print("")
        else:
            level = [-1]
            print("Level read error")

        #create float
        level = float(level[0])

        # Calculate Point Slope as in ThingsPro Gateway
        # Point-slope: OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) / (sourceMax-sourceMin)) + targetMin
        # point_slope(INPUT, sourceMin, sourceMax, targetMin, targetMax):
        level = point_slope(level, 0, 65535, 0, 100)
        print("Level %lf" % level)
        # LED Logic from depending on level2
        if level >= THRESHOLD:
            alert = True
            iologik.write_single_coil(0,1)
            print("Level -> %1f >= %1f, ALERT = %r", level, THRESHOLD, alert)
            message = create_message({"Level: %1f", level}, "ALERT")
        elif alert == True:
            iologik.write_single_coil(0,0)
            print("Level -> %1f < %1f, ALERT = %r", level, THRESHOLD, alert)
            alert = False
            message = create_message({"Level: %1f", level}, "ALERT")
        else:
            message = ""

        # sending message to IoTHub
        if message != "":
            await hubManager.forward_event_to_output("output1", message, 0)

        await asyncio.sleep(1)
    iologik.close()

def create_message(input, type):
        message_json = json.loads(input)
        message_json.custom_properties["MessageType"] = type
        return message_json

def point_slope(INPUT, sourceMin, sourceMax, targetMin, targetMax):
    # Calculate Point Slope as in ThingsPro Gateway
    # Point-slope: OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) / (sourceMax-sourceMin)) + targetMin
    OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) / (sourceMax-sourceMin)) + targetMin
    return OUTPUT

class HubManager(object):

    def __init__(
            self,
            protocol=IoTHubTransportProvider.MQTT):
        self.client_protocol = protocol
        self.client = IoTHubModuleClient()
        self.client.create_from_environment(protocol)

        # set the time until a message times out
        self.client.set_option("messageTimeout", MESSAGE_TIMEOUT)
        
        # sets the callback when a message arrives on "input1" queue.  Messages sent to 
        # other inputs or to the default will be silently discarded.
        self.client.set_message_callback("input1", receive_message_callback, self)

    # Forwards the message received onto the next stage in the process.
    def forward_event_to_output(self, outputQueueName, event, send_context):
        self.client.send_event_async(
            outputQueueName, event, send_confirmation_callback, send_context)

def main(protocol):
    try:
        print ( "\nPython %s\n" % sys.version )
        print ( "IoT Hub Client for Python" )

        hub_manager = HubManager(protocol)

        print ( "Starting the IoT Hub Python sample using protocol %s..." % hub_manager.client_protocol )
        check_level(hub_manager)
        print ( "The sample is now checking level and will indefinitely.  Press Ctrl-C to exit. ")

    except IoTHubError as iothub_error:
        print ( "Unexpected error %s from IoTHub" % iothub_error )
        return
    except KeyboardInterrupt:
        print ( "IoTHubModuleClient sample stopped" )

if __name__ == '__main__':
    main(PROTOCOL)