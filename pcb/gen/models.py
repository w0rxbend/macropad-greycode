"""Block models of the parts, for the 3D renders. Needs pcbnew.

The KiCad container ships no 3D library, so every part is drawn here as a few boxes and cylinders
and written to pcb/lib/3d/ as VRML. The outline of a body comes from the footprint's own
fabrication-layer drawing; the heights are nominal datasheet values typed from memory (guesses) or
board.toml's [case] stack. These models are pictures. The only check made with them is that no
bottom-side part is taller than the gap to the case floor (layout.write_models); the case model in
cad/ has its own clearance checks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pcbnew

import circuit
from circuit import BOARD_SPEC, PCB

MODEL_DIR = circuit.REPO_ROOT / "pcb" / "lib" / "3d"
# As KiCad resolves it from pcb/kicad/, where the board file lives.
_MODEL_REFERENCE = "${KIPRJMOD}/../lib/3d"
_VRML_UNIT = 2.54  # KiCad reads one VRML unit as a tenth of an inch
_ROUND_FACETS = 32
_BOARD_THICKNESS = PCB["thickness"]
_CASE = BOARD_SPEC["case"]
_PLATE_TOP = _CASE["plate_top_z"] - _CASE["joint_z"]  # MX plate top above the PCB top
_SOCKET_DEPTH = 1.85  # Kailh hot-swap socket below the PCB, guess from the CPG151101S11 drawing
_ENCODER_BODY_TOP = 4.5  # MEASURE: Alps EC11E drawing, mounting surface to the bushing shoulder
_ENCODER_SHAFT_TOP = 24.5  # MEASURE: EC11E18244AU, mounting surface to the shaft end
_ENCODER_BUSHING = 7.0
# OLED module on its header: plastic spacer 2.5, module board 1.6, glass 1.5. Guesses, MEASURE.
_OLED_BOARD_BOTTOM, _OLED_BOARD_TOP, _OLED_GLASS_TOP = 2.5, 4.1, 5.6

Colour = tuple[float, float, float]
BLACK: Colour = (0.08, 0.08, 0.09)
DARK_GREY: Colour = (0.25, 0.25, 0.27)
METAL: Colour = (0.55, 0.55, 0.54)
CERAMIC: Colour = (0.62, 0.52, 0.40)
GREEN: Colour = (0.15, 0.35, 0.22)
WHITE: Colour = (0.93, 0.93, 0.88)
GLASS: Colour = (0.55, 0.62, 0.60)
STEM: Colour = (0.55, 0.27, 0.12)

Rect = tuple[float, float, float, float]  # left, top, right, bottom in footprint coordinates, Y down


@dataclass(frozen=True)
class Solid:
    """A box, or a cylinder standing on the board when `round` is set. Heights are above the
    footprint's own face; negative values reach through the board to the other face."""
    footprint_rect: Rect
    z_bottom: float
    z_top: float
    colour: Colour
    round: bool = False


# Body height above the board and colour, for parts that are one block on their fabrication outline.
_ONE_BLOCK = {
    "C0402": (0.5, CERAMIC),
    "C0603": (0.8, CERAMIC),
    "R0402": (0.35, BLACK),
    "QFN56": (0.9, BLACK),
    "SOIC8": (1.75, BLACK),
    "SOT23-5": (1.1, BLACK),
    "SOT23-6": (1.1, BLACK),
    "XTAL3225": (0.7, METAL),
    "F1206": (0.6, GREEN),
    "USBC": (3.26, METAL),
}


def _centred(x: float, y: float, size_x: float, size_y: float) -> Rect:
    return x - size_x / 2, y - size_y / 2, x + size_x / 2, y + size_y / 2


def _fab_outline(footprint: pcbnew.FOOTPRINT) -> Rect:
    """The box around the footprint's fabrication-layer drawing, with the footprint at the origin."""
    shapes = [item for item in footprint.GraphicalItems()
              if item.GetLayer() == pcbnew.F_Fab and item.GetClass() == "PCB_SHAPE"]
    assert shapes, f"{footprint.GetFPIDAsString()}: no fabrication outline to build a model from"
    box = shapes[0].GetBoundingBox()
    for shape in shapes[1:]:
        box.Merge(shape.GetBoundingBox())
    return tuple(pcbnew.ToMM(edge) for edge in (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom()))


def _tact_switch(footprint: pcbnew.FOOTPRINT) -> list[Solid]:
    return [Solid(_fab_outline(footprint), 0.0, 1.0, METAL),
            Solid(_centred(0.0, 0.0, 2.4, 2.4), 1.0, 1.5, BLACK, round=True)]


def _side_led(_: pcbnew.FOOTPRINT) -> list[Solid]:
    # The project footprint has no fabrication outline; its silkscreen body is 4.0 x 1.6 mm.
    return [Solid(_centred(0.0, 0.0, 4.0, 1.6), 0.0, 1.5, WHITE)]


def _mini_e(_: pcbnew.FOOTPRINT) -> list[Solid]:
    """Reverse mount: the body sits in the board's cut-out and shows on the key side."""
    return [Solid(_centred(0.0, 0.0, 3.2, 2.8), -_BOARD_THICKNESS - 0.1, 0.1, WHITE)]


def _encoder(footprint: pcbnew.FOOTPRINT) -> list[Solid]:
    shaft_x, shaft_y = circuit.ENCODER_SHAFT_OFFSET  # from pad A, the footprint origin
    bushing_top = _ENCODER_BODY_TOP + 5.0
    return [
        Solid(_fab_outline(footprint), 0.0, _ENCODER_BODY_TOP, METAL),
        Solid(_centred(shaft_x, shaft_y, _ENCODER_BUSHING, _ENCODER_BUSHING), _ENCODER_BODY_TOP, bushing_top, METAL,
              round=True),
        Solid(_centred(shaft_x, shaft_y, 6.0, 6.0), bushing_top, _ENCODER_SHAFT_TOP, METAL, round=True),
    ]


