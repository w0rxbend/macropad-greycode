"""The greycode circuit: every part, its JLCPCB part number, its place on the board and its nets.

Pure Python, no KiCad import, so the netlist can be checked anywhere.

Two coordinate systems:
- board.toml: origin at the PCB's front-left corner, x right, y away from the user, mm.
- KiCad (everything in this file and the other generator modules): origin at the back-left corner, x right,
  y towards the user, top view. `kicad_xy` converts. The USB edge (board.toml y = depth) is KiCad y = 0.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOARD_SPEC = tomllib.loads((REPO_ROOT / "board.toml").read_text())
PCB = BOARD_SPEC["pcb"]
WIDTH, DEPTH = PCB["width"], PCB["depth"]

TOP = "top"
BOTTOM = "bottom"

GND = "GND"
VBUS = "VBUS"
V5 = "+5V"
V3 = "+3V3"
V1 = "+1V1"
NO_NET = ""

# JLCPCB part numbers. Shared parts were checked against the JLCPCB parts search on 2026-11-12 for the sibling
# board (~/Projects/macropad). The four new ones (RP2040, W25Q128JVSIQ, SK6812MINI-E, 4.7k) were checked against
# their JLCPCB part pages on 2026-11-15: part number and package only, not stock or price.
LCSC = {
    "RP2040": "C2040",
    "W25Q128JVS": "C97521",
    "AP2112K-3.3": "C51118",
    "USBLC6-2SC6": "C7519",
    "74LVC1T45": "C168856",
    # Abracon ABM8-272-T3: the crystal "Hardware design with RP2040" uses with 15 pF and 1 k.
    "12MHz": "C20625731",
    "USB-C": "C165948",
    "nSMD050": "C69688",
    "TS-1187A": "C318884",
    "SK6812MINI-E": "C5149201",
    "SK6812SIDE-A": "C5378721",
    "MX hot-swap": "C49352235",
    "EC11E18244AU": "C202365",
    # A 40-pin strip; break off four. Only if the OLED module comes without its own pins.
    "1x4 header": "C2337",
    "100nF": "C1525",
    "1uF": "C52923",
    "2.2uF": "C23630",
    "10uF": "C19702",
    "15pF": "C1548",
    "1k": "C11702",
    "4.7k": "C25900",
    "5.1k": "C25905",
    "27R": "C25100",
    "330R": "C25104",
}

MPN = {
    "RP2040": ("Raspberry Pi", "RP2040"),
    "W25Q128JVS": ("Winbond", "W25Q128JVSIQ"),
    "AP2112K-3.3": ("Diodes Incorporated", "AP2112K-3.3TRG1"),
    "USBLC6-2SC6": ("STMicroelectronics", "USBLC6-2SC6"),
    "74LVC1T45": ("Diodes Incorporated", "74LVC1T45W6-7"),
    "12MHz": ("Abracon", "ABM8-272-T3"),
    "USB-C": ("HRO (Korean Hroparts Elec)", "TYPE-C-31-M-12"),
    "nSMD050": ("TECHFUSE", "nSMD050"),
    "TS-1187A": ("XKB Connection", "TS-1187A-B-A-B"),
    "SK6812MINI-E": ("OPSCO Optoelectronics", "SK6812MINI-E"),
    "SK6812SIDE-A": ("OPSCO Optoelectronics", "SK6812SIDE-A"),
    "MX hot-swap": ("HanElectricity", "CPG151101S11-2"),
    "EC11E18244AU": ("Alps Alpine", "EC11E18244AU"),
    "1x4 header": ("BOOMELE", "2.54-1*40P"),
    "100nF": ("Samsung Electro-Mechanics", "CL05B104KO5NNNC"),
    "1uF": ("Samsung Electro-Mechanics", "CL05A105KA5NQNC"),
    "2.2uF": ("Samsung Electro-Mechanics", "CL10A225KO8NNNC"),
    "10uF": ("Samsung Electro-Mechanics", "CL10A106KP8NNNC"),
    "15pF": ("FH (Guangdong Fenghua)", "0402CG150J500NT"),
    "1k": ("UNI-ROYAL", "0402WGF1001TCE"),
    "4.7k": ("UNI-ROYAL", "0402WGF4701TCE"),
    "5.1k": ("UNI-ROYAL", "0402WGF5101TCE"),
    "27R": ("UNI-ROYAL", "0402WGF270JTCE"),
    "330R": ("UNI-ROYAL", "0402WGF3300TCE"),
}

FOOTPRINT = {
    "C0402": "Capacitor_SMD:C_0402_1005Metric",
    "C0603": "Capacitor_SMD:C_0603_1608Metric",
    "R0402": "Resistor_SMD:R_0402_1005Metric",
    "QFN56": "greycode:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm_ViaWindows",
    "SOIC8": "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm",
    "SOT23-5": "Package_TO_SOT_SMD:SOT-23-5",
    "SOT23-6": "Package_TO_SOT_SMD:SOT-23-6",
    "XTAL3225": "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
    "F1206": "Fuse:Fuse_1206_3216Metric",
    "TACT": "Button_Switch_SMD:SW_Push_1P1T_XKB_TS-1187A",
    "USBC": "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
    "HEADER4": "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
    "EC11": "Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
    "TESTPAD": "TestPoint:TestPoint_Pad_D1.0mm",
    "FIDUCIAL": "Fiducial:Fiducial_1mm_Mask2mm",
    "HOLE_M2": "greycode:Hole_M2",
    "LED_MINI_E": "greycode:SK6812MINI-E_Reverse",
    "LED_SIDE": "greycode:SK6812-side-a",
    "MX_HOTSWAP": "greycode:MX_Hotswap",
}

# Project footprints that are a stock footprint with only the paste changed: project -> stock. The copper must
# stay the stock footprint's (layout.check_derived_footprints), so the stock footprint the KiCad symbol names
# is still the one in use (schematic.check_part_against_symbol).
DERIVED_FOOTPRINTS = {
    # The exposed pad's paste as windows with the four ground vias between them (layout.EP_PASTE_WINDOWS).
    FOOTPRINT["QFN56"]: "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm",
}

HAND_SOLDERED = {"EC11", "HEADER4"}
NOT_A_PART = {"TESTPAD", "HOLE_M2", "FIDUCIAL"}


@dataclass(frozen=True)
class Part:
    ref: str
    value: str
    footprint_key: str
    x: float  # KiCad coordinates, see the module docstring
    y: float
    rotation: float = 0.0
    side: str = BOTTOM
    nets: dict[str, str] = field(default_factory=dict)

    @property
    def footprint(self) -> str:
        return FOOTPRINT[self.footprint_key]

    @property
    def lcsc(self) -> str:
        return "" if self.footprint_key in NOT_A_PART else LCSC[self.value]

    @property
    def manufacturer_part(self) -> tuple[str, str]:
        """(manufacturer, manufacturer part number); empty for a footprint that is not a part."""
        return ("", "") if self.footprint_key in NOT_A_PART else MPN.get(self.value, ("", ""))

    @property
    def machine_assembled(self) -> bool:
        """Placed by the assembly house. Hand-soldered parts and footprints that are not parts are not."""
        return self.footprint_key not in HAND_SOLDERED | NOT_A_PART


def kicad_xy(x: float, y: float) -> tuple[float, float]:
    """board.toml (front-left origin, y away from the user) -> KiCad (back-left origin, y towards the user)."""
    return x, round(DEPTH - y, 4)


def spec_xy(x: float, y: float) -> tuple[float, float]:
    """KiCad -> board.toml. The same mirror, so the same formula."""
    return kicad_xy(x, y)


# --- MCU geometry -----------------------------------------------------------------------------

MCU_X, MCU_Y = 26.0, 22.0
# Turned so that, seen from the top, the key GPIOs face the keys (front), USB and QSPI face the USB-C receptacle
# and the flash (right), and I2C, crystal, SWD, RUN and LED data face the display header and the buttons (left).
MCU_ROTATION = 270
_PAD_ROW_OFFSET = 3.4375  # QFN-56 pad centre to package centre (KiCad's stock footprint)
_PIN_PITCH = 0.4
_FIRST_PIN_OFFSET = 2.6
_PINS_PER_SIDE = 14


def _turned(dx: float, dy: float) -> tuple[float, float]:
    """An offset from the chip centre turned by MCU_ROTATION, as KiCad turns it seen from the top."""
    for _ in range(MCU_ROTATION // 90):
        dx, dy = dy, -dx
    return dx, dy


def mcu_pin_xy(pin: int) -> tuple[float, float]:
    """Top-view position of an MCU pad. The chip is on the bottom face, so unturned it appears mirrored: pins
    1-14 down the right side, 15-28 right to left along the front, 29-42 up the left side, 43-56 left to right
    along the back. layout.check_placement compares this with the placed footprint."""
    side, index = divmod(pin - 1, _PINS_PER_SIDE)
    along = -_FIRST_PIN_OFFSET + index * _PIN_PITCH
    offset = {0: (_PAD_ROW_OFFSET, along), 1: (-along, _PAD_ROW_OFFSET), 2: (-_PAD_ROW_OFFSET, -along),
              3: (along, -_PAD_ROW_OFFSET)}[side]
    dx, dy = _turned(*offset)
    return round(MCU_X + dx, 4), round(MCU_Y + dy, 4)


def _mcu_side(pin: int) -> int:
    return (pin - 1) // _PINS_PER_SIDE


def gpio_pin(gpio: int) -> int:
    """QFN-56 pin number of a GPIO (RP2040 datasheet, pinout). schematic.check_mcu_pins checks it against
    KiCad's RP2040 symbol."""
    gpio_pins = [2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18,
                 27, 28, 29, 30, 31, 32, 34, 35, 36, 37, 38, 39, 40, 41]
    return gpio_pins[gpio]


