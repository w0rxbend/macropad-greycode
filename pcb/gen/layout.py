"""Builds the unrouted KiCad board from circuit.py. Runs inside the KiCad container (needs pcbnew)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pcbnew

import circuit
import models
import route
import schematic
import silk
from circuit import BOTTOM, DEPTH, GND, NO_NET, PCB, V1, V3, V5, WIDTH, Part
from router import Rules

STOCK_FOOTPRINTS = Path("/usr/share/kicad/footprints")
PROJECT_FOOTPRINTS = circuit.REPO_ROOT / "pcb" / "lib"
POSITION_TOLERANCE = 0.02
# Passives are too dense for readable silkscreen. Connectors, chips and the other one-of-a-kind parts
# keep their reference; the two buttons are named BOOT and RESET instead (see silk.py). The MCU and the
# flash have no room for theirs among the capacitors; the assembly drawing (B.Fab) names them.
SILK_LABELLED = {"USBC", "HEADER4", "EC11", "SOT23-5", "SOT23-6", "F1206"}
# Footprints whose library silkscreen outline is dropped: the OLED header's runs into the USB shell pad's solder
# mask opening. silk.py names its pins instead.
NO_SILK_OUTLINE = {"HEADER4"}
# Top-view position of a reference that would sit on other parts' pads or off the board at its library spot.
REFERENCE_POSITION = {"J1": (37.0, 9.2), "J2": (16.0, 3.6)}

# JLCPCB 4-layer capability with margin: 0.09 mm track/space and 0.3 mm drill are their limits.
TRACK_WIDTH = 0.15
CLEARANCE = 0.15
VIA_DIAMETER = 0.6
VIA_DRILL = 0.3
EDGE_CLEARANCE = 0.3
SILK_EDGE_CLEARANCE = 0.2
# Copper layer of each plane. Ground sits next to the bottom face, which carries every machine-placed part;
# the 5 V plane with its 3.3 V and 1.1 V islands sits next to the top face.
GROUND_LAYER = pcbnew.In2_Cu
POWER_LAYER = pcbnew.In1_Cu
# The 3.3 V island on the power layer (left, top, right, bottom): the strip behind the keys with the MCU, the
# flash, the display header and the regulator output. The 5 V plane keeps the back edge right of the display
# header (fuse, regulator input), a strip along the right edge, and everything in front of the keys' back row.
V3_ISLAND = [(1.0, 6.0, 57.0, 36.0), (1.0, 0.3, 28.0, 6.5)]
# The 1.1 V island inside it: under the chip, with a lobe to the back for the capacitors of VREG_VOUT and the DVDD
# pins, between the capacitors of IOVDD pins 33 and 42.
V1_ISLAND = [(22.6, 18.6, 29.4, 23.6), (25.5, 8.0, 28.1, 18.7)]
ROUTING_RULES = Rules(track_width=TRACK_WIDTH, clearance=CLEARANCE, via_diameter=VIA_DIAMETER,
                      via_drill=VIA_DRILL, edge_clearance=EDGE_CLEARANCE)
# The board-wide limits kicad-cli's DRC checks against, as they are written into greycode.kicad_pro.
# KiCad 9 keeps the design rules in the project file, not in the board file.
DRC_RULES = {
    "min_track_width": 0.127,
    "min_clearance": 0.127,
    "min_via_diameter": 0.45,
    "min_through_hole_diameter": 0.3,
    "min_copper_edge_clearance": EDGE_CLEARANCE,
    "min_hole_clearance": 0.2,
    "min_hole_to_hole": 0.25,
}
DEFAULT_NET_CLASS = {"track_width": TRACK_WIDTH, "clearance": CLEARANCE, "via_diameter": VIA_DIAMETER,
                     "via_drill": VIA_DRILL}
# Solder paste on the MCU's exposed pad: windows (x, y, width, height) in footprint coordinates, with the four
# ground vias (route.EXPOSED_PAD_VIA_OFFSETS) between them: a centre square and four arms. Each window keeps
# EP_PASTE_VIA_GAP from every via's copper ring, so paste does not wick into the holes.
EP_PASTE_WINDOWS = ((0.0, 0.0, 1.3, 1.3),
                    (1.125, 0.0, 0.95, 1.0), (-1.125, 0.0, 0.95, 1.0),
                    (0.0, 1.125, 1.0, 0.95), (0.0, -1.125, 1.0, 0.95))
EP_SIZE = 3.2
EP_PASTE_COVERAGE = (0.5, 0.7)
EP_PASTE_VIA_GAP = 0.15
STOCK_EP_PASTE_SQUARES = 4
# No paste aperture anywhere comes closer than this to a via's drilled hole.
PASTE_TO_VIA_DRILL = 0.15
COPPER_LAYERS = (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu)


def routing_setup(head_start: tuple[str, ...]) -> route.Setup:
    return route.Setup(ROUTING_RULES, V3_ISLAND, V1_ISLAND, head_start)


def mm(value: float) -> int:
    return pcbnew.FromMM(value)


def point(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(mm(x), mm(y))


def pad_xy(pad: pcbnew.PAD) -> tuple[float, float]:
    position = pad.GetPosition()
    return pcbnew.ToMM(position.x), pcbnew.ToMM(position.y)


def _load_footprint(name: str) -> pcbnew.FOOTPRINT:
    library, footprint_name = name.split(":")
    root = PROJECT_FOOTPRINTS if library == "greycode" else STOCK_FOOTPRINTS
    footprint = pcbnew.FootprintLoad(str(root / f"{library}.pretty"), footprint_name)
    assert footprint is not None, f"footprint not found: {name}"
    footprint.SetFPID(pcbnew.LIB_ID(library, footprint_name))  # with its library, as the schematic names it
    return footprint


def _net(board: pcbnew.BOARD, name: str) -> pcbnew.NETINFO_ITEM:
    return _board_net(board, schematic.board_net_name(name))


def _board_net(board: pcbnew.BOARD, board_name: str) -> pcbnew.NETINFO_ITEM:
    existing = board.FindNet(board_name)
    if existing is not None:
        return existing
    net = pcbnew.NETINFO_ITEM(board, board_name)
    board.Add(net)
    return net


def _place(board: pcbnew.BOARD, part: Part, open_pin_nets: dict[str, str]) -> pcbnew.FOOTPRINT:
    footprint = _load_footprint(part.footprint)
    models.attach(part.footprint_key, footprint)
    board.Add(footprint)  # pcbnew crashes when it flips a footprint that has no board
    footprint.SetReference(part.ref)
    footprint.SetPath(pcbnew.KIID_PATH(f"/{schematic.symbol_uuid(part.ref)}"))  # pairs it with its schematic symbol
    footprint.SetValue(part.value)
    footprint.SetPosition(point(part.x, part.y))
    if part.side == BOTTOM:
        # A top-bottom flip mirrors Y; the extra half turn makes it the X mirror you see from the top.
        footprint.Flip(footprint.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
        footprint.SetOrientationDegrees(part.rotation + 180)
    else:
        footprint.SetOrientationDegrees(part.rotation)
    if part.lcsc:
        footprint.SetField("LCSC", part.lcsc)
        footprint.GetFieldByName("LCSC").SetVisible(False)
    footprint.Value().SetVisible(False)
    _remove_silkscreen_off_the_board(footprint)
    if part.footprint_key in NO_SILK_OUTLINE:
        for item in list(footprint.GraphicalItems()):
            if item.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and item.GetClass() == "PCB_SHAPE":
                footprint.Remove(item)
    footprint.Reference().SetVisible(part.footprint_key in SILK_LABELLED)
    if part.ref in REFERENCE_POSITION:
        footprint.Reference().SetPosition(point(*REFERENCE_POSITION[part.ref]))
    silk.fit_footprint_silk(footprint)
    if not part.machine_assembled:
        footprint.SetExcludedFromPosFiles(True)
    _connect(board, footprint, part, open_pin_nets)
    return footprint


def _remove_silkscreen_off_the_board(footprint: pcbnew.FOOTPRINT) -> None:
    """The USB receptacle hangs over the edge and its outline with it; the fab house would clip those lines."""
    for item in list(footprint.GraphicalItems()):
        if item.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        box = item.GetBoundingBox()
        inside = (box.GetLeft() >= mm(SILK_EDGE_CLEARANCE) and box.GetTop() >= mm(SILK_EDGE_CLEARANCE)
                  and box.GetRight() <= mm(WIDTH - SILK_EDGE_CLEARANCE)
                  and box.GetBottom() <= mm(DEPTH - SILK_EDGE_CLEARANCE))
        if not inside:
            footprint.Remove(item)


def _connect(board: pcbnew.BOARD, footprint: pcbnew.FOOTPRINT, part: Part, open_pin_nets: dict[str, str]) -> None:
    """Nets from circuit.py. An open pin gets the one-pad net KiCad's netlist names for it, so the board
    carries exactly the nets of the schematic."""
    pad_numbers = {pad.GetNumber() for pad in footprint.Pads()}
    unknown = set(part.nets) - pad_numbers
    assert not unknown, f"{part.ref}: no such pads {sorted(unknown)}"
    for pad in footprint.Pads():
        net_name = part.nets.get(pad.GetNumber(), NO_NET)
        open_net = open_pin_nets.get(f"{part.ref}.{pad.GetNumber()}")
        if net_name != NO_NET:
            pad.SetNet(_net(board, net_name))
        elif open_net is not None:
            pad.SetNet(_board_net(board, open_net))


def _outline(board: pcbnew.BOARD) -> None:
    width, height, radius = WIDTH, DEPTH, PCB["corner_radius"]
    corners = [(radius, radius, 180), (width - radius, radius, 270),
               (width - radius, height - radius, 0), (radius, height - radius, 90)]
    arc_ends = []
    for centre_x, centre_y, start_angle in corners:
        start, mid, end = (
            (centre_x + radius * math.cos(math.radians(a)), centre_y + radius * math.sin(math.radians(a)))
            for a in (start_angle, start_angle + 45, start_angle + 90)
        )
        arc = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_ARC)
        arc.SetArcGeometry(point(*start), point(*mid), point(*end))
        _add_edge(board, arc)
        arc_ends.append((start, end))
    for (_, line_start), (line_end, _) in zip(arc_ends, arc_ends[1:] + arc_ends[:1]):
        line = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_SEGMENT)
        line.SetStart(point(*line_start))
        line.SetEnd(point(*line_end))
        _add_edge(board, line)


def _add_edge(board: pcbnew.BOARD, shape: pcbnew.PCB_SHAPE) -> None:
    shape.SetLayer(pcbnew.Edge_Cuts)
    shape.SetWidth(mm(0.1))
    board.Add(shape)


def _zone(board: pcbnew.BOARD, net_name: str, layer: int, rectangles: list[tuple], priority: int = 0) -> None:
    """One zone over the union of the rectangles (left, top, right, bottom)."""
    zone = pcbnew.ZONE(board)
    zone.SetLayer(layer)
    zone.SetNet(_net(board, net_name))
    zone.SetAssignedPriority(priority)
    zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THT_THERMAL)  # hand-soldered pins must not sink the heat
    zone.SetThermalReliefGap(mm(0.25))
    zone.SetThermalReliefSpokeWidth(mm(0.4))
    zone.SetMinThickness(mm(0.2))
    zone.SetLocalClearance(mm(0.2))
    union = pcbnew.SHAPE_POLY_SET()
    for left, top, right, bottom in rectangles:
        union.NewOutline()
        for x, y in ((left, top), (right, top), (right, bottom), (left, bottom)):
            union.Append(mm(x), mm(y))
    union.Simplify()
    assert union.OutlineCount() == 1, f"{net_name} zone: the rectangles do not form one piece"
    # Copied point by point: handing the union itself to the zone makes pcbnew free it twice.
    merged = union.Outline(0)
    outline = zone.Outline()
    outline.NewOutline()
    for index in range(merged.PointCount()):
        corner = merged.CPoint(index)
        outline.Append(corner.x, corner.y)
    board.Add(zone)


def _circle_rule_area(board: pcbnew.BOARD, layers: tuple[int, ...], x: float, y: float, radius: float) -> None:
    """No copper pour, no track and no via inside the circle on these layers."""
    area = pcbnew.ZONE(board)
    area.SetIsRuleArea(True)
    layer_set = pcbnew.LSET()
    for layer in layers:
        layer_set.AddLayer(layer)
    area.SetLayerSet(layer_set)
    area.SetDoNotAllowCopperPour(True)
    area.SetDoNotAllowTracks(True)
    area.SetDoNotAllowVias(True)
    area.SetDoNotAllowPads(False)
    area.SetDoNotAllowFootprints(False)
    outline = area.Outline()
    outline.NewOutline()
    for step in range(32):
        angle = math.radians(step * 360 / 32)
        # The polygon's flats sit on the circle, so the polygon holds the whole circle.
        reach = radius / math.cos(math.pi / 32)
        outline.Append(mm(x + reach * math.cos(angle)), mm(y + reach * math.sin(angle)))
    board.Add(area)


def add_keepouts(board: pcbnew.BOARD) -> None:
    """board.toml hole_keepout_diameter round every M2 hole on all four copper layers; bare board inside each
    fiducial's solder-mask opening."""
    for x, y in hole_centres():
        _circle_rule_area(board, COPPER_LAYERS, x, y, PCB["hole_keepout_diameter"] / 2)
    for x, y in circuit.FIDUCIALS:
        _circle_rule_area(board, (pcbnew.B_Cu,), x, y, circuit.FIDUCIAL_MASK_DIAMETER / 2 + 0.1)


