"""F1C200s prototyping board - netlist, the single source of truth.

Every part is declared here with its symbol, footprint, value and a
pin-number -> net map. gen_sch.py draws the schematic from it, gen_pcb.py
places the board from it. Section references are to ../../DESIGN.md.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# footprints
R0805 = "Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder"
C0805 = "Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder"
C1206 = "Capacitor_SMD:C_1206_3216Metric_Pad1.33x1.80mm_HandSolder"
L_PWR = "Inductor_SMD:L_Bourns-SRN4018"          # 4 x 4 x 1.8 mm, low enough under the ribbon
L0805 = "Inductor_SMD:L_0805_2012Metric_Pad1.05x1.20mm_HandSolder"
LED0805 = "LED_SMD:LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x%02d_P2.54mm_Vertical"
TP = "TestPoint:TestPoint_Pad_D1.5mm"

SHEETS = [
    ("power", "Power"),
    ("soc", "F1C200s"),
    ("display", "LCD, backlight, touch"),
    ("storage", "microSD and SPI flash"),
    ("wifi", "ESP32-C3 WiFi"),
    ("audio", "Audio"),
    ("io", "I/O expander and breakouts"),
]

# nets drawn with power symbols (everything else becomes a label)
POWER_NETS = {"GND": "power:GND", "+5V": "power:+5V", "+3V3": "power:+3V3",
              "+1V1": "power:+1V1", "+2V5": "power:+2V5", "+3V0": "power:+3V0"}

parts = []
_counters = {}


def _ref(prefix):
    _counters[prefix] = _counters.get(prefix, 0) + 1
    return "%s%d" % (prefix, _counters[prefix])


class Part:
    def __init__(self, sheet, prefix, lib_id, value, footprint, pins, ref=None, dnp=False, fields=None, nc=()):
        self.sheet = sheet
        self.ref = ref or _ref(prefix)
        self.lib_id = lib_id
        self.value = value
        self.footprint = footprint
        self.pins = {str(k): v for k, v in pins.items()}   # number -> net
        self.nc = set(str(x) for x in nc)
        self.dnp = dnp
        self.fields = fields or {}
        parts.append(self)


SHEET = "power"


def sheet(name):
    global SHEET
    SHEET = name


def R(val, a, b, fp=R0805, **kw):
    return Part(SHEET, "R", "Device:R", val, fp, {1: a, 2: b}, **kw)


def C(val, a, b, fp=C0805, **kw):
    return Part(SHEET, "C", "Device:C", val, fp, {1: a, 2: b}, **kw)


def CP(val, a, b, fp="Capacitor_SMD:CP_Elec_6.3x5.8", **kw):
    return Part(SHEET, "C", "Device:C_Polarized", val, fp, {1: a, 2: b}, **kw)


def L(val, a, b, fp=L_PWR, **kw):
    return Part(SHEET, "L", "Device:L", val, fp, {1: a, 2: b}, **kw)


def LED(val, a, k, **kw):
    return Part(SHEET, "D", "Device:LED", val, LED0805, {2: a, 1: k}, **kw)


def TPt(net, label=None):
    return Part(SHEET, "TP", "Connector:TestPoint", label or net, TP, {1: net})


def HEADER(nets, value=None, fp=None, **kw):
    n = len(nets)
    return Part(SHEET, "J", "Connector:Conn_01x%02d_Pin" % n, value or "Conn_01x%02d" % n,
                fp or HDR % n, {i + 1: net for i, net in enumerate(nets)}, **kw)


# ======================================================================
# Power  (DESIGN.md "Power")
# ======================================================================
sheet("power")

Part(SHEET, "J", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C (power, OTG, FEL)",
     "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
     {"A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND",
      "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
      "A5": "USB_CC1", "B5": "USB_CC2",
      "A6": "USB_DP", "B6": "USB_DP", "A7": "USB_DM", "B7": "USB_DM",
      "SH": "GND"}, nc=("A8", "B8"))
R("5.1k", "USB_CC1", "GND")
R("5.1k", "USB_CC2", "GND")
Part(SHEET, "U", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
     {1: "USB_DP", 6: "USB_DP", 3: "USB_DM", 4: "USB_DM", 2: "GND", 5: "+5V"})
Part(SHEET, "F", "Device:Polyfuse", "1.1A hold", "Fuse:Fuse_1206_3216Metric_Pad1.42x1.75mm_HandSolder",
     {1: "VBUS", 2: "+5V"})

# 2-pin 5 V input on the rail strip, reverse-polarity protected by a P-FET
HEADER(["VIN_EXT", "GND"], value="5V IN", fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-2-3.5-H_1x02_P3.50mm_Horizontal")
Part(SHEET, "Q", "Transistor_FET:AO3401A", "AO3401A", "Package_TO_SOT_SMD:SOT-23",
     {1: "QREV_G", 2: "+5V", 3: "VIN_EXT"})
R("10k", "QREV_G", "GND")

C("10u", "+5V", "GND", fp=C1206)

# three SY8089 bucks: Vout = 0.6 * (1 + Ra/Rb)
BUCKS = [("+1V1", "150k", "150k", "1.2 V (VDD-CORE, Nano values)"),
         ("+2V5", "470k", "160k", "2.36 V (VCC-DRAM, Nano values)"),
         ("+3V3", "680k", "150k", "3.32 V (VCC-IO)")]
prev = None
for i, (rail, ra, rb, note) in enumerate(BUCKS):
    n = i + 1
    en, lx, fb = "BUCK%d_EN" % n, "BUCK%d_LX" % n, "BUCK%d_FB" % n
    Part(SHEET, "U", "protoboard:SY8089", "SY8089AAAC", "Package_TO_SOT_SMD:SOT-23-5",
         {4: "+5V", 1: en, 2: "GND", 3: lx, 5: fb}, fields={"Note": note})
    C("10u", "+5V", "GND", fp=C1206)                 # input cap
    L("2.2uH", lx, rail)
    C("10u", rail, "GND", fp=C1206)                  # output cap
    R(ra + " 1%", rail, fb)
    R(rb + " 1%", fb, "GND")
    C("18p", rail, fb)
    # enable: 0R straight from 5 V by default (as the Nano); RC footprints to chain 1.1 -> 2.5 -> 3.3
    R("0R", "+5V", en)
    if prev:
        R("100k", prev, en, dnp=True)
    C("1u", en, "GND", dnp=True)
    prev = rail

# 3.0 V LDO for the codec AVCC
Part(SHEET, "U", "Regulator_Linear:XC6206PxxxMR", "LN6206P302", "Package_TO_SOT_SMD:SOT-23-3",
     {3: "+3V3", 2: "+3V0", 1: "GND"})
C("1u", "+3V3", "GND")
C("10u", "+3V0", "GND")
C("100n", "+3V0", "GND")

# power LED
R("1k", "+5V", "LED_PWR_A")
LED("green", "LED_PWR_A", "GND")

for net in ["+1V1", "+2V5", "+3V0"]:      # 5V / 3V3 / GND test access is the rail strip
    TPt(net)

# ======================================================================
# F1C200s  (DESIGN.md "F1C200s basics", pin plan)
# ======================================================================
sheet("soc")
F1C_PINS = {int(k): v for k, v in json.load(open(os.path.join(HERE, "f1c_pins.json"))).items()}
LCD_MAP = {}
for i in range(6):
    LCD_MAP["PD%d" % i] = "LCD_B%d" % (i + 2)
    LCD_MAP["PD%d" % (i + 6)] = "LCD_G%d" % (i + 2)
    LCD_MAP["PD%d" % (i + 12)] = "LCD_R%d" % (i + 2)
LCD_MAP.update({"PD18": "LCD_CLK", "PD19": "LCD_DE", "PD20": "LCD_HSYNC", "PD21": "LCD_VSYNC"})
GPIO_MAP = dict(LCD_MAP)
GPIO_MAP.update({
    "PF0": "SD_D1", "PF1": "SD_D0", "PF2": "SD_CLK", "PF3": "SD_CMD", "PF4": "SD_D3", "PF5": "SD_D2",
    "PE0": "UART0_RX", "PE1": "UART0_TX", "PE2": "ESP_EN_IN", "PE3": "GPIO_PE3", "PE4": "EXP_INT",
    "PE5": "SPI0_CS2", "PE6": "LCD_PWM", "PE7": "UART2_TX", "PE8": "UART2_RX",
    "PE9": "ESP_HANDSHAKE", "PE10": "ESP_DATAREADY", "PE11": "I2C0_SCL", "PE12": "I2C0_SDA",
    "PA0": "SPI1_CS", "PA1": "SPI1_MOSI", "PA2": "SPI1_CLK", "PA3": "SPI1_MISO",
    "PC0": "SPI0_CLK", "PC1": "SPI0_CS", "PC2": "SPI0_MISO", "PC3": "SPI0_MOSI",
})
OTHER_MAP = {
    "VDD-CORE": "+1V1", "VCC-DRAM": "+2V5", "VCC-IO": "+3V3", "UVCC": "+3V3", "HPVCC": "+3V3",
    "TV_VCC": "+3V3", "AVCC": "+3V0", "GND": "GND", "AGND": "GND", "TVGND": "GND",
    "SVREF": "SVREF", "VRA1": "VRA1", "VRA2": "VRA2", "RESET": "RESET", "HOSCI": "HOSCI", "HOSCO": "HOSCO",
    "USB-DP": "USB_DP", "USB-DM": "USB_DM", "LRADC0": "LRADC0", "MICIN": "MICIN", "HPL": "HPL", "HPR": "HPR",
}
F1C_NC = {"HPCOM", "HPCOMFB", "TVOUT", "TVIN0", "TVIN1", "TV_VRN", "TV_VRP", "FMINL", "FMINR", "LINEIN"}
f1c_pins, f1c_nc = {}, []
for num, name in F1C_PINS.items():
    key = name.split("/")[0]
    if key in GPIO_MAP:
        f1c_pins[num] = GPIO_MAP[key]
    elif key in OTHER_MAP:
        f1c_pins[num] = OTHER_MAP[key]
    elif key in F1C_NC:
        f1c_nc.append(num)
    else:
        raise KeyError(name)
Part(SHEET, "U", "protoboard:F1C200s", "F1C200s", None, f1c_pins, nc=f1c_nc,
     fields={"Note": "EP (pad 89) to GND with thermal vias"})

# crystal
Part(SHEET, "Y", "Device:Crystal_GND24", "24MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm_HandSoldering",
     {1: "HOSCI", 3: "HOSCO", 2: "GND", 4: "GND"})
C("18p", "HOSCI", "GND")
C("18p", "HOSCO", "GND")

# reset
R("47k", "+3V3", "RESET")
C("100n", "RESET", "GND")
Part(SHEET, "SW", "Switch:SW_Push", "RESET", "Button_Switch_THT:SW_PUSH_6mm", {1: "RESET", 2: "GND"})

# SVREF = VCC-DRAM / 2
R("2k 1%", "+2V5", "SVREF")
R("2k 1%", "SVREF", "GND")
C("100n", "SVREF", "GND")
C("100n", "+2V5", "SVREF")
# VRA1 / VRA2
for n in ("VRA1", "VRA2"):
    C("1u", n, "GND")
    R("200k 1%", n, "GND")

# decoupling (as the Nano)
C("10u", "+1V1", "GND", fp=C1206)
C("100n", "+1V1", "GND")
C("100n", "+1V1", "GND")
C("10u", "+3V3", "GND", fp=C1206)
C("100n", "+3V3", "GND")
C("100n", "+3V3", "GND")
C("1u", "+2V5", "GND")
C("100n", "+2V5", "GND")
C("10u", "+3V3", "GND", fp=C1206)     # TV_VCC
C("100n", "+3V3", "GND")              # TV_VCC
C("100n", "+3V3", "GND")              # UVCC
C("100n", "+3V3", "GND")              # HPVCC
C("100n", "+3V0", "GND")              # AVCC

# ======================================================================
# LCD, backlight, touch
# ======================================================================
sheet("display")
fpc = {1: "VLED-", 2: "VLED+", 3: "GND", 4: "+3V3", 5: "GND", 6: "GND",
       13: "GND", 14: "GND", 21: "GND", 22: "GND", 29: "GND", 30: "LCD_CLK", 31: "+3V3",
       32: "LCD_HSYNC", 33: "LCD_VSYNC", 34: "LCD_DE", 36: "GND",
       37: "TP_XR", 38: "TP_YD", 39: "TP_XL", 40: "TP_YU", "MP": "GND"}
for i in range(6):
    fpc[7 + i] = "LCD_R%d" % (i + 2)
    fpc[15 + i] = "LCD_G%d" % (i + 2)
    fpc[23 + i] = "LCD_B%d" % (i + 2)
Part(SHEET, "J", "Connector_Generic_MountingPin:Conn_01x40_MountingPin", "LCD 40P bottom-contact",
     "Connector_FFC-FPC:Hirose_FH12-40S-0.5SH_1x40-1MP_P0.50mm_Horizontal", fpc, nc=(35,),
     fields={"Note": "Hirose FH12-40S-0.5SH(55), bottom contact: the ribbon drops from the panel onto "
                     "the board's front edge, contacts face the board"})

# backlight boost
Part(SHEET, "U", "protoboard:PT4103", "PT4103", "Package_TO_SOT_SMD:SOT-23-6",
     {6: "+5V", 4: "BL_EN", 1: "BL_SW", 5: "VLED+", 3: "VLED-", 2: "GND"})
C("10u", "+5V", "GND", fp=C1206)
L("2.2uH", "+5V", "BL_SW")
Part(SHEET, "D", "Device:D_Schottky", "1N5819 (SOD-123)", "Diode_SMD:D_SOD-123", {2: "BL_SW", 1: "VLED+"})
C("10u 25V", "VLED+", "GND", fp=C1206)
C("100n 25V", "VLED+", "GND")
R("5.1R", "VLED-", "GND")
R("0R", "LCD_PWM", "BL_EN")
R("10k", "+3V3", "BL_EN")

# touch
Part(SHEET, "U", "protoboard:NS2009", "NS2009", None,
     {1: "+3V3", 2: "TP_XR", 3: "TP_YD", 4: "TP_XL", 5: "TP_YU", 6: "GND", 7: "TP_PENIRQ",
      8: "GND", 9: "I2C0_SDA", 10: "I2C0_SCL"}, fields={"Note": "I2C 0x48"})
C("100n", "+3V3", "GND")
R("100k", "+3V3", "TP_PENIRQ")
R("4.7k", "+3V3", "I2C0_SDA")
R("4.7k", "+3V3", "I2C0_SCL")

# ======================================================================
# microSD + SPI NOR
# ======================================================================
sheet("storage")
Part(SHEET, "J", "Connector:Micro_SD_Card_Det_Hirose_DM3AT", "microSD push-push",
     "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
     {1: "SD_D2", 2: "SD_D3", 3: "SD_CMD", 4: "+3V3", 5: "SD_CLK", 6: "GND", 7: "SD_D0", 8: "SD_D1",
      "SH": "GND"}, nc=(9, 10))
for n in ("SD_CMD", "SD_D0", "SD_D1", "SD_D2", "SD_D3"):
    R("47k", "+3V3", n)
C("100n", "+3V3", "GND")
# FEL: hold CMD low at power-up so the card never answers; boot ROM falls to SPI then FEL  (verify)
Part(SHEET, "SW", "Switch:SW_Push", "FEL", "Button_Switch_THT:SW_PUSH_6mm", {1: "FEL_SW", 2: "GND"})
R("470R", "SD_CMD", "FEL_SW")

Part(SHEET, "U", "Memory_Flash:W25Q128JVS", "W25Q128JVS (optional)", None,
     {1: "SPI0_CS", 6: "SPI0_CLK", 5: "SPI0_MOSI", 2: "SPI0_MISO", 3: "FLASH_WP", 7: "FLASH_HOLD", 8: "+3V3", 4: "GND"},
     dnp=True)
C("100n", "+3V3", "GND")
R("10k", "+3V3", "SPI0_CS")
R("10k", "+3V3", "FLASH_WP")
R("10k", "+3V3", "FLASH_HOLD")

# ======================================================================
# ESP32-C3 SuperMini
# ======================================================================
sheet("wifi")
Part(SHEET, "U", "Power_Management:TPS22917DBV", "TPS22917", None,
     {1: "+5V", 2: "GND", 3: "ESP_PWR_EN", 4: "ESP_SW_CT", 5: "ESP_QOD", 6: "ESP_5V"},
     fields={"Note": "load switch, controlled inrush (SY6280 / TPS22918 class)"})
C("10u", "+5V", "GND", fp=C1206)
C("1n", "ESP_SW_CT", "GND")
R("0R", "ESP_QOD", "ESP_5V")   # quick output discharge (series R sets its rate)
R("100k", "ESP_PWR_EN", "GND")
C("10u", "ESP_5V", "GND", fp=C1206)

Part(SHEET, "M", "protoboard:ESP32-C3_SuperMini", "ESP32-C3 SuperMini", None,
     {1: "ESP_5V", 2: "GND", 3: "ESP_3V3",
      4: "ESP_DATAREADY_O",   # GPIO4  data-ready
      5: "ESP_HANDSHAKE_O",   # GPIO3  handshake
      6: "ESP_MISO",          # GPIO2  SPI MISO (ESP-Hosted-NG default; strapping pin)
      14: "ESP_MOSI",         # GPIO7
      15: "ESP_CLK",          # GPIO6
      11: "ESP_CS",           # GPIO10
      12: "ESP_GPIO9",        # boot
      10: "ESP_RXD",          # GPIO20
      9: "ESP_TXD"},          # GPIO21
     nc=(7, 8, 13, 16),
     fields={"Note": "ESP-Hosted-NG C3 pins (verify against firmware)"})
C("100n", "ESP_3V3", "GND")

# 74LVC244 powered from the ESP's 3V3 so the ESP really turns off (Ioff)
Part(SHEET, "U", "74xx:74HC244", "74LVC244", "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
     {20: "ESP_3V3", 10: "GND", 1: "GND", 19: "GND",
      2: "SPI1_CS", 18: "ESP_CS",
      4: "SPI1_MOSI", 16: "ESP_MOSI",
      6: "SPI1_CLK", 14: "ESP_CLK",
      8: "UART2_TX_ESP", 12: "ESP_RXD",
      17: "ESP_EN_IN", 3: "ESP_EN",
      15: "ESP_BOOT_IN", 5: "ESP_GPIO9",
      13: "GND", 11: "GND"}, nc=(7, 9))
C("100n", "ESP_3V3", "GND")
R("10k", "+3V3", "ESP_EN_IN")
R("10k", "+3V3", "ESP_BOOT_IN")
R("10k", "+3V3", "SPI1_CS")
R("10k", "+3V3", "UART2_TX_ESP")

# lines out of the ESP: direct, pulled down so they don't float while it's off
for esp, soc in (("ESP_MISO", "SPI1_MISO"), ("ESP_TXD", "UART2_RX_ESP"),
                 ("ESP_HANDSHAKE_O", "ESP_HANDSHAKE"), ("ESP_DATAREADY_O", "ESP_DATAREADY")):
    R("0R", esp, soc)
    R("100k", soc, "GND")

# UART2: ESP (default) or breakout
Part(SHEET, "JP", "Jumper:SolderJumper_3_Bridged12", "UART2 TX: ESP|BRK",
     "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm_NumberLabels",
     {1: "UART2_TX_ESP", 2: "UART2_TX", 3: "UART2_TX_BRK"})
Part(SHEET, "JP", "Jumper:SolderJumper_3_Bridged12", "UART2 RX: ESP|BRK",
     "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm_NumberLabels",
     {1: "UART2_RX_ESP", 2: "UART2_RX", 3: "UART2_RX_BRK"})

# EN is not on the SuperMini's headers: bodge pad to the module's EN/RST
TPt("ESP_EN", "ESP_EN (bodge to module EN)")
for n in ("SPI1_CS", "SPI1_MOSI", "SPI1_CLK", "SPI1_MISO", "ESP_GPIO9", "ESP_HANDSHAKE", "ESP_DATAREADY", "ESP_5V", "ESP_3V3"):
    TPt(n)

# ======================================================================
# Audio (as the Nano dock)
# ======================================================================
sheet("audio")
Part(SHEET, "U", "Amplifier_Audio:PAM8403D", "PAM8403", None,
     {6: "AMP_VDD", 4: "+5V", 13: "+5V", 2: "GND", 15: "GND", 11: "GND",
      7: "AMP_INL", 10: "AMP_INR", 8: "AMP_VREF", 5: "+5V", 12: "AMP_SHDN",
      1: "SPK_L+", 3: "SPK_L-", 16: "SPK_R+", 14: "SPK_R-"}, nc=(9,))
L("10uH", "+5V", "AMP_VDD", fp=L0805)
C("1u", "AMP_VDD", "GND")
for _ in range(2):
    C("10u", "+5V", "GND", fp=C1206)
    C("1u", "+5V", "GND")
C("1u", "AMP_VREF", "GND")
R("100k", "AMP_SHDN", "GND")
for side in ("L", "R"):
    C("220n", "HP" + side, "AMP_C" + side)
    R("10k", "AMP_C" + side, "AMP_IN" + side)
HEADER(["SPK_L+", "SPK_L-"], value="Speaker L", fp="Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical")
HEADER(["SPK_R+", "SPK_R-"], value="Speaker R", fp="Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical")
# electret mic
R("2k", "+3V0", "MIC_BIAS")
C("10u", "MIC_BIAS", "GND")
R("2k", "MIC_BIAS", "MIC_P")
C("100n", "MIC_P", "MICIN")
HEADER(["MIC_P", "GND"], value="MIC")

# ======================================================================
# I/O expander, LEDs, breakouts, rails
# ======================================================================
sheet("io")
EXP = {4: "ESP_PWR_EN", 5: "ESP_BOOT_IN", 6: "AMP_SHDN", 7: "TP_PENIRQ", 8: "LED1_K", 9: "LED2_K",
       10: "FLASH_WP", 11: "EXP_P07"}
for i in range(8):
    EXP[13 + i] = "EXP_P1%d" % i
EXP.update({24: "+3V3", 12: "GND", 21: "GND", 2: "GND", 3: "GND", 22: "I2C0_SCL", 23: "I2C0_SDA", 1: "EXP_INT"})
Part(SHEET, "U", "Interface_Expansion:TCA9535PWR", "TCA9535PWR", None, EXP, fields={"Note": "I2C 0x20"})
C("100n", "+3V3", "GND")
R("10k", "+3V3", "EXP_INT")
for n in (1, 2):
    R("1k", "+3V3", "LED%d_A" % n)
    LED("status %d" % n, "LED%d_A" % n, "LED%d_K" % n)

# I2C: 2.54 mm header
HEADER(["GND", "+3V3", "I2C0_SDA", "I2C0_SCL"], value="I2C")
HEADER(["+3V3", "GND", "SPI0_CLK", "SPI0_MOSI", "SPI0_MISO", "SPI0_CS2"], value="SPI0")
HEADER(["GND", "UART0_RX", "UART0_TX"], value="CONSOLE (UART0)")
HEADER(["+3V3", "GND", "UART2_TX_BRK", "UART2_RX_BRK"], value="UART2")
HEADER(["+3V3", "GND", "GPIO_PE3", "LRADC0", "EXP_P07"] + ["EXP_P1%d" % i for i in range(8)], value="GPIO")

# NeoPixel
Part(SHEET, "U", "74xGxx:74AHCT1G125", "74AHCT1G125", "Package_TO_SOT_SMD:SOT-23-5",
     {5: "+5V", 3: "GND", 1: "GND", 2: "NEO_IN", 4: "NEO_Y"})
C("100n", "+5V", "GND")
Part(SHEET, "JP", "Jumper:SolderJumper_2_Open", "NeoPixel <- SPI0 MOSI",
     "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", {1: "SPI0_MOSI", 2: "NEO_IN"})
R("100k", "NEO_IN", "GND")
R("330R", "NEO_Y", "NEO_DOUT")
HEADER(["+5V", "NEO_DOUT", "GND"], value="NEOPIXEL")
C("47u 10V", "+5V", "GND", fp="Capacitor_SMD:C_1210_3225Metric_Pad1.33x2.70mm_HandSolder", dnp=True)   # bulk, optional

# RCWL-0516 (pins: 3V3 out, GND, OUT, VIN, CDS)
Part(SHEET, "J", "Connector:Conn_01x05_Socket", "RCWL-0516",
     "Connector_PinSocket_2.54mm:PinSocket_1x05_P2.54mm_Vertical",
     {2: "GND", 3: "GPIO_PE3", 4: "+5V"}, nc=(1, 5))

# rails strip along the bottom edge
RAIL_N = 32 if os.environ.get("SD_SIDE") == "1" else 26   # microSD on the back edge takes 6 holes
for net, val in (("+5V", "RAIL 5V"), ("+3V3", "RAIL 3V3"), ("GND", "RAIL GND")):
    HEADER([net] * RAIL_N, value=val, fp="protoboard:RailStrip_1x%02d_P2.54mm" % RAIL_N)

for _ in range(4):
    Part(SHEET, "H", "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", {})

for n in ("USB_DP", "USB_DM"):     # UART0 / I2C test access is on their headers
    TPt(n)

# default footprints for parts declared with None
for p in parts:
    if p.footprint is None:
        from kilib import get_symbol
        from sexp import findall
        s = get_symbol(p.lib_id)
        p.footprint = [x for x in findall(s, "property") if x[1] == "Footprint"][0][2]


def nets():
    out = {}
    for p in parts:
        for pin, net in p.pins.items():
            out.setdefault(net, []).append((p.ref, pin))
    return out


if __name__ == "__main__":
    ns = nets()
    print(len(parts), "parts,", len(ns), "nets")
    for n, m in sorted(ns.items()):
        if len(m) < 2:
            print("SINGLE-PIN NET", n, m)