MCU_POWER_PINS = {
    1: V3, 10: V3, 22: V3, 33: V3, 42: V3, 49: V3,   # IOVDD
    23: V1, 50: V1,                                  # DVDD
    43: V3,                                          # ADC_AVDD
    44: V3,                                          # VREG_VIN
    45: V1,                                          # VREG_VOUT: the internal 1.1 V regulator's output
    48: V3,                                          # USB_VDD
    19: GND,                                         # TESTEN
    57: GND,                                         # exposed pad
}
MCU_FIXED_SIGNALS = {
    20: "XIN", 21: "XOUT", 24: "SWCLK", 25: "SWDIO", 26: "RUN", 46: "USB_DM", 47: "USB_DP",
    51: "QSPI_SD3", 52: "QSPI_SCLK", 53: "QSPI_SD0", 54: "QSPI_SD2", 55: "QSPI_SD1", 56: "QSPI_SS",
}
# One capacitor in front of each of these supply pins: capacitor -> MCU pin ("Hardware design with RP2040":
# 100 nF per IOVDD and DVDD pin, 1 uF on VREG_VIN and VREG_VOUT).
DECOUPLING_CAPS = {"C1": 1, "C3": 22, "C4": 33, "C5": 42, "C6": 44, "C7": 49}
VREG_IN_PIN = 44
# Pins whose own capacitor has no room in front of the pin: capacitor -> MCU pin. IOVDD pin 10 sits between two
# key GPIOs, and the 1.1 V pins (DVDD 23 and 50, VREG_VOUT 45) beside signal or supply pins. Each drops a via
# just inside the pad ring into its plane island (3.3 V or 1.1 V); its capacitor sits on that island as near as
# it fits. The 1.1 V capacitors sit behind the unused GPIOs at the back of the chip, on a lobe of the 1.1 V
# island. USB_VDD (48) and ADC_AVDD (43) are tied to the IOVDD or VREG_VIN pin beside them and reach that pin's
# capacitor; their own 100 nF sits on the 3.3 V plane nearby.
SECOND_SUPPLY_CAPS = {"C2": 10, "C8": 23, "C9": 50, "C10": 45, "C11": 48, "C12": 43}
VREG_OUT_PIN = 45
# Supply pins tied to the pin beside them by a short track outside the pad row: pin -> neighbour.
TIED_PINS = {43: 44, 48: 49}
# Supply pins that reach their plane through a via just inside the pad ring.
INNER_VIA_PINS = (10, 23, 45, 50)
# Pad centre to that via, towards the chip centre: 0.4 mm clear of the pad ends and of the exposed pad.
INNER_VIA_DEPTH = 1.1375
# Sideways shift (x, y) of a capacitor away from the spot straight in front of its pin: IOVDD 22 moves to the
# middle of the gap between XOUT and SWCLK, so both keep their lane.
DECOUPLING_SHIFT = {22: (0.0, -0.2)}
_SECOND_CAP_PLACE = {"C2": (20.8, 28.0, 90), "C8": (26.8, 14.6, 0), "C9": (26.8, 12.6, 0),
                     "C10": (26.8, 10.6, 0), "C11": (30.8, 27.8, 0), "C12": (30.8, 29.2, 0)}


