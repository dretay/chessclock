/* Wiring test for the Nano's WiFi ESP32 (flashed in place of the ESP-Hosted firmware, then flashed back).
 *
 * Each of the six signal pins the Nano is wired to plays a square wave of its own: high for its time, low
 * for the same time, over and over (prime numbers of milliseconds, so no wire's rhythm is a multiple of
 * another's). The Nano's Settings > Device > WiFi > Wiring test listens on its six pins and names the ESP
 * pin each one hears: right, swapped, silent (not connected) or garbled (touching another wire). Then it
 * pulls the reset line (EN) low a moment: if every rhythm stops for the restart, the reset wire is right too.
 *
 * The pins are the ESP32 D1 mini / MiniKit's, by their silkscreen names (the JTAG names for IO12-15) and the
 * Nano header pins they go to (docs/wifi.md). The ESP32-C3's are set in its ESP-Hosted settings
 * (tools/wifi/sdkconfig.nano): add them below when the protoboard's C3 is wired.
 *
 * Built in Espressif's container by tools/wifi/build_esp_firmware.sh esp32 --wiretest; flashed by
 * tools/wifi/flash_esp.sh esp32 PORT --wiretest. While it runs it prints the table on its USB serial.
 */
#include <stdio.h>
#include "driver/gpio.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

typedef struct { int gpio, half_ms; const char *silk, *role, *nano; } wire_t;

#if CONFIG_IDF_TARGET_ESP32
static const wire_t WIRES[] = {
    {15,  5, "TDO (IO15)", "SPI CS",     "A0 (PA0)"},
    {13,  7, "TCK (IO13)", "SPI MOSI",   "A1 (PA1)"},
    {14, 11, "TMS (IO14)", "SPI clock",  "A2 (PA2)"},
    {12, 13, "TDI (IO12)", "SPI MISO",   "A3 (PA3)"},
    { 2, 17, "IO2",        "handshake",  "D6 (PE9)"},
    { 4, 19, "IO4",        "data ready", "D7 (PE10)"},
};
#else
#error "wiretest: this ESP's pins aren't in the table yet (the C3's are in tools/wifi/sdkconfig.nano): add them to WIRES"
#endif
#define NW (int)(sizeof WIRES / sizeof WIRES[0])

static void print_table(void) {
    printf("\nwiretest: each pin plays its own rhythm (high, then low, for this long)\n");
    for (int i = 0; i < NW; i++)
        printf("  %-11s %-11s %2d ms  -> Nano %s\n", WIRES[i].silk, WIRES[i].role, WIRES[i].half_ms, WIRES[i].nano);
    printf("then Settings > Device > WiFi > Wiring test on the Nano\n\n");
}

void app_main(void) {
    for (int i = 0; i < NW; i++) {
        gpio_reset_pin(WIRES[i].gpio);
        gpio_set_direction(WIRES[i].gpio, GPIO_MODE_OUTPUT);
        gpio_set_drive_capability(WIRES[i].gpio, GPIO_DRIVE_CAP_2);
        gpio_set_level(WIRES[i].gpio, 0);
    }
    print_table();
    const int64_t t0 = esp_timer_get_time();
    int64_t next_print = 10000;
    for (;;) {
        const int64_t ms = (esp_timer_get_time() - t0) / 1000;
        for (int i = 0; i < NW; i++) gpio_set_level(WIRES[i].gpio, (int)((ms / WIRES[i].half_ms) & 1));
        if (ms >= next_print) { next_print += 30000; print_table(); }   /* (again now and then: a serial monitor opened late) */
        vTaskDelay(1);                                                   /* (1 ms: the tick; the idle task's watchdog stays fed) */
    }
}