def hole_centres() -> list[tuple[float, float]]:
    return [circuit.kicad_xy(x, y) for x, y in PCB["holes"]]


def _whole_board() -> list[tuple]:
    return [(0.0, 0.0, WIDTH, DEPTH)]


def add_inner_planes(board: pcbnew.BOARD) -> None:
    _zone(board, GND, GROUND_LAYER, _whole_board())
    _zone(board, V5, POWER_LAYER, _whole_board())
    _zone(board, V3, POWER_LAYER, V3_ISLAND, priority=1)
    _zone(board, V1, POWER_LAYER, V1_ISLAND, priority=2)


def add_outer_ground_pours(board: pcbnew.BOARD) -> None:
    _zone(board, GND, pcbnew.F_Cu, _whole_board())
    _zone(board, GND, pcbnew.B_Cu, _whole_board())


def _rules(board: pcbnew.BOARD) -> None:
    """The same rules on the board in memory, for the DRC runs on boards saved without the project file."""
    settings = board.GetDesignSettings()
    settings.m_TrackMinWidth = mm(DRC_RULES["min_track_width"])
    settings.m_MinClearance = mm(DRC_RULES["min_clearance"])
    settings.m_ViasMinSize = mm(DRC_RULES["min_via_diameter"])
    settings.m_MinThroughDrill = mm(DRC_RULES["min_through_hole_diameter"])
    settings.m_CopperEdgeClearance = mm(DRC_RULES["min_copper_edge_clearance"])
    settings.m_HoleClearance = mm(DRC_RULES["min_hole_clearance"])
    settings.m_HoleToHoleMin = mm(DRC_RULES["min_hole_to_hole"])
    settings.m_TentViasFront = True  # the vias in the MCU's exposed pad stay covered on the top face
    settings.m_TentViasBack = True
    default_class = settings.m_NetSettings.GetDefaultNetclass()
    default_class.SetTrackWidth(mm(TRACK_WIDTH))
    default_class.SetClearance(mm(CLEARANCE))
    default_class.SetViaDiameter(mm(VIA_DIAMETER))
    default_class.SetViaDrill(mm(VIA_DRILL))