def key_net(index: int) -> str:
    return f"KEY{index}"


def _gpio_nets() -> dict[int, str]:
    spec = BOARD_SPEC
    nets = {gpio: key_net(i) for i, gpio in enumerate(spec["keys"]["gpio"])}
    knob = spec["knob"]
    nets[knob["gpio_a"]] = "ENC_A"
    nets[knob["gpio_b"]] = "ENC_B"
    nets[knob["gpio_push"]] = "ENC_SW"
    display = spec["display"]
    nets[display["gpio_sda"]] = "I2C_SDA"
    nets[display["gpio_scl"]] = "I2C_SCL"
    nets[spec["leds"]["gpio_data"]] = "LED_DATA_3V3"
    return nets


GPIO_NETS = _gpio_nets()


def _mcu() -> Part:
    nets = {str(pin): net for pin, net in (MCU_POWER_PINS | MCU_FIXED_SIGNALS).items()}
    expected = len(BOARD_SPEC["keys"]["gpio"]) + 3 + 2 + 1
    assert len(GPIO_NETS) == expected, "two functions share a GPIO in board.toml"
    for gpio, net in GPIO_NETS.items():
        nets[str(gpio_pin(gpio))] = net
    return Part("U1", "RP2040", "QFN56", MCU_X, MCU_Y, MCU_ROTATION, nets=nets)


