# The Nano's WiFi ESP32, wiring test: see main/main.c. Built by tools/wifi/build_esp_firmware.sh TARGET --wiretest.
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(wiretest)
