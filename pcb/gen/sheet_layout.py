"""Where everything sits on the schematic sheet. Data only; schematic.py draws it.

Units are grid steps of 1.27 mm. Inside a block, positions count from the block's top-left corner,
X to the right and Y down. A point is either a pin ("R7.1") or a position (x, y).

What is not listed here is drawn by rule (see schematic.py): a pin on a supply net gets a short
wire and the supply symbol, a pin on a signal net gets a short wire and the net's label, an open
pin gets a no-connect mark.
"""

from __future__ import annotations

from dataclasses import dataclass

import circuit
from circuit import GND, V1, V3, V5, VBUS


@dataclass(frozen=True)
class Place:
    ref: str
    x: int
    y: int
    rotation: int = 0  # degrees counter-clockwise


@dataclass(frozen=True)
class Wire:
    """A chain of straight wires through the points. Every pin on it must be on this net in circuit.py."""
    net: str
    points: tuple
    label: tuple | None = None  # (x, y) on the wire, text to the right; (x, y, "left") for text to the left


@dataclass(frozen=True)
class Rail:
    """A supply symbol at this point."""
    net: str
    point: tuple[int, int]


@dataclass(frozen=True)
class Flag:
    """KiCad's PWR_FLAG: tells the rule check that this net is driven from outside the sheet's symbols
    (through the fuse, an inductor or a resistor)."""
    point: tuple[int, int]


@dataclass(frozen=True)
class Note:
    text: str
    x: int
    y: int


@dataclass(frozen=True)
class Block:
    title: str
    x: int
    y: int
    width: int
    height: int
    places: tuple[Place, ...]
    wires: tuple[Wire, ...] = ()
    rails: tuple[Rail, ...] = ()
    flags: tuple[Flag, ...] = ()
    notes: tuple[Note, ...] = ()


PAPER = "A3"
SHEET_WIDTH, SHEET_HEIGHT = 330, 233  # A3 landscape in grid steps

_USB = Block(
    "USB-C input, ESD protection, fuse", 6, 10, 72, 56,
    places=(Place("J1", 12, 24), Place("F1", 42, 12, 90), Place("R2", 58, 21), Place("R1", 66, 19),
            Place("R3", 43, 22, 90), Place("R4", 43, 26, 90), Place("U3", 48, 40)),
    wires=(
        Wire(VBUS, ("J1.A4", (27, 12), (34, 12), "F1.1")),
        Wire(V5, ("F1.2", (54, 12))),
        Wire("CC1", ("J1.A5", "R1.1"), label=(25, 16)),
        Wire("CC2", ("J1.B5", "R2.1"), label=(25, 18)),
        Wire("USB_D_N", ("J1.A7", (28, 22), "R3.1"), label=(31, 22)),
        Wire("USB_D_N", ("J1.B7", (28, 24), (28, 22))),
        Wire("USB_D_P", ("J1.A6", (30, 26), "R4.1"), label=(31, 26)),
        Wire("USB_D_P", ("J1.B6", (30, 28), (30, 26))),
    ),
    rails=(Rail(VBUS, (27, 12)), Rail(V5, (54, 12))),
    flags=(Flag((34, 12)),),
    notes=(Note("5.1 k on each CC line: the host sees a device and switches 5 V on.", 2, 53),),
)

_REGULATOR_3V3 = Block(
    "3.3 V regulator", 6, 70, 72, 28,
    places=(Place("U2", 22, 12), Place("C16", 8, 13), Place("C17", 34, 13), Place("TP5", 46, 10),
            Place("TP4", 68, 10)),
    wires=(
        Wire(V5, ((3, 10), "C16.1", (14, 10), "U2.1")),
        Wire(V5, ("U2.3", (14, 12), (14, 10))),
        Wire(V3, ("U2.5", "C17.1", (40, 10), "TP5.1")),
        Wire(V5, ((52, 10), (60, 10), "TP4.1")),
    ),
    rails=(Rail(V5, (3, 10)), Rail(V3, (40, 10)), Rail(V5, (52, 10)), Rail(GND, (56, 20))),
    flags=(Flag((60, 10)), Flag((56, 20))),
    notes=(Note("TP4, TP5: probe pads on the bottom face.", 44, 26),),
)

_CLOCK = Block(
    "12 MHz crystal (Hardware design with RP2040)", 6, 102, 72, 28,
    places=(Place("Y1", 22, 12), Place("C14", 13, 15), Place("C15", 31, 15), Place("R6", 39, 12, 270)),
    wires=(
        Wire("XIN", ((5, 12), "C14.1", "Y1.1"), label=(5, 12)),
        Wire("XTAL_DRIVE", ("Y1.3", "C15.1", "R6.2"), label=(26, 12)),
    ),
    notes=(Note("ABM8-272-T3, 15 pF, 1 k: the reference values, not measured here.", 2, 26),),
)

_DISPLAY = Block(
    "OLED header (I2C1), 4.7 k pull-ups", 6, 134, 72, 26,
    places=(Place("J2", 20, 14), Place("R7", 36, 12, 270), Place("R8", 36, 18, 270), Place("C18", 60, 15)),
    notes=(Note("Pin order GND VCC SCL SDA: MEASURE against the module.", 2, 24),),
)

_LEVEL_SHIFTER = Block(
    "LED data: 3.3 V to 5 V", 6, 164, 72, 36,
    places=(Place("U4", 26, 22), Place("C19", 50, 20), Place("C20", 58, 20), Place("R9", 46, 30, 90)),
    wires=(
        Wire(V3, ("U4.1", (24, 12), (14, 12), (14, 26), "U4.5")),
        Wire(V5, ("U4.6", (28, 12), (32, 12))),
        Wire("LED_DATA_3V3", ("U4.3", (12, 22)), label=(12, 22, "left")),
    ),
    rails=(Rail(V3, (24, 12)), Rail(V5, (32, 12))),
    notes=(Note("DIR high: A drives B.", 2, 34),),
)