# --- parts around the MCU ---------------------------------------------------------------------

_RADIAL_ROTATION = {0: 180.0, 1: 90.0, 2: 0.0, 3: 270.0}  # pad 1 toward the chip
_OUTWARD = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}
# MCU pad centre to capacitor centre. Far enough for a via between the pin and the capacitor, in
# line with both, so the tracks of the neighbouring pins keep their way out.
DECOUPLING_DISTANCE = 2.0
# Along the same line: MCU pad centre to the supply via, and capacitor centre to its ground via.
SUPPLY_VIA_DISTANCE = 0.85
GROUND_VIA_DISTANCE = 1.45


def outward(pin: int) -> tuple[int, int]:
    """Unit step away from the chip, for the side this pin is on."""
    dx, dy = _turned(*_OUTWARD[_mcu_side(pin)])
    return round(dx), round(dy)


def radial_rotation(pin: int) -> float:
    """Rotation of a two-pad part in front of this pin with pad 1 toward the chip."""
    return (_RADIAL_ROTATION[_mcu_side(pin)] + MCU_ROTATION) % 360


def _decoupling_caps() -> list[Part]:
    caps = []
    for ref, pin in DECOUPLING_CAPS.items():
        pad_x, pad_y = mcu_pin_xy(pin)
        out_x, out_y = outward(pin)
        shift_x, shift_y = DECOUPLING_SHIFT.get(pin, (0.0, 0.0))
        caps.append(Part(
            ref, "1uF" if pin == VREG_IN_PIN else "100nF", "C0402",
            round(pad_x + out_x * DECOUPLING_DISTANCE + shift_x, 4),
            round(pad_y + out_y * DECOUPLING_DISTANCE + shift_y, 4),
            rotation=radial_rotation(pin),
            nets={"1": MCU_POWER_PINS[pin], "2": GND},
        ))
    for ref, pin in SECOND_SUPPLY_CAPS.items():
        x, y, rotation = _SECOND_CAP_PLACE[ref]
        caps.append(Part(ref, "1uF" if pin == VREG_OUT_PIN else "100nF", "C0402", x, y, rotation,
                         nets={"1": MCU_POWER_PINS[pin], "2": GND}))
    return caps