def write_project_rules(project_path: Path, rules: dict[str, float] = DRC_RULES) -> None:
    """Writes the design rules into the KiCad project file, where kicad-cli's DRC reads them. Saving the board
    from Python does not write this file, so a missing one is started from a minimal skeleton."""
    if project_path.exists():
        project = json.loads(project_path.read_text())
    else:
        project = {"board": {"design_settings": {"rules": {}}},
                   "net_settings": {"classes": [{"name": "Default"}], "meta": {"version": 3}},
                   "meta": {"filename": project_path.name, "version": 1}}
    project["board"]["design_settings"]["rules"].update(rules)
    (default_class,) = [c for c in project["net_settings"]["classes"] if c["name"] == "Default"]
    default_class.update(DEFAULT_NET_CLASS)
    project_path.write_text(json.dumps(project, indent=2, sort_keys=True) + "\n")


# --- the MCU footprint with windowed exposed-pad paste -----------------------------------------

def _paste_pad(x: float, y: float, width: float, height: float) -> str:
    return (f'\t(pad "" smd rect\n\t\t(at {x:g} {y:g})\n\t\t(size {width:g} {height:g})\n'
            f'\t\t(layers "F.Paste")\n\t)\n')


def check_paste_windows() -> None:
    """The exposed-pad windows: inside the pad, EP_PASTE_VIA_GAP clear of every via's copper ring, about half
    the pad."""
    half = EP_SIZE / 2
    via_reach = VIA_DIAMETER / 2 + EP_PASTE_VIA_GAP
    for x, y, width, height in EP_PASTE_WINDOWS:
        window = (x - width / 2, y - height / 2, x + width / 2, y + height / 2)
        assert -half <= window[0] and window[2] <= half and -half <= window[1] and window[3] <= half, \
            f"paste window at ({x}, {y}) leaves the exposed pad"
        for dx, dy in route.EXPOSED_PAD_VIA_OFFSETS:
            assert not route.circle_meets_rect(dx, dy, via_reach, window), \
                f"paste window at ({x}, {y}) is within {EP_PASTE_VIA_GAP} mm of the via at ({dx}, {dy})"
    coverage = sum(width * height for _, _, width, height in EP_PASTE_WINDOWS) / EP_SIZE ** 2
    low, high = EP_PASTE_COVERAGE
    assert low <= coverage <= high, f"exposed-pad paste covers {coverage:.0%}, wanted {low:.0%} to {high:.0%}"


