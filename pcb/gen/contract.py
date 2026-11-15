"""The routed board against board.toml, read independently of circuit.py's placement code. Needs pcbnew.

    build.py contract

Checks the outline, the layer count and thickness, every M2 hole, the key, knob, OLED, USB and LED positions,
and that every GPIO board.toml names reaches the right RP2040 pin on the board. Prints one line per group.
"""

from __future__ import annotations

import math
import tomllib

import pcbnew

import circuit
import schematic

SPEC = tomllib.loads((circuit.REPO_ROOT / "board.toml").read_text())
PCB = SPEC["pcb"]
TOLERANCE = 0.01  # mm


def _xy(vector: pcbnew.VECTOR2I) -> tuple[float, float]:
    return pcbnew.ToMM(vector.x), pcbnew.ToMM(vector.y)


def _spec_xy(x: float, y: float) -> tuple[float, float]:
    """board.toml (front-left origin, y away from the user) -> KiCad (back-left origin, y towards the user).
    Written out here again on purpose: this check does not trust circuit.kicad_xy."""
    return x, PCB["depth"] - y


def _near(actual: tuple[float, float], expected: tuple[float, float], what: str) -> None:
    assert math.dist(actual, expected) < TOLERANCE, f"{what} is at {actual}, board.toml says {expected}"


def _pad(footprint: pcbnew.FOOTPRINT, number: str) -> pcbnew.PAD:
    (pad,) = [pad for pad in footprint.Pads() if pad.GetNumber() == number] or [None]
    assert pad is not None, f"{footprint.GetReference()} has no pad {number}"
    return pad


def _net(pad: pcbnew.PAD) -> str:
    return schematic.circuit_net_name(pad.GetNetname())


def check_outline(board: pcbnew.BOARD) -> str:
    edges = [item for item in board.GetDrawings() if item.GetLayer() == pcbnew.Edge_Cuts]
    box = edges[0].GetBoundingBox()
    for item in edges[1:]:
        box.Merge(item.GetBoundingBox())
    # The outline's line width pads the box by half a stroke on each side.
    half = pcbnew.ToMM(edges[0].GetWidth()) / 2
    left, top = pcbnew.ToMM(box.GetLeft()) + half, pcbnew.ToMM(box.GetTop()) + half
    right, bottom = pcbnew.ToMM(box.GetRight()) - half, pcbnew.ToMM(box.GetBottom()) - half
    _near((left, top), (0.0, 0.0), "outline corner")
    _near((right, bottom), (PCB["width"], PCB["depth"]), "outline corner")
    arcs = [item for item in edges if item.GetShape() == pcbnew.SHAPE_T_ARC]
    assert len(arcs) == 4, f"{len(arcs)} rounded corners"
    for arc in arcs:
        radius = pcbnew.ToMM(arc.GetRadius())
        assert abs(radius - PCB["corner_radius"]) < TOLERANCE, f"corner radius {radius}"
    assert board.GetCopperLayerCount() == PCB["layers"], f"{board.GetCopperLayerCount()} copper layers"
    thickness = pcbnew.ToMM(board.GetDesignSettings().GetBoardThickness())
    assert abs(thickness - PCB["thickness"]) < TOLERANCE, f"board thickness {thickness}"
    return f"outline {PCB['width']} x {PCB['depth']} mm, r {PCB['corner_radius']}, {PCB['layers']} layers"


def check_holes(board: pcbnew.BOARD) -> str:
    drilled = []
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH and abs(
                    pcbnew.ToMM(pad.GetDrillSize().x) - PCB["hole_diameter"]) < TOLERANCE:
                drilled.append(_xy(pad.GetPosition()))
    wanted = [_spec_xy(x, y) for x, y in PCB["holes"]]
    assert len(drilled) == len(wanted), f"{len(drilled)} holes of {PCB['hole_diameter']} mm, board.toml has {len(wanted)}"
    for hole in wanted:
        assert any(math.dist(hole, found) < TOLERANCE for found in drilled), f"no M2 hole at {hole}"
    # The keep-out: one rule area per hole on all copper layers, no copper allowed inside.
    areas = [zone for zone in board.Zones() if zone.GetIsRuleArea() and zone.GetDoNotAllowTracks()
             and zone.GetDoNotAllowVias() and zone.GetDoNotAllowCopperPour()
             and all(zone.IsOnLayer(layer) for layer in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu))]
    radius = PCB["hole_keepout_diameter"] / 2
    for x, y in wanted:
        covering = [area for area in areas
                    if all(area.Outline().Contains(pcbnew.VECTOR2I(pcbnew.FromMM(x + radius * math.cos(a)),
                                                                   pcbnew.FromMM(y + radius * math.sin(a))))
                           for a in (k * math.pi / 8 for k in range(16)))]
        assert covering, f"no {PCB['hole_keepout_diameter']} mm keep-out round the hole at ({x}, {y})"
    return f"{len(wanted)} M2 holes of {PCB['hole_diameter']} mm, each with a {PCB['hole_keepout_diameter']} mm keep-out"


