# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license. See LICENSE file in the project root for
# full license information.
import sys
import asyncio
import uuid
import json
from datetime import datetime
from azure.iot.device import Message, MethodResponse
from azure.iot.device.aio import IoTHubModuleClient
from pyModbusTCP.client import ModbusClient

THRESHOLD = 70.0
MODBUS_TCP_CLIENT_ADDRESS = "192.168.4.254"

def create_module_clinet():

    moduleClient = IoTHubModuleClient.create_from_edge_environment()

    # Define behavior for receiving an input message on input1 and input2
    # NOTE: this could be a coroutine or a function
    async def message_handler(message):
        if message.input_name == "control":
            print("Message received on \"Control\"")
            print("the data in the message received was ")
            print(message.data)
            print("custom properties are")
            print(message.custom_properties)
            await temperature_alarm()
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
    # message_handler is asynchronous method, but can run without "awaited", because moduleClient is asynchronous (??)
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

    # TCP auto connect on first modbus request
    iologik = open_modbusTCP_client_connection(MODBUS_TCP_CLIENT_ADDRESS)

    while True:
        # request will get a list --> cast first element to int or float
        knob2 = iologik.read_input_registers(513, 1)
        # check if read successful
        if not knob2:
            knob2 = [-1]
            print("Level read error")
        # cast to float
        knob2 = float(knob2[0])

        # Calculate Point Slope as in ThingsPro Gateway
        knob2 = point_slope(knob2, 0, 65535, 0, 100)
        probe_time = datetime.now().isoformat()

        # alert logic
        if knob2 >= THRESHOLD and alert == False:
            alert = True
            iologik.write_single_coil(0, 1)
            data = {
                "machine": {
                    "knob2": knob2
            },
            "timeCreated": "%s" % probe_time
            }
            msg = create_message(json.dumps(data), "alert")

            print("==============================")
            print(msg.data)

            # sending alert message to IoTHub
            try:
                await moduleClient.send_message_to_output(msg, "knob2")
                print("Alert send to IotHub!")
                print("==============================")
            except Exception as send_message_to_output_error:
                print("Unexpected error %s from check_level method" %
                      send_message_to_output_error)
        elif knob2 < THRESHOLD and alert == True:
            alert = False
            iologik.write_single_coil(0,0)

        # interupt coroutine
        await asyncio.sleep(0)

    close_modbusTCP_client_connection(iologik)


def create_message(input, type):
    msg = Message(input)
    msg.message_id = uuid.uuid4()
    msg.content_type = "application/json"
    msg.content_encoding = "utf-8"
    msg.custom_properties["MsgType"] = type
    return msg


def point_slope(INPUT, sourceMin, sourceMax, targetMin, targetMax):
    # Point-slope: OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) / (sourceMax-sourceMin)) + targetMin
    OUTPUT = ((INPUT-sourceMin) * (targetMax-targetMin) /
              (sourceMax-sourceMin)) + targetMin
    return OUTPUT

async def temperature_alarm():
    modbusClient = open_modbusTCP_client_connection(MODBUS_TCP_CLIENT_ADDRESS)
    modbusClient.write_single_coil(1, 1)
    await asyncio.sleep(3)
    modbusClient.write_single_coil(1, 0)
    close_modbusTCP_client_connection(modbusClient)
    return 0
 

def open_modbusTCP_client_connection(ipAddress):
    modbusClient = ModbusClient(
        host=ipAddress, port=502, unit_id=1, auto_open=True)
    try:
        modbusClient.open()
    except Exception as modbusClientError:
        print("Unexpected error %s from open_modbusTCP_client_connection method" %
              modbusClientError)
    return modbusClient


def close_modbusTCP_client_connection(modbusClient):
    try:
        modbusClient.close()
    except Exception as modbusClientError:
        print("Unexpected error %s from close_modbusTCP_client_connection method" %
              modbusClientError)


async def run_function(moduleClient):
    await asyncio.gather(
        knob2_handler(moduleClient),
        temperature_handler(moduleClient)
    )


def main():
    print("Python %s" % sys.version)
    print("\n==============================\n")
    print("IoT Hub Client for Python - SampleModule")
    print("\n==============================")

    moduleClient = create_module_clinet()
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(run_function(moduleClient))
    except Exception as e:
        print("Unexpected error %s " % e)
        raise
    finally:
        print("Shutting down IoT Hub Client...")
        loop.run_until_complete(moduleClient.shutdown())
        loop.close()


if __name__ == '__main__':
    main()
