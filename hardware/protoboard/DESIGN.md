# F1C200s Prototyping Board - Design Spec

A 72.5 x 118 mm board for a desk stand with the 5" 800x480 panel: the panel
stands in the upright part, the board lies flat in the base. On it: an F1C200s running Linux from a microSD card, an ESP32-C3 SuperMini
as a power-switchable WiFi co-processor, a PAM8403 speaker amplifier, the
40-pin LCD/touch connector, and a through-hole prototyping area with
breakouts.

Status: **schematic and autorouted board (5 connections left by hand) in [`kicad/`](kicad/README.md)**,
generated from `kicad/gen/design.py`. Items marked *(verify)* still need
checking before the board is ordered.

## References

The core circuits copy Sipeed's own, proven designs (both on
[dl.sipeed.com, LICHEE/Nano/HDK](https://dl.sipeed.com/shareURL/LICHEE/Nano/HDK)):

* **Lichee Pi Nano schematic** (`lichee_nano_8.16(Schematic).pdf`, drawn in
  KiCad): power, crystal, reset, SD card, 40-pin LCD, backlight, touch.
  The F1C100s and F1C200s are pin-compatible (QFN-88); the F1C200s has 64 MB
  of DRAM inside instead of 32 MB.
* **Lichee Pi Nano dock** (`lpi-nano-dock.pdf`): PAM8403 amplifier and
  microphone circuits on the same codec pins.
* **F1C200s datasheet** Rev 1.0: pin functions (section 4.2), supply ranges
  (5.2), power-up order (5.5).

## Decisions so far

| | |
|---|---|
| Size | 72.5 x 118 mm (grown from 90 x 70 for routing room; kept at this size for the stand's base), one M3 mounting hole in each corner |
| Layers | 4 (signal + GND pour / solid GND / signal + 3V3 pour / signal + GND pour) - the 0.4 mm-pitch F1C200s and the 22 LCD lines need the solid ground plane |
| Assembly | all by hand, hot air + stencil. Passives 0805 (the "0804" in the brief is taken to mean 0805); larger packages wherever there's a choice. Only the F1C200s (QFN-88, 0.4 mm) and the FPC connector (0.5 mm) are unavoidably fine-pitch |
| Orientation | flat in the stand's base, components up. The **front** edge (top in KiCad) is at the foot of the panel, the **back** edge (bottom in KiCad) is where the stand is powered from |
| Layout (board's own frame) | front half: the dedicated chips. Back half, front to back: breakout headers, through-hole prototyping grid (2.54 mm), then along the back edge the power rails, 5 V IN terminal, microSD slot and USB-C |
| LCD connector | bottom-contact FPC flush with the front edge: the ribbon drops from the panel onto it (see below) |
| Clock | no real-time clock: the time comes over WiFi (NTP) |

## Board outline and the LCD ribbon

The panel (F50GLQ24E22, 120.7 x 75.8 mm) has its ribbon leaving the bottom
edge of the panel. Measured on the panel, seen from the **front**:

* the ribbon starts 26 mm in from the left edge
* its wide section is 47 mm wide; the tail with the contacts is 21 mm wide
  (40 x 0.5 mm)
* 44 mm from the panel edge to the start of the copper contacts

In the stand the panel is upright and the board lies flat behind its foot,
front edge towards the panel. The ribbon hangs from the panel's bottom edge,
bends 90 degrees backwards onto the board's front edge, lies over the chip
half and runs into the connector about 30 mm back from the front edge:

* **bottom-contact connector:** hanging from the panel the contacts face
  forward, so after the bend they face down onto the board. The connector
  is a Hirose **FH12-40S-0.5SH(55)** (0.5 mm, 40 pins, bottom contact, flip
  lock), cable opening facing the front edge.
* **sideways:** seen from above from behind the stand (panel at the far
  side, as in KiCad's top view with the front edge at the top), left and
  right are the reverse of the front view. So the ribbon, 26 mm from the
  panel's left edge seen from the front, lands on the board's **right**:
  the tail covers ~72-93 mm from the board's left edge, the wide section
  ~46-93 mm (the board is centred under the 120.7 mm panel). The connector
  is centred 83 mm from the left edge.
* **pin 1** (checked on the panel): with the panel face up and the ribbon
  towards you, contacts up, pin 1 is the leftmost contact (pins 1-2 run to
  the backlight, 36-40 to the touch panel - the Lichee Nano pinout). That
  puts pin 1 at the right end of the connector seen from above.
* the front half is laid out to suit: the SoC sits just left of the
  connector, turned 90 degrees so its LCD pins (bottom and right sides) face
  it, and the ESP32 module is at the left edge, antenna outwards.
* **length:** the contacts start 44 mm from the panel edge and the
  connector's contact line is ~32 mm from the board's front edge, so the
  panel's bottom edge can sit up to ~10 mm from the board edge (less the
  bend); the case sets this.
* **under the ribbon:** its wide section covers roughly x = 46-93 mm over
  the first ~19 mm from the front edge, then the tail runs to the
  connector. Only low parts (passives, SOT-23, SMD inductors) go there.
* the microSD, USB-C and 5 V IN are on the back edge, reachable from behind
  the stand.

## Pin plan (from the F1C200s datasheet, section 4.2)

The F1C200s has only PA0-3, PC0-3, PD0-21, PE0-12 and PF0-5. The LCD alone
takes all of port D, so pins are the tightest constraint on this board.

| Pins | Use | Notes |
|---|---|---|
| PD0-PD21 | LCD, 18-bit RGB666 + CLK/DE/HSYNC/VSYNC | exactly as on the Nano (see the 40-pin table below) |
| PF0-PF5 | microSD (SDC0) | the boot card - the boot ROM looks here first |
| PE0 / PE1 | UART0 RX/TX | serial console, on its own 3-pin header (as on the Nano) |
| PE6 | PWM1 | backlight driver enable/dimming (as on the Nano; PWM under 1 kHz) |
| PE11 / PE12 | TWI0 (I2C) SCK/SDA | touch chip, I/O expander, the I2C breakouts (as on the Nano) |
| PA0-PA3 | SPI1 CS/MOSI/CLK/MISO | ESP32 link for wlan0. PA0-3 double as the SoC's own touch-panel pins, but the Nano doesn't use them for touch either (it uses the NS2009) |
| PE7 / PE8 | UART2 TX/RX | ESP32 programming (and optionally its Bluetooth HCI) |
| PE9 / PE10 | ESP handshake / data-ready | ESP-Hosted-NG needs both, as interrupts (port E has EINT) |
| PE2 | ESP EN (reset) | direct pin: the ESP-Hosted driver resets the ESP through it |
| PC0-PC3 | SPI0 | optional SPI NOR flash footprint (as on the Nano) + the SPI breakout + NeoPixel data |
| PE3, PE4, PE5 | free, interrupt-capable | PE3 breakout GPIO (e.g. RCWL-0516 output), PE4 I/O expander interrupt, PE5 SPI breakout CS |
| LRADC0 | breakout | analog keys / slow 0-2 V input (the dock uses it for a resistor-ladder keypad) |
| USB DP/DM | USB-C | power, USB OTG and FEL recovery flashing |
| HPL / HPR | PAM8403 inputs | as on the dock |
| MICIN | microphone | as on the dock |

**No spare hardware UART** remains for a UART breakout: UART1 only exists on
port A (taken by SPI1) and port D (the LCD). The console header doubles as
the UART breakout, and solder jumpers let UART2 go to the breakout instead
of the ESP32.

Slow control lines go through an **I2C I/O expander** (e.g. TCA9535 / PCA9535,
16 bits) *(verify package)*: ESP power, ESP GPIO9 (boot mode), amplifier
shutdown, touch pen-down, two status LEDs, SPI flash WP, and the rest broken
out as extra GPIO.

## Blocks

### Power (as on the Nano)

* **Input:** USB-C (5.1 k CC pull-downs) feeding a polyfuse, then the 5 V
  rail, plus a 2-pin 5 V input on the rail strip with reverse-polarity
  protection. ESD protection on USB D+/D-.
* **Rails** (Nano schematic, "DCDC&LDO"):
  * **three separate buck converters from 5 V**, making 1.1 V (VDD-CORE),
    2.5 V (VCC-DRAM) and 3.3 V (VCC-IO, UVCC, HPVCC, TV). The Nano uses one
    TMI7003 triple buck, but its fine-pitch QFN is impractical to hand-solder,
    so each rail gets its own SOT-23 buck - e.g. SY8089 class: 0.6 V
    reference like the TMI7003, 2 A, 5 V in *(verify part and stock)*. The
    Nano's output networks carry over unchanged: 2.2 uH inductor, 10 uF out,
    18 pF across the upper feedback resistor; Vout = 0.6 x (1 + Ra/Rb) with
    Ra/Rb = 150k/150k (1.1 V), 470k/160k (2.5 V), 680k/150k (3.3 V). Separate
    regulators also make the datasheet's start-up order possible later:
    each has its own EN pin, with RC-delay footprints chaining them
    1.1 -> 2.5 -> 3.3 V (fitted with 0 ohm / left empty by default, as the
    Nano runs without sequencing)
  * **3.0 V LDO from 3.3 V** for the codec's AVCC (Nano: LN6206P302,
    SOT-23) - quiet supply for the audio
  * SVREF = VCC-DRAM / 2: 2k/2k divider with 100 nF on each side
  * VRA1, VRA2: 1 uF + 200 k each to ground
  * decoupling per rail as on the Nano: 10 uF + 2 x 100 nF on VDD-CORE and
    VCC-IO, 1 uF + 100 nF on VCC-DRAM, 10 uF + 100 nF on TV
* **Start-up order:** the datasheet asks for 1.1, then 2.5, then 2.8/3.0,
  then 3.3 V. The Nano ignores this (all three buck channels enabled straight
  from 5 V) and works, so by default this board does the same; the EN chain
  footprints above are there if it ever turns out to matter.
* The **ESP32** runs from 5 V through its own switch (below), so its WiFi
  current peaks don't load the 3.3 V buck.
* **Rails strip** along the bottom edge: 5 V, 3.3 V and GND as long
  2.54 mm-pitch buses, each with a test point.

### F1C200s basics (as on the Nano)

* 24 MHz crystal on HOSCI/HOSCO with 18 pF to ground on each side.
* RESET: 47 k pull-up to 3.3 V, 100 nF to ground, plus a reset button.

### LCD, backlight and touch (as on the Nano)

**40-pin connector** (Nano J3), 0.5 mm pitch:

| Pin | Signal | Pin | Signal |
|---|---|---|---|
| 1 | LEDK (backlight -) | 2 | LEDA (backlight +) |
| 3 | GND | 4 | VCC 3.3 V |
| 5, 6 | R0, R1 -> GND | 7-12 | R2-R7 = LCD_D18-D23 (PD12-PD17) |
| 13, 14 | G0, G1 -> GND | 15-20 | G2-G7 = LCD_D10-D15 (PD6-PD11) |
| 21, 22 | B0, B1 -> GND | 23-28 | B2-B7 = LCD_D2-D7 (PD0-PD5) |
| 29 | GND | 30 | CLK (PD18) |
| 31 | DISP -> 3.3 V | 32 | HSYNC (PD20) |
| 33 | VSYNC (PD21) | 34 | DE (PD19) |
| 35 | NC | 36 | GND |
| 37 | XR (touch X+) | 38 | YD (touch Y+) |
| 39 | XL (touch X-) | 40 | YU (touch Y-) |

(Connector mounting pads to GND.)

**Backlight** (Nano "LCD Backlight"): PT4103 boost LED driver (SOT-23-6)
from 5 V. 2.2 uH inductor, 1N5819 Schottky (an SOD-123 equivalent is
fine), 10 uF/25 V + 100 nF/25 V output caps, 5.1 ohm sense resistor for
~20 mA (I = 104 mV / R). EN is driven from PWM1 (PE6) through 0 ohm, with
a 10 k pull-up to 3.3 V. The PWM must stay under 1 kHz (the clock software
uses 500 Hz).

**Touch** (Nano "Resistive touch screen IC"): NS2009 on I2C0, address 0x48
(A0 to GND). XP/YP/XN/YN = connector pins 37/38/39/40. Its pen-down output
(PENIRQ), unconnected on the Nano, goes to the I/O expander here, so touch
could become interrupt-driven later.

### microSD (as on the Nano)

Push-push microSD socket on SDC0 (PF0-PF5), 47 k pull-ups on CMD and D0-D3,
100 nF on its supply, mounting pads to GND. (The Nano's note: no series
termination needed for traces under 15 cm.)

### ESP32-C3 SuperMini (power-switchable WiFi)

* At the **left-hand edge** of the front half, antenna end at the board
  edge over a no-copper keep-out; the module's own USB-C faces inwards
  (towards the RESET/FEL buttons). In the stand the board is below the
  panel rather than behind it, so the panel's metal back shields the
  antenna less than before. Footprint for both its pin headers
  and soldering it down flat.
* **Power switch:** a load switch (e.g. SY6280 / TPS22918 class, with
  controlled inrush) on the module's 5 V input, enabled from the I/O
  expander. More robust than a bare P-MOSFET and limits inrush so switching
  it on doesn't dip the main rails.
* **Back-powering - easy to overlook:** with the ESP switched off, any
  F1C200s output still driving its pins would power it through its input
  protection diodes. Lines into the ESP (SPI MOSI/CLK/CS, UART TX, EN, GPIO9)
  go through a **74LVC244 buffer powered from the ESP's own 3.3 V**. LVC parts
  are safe when unpowered (Ioff), so the ESP truly turns off. Lines out of
  the ESP (MISO, UART RX, handshake, data-ready) get pull-downs so they don't
  float while it's off.
* **Programming from Linux:** UART2 + EN (PE2) + GPIO9 (expander): hold GPIO9
  low, pulse EN, run esptool on /dev/ttyS2 with no auto-reset.
* **wlan0:** ESP-Hosted-NG over SPI1, with handshake (PE9) and data-ready
  (PE10) as interrupts and reset on PE2. The ESP-side pins are set in its
  firmware; default to the ESP-Hosted-NG ESP32-C3 assignments *(verify)*,
  avoiding the C3's strapping pins (GPIO2, 8, 9) where possible.

### Audio (as on the Nano dock)

* **PAM8403** (SOP-16) from 5 V. Inputs from HPL and HPR, each through a
  220 nF capacitor and 10 k resistor. VDD fed through a 10 uH inductor from
  5 V; 10 uF + 1 uF on each PVDD side; 1 uF on VREF; MUTE tied high.
* **SHDN** driven from the I/O expander (the dock pulls it to 5 V with
  10 k; here a pull-down keeps the amp off until Linux enables it, so no
  hiss or power-up pop) *(verify SHDN logic threshold at 3.3 V)*.
* Outputs to two 2-pin JST-PH speaker connectors (4-8 ohm, 1-2 W each);
  populate one for mono. Bridged outputs: neither speaker wire may go to
  ground.
* **Microphone:** electret bias from AVCC through 2 k + 2 k with 10 uF
  filtering, 100 nF coupling into MICIN (dock "Main MIC"), on a 2-pin header.

### Other basics

* **Reset** and **FEL/boot** buttons (6 x 6 mm through-hole). With no SD card
  and no SPI flash the boot ROM drops to FEL (USB recovery); a "FEL" button
  that holds the SD card's CMD line inactive at power-up makes that possible
  without pulling the card *(verify approach)*.
* Optional SPI NOR (SOIC-8, e.g. W25Q128) on SPI0 with a 10 k CS pull-up,
  as on the Nano.
* Power LED (5 V), two status LEDs (expander).
* Test points on every rail, UART0, USB, SPI1 and the ESP control lines.

## Prototyping half

From the middle of the board down:

1. **Breakouts** (a row of 2.54 mm headers, each with its own 3.3 V and GND):
   * I2C on 2.54 mm pins - plug-in for the ambient-light sensor, the I2C
     rotary encoder and similar
   * SPI0 (MOSI/MISO/CLK + CS on PE5)
   * UART (see the pin plan)
   * GPIO: PE3 (interrupt-capable; e.g. the RCWL-0516's output), expander
     GPIO, LRADC0
   * **NeoPixel:** 3-pin header (5 V, data, GND) with a 74AHCT1G125
     3.3 V -> 5 V level shifter (WS2812s need ~3.5 V logic at 5 V), a 330 ohm
     series resistor and a footprint for a bulk capacitor. Data from SPI0
     MOSI (the usual Linux way to drive WS2812s), selected by a solder
     jumper
   * **RCWL-0516:** 5-pin footprint matching the module (needs 4-28 V in, so
     from 5 V; its 3.3 V output goes to PE3)
2. **Through-hole grid:** 2.54 mm, plated holes: 31 columns x 5 rows (the
   microSD slot takes the back-right corner).
3. **Rails:** 5 V, 3.3 V and GND strips (26 holes each) along the back edge.

## Open items

* Confirm with a mock-up of the stand that the ribbon reaches the FPC
  connector (~32 mm back from the front edge, ~72-93 mm from the left
  edge seen from above), contacts down.
* Parts picked in the KiCad design, to confirm against stock: SY8089AAAC
  buck (SOT-23-5), TPS22917 load switch (SOT-23-6), TCA9535PWR expander
  (TSSOP-24, 0.65 mm), Hirose FH12-40S-0.5SH(55) bottom-contact FPC, 74LVC244 in
  SOIC-20W, NS2009 assumed MSOP-10 *(verify)*.
* **ESP32-C3 SuperMini has no EN pin on its headers.** ESP_EN (buffered
  PE2) ends on a bodge pad for a wire to the module's EN/reset; without it,
  reset the ESP by power-cycling it through the load switch.
* SuperMini pinout and 15.24 mm row spacing in the custom footprint
  *(verify against the module)*.
* The SuperMini can go on headers or be soldered flat: its F.Cu pads are
  2.7 x 1.7 mm ovals running 0.5 mm past the module edge (an iron landing
  and fillet; inner layers and B.Cu keep 1.7 mm round pads), and the holes
  stay for headers or for feeding solder through the module's plated holes.
  The module has full holes 1.4 mm in from its edge, not castellations: if
  yours has half-holes at the edge, the rows are ~18 mm apart and the
  footprint is wrong. Flat, its underside rests on tented F.Cu tracks and
  vias: check the module's back for exposed copper (Kapton under it if so).
* F1C200s footprint: the stock QFN-88 10x10 with pads narrowed to 0.22 mm
  (0.18 mm gaps) and EP 6.74 mm *(verify EP size against the F1C200s package
  drawing)*.
* Routing: autorouted for the stand layout, 5 connections to finish by hand
  (a +2V5 SoC pin, RESET, two GND islands) - see [`kicad/README.md`](kicad/README.md#routing).
