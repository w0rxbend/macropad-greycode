"""Dimensions of the case. The PCB and case contract comes from board.toml at run time; everything
below it is a case design value or a bought part's size.

Coordinates: x, y are PCB coordinates (origin at the PCB's front-left corner, y away from the user),
z is the case height (0 = underside of the base). Millimetres throughout.
Nothing has been built. `MEASURE` marks a size taken from a drawing or a guess that needs a caliper.
"""

import tomllib
from math import radians, sqrt, tan
from pathlib import Path
from types import SimpleNamespace

BOARD_TOML = Path(__file__).resolve().parents[2] / "board.toml"
USB_FACE_SIGN = {"top": 1.0, "bottom": -1.0}  # pcb.usb_face: which way the receptacle stands off the PCB


def _load() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    board = tomllib.loads(BOARD_TOML.read_text())
    pcb, case = SimpleNamespace(**board["pcb"]), SimpleNamespace(**board["case"])
    pcb_top = pcb.bottom_z + pcb.thickness
    if abs(pcb_top - case.joint_z) > 1e-9:
        raise ValueError(f"board.toml: joint_z {case.joint_z} must equal PCB top {pcb_top}")
    if pcb.usb_face not in USB_FACE_SIGN:
        raise ValueError(f"board.toml: pcb.usb_face {pcb.usb_face!r} must be one of {sorted(USB_FACE_SIGN)}")
    return pcb, case, SimpleNamespace(**board["keys"]), SimpleNamespace(**board["leds"])


PCB, CASE, KEYS, LEDS = _load()
PCB_TOP = CASE.joint_z

# ---- Shells -------------------------------------------------------------------------------
OUTLINE_GROW = CASE.pcb_clearance + CASE.wall  # case outline = PCB outline grown by this
TOP_CHAMFER = 0.6
BOTTOM_CHAMFER = 0.6
PLATE_WEB = 1.5
PLATE_UNDER = CASE.plate_top_z - PLATE_WEB
SWITCH_CUTOUT = 14.0
# Corner relief so a square switch housing fits. R1.5 (3 mm end mill), not R0.5: the tool reaches 5.0
# below the face it enters (through the 3.5 key well or up the 3.5 cavity), so the deep-pocket rule applies.
DOGBONE_RADIUS = 1.5
WELL_SIZE = 3 * KEYS.pitch_mm + 1.0
WELL_RADIUS = 1.5
KEY_GRID_CENTRE = (sum(PCB.key_x) / 3, sum(PCB.key_y) / 3)
STANDOFF_DIAMETER = 4.0  # must fit inside pcb.hole_keepout_diameter (checked)
# Shadow gap: the top shell's outer face steps in for its lowest part. Its height equals the light
# channel's, so the channel leaves no thin lip above the strip (README: design notes).
SHADOW_GAP_INSET = 0.8
CUT_OVERSHOOT = 0.01  # cuts run past the face they open, so no zero-thickness skin is left

# ---- Fasteners ------------------------------------------------------------------------------
# M2 x 8 countersunk screws (ISO 10642) from the underside, through base bosses and the PCB holes,
# into the top shell's standoffs: one stack clamps base, PCB and top together.
M2_TAP_DRILL = 1.6
M2_MAJOR = 2.0
M2_THREAD_DEPTH = 3.0  # from the standoff face
M2_DRILL_DEPTH = 3.5
DRILL_POINT_HALF_ANGLE = 59.0  # 118 degree drill point
FLOOR = 2.4  # pocket floor top; at or below the USB opening's lower edge (checked: plug overmold to base)
BASE_BOSS_DIAMETER = 4.6  # must fit inside pcb.hole_keepout_diameter (checked)
SCREW_CLEARANCE = 2.4
COUNTERSINK_DIAMETER = 4.0  # 90 degrees; head is 3.8 (ISO 10642 M2 dk max, MEASURE the screws)
COUNTERSINK_RECESS = 1.1  # head sits this far up inside the floor (README: why)
SCREW_HEAD = 3.8
SCREW_LENGTH = 10.0  # countersunk: overall length, head included
SCREW_HEAD_GAP = 0.02  # the reference head sits this much short of its seat, so contact is not a clash
FOOT_DIAMETER = 8.4  # pocket for an 8 mm silicone bumper, MEASURE the bumpers
FOOT_DEPTH = 0.6
FOOT_EDGE = 6.5  # foot centre from the case's front and back faces
FOOT_SPAN = 44.0  # between the left and right feet; clear of the screw countersinks (checked)

# ---- EC11 encoder and knob -----------------------------------------------------------------------
EC11_BODY = (12.0, 12.0, 6.5)  # above the PCB top, MEASURE
EC11_BUSHING = (7.0, 5.0)  # M7 bushing diameter, height above the body, MEASURE
EC11_SHAFT = (6.0, 4.5)  # D-shaft diameter, across the flat, MEASURE
EC11_SHAFT_TIP = 24.5  # above the PCB top, MEASURE
EC11_PUSH = 0.5
EC11_POCKET_RADIUS = 1.5  # pocket is deeper than 3 mm
EC11_POCKET_SIDE_CLEARANCE = 0.2
EC11_POCKET_TOP_CLEARANCE = 0.3
BUSHING_HOLE = 7.4
KNOB_DIAMETER = 22.0
KNOB_LIFT = 0.8  # knob underside above the top face at rest
KNOB_SKIN = 1.0  # above the shaft tip
KNOB_CHAMFERS = (0.4, 0.6)  # bottom, top edge
KNOB_COUNTERBORE = 8.4
KNOB_BUSHING_GAP = 0.5  # above the bushing with the knob pressed
KNOB_BORE_CLEARANCE = 0.025  # radial, on the D-shaft
KNOB_BORE_BEYOND_TIP = 0.4
KNOB_FLUTES = 30
KNOB_FLUTE_RADIUS = 0.6  # 1.2 mm ball end mill along the knob axis
KNOB_FLUTE_DEPTH = 0.5
KNOB_FLUTE_TOP_MARGIN = 1.2  # plain ring under the top chamfer
M3_TAP_DRILL = 2.5
M3_MAJOR = 3.0