def write_derived_footprints() -> None:
    """The project copy of the MCU footprint: KiCad's stock QFN-56 with its exposed-pad paste squares
    replaced by EP_PASTE_WINDOWS. Everything else is the stock file's text."""
    check_paste_windows()
    project_name = circuit.FOOTPRINT["QFN56"]
    library, stock_name = circuit.DERIVED_FOOTPRINTS[project_name].split(":")
    text = (STOCK_FOOTPRINTS / f"{library}.pretty" / f"{stock_name}.kicad_mod").read_text()
    paste_pad = re.compile(r'\t\(pad "" smd roundrect\n(?:\t\t[^\n]*\n)*?\t\)\n')
    found = len(paste_pad.findall(text))
    assert found == STOCK_EP_PASTE_SQUARES, f"the stock QFN-56 has {found} exposed-pad paste squares"
    first = paste_pad.search(text).start()
    text = paste_pad.sub("", text)
    text = text[:first] + "".join(_paste_pad(*window) for window in EP_PASTE_WINDOWS) + text[first:]
    footprint_name = project_name.split(":")[1]
    text = text.replace(f'(footprint "{stock_name}"', f'(footprint "{footprint_name}"', 1)
    text = text.replace(f'(property "Value" "{stock_name}"', f'(property "Value" "{footprint_name}"', 1)
    text = text.replace('(generator "kicad-footprint-generator")',
                        '(generator "greycode")\n\t(generator_version "pcb/gen/layout.py")', 1)
    (PROJECT_FOOTPRINTS / "greycode.pretty" / f"{footprint_name}.kicad_mod").write_text(text)