def _oled(footprint: pcbnew.FOOTPRINT) -> list[Solid]:
    """The header with the OLED module on it. Header pin 1 is the footprint origin; the row runs down (+y)."""
    first_x, first_y = circuit.oled_header_first_pin()
    centre_x, centre_y = circuit.kicad_xy(*PCB["oled_module_centre"])
    width, height = circuit.OLED_MODULE_SIZE
    # Board -> footprint coordinates: the header is turned 90 degrees, footprint (x, y) = board (-dy, dx).
    dx, dy = centre_x - first_x, centre_y - first_y
    module = _centred(-dy, dx, height, width)
    glass = _centred(-dy + 2.0, dx, 23.0, 34.5)  # glass 34.5 x 23, 2 mm toward the header: a guess
    return [
        Solid(_fab_outline(footprint), 0.0, _OLED_BOARD_BOTTOM, BLACK),
        Solid(module, _OLED_BOARD_BOTTOM, _OLED_BOARD_TOP, DARK_GREY),
        Solid(glass, _OLED_BOARD_TOP, _OLED_GLASS_TOP, GLASS),
    ]


def _key_switch(footprint: pcbnew.FOOTPRINT) -> list[Solid]:
    """Hot-swap socket on the footprint's face (the bottom), MX switch through the board on the key side."""
    def above_key_side(low: float, high: float) -> tuple[float, float]:
        return -_BOARD_THICKNESS - high, -_BOARD_THICKNESS - low

    return [
        Solid(_fab_outline(footprint), 0.0, _SOCKET_DEPTH, DARK_GREY),
        Solid(_centred(0.0, 0.0, 14.0, 14.0), *above_key_side(0.0, _PLATE_TOP), BLACK),
        Solid(_centred(0.0, 0.0, 12.0, 12.0), *above_key_side(_PLATE_TOP, _PLATE_TOP + 6.6), DARK_GREY),
        Solid(_centred(0.0, 0.0, 5.5, 5.5), *above_key_side(_PLATE_TOP + 6.6, _PLATE_TOP + 10.2), STEM),
    ]


_SHAPED = {"TACT": _tact_switch, "LED_SIDE": _side_led, "LED_MINI_E": _mini_e, "EC11": _encoder, "HEADER4": _oled,
           "MX_HOTSWAP": _key_switch}
MODELLED = set(_ONE_BLOCK) | set(_SHAPED)


def solids(footprint_key: str, footprint: pcbnew.FOOTPRINT) -> list[Solid]:
    if footprint_key in _ONE_BLOCK:
        height, colour = _ONE_BLOCK[footprint_key]
        return [Solid(_fab_outline(footprint), 0.0, height, colour)]
    return _SHAPED[footprint_key](footprint)


def _footprint_polygon(solid: Solid) -> list[tuple[float, float]]:
    """The solid seen from above, counter-clockwise in model coordinates (footprint Y points down, model Y up)."""
    left, top, right, bottom = solid.footprint_rect
    assert right > left and bottom > top and solid.z_top > solid.z_bottom, f"empty solid {solid}"
    if not solid.round:
        return [(left, -bottom), (right, -bottom), (right, -top), (left, -top)]
    centre_x, centre_y, radius = (left + right) / 2, -(top + bottom) / 2, (right - left) / 2
    return [(centre_x + radius * math.cos(2 * math.pi * step / _ROUND_FACETS),
             centre_y + radius * math.sin(2 * math.pi * step / _ROUND_FACETS)) for step in range(_ROUND_FACETS)]


def _vrml_shape(solid: Solid) -> str:
    """A prism as a face set. KiCad's VRML reader draws boxes but skips cylinders, so both are written this way."""
    polygon = _footprint_polygon(solid)
    count = len(polygon)
    points = [(x, y, z) for z in (solid.z_bottom, solid.z_top) for x, y in polygon]
    faces = [list(range(count, 2 * count)), list(range(count - 1, -1, -1))]
    faces += [[i, (i + 1) % count, count + (i + 1) % count, count + i] for i in range(count)]
    coordinates = ", ".join(" ".join(f"{value / _VRML_UNIT:.5f}" for value in point) for point in points)
    indices = " ".join(" ".join(map(str, face)) + " -1" for face in faces)
    red, green, blue = solid.colour
    return ("Shape {\n"
            f"  appearance Appearance {{ material Material {{ diffuseColor {red} {green} {blue} "
            "specularColor 0.1 0.1 0.1 shininess 0.2 } }\n"
            f"  geometry IndexedFaceSet {{ solid FALSE coord Coordinate {{ point [ {coordinates} ] }} "
            f"coordIndex [ {indices} ] }}\n}}\n")


def vrml(parts: list[Solid]) -> str:
    return "#VRML V2.0 utf8\n" + "".join(_vrml_shape(part) for part in parts)


def write_model(footprint_key: str, footprint: pcbnew.FOOTPRINT, model_dir: Path = MODEL_DIR) -> None:
    """Writes the model file of one footprint type. `footprint` must be freshly loaded: not moved, not flipped."""
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / f"{footprint_key}.wrl").write_text(vrml(solids(footprint_key, footprint)))


def attach(footprint_key: str, footprint: pcbnew.FOOTPRINT) -> None:
    """Replaces the stock model references, which point into a library the container does not have."""
    footprint.Models().clear()
    if footprint_key not in MODELLED:
        return
    model = pcbnew.FP_3DMODEL()
    model.m_Filename = f"{_MODEL_REFERENCE}/{footprint_key}.wrl"
    footprint.Models().push_back(model)