# ---- OLED -----------------------------------------------------------------------------------
OLED_BOARD = (*PCB.oled_module_size, 1.6)  # size from board.toml, thickness MEASURE
OLED_GLASS = (34.5, 23.0, 1.8)  # guess, centred on the active area, MEASURE
OLED_ACTIVE = (29.42, 14.7)
OLED_HEADER = 2.2  # module underside above the PCB top: needs a low-profile header, MEASURE
OLED_POCKET_SIDE_CLEARANCE = 0.2
OLED_POCKET_TOP_CLEARANCE = 0.2  # glass top under the lens ledge, board top under its pocket
OLED_POCKET_RADIUS = 1.5  # cut from the joint face: tool reach 4.0 (board) and 5.8 (glass)
WINDOW_MARGIN = 1.0
WINDOW_RADIUS = 0.5
LENS_LEDGE = 1.5
LENS_DEPTH = 1.0
LENS_RADIUS = 1.0
LENS_FIT = 0.1  # per side

# ---- Light strip (frosted acrylic, laser cut) -----------------------------------------------------
STRIP_LENGTH = 56.0  # the part that shows through the shadow gap
STRIP_EAR = 2.0  # the strip is this much wider on each side behind the front wall: it cannot slide out
STRIP_THICKNESS = 1.4
STRIP_FRONT_DEPTH = 2.2  # from the gap face to the ears
STRIP_BACK_GAP = 0.6  # strip back face to the PCB front edge, where the side LEDs sit
STRIP_FIT = 0.1  # per side
STRIP_CORNER_RADIUS = 0.5  # channel corners behind the ears
SHADOW_GAP_HEIGHT = STRIP_THICKNESS + STRIP_FIT

# ---- USB-C ----------------------------------------------------------------------------------
USB_OPENING = (13.0, 7.0)  # rounded ends
# HRO TYPE-C-31-M-12 on the PCB face named by pcb.usb_face, mouth pcb.usb_mouth_overhang past the back edge.
USB_CENTRE_FROM_PCB = 1.6  # receptacle centre from the PCB face it sits on, MEASURE
USB_RECEPTACLE = (8.94, 7.35, 3.26)  # width, length, height, MEASURE
USB_PLUG = (12.4, 6.5, 20.0)  # overmold width, height, length shown, MEASURE
# Plug fully in: overmold front face this far beyond the receptacle mouth. Guess, MEASURE with the cable used.
USB_PLUG_FRONT = 0.1

# ---- Reference parts (checks only) ------------------------------------------------------------
KEYCAP = SimpleNamespace(base=18.0, top=13.0, height=7.5, wall=1.2, cavity=5.0, rest=6.0, pressed=2.0)  # MEASURE
SWITCH_BOTTOM = 13.95
SWITCH_TOP = (15.6, 11.0, 5.0)  # housing above the plate: base, top, height, MEASURE
SOCKET = SimpleNamespace(size=(11.0, 6.0), offset=(-0.64, 3.81), height=1.85)  # Kailh MX, guess, MEASURE


def pocket_grow(radius: float, clearance: float) -> float:
    """How much a pocket with corner `radius` must exceed a sharp-cornered body on each side so the
    corner arc still clears the body's corner by `clearance`."""
    return max(clearance, radius - (radius - clearance) / sqrt(2))


def drill_point_length(diameter: float) -> float:
    return diameter / 2 / tan(radians(DRILL_POINT_HALF_ANGLE))


def case_corner(grow: float = 0.0) -> float:
    return CASE.corner_radius + grow


def key_centres() -> list[tuple[float, float]]:
    return [(x, y) for y in PCB.key_y for x in PCB.key_x]


def knob_bottom() -> float:
    return CASE.top_z + KNOB_LIFT


def knob_top() -> float:
    return PCB_TOP + EC11_SHAFT_TIP + KNOB_BORE_BEYOND_TIP + KNOB_SKIN


def bushing_top() -> float:
    return PCB_TOP + EC11_BODY[2] + EC11_BUSHING[1]


def oled_stack() -> SimpleNamespace:
    """Heights of the OLED module and its two pockets, bottom up."""
    bottom = PCB_TOP + OLED_HEADER
    board_top = bottom + OLED_BOARD[2]
    glass_top = board_top + OLED_GLASS[2]
    return SimpleNamespace(
        bottom=bottom,
        board_top=board_top,
        glass_top=glass_top,
        board_ceiling=board_top + OLED_POCKET_TOP_CLEARANCE,
        glass_ceiling=glass_top + OLED_POCKET_TOP_CLEARANCE,
        lens_floor=CASE.top_z - LENS_DEPTH,
    )


def usb_face() -> tuple[float, float]:
    """z of the PCB face the USB-C receptacle sits on, and +1 (top face) or -1 (bottom face)."""
    sign = USB_FACE_SIGN[PCB.usb_face]
    return (PCB_TOP if sign > 0 else PCB.bottom_z), sign


def usb_centre_z() -> float:
    face, sign = usb_face()
    return face + sign * USB_CENTRE_FROM_PCB


def usb_mouth_y() -> float:
    return PCB.depth + PCB.usb_mouth_overhang


def strip_front_y() -> float:
    return -OUTLINE_GROW + SHADOW_GAP_INSET