def _flash() -> list[Part]:
    """W25Q128JVS on the QSPI pins, with its 100 nF. Pin 1 /CS, 2 DO (IO1), 3 /WP (IO2), 4 GND, 5 DI (IO0),
    6 CLK, 7 /HOLD (IO3), 8 VCC."""
    return [
        Part("U5", "W25Q128JVS", "SOIC8", 37.0, 25.4, 0,
             nets={"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": GND, "5": "QSPI_SD0",
                   "6": "QSPI_SCLK", "7": "QSPI_SD3", "8": V3}),
        Part("C13", "100nF", "C0402", 35.6, 22.0, 0, nets={"1": V3, "2": GND}),
    ]


def _clock_and_reset() -> list[Part]:
    return [
        # 12 MHz crystal in front of XIN and XOUT (pins 20 and 21), the reference part and values of
        # "Hardware design with RP2040": ABM8-272-T3, 15 pF load capacitors, 1 k in series from XOUT.
        Part("Y1", "12MHz", "XTAL3225", 17.4, 23.0, 0,
             nets={"1": "XIN", "2": GND, "3": "XTAL_DRIVE", "4": GND}),
        Part("C14", "15pF", "C0402", 18.5, 26.2, 90, nets={"1": "XIN", "2": GND}),
        Part("C15", "15pF", "C0402", 13.9, 22.15, 0, nets={"1": "XTAL_DRIVE", "2": GND}),
        Part("R6", "1k", "R0402", 17.4, 20.5, 0, nets={"1": "XOUT", "2": "XTAL_DRIVE"}),
        # RESET pulls RUN low; RUN has the chip's own pull-up (RP2040 datasheet).
        Part("SW11", "TS-1187A", "TACT", 8.0, 9.0, 0, nets={"1": "RUN", "2": GND}),
        # BOOTSEL: QSPI_SS to ground through 1 k while plugging in, as in "Hardware design with RP2040".
        Part("R5", "1k", "R0402", 42.8, 23.4, 90, nets={"1": "QSPI_SS", "2": "BOOT"}),
        Part("SW10", "TS-1187A", "TACT", 42.0, 32.4, 0, nets={"1": "BOOT", "2": GND}),
        # SWD and supply probe pads.
        Part("TP1", "SWCLK", "TESTPAD", 12.0, 16.0, nets={"1": "SWCLK"}),
        Part("TP2", "SWDIO", "TESTPAD", 12.0, 18.5, nets={"1": "SWDIO"}),
        Part("TP3", "GND", "TESTPAD", 12.0, 13.5, nets={"1": GND}),
    ]


USB_MOUTH_OVERHANG = 0.5  # receptacle mouth past the back edge; the case slice can change it, see README