_MCU_X, _MCU_Y = 34, 46
_MCU = Block(
    "MCU: RP2040", 82, 10, 72, 92,
    places=(Place("U1", _MCU_X, _MCU_Y),),
    wires=(
        Wire(V3, ("U1.48", (24, 6), (26, 6), (29, 6), (32, 6), (36, 6), "U1.44")),
        Wire(V3, ("U1.43", (26, 6))),
        Wire(V3, ("U1.1", (32, 6))),
        Wire(V1, ("U1.45", (40, 6), (42, 6), (44, 6), "U1.23")),
    ),
    rails=(Rail(V3, (29, 6)), Rail(V1, (42, 6))),
    notes=(Note("Internal 1.1 V regulator: VREG_VOUT feeds both DVDD pins.", 2, 90),),
)

_DECOUPLING_PITCH = 7
_DECOUPLING_PINS = circuit.DECOUPLING_CAPS | circuit.SECOND_SUPPLY_CAPS
_DECOUPLING = Block(
    "MCU decoupling: 100 nF per supply pin, 1 uF at VREG_VIN and VREG_VOUT", 82, 106, 92, 30,
    places=tuple(Place(ref, 6 + _DECOUPLING_PITCH * n, 14) for n, ref in enumerate(_DECOUPLING_PINS)),
    notes=tuple(Note(f"pin {pin}", 4 + _DECOUPLING_PITCH * n, 27) for n, pin in enumerate(_DECOUPLING_PINS.values())),
)

_FLASH = Block(
    "QSPI flash, 16 MB", 82, 140, 72, 34,
    places=(Place("U5", 22, 16), Place("C13", 40, 16)),
)

_RESET_BOOT_DEBUG = Block(
    "Reset, boot select, debug and probe pads", 82, 178, 108, 30,
    places=(Place("SW11", 22, 22), Place("R5", 45, 22, 90), Place("SW10", 58, 22),
            Place("TP1", 76, 14), Place("TP2", 84, 14), Place("TP3", 92, 14), Place("TP6", 100, 14)),
    wires=(
        Wire("RUN", ((5, 22), "SW11.1"), label=(5, 22)),
        Wire("BOOT", ("R5.2", "SW10.1"), label=(49, 22)),
    ),
    notes=(Note("Hold BOOT while plugging in: USB drive for the UF2 file. RUN has the chip's pull-up.", 2, 28),),
)

_MECHANICAL_REFS = [f"H{n}" for n in range(1, len(circuit.PCB["holes"]) + 1)] + [f"FID{n}" for n in range(1, 4)]
_MECHANICAL = Block(
    "Mounting holes (M2), fiducials", 82, 212, 108, 18,
    places=tuple(Place(ref, 8 + 10 * n, 10) for n, ref in enumerate(_MECHANICAL_REFS)),
)

_KEY_COLUMNS = len(circuit.PCB["key_x"])
_KEYS = Block(
    "Keys: one GPIO each, switch to ground, pull-ups inside U1", 194, 10, 84, 46,
    places=tuple(Place(f"SW{i + 1}", 16 + 26 * (i % _KEY_COLUMNS), 14 + 12 * (i // _KEY_COLUMNS))
                 for i in range(circuit.KEY_COUNT)),
)

_ENCODER = Block(
    "Rotary encoder with push switch", 194, 60, 60, 26,
    places=(Place("ENC1", 26, 12),),
    wires=(Wire(GND, ("ENC1.C", (8, 12))),),
    rails=(Rail(GND, (8, 12)),),
    notes=(Note("Internal pull-ups on A, B and SW.", 2, 24),),
)

_LED_PITCH = 24
_LEDS_PER_ROW = 5
_LED_ROW_PITCH = 36


def _leds() -> Block:
    """The LED chain in rows of five, each LED with its 100 nF below and to the right."""
    count = circuit.KEY_COUNT + len(circuit.BOARD_SPEC["leds"]["edge_x"])
    places, wires = [], []
    for i in range(count):
        row, column = divmod(i, _LEDS_PER_ROW)
        x, y = 14 + _LED_PITCH * column, 16 + _LED_ROW_PITCH * row
        places.append(Place(f"LED{i + 1}", x, y))
        places.append(Place(f"C{21 + i}", x + 14, y + 14))
        if column < _LEDS_PER_ROW - 1 and i < count - 1:
            wires.append(Wire(f"LED_D{i + 1}", (f"LED{i + 1}.{_DOUT[i < circuit.KEY_COUNT]}",
                                                 f"LED{i + 2}.{_DIN[i + 1 < circuit.KEY_COUNT]}"), label=(x + 9, y)))
    notes = (Note("LED1-9: SK6812MINI-E under the keys, row by row from the back left.", 2, 120),
             Note("LED10-15: SK6812 SIDE-A on the front edge, left to right. Pin orders: MEASURE.", 2, 124))
    return Block("LED chain: 15 x SK6812, one 100 nF each, the firmware's order", 194, 90, 132, 128,
                 tuple(places), tuple(wires), notes=notes)


# Data pins per LED type: MINI-E (True) and SIDE-A (False). See circuit._leds.
_DOUT = {True: "2", False: "3"}
_DIN = {True: "4", False: "1"}

BLOCKS = (_USB, _REGULATOR_3V3, _CLOCK, _DISPLAY, _LEVEL_SHIFTER, _MCU, _DECOUPLING, _FLASH, _RESET_BOOT_DEBUG,
          _MECHANICAL, _KEYS, _ENCODER, _leds())
