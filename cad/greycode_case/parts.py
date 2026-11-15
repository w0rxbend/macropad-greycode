"""The made parts in their assembled position: top shell, base, knob (6061-T6, CNC) and the two
acrylic parts (light strip, lens).

Each machined part is an outline slab with every cut it gets kept by name, so the checks can measure
the metal left between cuts.
"""

from dataclasses import dataclass, field
from functools import cache
from math import cos, radians, sin

from build123d import Axis, Circle, Part, Plane, Polygon, Pos, Rectangle, SlotOverall, Sketch, chamfer, extrude, fillet

from .shapes import Hole, box, cylinder, pcb_outline, rounded, slab
from .spec import (
    BOTTOM_CHAMFER,
    BUSHING_HOLE,
    CASE,
    COUNTERSINK_DIAMETER,
    COUNTERSINK_RECESS,
    CUT_OVERSHOOT,
    DOGBONE_RADIUS,
    EC11_BODY,
    EC11_POCKET_RADIUS,
    EC11_POCKET_SIDE_CLEARANCE,
    EC11_POCKET_TOP_CLEARANCE,
    EC11_PUSH,
    EC11_SHAFT,
    FLOOR,
    FOOT_DEPTH,
    FOOT_DIAMETER,
    FOOT_EDGE,
    FOOT_SPAN,
    KEY_GRID_CENTRE,
    KNOB_BORE_CLEARANCE,
    KNOB_BUSHING_GAP,
    KNOB_CHAMFERS,
    KNOB_COUNTERBORE,
    KNOB_DIAMETER,
    KNOB_FLUTE_DEPTH,
    KNOB_FLUTE_RADIUS,
    KNOB_FLUTE_TOP_MARGIN,
    KNOB_FLUTES,
    KNOB_SKIN,
    LEDS,
    LENS_DEPTH,
    LENS_FIT,
    LENS_LEDGE,
    LENS_RADIUS,
    M2_DRILL_DEPTH,
    M2_MAJOR,
    M2_TAP_DRILL,
    M2_THREAD_DEPTH,
    M3_MAJOR,
    M3_TAP_DRILL,
    OLED_ACTIVE,
    OLED_BOARD,
    OLED_GLASS,
    OLED_POCKET_RADIUS,
    OLED_POCKET_SIDE_CLEARANCE,
    OUTLINE_GROW,
    PCB,
    PCB_TOP,
    PLATE_UNDER,
    SCREW_CLEARANCE,
    SHADOW_GAP_HEIGHT,
    SHADOW_GAP_INSET,
    STANDOFF_DIAMETER,
    STRIP_BACK_GAP,
    STRIP_CORNER_RADIUS,
    STRIP_EAR,
    STRIP_FIT,
    STRIP_FRONT_DEPTH,
    STRIP_LENGTH,
    STRIP_THICKNESS,
    SWITCH_CUTOUT,
    TOP_CHAMFER,
    USB_OPENING,
    WELL_RADIUS,
    WELL_SIZE,
    WINDOW_MARGIN,
    WINDOW_RADIUS,
    BASE_BOSS_DIAMETER,
    bushing_top,
    drill_point_length,
    key_centres,
    knob_bottom,
    knob_top,
    oled_stack,
    pocket_grow,
    strip_front_y,
    usb_centre_z,
)

OVER = CUT_OVERSHOOT
ABOVE = CASE.top_z + 1.0


@dataclass
class Built:
    solid: Part
    cutters: dict[str, Part] = field(default_factory=dict)  # air features, for the metal-between-cuts check
    holes: list[Hole] = field(default_factory=list)  # screw holes, checked on their own


def _cut_all(body: Part, cutters: dict[str, Part]) -> Part:
    for cutter in cutters.values():
        body -= cutter
    return body


def _drill(body: Part, holes: list[Hole]) -> Part:
    for hole in holes:
        body -= hole.body()
    return body


def case_outline(grow: float = 0.0) -> Sketch:
    return pcb_outline(OUTLINE_GROW + grow, CASE.corner_radius + grow)


# ---- Top shell -------------------------------------------------------------------------------------