def _mcu_pad_net(board: pcbnew.BOARD, gpio: int) -> str:
    return _net(_pad(board.FindFootprintByReference("U1"), str(circuit.gpio_pin(gpio))))


def check_keys(board: pcbnew.BOARD) -> str:
    columns = len(PCB["key_x"])
    for index, gpio in enumerate(SPEC["keys"]["gpio"]):
        row, column = divmod(index, columns)
        centre = _spec_xy(PCB["key_x"][column], PCB["key_y"][row])
        socket = board.FindFootprintByReference(f"SW{index + 1}")
        _near(_xy(socket.GetPosition()), centre, f"key {index} socket")
        # The switch's centre post hole marks the key centre whatever the footprint origin is.
        centre_hole = [pad for pad in socket.Pads() if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
                       and abs(pcbnew.ToMM(pad.GetDrillSize().x) - 4.0) < TOLERANCE]
        assert len(centre_hole) == 1, f"key {index}: no 4 mm centre hole"
        _near(_xy(centre_hole[0].GetPosition()), centre, f"key {index} centre hole")
        signal = _net(_pad(socket, "1"))
        assert signal == _mcu_pad_net(board, gpio), f"key {index}: socket on {signal}, GPIO{gpio} elsewhere"
        assert _net(_pad(socket, "2")) == circuit.GND, f"key {index}: second socket pad not on GND"
    return f"{len(SPEC['keys']['gpio'])} keys at key_x/key_y, each socket on its GPIO and GND"


def check_knob(board: pcbnew.BOARD) -> str:
    knob, encoder = SPEC["knob"], board.FindFootprintByReference("ENC1")
    pad_a = _xy(_pad(encoder, "A").GetPosition())
    dx, dy = circuit.ENCODER_SHAFT_OFFSET
    _near((pad_a[0] + dx, pad_a[1] + dy), _spec_xy(*PCB["knob"]), "knob shaft")
    for pin, key in (("A", "gpio_a"), ("B", "gpio_b"), ("S1", "gpio_push")):
        net = _net(_pad(encoder, pin))
        assert net == _mcu_pad_net(board, knob[key]), f"encoder {pin} on {net}, not on GPIO{knob[key]}"
    for pin in ("C", "S2"):
        assert _net(_pad(encoder, pin)) == circuit.GND, f"encoder {pin} not on GND"
    return f"knob shaft at {PCB['knob']}, A/B/push on GPIO{knob['gpio_a']}/{knob['gpio_b']}/{knob['gpio_push']}"


def check_display(board: pcbnew.BOARD) -> str:
    display, header = SPEC["display"], board.FindFootprintByReference("J2")
    pins = [_xy(_pad(header, str(n)).GetPosition()) for n in range(1, 5)]
    centre_x, centre_y = _spec_xy(*PCB["oled_module_centre"])
    middle_x = sum(x for x, _ in pins) / len(pins)
    assert abs(middle_x - centre_x) < TOLERANCE, f"OLED header centred at x {middle_x}, module at {centre_x}"
    assert len({round(y, 3) for _, y in pins}) == 1, "OLED header pins not in one row across the board"
    assert centre_y - PCB["oled_module_size"][1] / 2 < pins[0][1] < centre_y, "OLED header not at the module's back"
    # Pin by pin, left to right seen from the top, in circuit.OLED_PINS order (the module's order, MEASURE).
    wanted = {"GND": circuit.GND, "VCC": circuit.V3, "SCL": _mcu_pad_net(board, display["gpio_scl"]),
              "SDA": _mcu_pad_net(board, display["gpio_sda"])}
    left_to_right = sorted((_pad(header, str(n)) for n in range(1, 5)), key=lambda pad: pad.GetPosition().x)
    found = [_net(pad) for pad in left_to_right]
    expected = [wanted[name] for name in circuit.OLED_PINS]
    assert found == expected, f"OLED header pins left to right {found}, {'/'.join(circuit.OLED_PINS)} wants {expected}"
    return (f"OLED header centred under the module, pins {'/'.join(circuit.OLED_PINS)} left to right, "
            f"SDA/SCL on GPIO{display['gpio_sda']}/{display['gpio_scl']}")


