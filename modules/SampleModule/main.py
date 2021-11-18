# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.
import sys
import asyncio
import uuid
from datetime import datetime
from azure.iot.device import Message
from azure.iot.device.aio import IoTHubModuleClient
from pyModbusTCP.client import ModbusClient

THRESHOLD = 70.0
MODBUSC_CLIENT_ADDRESS = "192.168.4.254"

async def check_level(module_client):
    alert = False
    message = ""
    # Customize this coroutine to do whatever tasks the module initiates
    # TCP auto connect on first modbus request
    iologik = ModbusClient(host=MODBUSC_CLIENT_ADDRESS, port=502,
                           unit_id=1, auto_open=True)
    iologik.open()

    while True:
        # request will get a list --> cast first element to int or float
        level = iologik.read_input_registers(513, 1)
        # check if read successful
        if not level:
            level = [-1]
            print("Level read error")
        #create float
        level = float(level[0])

        # Calculate Point Slope as in ThingsPro Gateway
        level = point_slope(level, 0, 65535, 0, 100)

        # LED alert logic
        if level >= THRESHOLD and alert == False:
            alert = True
            iologik.write_single_coil(0, 1)
            alert_time = datetime.now().strftime("%H:%M:%S")
            print("ALERT: %s \nLevel -> %1f >= %1f, \ntime: %s" % (alert, level, THRESHOLD, alert_time))
            msg = create_message(str("Level: %1f, time: %s" % (level, alert_time)), "ALERT")
            # sending alert message to IoTHub
            try:
                await module_client.send_message_to_output(msg, "output1")
                print("Alert send to IotHub!")
            except Exception as send_message_to_output_error:
                print("Unexpected error %s from IoTHub" % send_message_to_output_error)
        elif level < THRESHOLD and alert == True:
            alert = False
            alert_time = datetime.now().strftime("%H:%M:%S")
            iologik.write_single_coil(0, 0)
            print("ALERT: %s \nLevel -> %1f < %1f, \ntime = %s" % (alert, level, THRESHOLD, alert_time))
    iologik.close()

def create_message(input, type):
    msg = Message(input)
    msg.message_id = uuid.uuid4()
    msg.correlation_id = "correlation-1234"
    msg.custom_properties["MsgType"] = type
    return msg

def point_slope(INPUT, sourceMin, sourceMax, targetMin, targetMax):
    # Calculate Point Slope as in ThingsPro Gateway
    # Point-slope: OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) / (sourceMax-sourceMin)) + targetMin
    OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) /
              (sourceMax-sourceMin)) + targetMin
    return OUTPUT

async def main():
    module_client = IoTHubModuleClient.create_from_edge_environment()
    await module_client.connect()
    print("\nPython %s\n" % sys.version)
    print("IoT Hub Client for Python")
    try:
        await check_level(module_client)
        print("The sample is now checking level and will indefinitely.  Press Ctrl-C to exit. ")
    except Exception as iothub_error:
        print("Unexpected error %s from IoTHub" % iothub_error)
        await module_client.shutdown()
        return

if __name__ == '__main__':
    asyncio.run(main())
