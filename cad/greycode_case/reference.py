"""Bought and electronic parts as plain envelopes, for clash and clearance checks and pictures only.

Every size here is a guess or a drawing value (spec.py, MEASURE). They are not part of the shop order.
"""

from math import atan, degrees

from build123d import Cone, Part, Plane, Pos, Rectangle, SlotOverall, extrude

from .parts import d_profile
from .shapes import MIN_ALIGN, box, cylinder, pcb_outline, slab
from .spec import (
    CASE,
    COUNTERSINK_DIAMETER,
    COUNTERSINK_RECESS,
    EC11_BODY,
    EC11_BUSHING,
    EC11_PUSH,
    EC11_SHAFT,
    EC11_SHAFT_TIP,
    KEYCAP,
    M2_MAJOR,
    M2_TAP_DRILL,
    OLED_BOARD,
    OLED_GLASS,
    PCB,
    PCB_TOP,
    SCREW_HEAD,
    SCREW_HEAD_GAP,
    SCREW_LENGTH,
    SOCKET,
    SWITCH_BOTTOM,
    SWITCH_TOP,
    USB_PLUG,
    USB_PLUG_FRONT,
    USB_RECEPTACLE,
    key_centres,
    oled_stack,
    usb_centre_z,
    usb_face,
    usb_mouth_y,
)

THREAD_ENVELOPE = M2_TAP_DRILL - 0.05  # screw drawn at the tap drill size inside the thread, so it does not clash


def pcb() -> Part:
    board = slab(pcb_outline(0.0), (PCB.bottom_z, PCB_TOP))
    for centre in PCB.holes:
        board -= cylinder(centre, PCB.hole_diameter, (PCB.bottom_z - 1, PCB_TOP + 1))
    return board


def _tapered(size: float, top: float, height: float) -> Part:
    taper = degrees(atan((size - top) / 2 / height))
    return extrude(Rectangle(size, size), height, taper=taper)


def switch(centre: tuple[float, float]) -> Part:
    below = box(
        (centre[0] - SWITCH_BOTTOM / 2, centre[0] + SWITCH_BOTTOM / 2),
        (centre[1] - SWITCH_BOTTOM / 2, centre[1] + SWITCH_BOTTOM / 2),
        (PCB_TOP, CASE.plate_top_z),
    )
    return below + Pos(centre[0], centre[1], CASE.plate_top_z) * _tapered(*SWITCH_TOP)


def keycap(centre: tuple[float, float], pressed: bool) -> Part:
    """A hollow tapered cap; its skirt sits KEYCAP.rest (or .pressed) above the plate top."""
    lift = KEYCAP.pressed if pressed else KEYCAP.rest
    taper = (KEYCAP.base - KEYCAP.top) / 2 / KEYCAP.height
    inner = KEYCAP.base - 2 * KEYCAP.wall
    shell = _tapered(KEYCAP.base, KEYCAP.top, KEYCAP.height) - _tapered(
        inner, inner - 2 * taper * KEYCAP.cavity, KEYCAP.cavity
    )
    return Pos(centre[0], centre[1], CASE.plate_top_z + lift) * shell


def socket(centre: tuple[float, float]) -> Part:
    x, y = centre[0] + SOCKET.offset[0], centre[1] + SOCKET.offset[1]
    half_x, half_y = SOCKET.size[0] / 2, SOCKET.size[1] / 2
    return box((x - half_x, x + half_x), (y - half_y, y + half_y), (PCB.bottom_z - SOCKET.height, PCB.bottom_z))


def encoder() -> Part:
    """EC11 body and bushing, bored for the shaft; they do not move when the knob is pressed."""
    knob = tuple(PCB.knob)
    half = EC11_BODY[0] / 2, EC11_BODY[1] / 2
    body = box(
        (knob[0] - half[0], knob[0] + half[0]),
        (knob[1] - half[1], knob[1] + half[1]),
        (PCB_TOP, PCB_TOP + EC11_BODY[2]),
    )
    top = PCB_TOP + EC11_BODY[2]
    bushing = cylinder(knob, EC11_BUSHING[0], (top, top + EC11_BUSHING[1]))
    return body + bushing - cylinder(knob, EC11_SHAFT[0] + 0.1, (top, top + EC11_BUSHING[1] + 1))


