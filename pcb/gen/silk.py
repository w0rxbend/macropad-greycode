"""Silkscreen: what a person needs to read off the bare board. Needs pcbnew.

Top face (keys, knob, display): key numbers with their GPIO, the display module outline and its pin
names, the board name. Bottom face (all machine-placed parts): button names, test pad names, revision.
"""

from __future__ import annotations

import pcbnew

import circuit
from circuit import BOARD_SPEC, PCB

REVISION = "A"
# JLCPCB's legibility minimums: 1.0 mm text height, 0.15 mm line and stroke width.
_LINE_WIDTH = 0.15
_TEXT_SIZE = 1.0
_STROKE_RATIO = 0.15  # stroke width over text height
# Test pad names, under each pad on the bottom face.
_PAD_NAMES = {"TP1": "CLK", "TP2": "DIO", "TP3": "GND", "TP4": "5V", "TP5": "3V3", "TP6": "1V1"}
_PAD_NAME_OFFSET = {"TP1": (-2.6, 0.0), "TP2": (-2.6, 0.0), "TP3": (-2.6, 0.0),
                    "TP4": (2.6, 0.0), "TP5": (2.6, 0.0), "TP6": (-2.6, 0.0)}
# Below the key's LED window, inside the key's own 19.05 mm cell.
_KEY_LABEL_OFFSET = 7.6
# Length of each corner mark of the OLED module outline: a full rectangle would run over the USB shell pads.
_CORNER_MARK = 2.0


def _mm(value: float) -> int:
    return pcbnew.FromMM(value)


def _text(board: pcbnew.BOARD, text: str, x: float, y: float, layer: int, size: float = _TEXT_SIZE,
          angle: float = 0.0) -> None:
    assert size >= _TEXT_SIZE, f"silkscreen text {text!r} is {size} mm high, below the {_TEXT_SIZE} mm minimum"
    label = pcbnew.PCB_TEXT(board)
    label.SetText(text)
    label.SetPosition(pcbnew.VECTOR2I(_mm(x), _mm(y)))
    label.SetTextAngleDegrees(angle)
    label.SetLayer(layer)
    label.SetTextSize(pcbnew.VECTOR2I(_mm(size), _mm(size)))
    label.SetTextThickness(_mm(size * _STROKE_RATIO))
    label.SetMirrored(layer == pcbnew.B_SilkS)
    board.Add(label)


def fit_footprint_silk(footprint: pcbnew.FOOTPRINT) -> None:
    """Brings a library footprint's silkscreen up to the legibility minimums: the visible reference to the
    minimum text size, and every stroked line to the minimum width. KiCad's stock footprints draw 0.12 mm."""
    reference = footprint.Reference()
    if reference.IsVisible() and _is_silk(reference):
        reference.SetTextSize(pcbnew.VECTOR2I(_mm(_TEXT_SIZE), _mm(_TEXT_SIZE)))
        reference.SetTextThickness(_mm(_TEXT_SIZE * _STROKE_RATIO))
    for item in footprint.GraphicalItems():
        stroked_silk = item.GetClass() == "PCB_SHAPE" and _is_silk(item) and not item.IsFilled()
        if stroked_silk and item.GetWidth() < _mm(_LINE_WIDTH):
            item.SetWidth(_mm(_LINE_WIDTH))


def check_minimums(board: pcbnew.BOARD) -> None:
    """Every visible silkscreen text and every stroked silkscreen line on the board meets the minimums."""
    texts = [item for item in board.GetDrawings() if item.GetClass() == "PCB_TEXT"]
    shapes = [item for item in board.GetDrawings() if item.GetClass() == "PCB_SHAPE"]
    for footprint in board.GetFootprints():
        texts += [field for field in footprint.GetFields() if field.IsVisible()]
        texts += [item for item in footprint.GraphicalItems() if item.GetClass() == "PCB_TEXT"]
        shapes += [item for item in footprint.GraphicalItems() if item.GetClass() == "PCB_SHAPE"]
    for text in filter(_is_silk, texts):
        height, stroke = pcbnew.ToMM(text.GetTextHeight()), pcbnew.ToMM(text.GetTextThickness())
        assert height >= _TEXT_SIZE - 1e-6 and stroke >= _LINE_WIDTH - 1e-6, (
            f"silkscreen text {text.GetShownText(False)!r} is {height} mm high with a {stroke} mm stroke, "
            f"minimum {_TEXT_SIZE} / {_LINE_WIDTH}")
    for shape in filter(_is_silk, shapes):
        width = pcbnew.ToMM(shape.GetWidth())
        assert shape.IsFilled() or width >= _LINE_WIDTH - 1e-6, \
            f"silkscreen line of {width} mm at {shape.GetPosition()}, minimum {_LINE_WIDTH} mm"


def _is_silk(item: pcbnew.BOARD_ITEM) -> bool:
    return item.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS)


def _keys(board: pcbnew.BOARD) -> None:
    """In each key's cell, in front of its LED window: key number and GPIO."""
    for index, gpio in enumerate(BOARD_SPEC["keys"]["gpio"]):
        x, y = circuit.key_centre(index)
        _text(board, f"K{index} GP{gpio}", x, y + _KEY_LABEL_OFFSET, pcbnew.F_SilkS)


def _display(board: pcbnew.BOARD) -> None:
    """The OLED module's corners (MEASURE) and its pin names, standing under each header pin."""
    centre_x, centre_y = circuit.kicad_xy(*PCB["oled_module_centre"])
    width, height = circuit.OLED_MODULE_SIZE
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = (centre_x + sx * width / 2, centre_y + sy * height / 2)
            _line(board, corner, (corner[0] - sx * _CORNER_MARK, corner[1]))
            _line(board, corner, (corner[0], corner[1] - sy * _CORNER_MARK))
    first_x, pin_y = circuit.oled_header_first_pin()
    for n, name in enumerate(circuit.OLED_PINS):
        _text(board, name, first_x + n * circuit.HEADER_PITCH, pin_y + 3.4, pcbnew.F_SilkS, angle=90)
    _text(board, "OLED 1.3in SH1106", centre_x, centre_y, pcbnew.F_SilkS)


def _line(board: pcbnew.BOARD, start: tuple[float, float], end: tuple[float, float]) -> None:
    shape = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
    shape.SetStart(pcbnew.VECTOR2I(_mm(start[0]), _mm(start[1])))
    shape.SetEnd(pcbnew.VECTOR2I(_mm(end[0]), _mm(end[1])))
    shape.SetLayer(pcbnew.F_SilkS)
    shape.SetWidth(_mm(_LINE_WIDTH))
    board.Add(shape)


def _top_title(board: pcbnew.BOARD) -> None:
    _text(board, f"greycode rev {REVISION}", 33.0, 36.4, pcbnew.F_SilkS, 1.2)


def _bottom(board: pcbnew.BOARD) -> None:
    parts = {part.ref: part for part in circuit.all_parts()}
    _text(board, "BOOT", parts["SW10"].x, parts["SW10"].y + 3.6, pcbnew.B_SilkS)
    _text(board, "RESET", parts["SW11"].x, parts["SW11"].y - 3.6, pcbnew.B_SilkS)
    _text(board, f"greycode rev {REVISION}", 52.0, 34.0, pcbnew.B_SilkS)
    for ref, name in _PAD_NAMES.items():
        dx, dy = _PAD_NAME_OFFSET[ref]
        _text(board, name, parts[ref].x + dx, parts[ref].y + dy, pcbnew.B_SilkS)


def add_labels(board: pcbnew.BOARD) -> None:
    _keys(board)
    _display(board)
    _top_title(board)
    _bottom(board)