def check_usb(board: pcbnew.BOARD) -> str:
    receptacle = board.FindFootprintByReference("J1")
    x = pcbnew.ToMM(receptacle.GetPosition().x)
    assert abs(x - PCB["usb_x"]) < TOLERANCE, f"USB-C receptacle at x {x}, board.toml usb_x {PCB['usb_x']}"
    signal_pads = [_xy(_pad(receptacle, name).GetPosition()) for name in ("A6", "A7", "B6", "B7")]
    middle = sum(px for px, _ in signal_pads) / 4
    assert abs(middle - PCB["usb_x"]) < TOLERANCE, f"USB data pads centred at x {middle}"
    # The fab outline's top edge, less half its line width (the bounding box includes the stroke).
    mouth = min(pcbnew.ToMM(item.GetBoundingBox().GetTop() + item.GetWidth() // 2)
                for item in receptacle.GraphicalItems()
                if isinstance(item, pcbnew.PCB_SHAPE) and item.GetLayer() in (pcbnew.F_Fab, pcbnew.B_Fab))
    assert mouth <= 0.0, f"USB-C mouth {mouth} mm inside the back edge"
    return f"USB-C centred on x {PCB['usb_x']}, mouth at the back edge ({-mouth:.2f} mm over)"


def check_leds(board: pcbnew.BOARD) -> str:
    leds = SPEC["leds"]
    data_net = _mcu_pad_net(board, leds["gpio_data"])
    shifter = board.FindFootprintByReference("U4")
    assert _net(_pad(shifter, "3")) == data_net, f"GPIO{leds['gpio_data']} does not drive the level shifter"
    assert _net(_pad(shifter, "6")) == circuit.V5, "level shifter B side not on 5 V"
    columns = len(PCB["key_x"])
    for index in range(leds["per_key"]):
        row, column = divmod(index, columns)
        key_x, key_y = _spec_xy(PCB["key_x"][column], PCB["key_y"][row])
        led = board.FindFootprintByReference(f"LED{index + 1}")
        x, y = _xy(led.GetPosition())
        assert abs(x - key_x) < TOLERANCE and 0 < y - key_y < 9.525, f"LED{index + 1} not under key {index}"
    for n, edge_x in enumerate(leds["edge_x"]):
        led = board.FindFootprintByReference(f"LED{leds['per_key'] + n + 1}")
        x, y = _xy(led.GetPosition())
        assert abs(x - edge_x) < TOLERANCE and PCB["depth"] - y < 2.0, f"edge LED {n} not at x {edge_x} on the front edge"
    return f"{leds['per_key']} per-key and {leds['edge']} edge LEDs in place, data from GPIO{leds['gpio_data']}"


def check_unused_gpios(board: pcbnew.BOARD) -> str:
    """Every GPIO board.toml does not name is left open: one-pad net, no copper beyond the pin."""
    named = set(SPEC["keys"]["gpio"]) | {SPEC["knob"][k] for k in ("gpio_a", "gpio_b", "gpio_push")}
    named |= {SPEC["display"]["gpio_sda"], SPEC["display"]["gpio_scl"], SPEC["leds"]["gpio_data"]}
    mcu = board.FindFootprintByReference("U1")
    pads_on = {}
    for footprint in board.GetFootprints():
        for pad in footprint.Pads():
            pads_on[pad.GetNetname()] = pads_on.get(pad.GetNetname(), 0) + 1
    copper_nets = {item.GetNetname() for item in board.GetTracks()} | {zone.GetNetname() for zone in board.Zones()}
    for gpio in range(30):
        net = _pad(mcu, str(circuit.gpio_pin(gpio))).GetNetname()
        if gpio in named:
            assert not net.startswith(schematic.OPEN_PIN_NET_PREFIX), f"GPIO{gpio} is named but open"
        else:
            assert net.startswith(schematic.OPEN_PIN_NET_PREFIX), f"GPIO{gpio} is not in board.toml but on {net}"
            assert pads_on[net] == 1, f"GPIO{gpio} is open but its net {net} has {pads_on[net]} pads"
            assert net not in copper_nets, f"GPIO{gpio} is open but has tracks, vias or a zone on {net}"
    return f"{len(named)} GPIOs from board.toml on their pins, the other {30 - len(named)} open"


CHECKS = (check_outline, check_holes, check_keys, check_knob, check_display, check_usb, check_leds,
          check_unused_gpios)


def check(board: pcbnew.BOARD) -> None:
    for step in CHECKS:
        print(f"contract: {step(board)}")
    print(f"contract: {len(CHECKS)} groups match board.toml")