def _copper_pads(footprint: pcbnew.FOOTPRINT) -> list[tuple]:
    return sorted((pad.GetNumber(), pad.GetPosition().x, pad.GetPosition().y, pad.GetSize(pcbnew.F_Cu).x,
                   pad.GetSize(pcbnew.F_Cu).y, pad.GetShape(pcbnew.F_Cu), pad.GetLayerSet().FmtHex())
                  for pad in footprint.Pads() if pad.IsOnCopperLayer())


def check_derived_footprints() -> None:
    """Each project copy of a stock footprint has exactly the stock copper pads: only the paste differs."""
    for project_name, stock_name in circuit.DERIVED_FOOTPRINTS.items():
        project, stock = _load_footprint(project_name), _load_footprint(stock_name)
        assert _copper_pads(project) == _copper_pads(stock), f"{project_name}: copper differs from {stock_name}"


# --- placement self-checks: flipping and rotating are easy to get backwards -------------------

def _close(actual: tuple[float, float], expected: tuple[float, float]) -> bool:
    return math.dist(actual, expected) < POSITION_TOLERANCE


def _pads(footprint: pcbnew.FOOTPRINT, number: str) -> list[tuple[float, float]]:
    return [pad_xy(pad) for pad in footprint.Pads() if pad.GetNumber() == number]