def _usb_and_power() -> list[Part]:
    connector_nets = {pad: GND for pad in ("A1", "A12", "B1", "B12", "S1")}
    connector_nets |= {pad: VBUS for pad in ("A4", "A9", "B4", "B9")}
    connector_nets |= {"A5": "CC1", "B5": "CC2", "A6": "USB_D_P", "B6": "USB_D_P",
                       "A7": "USB_D_N", "B7": "USB_D_N", "A8": NO_NET, "B8": NO_NET}
    receptacle_half_depth = 3.65
    usb_x = PCB["usb_x"]
    return [
        Part("J1", "USB-C", "USBC", usb_x, receptacle_half_depth - USB_MOUTH_OVERHANG, 180, nets=connector_nets),
        Part("R1", "5.1k", "R0402", usb_x - 6.0, 6.6, 90, nets={"1": "CC1", "2": GND}),
        Part("R2", "5.1k", "R0402", usb_x + 6.0, 6.6, 90, nets={"1": "CC2", "2": GND}),
        # Turned so its VBUS pin faces the receptacle's VBUS pads on the fuse side.
        Part("U3", "USBLC6-2SC6", "SOT23-6", usb_x, 11.6, 180,
             nets={"1": "USB_D_N", "6": "USB_D_N", "3": "USB_D_P", "4": "USB_D_P", "2": GND, "5": VBUS}),
        # 27 ohm in series with each data line, close to the MCU pins 46 and 47.
        Part("R3", "27R", "R0402", 32.6, 17.0, 90, nets={"1": "USB_D_N", "2": "USB_DM"}),
        Part("R4", "27R", "R0402", 33.6, 17.0, 90, nets={"1": "USB_D_P", "2": "USB_DP"}),
        Part("F1", "nSMD050", "F1206", 42.0, 3.4, 90, nets={"1": VBUS, "2": V5}),
        Part("U2", "AP2112K-3.3", "SOT23-5", 47.0, 4.6, 90,
             nets={"1": V5, "2": GND, "3": V5, "4": NO_NET, "5": V3}),
        Part("C16", "2.2uF", "C0603", 47.0, 1.6, 0, nets={"1": V5, "2": GND}),
        Part("C17", "10uF", "C0603", 50.6, 4.6, 90, nets={"1": V3, "2": GND}),
        Part("TP4", V5, "TESTPAD", 9.0, 37.6, nets={"1": V5}),
        Part("TP5", V3, "TESTPAD", 9.0, 34.4, nets={"1": V3}),
        Part("TP6", V1, "TESTPAD", 26.8, 9.0, nets={"1": V1}),
    ]


# --- inputs, display, lights ------------------------------------------------------------------

def key_centre(index: int) -> tuple[float, float]:
    """KiCad position of key `index` (row by row from the top-left, as board.toml lists the GPIOs)."""
    row, column = divmod(index, len(PCB["key_x"]))
    return kicad_xy(PCB["key_x"][column], PCB["key_y"][row])


KEY_COUNT = len(BOARD_SPEC["keys"]["gpio"])


def _keys() -> list[Part]:
    return [Part(f"SW{i + 1}", "MX hot-swap", "MX_HOTSWAP", *key_centre(i), nets={"1": key_net(i), "2": GND})
            for i in range(KEY_COUNT)]


# The EC11 footprint's origin is pad A; the shaft is 7.5 mm right and 2.5 mm below it (KiCad directions).
ENCODER_SHAFT_OFFSET = (7.5, 2.5)


def knob_centre() -> tuple[float, float]:
    return kicad_xy(*PCB["knob"])


def _encoder() -> list[Part]:
    shaft_x, shaft_y = knob_centre()
    dx, dy = ENCODER_SHAFT_OFFSET
    value = "EC11E18244AU"
    assert value in BOARD_SPEC["knob"]["part"], f"board.toml knob.part is not {value}"
    return [Part("ENC1", value, "EC11", shaft_x - dx, shaft_y - dy, side=TOP,
                 nets={"A": "ENC_A", "B": "ENC_B", "C": GND, "S1": "ENC_SW", "S2": GND, "MP": GND})]