def top_shell() -> Built:
    body = slab(case_outline(), (CASE.joint_z, CASE.top_z))
    body = chamfer(body.edges().group_by(Axis.Z)[-1], TOP_CHAMFER)
    below = {
        "shadow gap": slab(
            case_outline(1.0) - case_outline(-SHADOW_GAP_INSET), (CASE.joint_z - OVER, CASE.joint_z + SHADOW_GAP_HEIGHT)
        ),
        "cavity": slab(pcb_outline(CASE.pcb_clearance), (CASE.joint_z - OVER, PLATE_UNDER)),
    }
    body = _cut_all(body, below)
    for x, y in PCB.holes:
        body += cylinder((x, y), STANDOFF_DIAMETER, (CASE.joint_z, PLATE_UNDER))
    cutters = {
        "key well": slab(rounded(KEY_GRID_CENTRE, (WELL_SIZE, WELL_SIZE), WELL_RADIUS), (CASE.plate_top_z, ABOVE)),
        **{f"switch {index + 1}": _switch_cutout(centre) for index, centre in enumerate(key_centres())},
        **_oled_cuts(),
        **_encoder_cuts(),
        "light channel": _light_channel(),
        "usb opening": usb_opening(),
    }
    holes = [_standoff_hole(index, centre) for index, centre in enumerate(PCB.holes)]
    return Built(_drill(_cut_all(body, cutters), holes), below | cutters, holes)


def _switch_cutout(centre: tuple[float, float]) -> Part:
    """14 x 14 with a dog-bone in each corner: a 1 mm end mill cuts it and a square housing still fits."""
    reach = SWITCH_CUTOUT / 2 - DOGBONE_RADIUS / 2**0.5
    profile = Pos(*centre) * Rectangle(SWITCH_CUTOUT, SWITCH_CUTOUT)
    for sign_x in (-1, 1):
        for sign_y in (-1, 1):
            profile += Pos(centre[0] + sign_x * reach, centre[1] + sign_y * reach) * Circle(DOGBONE_RADIUS)
    return slab(profile, (PLATE_UNDER - OVER, CASE.plate_top_z + OVER))


def _oled_cuts() -> dict[str, Part]:
    stack = oled_stack()
    grow = pocket_grow(OLED_POCKET_RADIUS, OLED_POCKET_SIDE_CLEARANCE)
    module, window = tuple(PCB.oled_module_centre), tuple(PCB.oled_window_centre)
    window_size = (OLED_ACTIVE[0] + 2 * WINDOW_MARGIN, OLED_ACTIVE[1] + 2 * WINDOW_MARGIN)
    lens_size = (window_size[0] + 2 * LENS_LEDGE, window_size[1] + 2 * LENS_LEDGE)
    return {
        "oled board pocket": slab(
            rounded(module, (OLED_BOARD[0] + 2 * grow, OLED_BOARD[1] + 2 * grow), OLED_POCKET_RADIUS),
            (PLATE_UNDER - OVER, stack.board_ceiling),
        ),
        "oled glass pocket": slab(
            rounded(window, (OLED_GLASS[0] + 2 * grow, OLED_GLASS[1] + 2 * grow), OLED_POCKET_RADIUS),
            (PLATE_UNDER - OVER, stack.glass_ceiling),
        ),
        "oled window": slab(
            rounded(window, window_size, WINDOW_RADIUS), (stack.glass_ceiling - OVER, stack.lens_floor + OVER)
        ),
        "lens recess": slab(rounded(window, lens_size, LENS_RADIUS), (stack.lens_floor, ABOVE)),
    }


def lens_outline() -> Sketch:
    size = (
        OLED_ACTIVE[0] + 2 * (WINDOW_MARGIN + LENS_LEDGE - LENS_FIT),
        OLED_ACTIVE[1] + 2 * (WINDOW_MARGIN + LENS_LEDGE - LENS_FIT),
    )
    return rounded(tuple(PCB.oled_window_centre), size, LENS_RADIUS - LENS_FIT)


def _encoder_cuts() -> dict[str, Part]:
    grow = pocket_grow(EC11_POCKET_RADIUS, EC11_POCKET_SIDE_CLEARANCE)
    knob = tuple(PCB.knob)
    pocket_top = PCB_TOP + EC11_BODY[2] + EC11_POCKET_TOP_CLEARANCE
    return {
        "encoder pocket": slab(
            rounded(knob, (EC11_BODY[0] + 2 * grow, EC11_BODY[1] + 2 * grow), EC11_POCKET_RADIUS),
            (PLATE_UNDER - OVER, pocket_top),
        ),
        "bushing hole": cylinder(knob, BUSHING_HOLE, (pocket_top - OVER, ABOVE)),
    }


def strip_centre_x() -> float:
    return sum(LEDS.edge_x) / len(LEDS.edge_x)


def strip_ear_y() -> float:
    return strip_front_y() + STRIP_FRONT_DEPTH