def check_placement(placed: dict[str, pcbnew.FOOTPRINT]) -> None:
    mcu = placed["U1"]
    for pin in (1, 14, 15, 29, 43, 56):
        assert _close(_pads(mcu, str(pin))[0], circuit.mcu_pin_xy(pin)), f"MCU pin {pin} is not where circuit.py says"

    key_x, key_y = circuit.key_centre(0)
    assert _close(_pads(placed["SW1"], "1")[0], (key_x - 7.085, key_y - 2.54)), "hot-swap socket is mirrored"

    usb_pad_y = _pads(placed["J1"], "A6")[0][1]
    assert usb_pad_y > pcbnew.ToMM(placed["J1"].GetPosition().y), "USB-C receptacle faces into the board"

    for ref, footprint in placed.items():
        if footprint.GetValue() == "SK6812SIDE-A":
            body_y = pcbnew.ToMM(footprint.GetPosition().y)
            pad_y = _pads(footprint, "2")[0][1]
            # The pads are at the back of a side-emitter, so they must sit inboard of the body.
            assert pad_y < body_y, f"{ref} shines into the board"
        if footprint.GetValue() == "SK6812MINI-E":
            assert footprint.IsFlipped(), f"{ref}: a reverse-mount LED belongs on the bottom face"

    for ref, pin in circuit.DECOUPLING_CAPS.items():
        cap = placed[ref]
        pin_xy = circuit.mcu_pin_xy(pin)
        near, far = _pads(cap, "1")[0], _pads(cap, "2")[0]
        assert math.dist(near, pin_xy) < math.dist(far, pin_xy), f"{ref} is reversed"

    # The crystal's load capacitors: the signal pad faces the crystal pad it loads.
    for cap_ref, crystal_pad in (("C14", "1"), ("C15", "3")):
        signal, ground = _pads(placed[cap_ref], "1")[0], _pads(placed[cap_ref], "2")[0]
        crystal_xy = _pads(placed["Y1"], crystal_pad)[0]
        assert math.dist(signal, crystal_xy) < math.dist(ground, crystal_xy), f"{cap_ref} is reversed"
    mcu_xin = circuit.mcu_pin_xy(20)
    xin_pad, drive_pad = _pads(placed["Y1"], "1")[0], _pads(placed["Y1"], "3")[0]
    assert math.dist(xin_pad, mcu_xin) < 8.0 and math.dist(drive_pad, mcu_xin) < 8.0, "the crystal is far from XIN"

    for ref, footprint in placed.items():
        if ref.startswith("FID"):
            assert footprint.IsFlipped(), f"{ref} is not on the assembly face"