# OLED header pins, left to right seen from the top, with the module's header at its back edge.
# MEASURE: both the order and the header position vary between 1.3in SH1106 modules.
OLED_PINS = ("GND", "VCC", "SCL", "SDA")
OLED_MODULE_SIZE = tuple(PCB["oled_module_size"])  # MEASURE
OLED_HEADER_INSET = 1.6  # module back edge to the header pin row, MEASURE
HEADER_PITCH = 2.54


def oled_header_first_pin() -> tuple[float, float]:
    centre_x, centre_y = kicad_xy(*PCB["oled_module_centre"])
    first_x = centre_x - HEADER_PITCH * (len(OLED_PINS) - 1) / 2
    return first_x, round(centre_y - OLED_MODULE_SIZE[1] / 2 + OLED_HEADER_INSET, 4)


def _display() -> list[Part]:
    signal_net = {"GND": GND, "VCC": V3, "SCL": "I2C_SCL", "SDA": "I2C_SDA"}
    x, y = oled_header_first_pin()
    return [
        # Stock pin header: pin 1 at the origin, the row runs down; turned 90 so it runs left to right.
        Part("J2", "1x4 header", "HEADER4", x, y, 90, side=TOP,
             nets={str(n): signal_net[name] for n, name in enumerate(OLED_PINS, start=1)}),
        Part("R7", "4.7k", "R0402", 20.0, 7.0, 90, nets={"1": "I2C_SDA", "2": V3}),
        Part("R8", "4.7k", "R0402", 21.0, 7.0, 90, nets={"1": "I2C_SCL", "2": V3}),
        Part("C18", "100nF", "C0402", 23.0, 7.0, 90, nets={"1": V3, "2": GND}),
    ]


# The per-key LED sits under the switch's LED window, 5.08 mm in front of the key centre (KiCad +y).
MINI_E_OFFSET = 5.08
# Its 100 nF: offset from the LED centre.
MINI_E_CAP_OFFSET = (4.6, 0.0)
EDGE_LED_INSET = 0.8  # SIDE-A body centre to the front edge
EDGE_LED_CAP_OFFSET = (0.0, -2.9)


def mini_e_xy(key: int) -> tuple[float, float]:
    x, y = key_centre(key)
    return x, round(y + MINI_E_OFFSET, 4)


def _leds() -> list[Part]:
    leds = BOARD_SPEC["leds"]
    assert leds["per_key"] == KEY_COUNT, "board.toml: one LED per key expected"
    assert len(leds["edge_x"]) == leds["edge"], "board.toml: leds.edge_x and leds.edge disagree"
    parts = [
        Part("U4", "74LVC1T45", "SOT23-6", 18.0, 35.8, 0,
             nets={"1": V3, "2": GND, "3": "LED_DATA_3V3", "4": "LED_DATA_5V", "5": V3, "6": V5}),
        # Series resistor at the level shifter's output (the SK6812 SIDE-A datasheet asks for one in the data
        # line). It slows the 5 V edges into the long track to the first LED.
        Part("R9", "330R", "R0402", 21.2, 37.6, 90, nets={"1": "LED_DATA_5V", "2": "LED_D0"}),
        Part("C19", "100nF", "C0402", 14.8, 34.6, 90, nets={"1": V3, "2": GND}),
        Part("C20", "100nF", "C0402", 14.8, 37.4, 90, nets={"1": V5, "2": GND}),
    ]
    # One chain in the firmware's order (firmware/greycode/keyboard.json rgb_matrix.layout): the per-key LEDs
    # row by row from the top-left, then the edge LEDs left to right.
    chain = [(mini_e_xy(i), "LED_MINI_E", "SK6812MINI-E", 0.0) for i in range(KEY_COUNT)]
    chain += [(kicad_xy(x, EDGE_LED_INSET), "LED_SIDE", "SK6812SIDE-A", 0.0) for x in leds["edge_x"]]
    cap_number = 21
    for i, ((x, y), key, value, rotation) in enumerate(chain):
        is_last = i == len(chain) - 1
        data_out = NO_NET if is_last else f"LED_D{i + 1}"
        if key == "LED_MINI_E":
            # Pin functions from the OPSCO and Mutipower pin tables; pad geometry is MEASURE (lib/SOURCES.txt).
            nets = {"1": V5, "2": data_out, "3": GND, "4": f"LED_D{i}"}
            cap_dx, cap_dy = MINI_E_CAP_OFFSET
        else:
            nets = {"1": f"LED_D{i}", "2": V5, "3": data_out, "4": GND}
            cap_dx, cap_dy = EDGE_LED_CAP_OFFSET
        parts.append(Part(f"LED{i + 1}", value, key, x, y, rotation, nets=nets))
        parts.append(Part(f"C{cap_number}", "100nF", "C0402", round(x + cap_dx, 4), round(y + cap_dy, 4), 90,
                          nets={"1": V5, "2": GND}))
        cap_number += 1
    return parts