def encoder_shaft(pressed: bool) -> Part:
    drop = EC11_PUSH if pressed else 0.0
    start = PCB_TOP + EC11_BODY[2] + EC11_PUSH - drop
    return slab(Pos(*PCB.knob) * d_profile(0.0), (start, PCB_TOP + EC11_SHAFT_TIP - drop))


def oled_module() -> Part:
    stack = oled_stack()
    board = _centred_box(tuple(PCB.oled_module_centre), OLED_BOARD[:2], (stack.bottom, stack.board_top))
    return board + _centred_box(tuple(PCB.oled_window_centre), OLED_GLASS[:2], (stack.board_top, stack.glass_top))


def _centred_box(centre: tuple[float, float], size: tuple[float, float], z: tuple[float, float]) -> Part:
    return box(
        (centre[0] - size[0] / 2, centre[0] + size[0] / 2), (centre[1] - size[1] / 2, centre[1] + size[1] / 2), z
    )


def usb_receptacle() -> Part:
    """Shell envelope on the PCB face pcb.usb_face names, mouth at usb_mouth_y()."""
    width, length, height = USB_RECEPTACLE
    face, sign = usb_face()
    mouth = usb_mouth_y()
    return box(
        (PCB.usb_x - width / 2, PCB.usb_x + width / 2),
        (mouth - length, mouth),
        tuple(sorted((face, face + sign * height))),
    )


def usb_plug() -> Part:
    """The overmold of a plugged-in cable, from its front face outward."""
    plane = Plane(origin=(PCB.usb_x, usb_mouth_y() + USB_PLUG_FRONT, usb_centre_z()), x_dir=(1, 0, 0), z_dir=(0, 1, 0))
    return extrude(plane * SlotOverall(USB_PLUG[0], USB_PLUG[1]), USB_PLUG[2])


def screw(centre: tuple[float, float]) -> Part:
    """ISO 10642 M2 x 8 seated in its countersink: head, shank through base and PCB, thread in the standoff."""
    sink = COUNTERSINK_DIAMETER / 2
    head_face = COUNTERSINK_RECESS + (sink - SCREW_HEAD / 2) - SCREW_HEAD_GAP
    head_height = (SCREW_HEAD - M2_MAJOR) / 2
    head = Pos(centre[0], centre[1], head_face) * Cone(SCREW_HEAD / 2, M2_MAJOR / 2, head_height, align=MIN_ALIGN)
    shank = cylinder(centre, M2_MAJOR, (head_face + head_height, PCB_TOP))
    thread = cylinder(centre, THREAD_ENVELOPE, (PCB_TOP, head_face + SCREW_LENGTH))
    return head + shank + thread


def screw_tip() -> float:
    sink = COUNTERSINK_DIAMETER / 2
    return COUNTERSINK_RECESS + (sink - SCREW_HEAD / 2) - SCREW_HEAD_GAP + SCREW_LENGTH


def static_parts() -> dict[str, Part]:
    parts = {
        "pcb": pcb(),
        "encoder": encoder(),
        "oled module": oled_module(),
        "usb receptacle": usb_receptacle(),
        "usb plug": usb_plug(),
    }
    for index, centre in enumerate(key_centres()):
        parts[f"switch {index + 1}"] = switch(centre)
        parts[f"socket {index + 1}"] = socket(centre)
    for index, centre in enumerate(PCB.holes):
        parts[f"screw {index + 1}"] = screw(centre)
    return parts


def moving_parts(pressed: bool) -> dict[str, Part]:
    """Parts that move with a key press or a knob push: keycaps and the encoder shaft."""
    parts = {f"keycap {index + 1}": keycap(centre, pressed) for index, centre in enumerate(key_centres())}
    parts["encoder shaft"] = encoder_shaft(pressed)
    return parts