def _light_channel() -> Part:
    """Cut from below through the front wall: a slot the strip's front shows through, and behind it a
    wider pocket for the strip's ears. The two corners behind the ears get the end mill's radius."""
    half_front = STRIP_LENGTH / 2 + STRIP_FIT
    half_back = half_front + STRIP_EAR
    shoulder = strip_ear_y() - STRIP_FIT
    x = strip_centre_x()
    z = (CASE.joint_z - OVER, CASE.joint_z + SHADOW_GAP_HEIGHT)
    front = box((x - half_front, x + half_front), (-OUTLINE_GROW - 1.0, shoulder + OVER), z)
    back = box((x - half_back, x + half_back), (shoulder, -CASE.pcb_clearance + 0.1), z)
    channel = front + back
    corners = [
        edge
        for edge in channel.edges().filter_by(Axis.Z)
        if abs(edge.center().Y - shoulder) < 1e-6 and abs(abs(edge.center().X - x) - half_back) < 1e-6
    ]
    return fillet(corners, STRIP_CORNER_RADIUS)


def usb_opening() -> Part:
    """Through the back wall, round the receptacle's axis; each shell takes the part of it that crosses
    its own z range (bottom-face receptacle: mostly the base). Starts at the wall's inner face."""
    start = PCB.depth + CASE.pcb_clearance - OVER
    plane = Plane(origin=(PCB.usb_x, start, usb_centre_z()), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    return extrude(plane * SlotOverall(*USB_OPENING), CASE.wall + 2 * OVER + 1.0)


def _standoff_hole(index: int, centre: tuple[float, float]) -> Hole:
    """M2 tapped from below into a standoff: thread M2_THREAD_DEPTH, tap drill M2_DRILL_DEPTH + point."""
    drill, point = M2_TAP_DRILL / 2, drill_point_length(M2_TAP_DRILL)
    thread = M2_THREAD_DEPTH + OVER
    return Hole(
        name=f"M2 standoff {index + 1}",
        mouth=(centre[0], centre[1], CASE.joint_z - OVER),
        axis=(0, 0, 1),
        cut=((drill, drill, M2_DRILL_DEPTH + OVER), (drill, 0.0, point)),
        metal=(
            (M2_MAJOR / 2, M2_MAJOR / 2, thread),
            (drill, drill, M2_DRILL_DEPTH - M2_THREAD_DEPTH),
            (drill, 0.0, point),
        ),
        guard=(OVER, 100.0),
    )


# ---- Base ------------------------------------------------------------------------------------------


def base() -> Built:
    body = slab(case_outline(), (0.0, CASE.joint_z))
    body = chamfer(body.edges().group_by(Axis.Z)[0], BOTTOM_CHAMFER)
    pocket = {"interior pocket": slab(pcb_outline(CASE.pcb_clearance), (FLOOR, CASE.joint_z + OVER))}
    body = _cut_all(body, pocket)
    for x, y in PCB.holes:
        body += cylinder((x, y), BASE_BOSS_DIAMETER, (FLOOR, PCB.bottom_z))
    cutters = {
        **{
            f"foot {index + 1}": cylinder(centre, FOOT_DIAMETER, (-OVER, FOOT_DEPTH))
            for index, centre in enumerate(foot_centres())
        },
        "usb opening": usb_opening(),
    }
    holes = [_countersunk_hole(index, centre) for index, centre in enumerate(PCB.holes)]
    return Built(_drill(_cut_all(body, cutters), holes), pocket | cutters, holes)


def foot_centres() -> list[tuple[float, float]]:
    middle = PCB.width / 2
    front, back = -OUTLINE_GROW + FOOT_EDGE, PCB.depth + OUTLINE_GROW - FOOT_EDGE
    return [(middle + side * FOOT_SPAN / 2, y) for y in (front, back) for side in (-1, 1)]


def _countersunk_hole(index: int, centre: tuple[float, float]) -> Hole:
    """From the underside: a short counterbore so the head sits COUNTERSINK_RECESS up, the 90 degree
    seat, then the clearance hole up through the boss."""
    sink, clear = COUNTERSINK_DIAMETER / 2, SCREW_CLEARANCE / 2
    seat = sink - clear
    rest = PCB.bottom_z - COUNTERSINK_RECESS - seat + OVER
    profile = ((sink, sink, COUNTERSINK_RECESS + OVER), (sink, clear, seat), (clear, clear, rest + OVER))
    return Hole(
        name=f"M2 countersunk {index + 1}",
        mouth=(centre[0], centre[1], -OVER),
        axis=(0, 0, 1),
        cut=profile,
        metal=profile,
        guard=(OVER, PCB.bottom_z + OVER),
    )


# ---- Knob ------------------------------------------------------------------------------------------


def knob_counterbore_top() -> float:
    return bushing_top() + EC11_PUSH + KNOB_BUSHING_GAP


def set_screw_z() -> float:
    return knob_counterbore_top() + M3_MAJOR / 2 + 1.1


def knob() -> Built:
    centre, bottom, top = tuple(PCB.knob), knob_bottom(), knob_top()
    body = cylinder(centre, KNOB_DIAMETER, (bottom, top))
    body = chamfer(body.edges().group_by(Axis.Z)[0], KNOB_CHAMFERS[0])
    body = chamfer(body.edges().group_by(Axis.Z)[-1], KNOB_CHAMFERS[1])
    cutters = {
        "counterbore": cylinder(centre, KNOB_COUNTERBORE, (bottom - OVER, knob_counterbore_top())),
        "d bore": slab(Pos(*centre) * d_profile(KNOB_BORE_CLEARANCE), (knob_counterbore_top() - OVER, knob_bore_end())),
        "flutes": _flutes(centre),
    }
    body = _cut_all(body, cutters)
    holes = [_set_screw_hole(centre)]
    return Built(_drill(body, holes), cutters, holes)


def knob_bore_end() -> float:
    return knob_top() - KNOB_SKIN


def d_profile(clearance: float) -> Sketch:
    """EC11 D-shaft section at the origin, flat toward +x, grown by `clearance`."""
    radius = EC11_SHAFT[0] / 2 + clearance
    flat = EC11_SHAFT[1] - EC11_SHAFT[0] / 2 + clearance
    return Circle(radius) & (Pos((flat - radius) / 2, 0) * Rectangle(flat + radius, 2 * radius))


def flute_band() -> tuple[float, float]:
    low = set_screw_z() + M3_MAJOR / 2 + 1.0
    return low, knob_top() - KNOB_CHAMFERS[1] - KNOB_FLUTE_TOP_MARGIN


def _flutes(centre: tuple[float, float]) -> Part:
    """All flutes as one cut (separate solids), so the metal-between-cuts check sees them."""
    reach = KNOB_DIAMETER / 2 + KNOB_FLUTE_RADIUS - KNOB_FLUTE_DEPTH
    low, high = flute_band()
    flutes = Part()
    for index in range(KNOB_FLUTES):
        angle = radians(360 * (index + 0.5) / KNOB_FLUTES)
        spot = (centre[0] + reach * cos(angle), centre[1] + reach * sin(angle))
        flutes += cylinder(spot, 2 * KNOB_FLUTE_RADIUS, (low, high))
    return flutes


def _set_screw_hole(centre: tuple[float, float]) -> Hole:
    """M3 grub screw onto the shaft's flat, radial along +x, below the fluted band."""
    flat = EC11_SHAFT[1] - EC11_SHAFT[0] / 2 + KNOB_BORE_CLEARANCE
    length = KNOB_DIAMETER / 2 + 1.0
    return Hole(
        name="M3 set screw",
        mouth=(centre[0], centre[1], set_screw_z()),
        axis=(1, 0, 0),
        cut=((M3_TAP_DRILL / 2, M3_TAP_DRILL / 2, length),),
        metal=((M3_MAJOR / 2, M3_MAJOR / 2, length),),
        guard=(flat + 0.1, KNOB_DIAMETER / 2 - 0.6),
    )


# ---- Acrylic -----------------------------------------------------------------------------------------


def light_strip() -> Part:
    """Frosted acrylic, laser cut from STRIP_THICKNESS sheet. The front edge shows in the shadow gap,
    the back edge faces the side LEDs; the ears keep it from sliding out."""
    x, front, ears = strip_centre_x(), strip_front_y(), strip_ear_y()
    back = -STRIP_BACK_GAP
    half_front, half_back = STRIP_LENGTH / 2, STRIP_LENGTH / 2 + STRIP_EAR
    relief = STRIP_CORNER_RADIUS + 0.1  # chamfer that clears the channel's corner radius
    half_outline = [
        (half_front, front),
        (half_front, ears),
        (half_back - relief, ears),
        (half_back, ears + relief),
        (half_back, back),
    ]
    points = [(x + px, py) for px, py in half_outline] + [(x - px, py) for px, py in reversed(half_outline)]
    return Pos(0, 0, CASE.joint_z) * extrude(Polygon(*points, align=None), STRIP_THICKNESS)


def lens() -> Part:
    """Smoked glass or acrylic, glued on the ledge, flush with the top face."""
    return slab(lens_outline(), (CASE.top_z - LENS_DEPTH, CASE.top_z))


@cache
def built_parts() -> dict[str, Built]:
    return {"top": top_shell(), "base": base(), "knob": knob()}


MACHINED = ("top", "base", "knob")