def _mounting_holes() -> list[Part]:
    return [Part(f"H{i}", "M2", "HOLE_M2", *kicad_xy(x, y), side=TOP)
            for i, (x, y) in enumerate(PCB["holes"], start=1)]


# Three optical marks for the pick-and-place camera, on the assembly face, in three corners so the
# board cannot be read upside down.
FIDUCIALS = [(4.0, 30.0), (60.0, 30.0), (4.0, 92.0)]
FIDUCIAL_MASK_DIAMETER = 2.0


def _fiducials() -> list[Part]:
    return [Part(f"FID{i}", "fiducial", "FIDUCIAL", x, y) for i, (x, y) in enumerate(FIDUCIALS, start=1)]


def all_parts() -> list[Part]:
    parts = (
        [_mcu()] + _decoupling_caps() + _flash() + _clock_and_reset() + _usb_and_power()
        + _keys() + _encoder() + _display() + _leds() + _mounting_holes() + _fiducials()
    )
    refs = [part.ref for part in parts]
    assert len(refs) == len(set(refs)), "duplicate reference designator"
    return parts


def nets_to_pads(parts: list[Part]) -> dict[str, list[str]]:
    connections: dict[str, list[str]] = {}
    for part in parts:
        for pad, net in part.nets.items():
            if net != NO_NET:
                connections.setdefault(net, []).append(f"{part.ref}.{pad}")
    return connections


def check_netlist(parts: list[Part]) -> None:
    """Every signal net needs at least two pads; a single-pad net is a wiring mistake."""
    dangling = sorted(net for net, pads in nets_to_pads(parts).items() if len(pads) < 2)
    assert not dangling, f"nets with a single pad: {dangling}"


def check_sourcing(parts: list[Part]) -> None:
    """Every real part has a JLCPCB number, a manufacturer and a manufacturer part number."""
    real = [part for part in parts if part.footprint_key not in NOT_A_PART]
    no_lcsc = sorted({part.value for part in real if not part.lcsc.startswith("C")})
    assert not no_lcsc, f"no JLCPCB part number for {no_lcsc}"
    no_mpn = sorted({part.value for part in real if not all(part.manufacturer_part)})
    assert not no_mpn, f"no manufacturer or part number for {no_mpn}"
    assert LCSC.keys() == MPN.keys(), f"LCSC and MPN list different parts: {sorted(LCSC.keys() ^ MPN.keys())}"


if __name__ == "__main__":
    circuit = all_parts()
    check_netlist(circuit)
    check_sourcing(circuit)
    for net_name, pad_names in sorted(nets_to_pads(circuit).items()):
        print(f"{net_name:14} {' '.join(pad_names)}")
