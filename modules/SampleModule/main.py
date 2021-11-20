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
MODBUS_TCP_CLIENT_ADDRESS = "192.168.4.254"

def create_module_clinet():

    moduleClient = IoTHubModuleClient.create_from_edge_environment()

    # Define behavior for receiving an input message on input1 and input2
    # NOTE: this could be a coroutine or a function
    def message_handler(message):
        if message.input_name == "control":
            print("Message received on \"Control\"")
            print("the data in the message received was ")
            print(message.data)
            print("custom properties are")
            print(message.custom_properties)
        else:
            print("message received on unknown input")

    # # Define behavior for receiving a twin desired properties patch
    # # NOTE: this could be a coroutine or function
    def twin_patch_handler(patch):
        print("the data in the desired properties patch was: {}".format(patch))

    # # Define behavior for receiving methods
    async def method_handler(method_request):
        if method_request.name == "get_data":
            print("Received request for data")
            method_response = MethodResponse.create_from_method_request(
                method_request, 200, "some data"
            )
            await moduleClient.send_method_response(method_response)
        else:
            print("Unknown method request received: {}".format(method_request.name))
            method_response = MethodResponse.create_from_method_request(
                method_request, 400, None)
            await moduleClient.send_method_response(method_response)

    # set the received data handlers on the client
    moduleClient.on_message_received = message_handler
    moduleClient.on_twin_desired_properties_patch_received = twin_patch_handler
    moduleClient.on_method_request_received = method_handler

    return moduleClient


async def temperature_handler(moduleClient):
    await moduleClient.connect()
    # TCP auto connect on first modbus request
    iologik = open_modbusTCP_client_connection(MODBUS_TCP_CLIENT_ADDRESS)

    while True:
        # request will get a list --> cast first element to int or float
        temperature = iologik.read_input_registers(512, 1)
        if not temperature:
            temperature = [-1]
            print("Temperature read error")

        #cast to float
        temperature = float(temperature[0])
        #scale read data
        temperature = point_slope(temperature, 0, 65535, 0, 100)
        data = {
            "machine": {
                "temperature": temperature
            },
            "timeCreated": "%s" % datetime.now().isoformat()
        }
        msg = create_message(json.dumps(data), "info")
        print(msg.data)

        # sending temperature data to moxa_demokit_streamAnalytics_DanielM module
        try:
            await moduleClient.send_message_to_output(msg, "temperature")
        except Exception as send_message_to_output_error:
            print("Unexpected error %s from IoTHub" %
                  send_message_to_output_error)

        # interupt coroutine for 5 sec.
        await asyncio.sleep(5)
    
    close_modbusTCP_client_connection(iologik)

async def knob2_handler(moduleClient):
    await moduleClient.connect()
    alert = False
    message = ""
    # Customize this coroutine to do whatever tasks the module initiates
    # TCP auto connect on first modbus request
    iologik = open_modbusTCP_client_connection(MODBUS_TCP_CLIENT_ADDRESS)

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
                await moduleClient.send_message_to_output(msg, "output1")
                print("Alert send to IotHub!")
            except Exception as send_message_to_output_error:
                print("Unexpected error %s from IoTHub" % send_message_to_output_error)
        elif level < THRESHOLD and alert == True:
            alert = False
            alert_time = datetime.now().strftime("%H:%M:%S")
            iologik.write_single_coil(0, 0)
            print("ALERT: %s \nLevel -> %1f < %1f, \ntime = %s" % (alert, level, THRESHOLD, alert_time))
    
    close_modbusTCP_client_connection(iologik)

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


def open_modbusTCP_client_connection(ipAddress):
    modbusClient = ModbusClient(host=ipAddress, port=502,
                           unit_id=1, auto_open=True)
    modbusClient.open()
    return modbusClient

def close_modbusTCP_client_connection(modbusClient):
    modbusClient.close()


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