def check_hole_keepouts(board: pcbnew.BOARD) -> None:
    """board.toml: no copper or parts on either face inside hole_keepout_diameter. Pads and courtyards here;
    the rule areas keep tracks, vias and pours out, and DRC checks those."""
    radius = PCB["hole_keepout_diameter"] / 2
    for x, y in hole_centres():
        for footprint in board.GetFootprints():
            if footprint.GetValue() == "M2":
                continue
            for pad in footprint.Pads():
                if pad.IsOnCopperLayer():
                    assert not route.circle_meets_rect(x, y, radius, route.box_mm(pad.GetBoundingBox())), \
                        f"{footprint.GetReference()} pad {pad.GetNumber()} inside the keep-out of the hole at ({x}, {y})"
            footprint.BuildCourtyardCaches()
            for layer in (pcbnew.F_CrtYd, pcbnew.B_CrtYd):
                courtyard = footprint.GetCourtyard(layer)
                if courtyard.OutlineCount():
                    assert not courtyard.Collide(point(x, y), mm(radius)), \
                        f"{footprint.GetReference()} courtyard inside the keep-out of the hole at ({x}, {y})"


def check_paste_clear_of_vias(board: pcbnew.BOARD) -> None:
    """Board-wide: no solder-paste aperture comes within PASTE_TO_VIA_DRILL of a via's hole, and every via is
    covered by solder mask on the top face."""
    vias = [track for track in board.GetTracks() if track.GetClass() == "PCB_VIA"]
    for via in vias:
        assert via.IsTented(pcbnew.F_Mask), f"via at {pad_xy(via)} is not tented on the top face"
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            for layer in (pcbnew.F_Paste, pcbnew.B_Paste):
                if not pad.IsOnLayer(layer):
                    continue
                margin = pad.GetSolderPasteMargin(layer)
                left, top, right, bottom = route.box_mm(pad.GetBoundingBox())
                aperture = (left - pcbnew.ToMM(margin.x), top - pcbnew.ToMM(margin.y),
                            right + pcbnew.ToMM(margin.x), bottom + pcbnew.ToMM(margin.y))
                for via in vias:
                    reach = pcbnew.ToMM(via.GetDrillValue()) / 2 + PASTE_TO_VIA_DRILL
                    assert not route.circle_meets_rect(*pad_xy(via), reach, aperture), (
                        f"{footprint.GetReference()}: paste aperture at {pad_xy(pad)} is within "
                        f"{PASTE_TO_VIA_DRILL} mm of the via hole at {pad_xy(via)}")


def write_models() -> None:
    """One model file per footprint type, and one sanity check on them: no bottom-side part reaches the case
    floor (board.toml pcb.bottom_z below the PCB)."""
    real_parts = [part for part in circuit.all_parts() if part.footprint_key not in circuit.NOT_A_PART]
    missing = sorted({part.footprint_key for part in real_parts} - models.MODELLED)
    assert not missing, f"no 3D model for {missing}"
    floor_gap = PCB["bottom_z"]
    for key in sorted(models.MODELLED):
        footprint = _load_footprint(circuit.FOOTPRINT[key])
        models.write_model(key, footprint)
        on_bottom = any(part.footprint_key == key and part.side == BOTTOM for part in real_parts)
        height = max(solid.z_top for solid in models.solids(key, footprint))
        assert not on_bottom or height < floor_gap, f"{key} is {height} mm tall, the case floor is {floor_gap} mm away"


def build_board(board_path: Path, open_pin_nets: dict[str, str]) -> pcbnew.BOARD:
    """open_pin_nets: "U1.14" -> the net name KiCad's schematic netlist gives that unconnected pin."""
    parts = circuit.all_parts()
    circuit.check_netlist(parts)
    board = pcbnew.NewBoard(str(board_path))
    board.SetCopperLayerCount(PCB["layers"])
    _rules(board)
    _outline(board)
    placed = {part.ref: _place(board, part, open_pin_nets) for part in parts}
    check_placement(placed)
    check_hole_keepouts(board)
    silk.add_labels(board)
    silk.check_minimums(board)
    add_inner_planes(board)
    add_keepouts(board)
    return board
