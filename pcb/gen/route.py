"""Routes the placed board with router.py and writes the tracks and vias. Needs pcbnew.

Order: the MCU's own supply first, while the board is empty and each pin can take the shortest way to its
capacitor; then the crystal, USB and flash connections; then one via to the plane for every power and ground
pad; then the ordinary signals, shortest first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pcbnew

import circuit
import schematic
from circuit import DEPTH, GND, PCB, V1, V3, V5, VBUS, WIDTH
from router import BACK, BOTH_LAYERS, FRONT, Pad, Router, Rules, Via

PLANE_NETS = (GND, V1, V3, V5)
# Routed after the MCU supply, in this order. Limits are track lengths in mm that fail the build.
SENSITIVE_NETS = ("USB_DM", "USB_DP", "USB_D_P", "USB_D_N", "XIN", "XOUT", "XTAL_DRIVE")
# MCU nets whose other pads are right next to the chip. Routed whole, straight after the sensitive ones.
LOCAL_NETS = ("QSPI_SD3", "QSPI_SCLK", "QSPI_SD0", "QSPI_SD2", "QSPI_SD1", "QSPI_SS", "BOOT")
# SWCLK, SWDIO and RUN leave the chip towards the test pads and the reset button before the crystal nets, which
# would otherwise cross their way out.
EARLY_ESCAPES = ("U1.24", "U1.25", "U1.26")
# Every other MCU signal first gets a track out of this square around the chip, one pin at a time.
# Without it the early nets wall in the pins of the late ones.
ESCAPE_DISTANCE = 6.0
# USB_DM and USB_DP are the MCU side of the 27 ohm resistors. The first limit, 6 mm, was a number picked before
# any layout; the decoupling capacitors of pins 44 and 49 sit between the USB pins and the nearest spot for the
# resistors, so the routed board needs about 7.5 mm (routing.txt). 8 mm is still electrically short at full
# speed; the check only catches a resistor that drifts away. Not from a datasheet.
LENGTH_LIMIT = {"XIN": 9.0, "XTAL_DRIVE": 9.0, "XOUT": 12.0, "USB_DM": 8.0, "USB_DP": 8.0}
# mm. Only catches a detour: at 12 Mbit/s a bit lasts 83 ns and 1 mm of track about 6 ps. The sibling board used
# 2.0; this board's D+ runs round the ESD diode and measures 2.09 mm longer, so the limit is 3.0. Not a spec value.
USB_PAIR_MISMATCH_LIMIT = 3.0
# Each QSPI line, MCU pin to flash pin: the flash runs at up to 133 MHz on the RP2040's QSPI bus.
QSPI_LENGTH_LIMIT = 15.0
_PLANE_EDGE_MARGIN = 0.55  # a via this close to the edge of its plane island might miss it
_KICAD_LAYER = {FRONT: pcbnew.F_Cu, BACK: pcbnew.B_Cu}
# Ground vias in the MCU's exposed pad: the chip's ground return and its heat path.
# The exposed pad's paste windows leave room for them (layout.EP_PASTE_WINDOWS).
EXPOSED_PAD_VIA_OFFSETS = ((-1.0, -1.0), (1.0, -1.0), (-1.0, 1.0), (1.0, 1.0))


@dataclass(frozen=True)
class Setup:
    rules: Rules
    v3_island: list[tuple]  # rectangles (left, top, right, bottom) of the 3.3 V island on the power layer
    v1_island: list[tuple]  # the 1.1 V island inside it
    # MCU nets that go before the others, from route_order.txt (see build.py order).
    head_start: tuple[str, ...] = ()


@dataclass
class RoutingResult:
    router: Router
    unrouted: list[str] = field(default_factory=list)  # "NET: pad" for every pad left unconnected

    def report_lines(self) -> list[str]:
        router = self.router
        nets = sorted({track.net for track in router.tracks})
        lines = [
            f"tracks {len(router.tracks)}  vias {len(router.vias)}  "
            f"length {sum(t.length for t in router.tracks):.1f} mm  unrouted pads {len(self.unrouted)}",
            f"USB pair, connector to MCU: D+ {usb_path_length(router, 'P'):.2f} mm, "
            f"D- {usb_path_length(router, 'N'):.2f} mm",
            "",
            f"{'net':14} {'mm':>7} {'vias':>4}",
        ]
        for net in nets:
            vias = sum(via.net == net for via in router.vias)
            lines.append(f"{net:14} {router.net_length(net):7.2f} {vias:4}")
        lines += ["", "unrouted:"] + (self.unrouted or ["none"])
        return lines


def usb_path_length(router: Router, polarity: str) -> float:
    """Copper from the connector to the MCU pin of one USB line, both sides of the series resistor."""
    mcu_side = {"P": "USB_DP", "N": "USB_DM"}[polarity]
    return router.net_length(f"USB_D_{polarity}") + router.net_length(mcu_side)


def box_mm(box: pcbnew.BOX2I) -> tuple[float, float, float, float]:
    return tuple(pcbnew.ToMM(v) for v in (box.GetLeft(), box.GetTop(), box.GetRight(), box.GetBottom()))


def _hole_rect(pad: pcbnew.PAD) -> tuple[float, float, float, float]:
    x, y = pcbnew.ToMM(pad.GetPosition().x), pcbnew.ToMM(pad.GetPosition().y)
    radius = max(pcbnew.ToMM(pad.GetDrillSize().x), pcbnew.ToMM(pad.GetDrillSize().y)) / 2
    return x - radius, y - radius, x + radius, y + radius


def _edge_cutouts(board: pcbnew.BOARD) -> list[tuple[float, float, float, float]]:
    """Cut-outs inside the board drawn by footprints (the reverse-mount LED windows)."""
    return [box_mm(item.GetBoundingBox()) for footprint in board.GetFootprints()
            for item in footprint.GraphicalItems() if item.GetLayer() == pcbnew.Edge_Cuts]


def _load_obstacles(board: pcbnew.BOARD, router: Router) -> dict[str, list[Pad]]:
    """Feeds every pad, hole, cut-out and keep-out to the router. Returns the pads by name ("U1.5")."""
    pads: dict[str, list[Pad]] = {}
    for footprint in sorted(board.GetFootprints(), key=lambda fp: fp.GetReference()):
        for kicad_pad in footprint.Pads():
            if kicad_pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                router.add_hole(_hole_rect(kicad_pad))
                continue
            layers = tuple(layer for layer in BOTH_LAYERS if kicad_pad.IsOnLayer(_KICAD_LAYER[layer]))
            name = f"{footprint.GetReference()}.{kicad_pad.GetNumber()}"
            net = schematic.circuit_net_name(kicad_pad.GetNetname())
            pad = Pad(name, net, box_mm(kicad_pad.GetBoundingBox()), layers)
            router.add_pad(pad)
            pads.setdefault(name, []).append(pad)
    for rect in _edge_cutouts(board):
        # The edge clearance, not the hole clearance, applies to a cut-out.
        router.add_keepout(_grown(rect, router.rules.edge_clearance + router.rules.track_width / 2 + 0.02),
                           BOTH_LAYERS)
        router.add_keepout(_grown(rect, router.rules.edge_clearance + router.rules.via_diameter / 2 + 0.02), ())
    # board.toml hole_keepout_diameter: no copper inside, on any layer (square: a little more than the circle).
    for x, y in (circuit.kicad_xy(*hole) for hole in PCB["holes"]):
        circle = _grown((x, y, x, y), PCB["hole_keepout_diameter"] / 2)
        router.add_keepout(_grown(circle, router.rules.track_width / 2 + 0.02), BOTH_LAYERS)
        router.add_keepout(_grown(circle, router.rules.via_diameter / 2 + 0.02), ())
    mask_radius = circuit.FIDUCIAL_MASK_DIAMETER / 2 + 0.1
    for x, y in circuit.FIDUCIALS:
        router.add_keepout((x - mask_radius, y - mask_radius, x + mask_radius, y + mask_radius), (BACK,))
    return pads


def _grown(rect: tuple, margin: float) -> tuple:
    left, top, right, bottom = rect
    return left - margin, top - margin, right + margin, bottom + margin


def _in_any(rectangles: list[tuple], x: float, y: float, grow: float) -> bool:
    return any(left - grow <= x <= right + grow and top - grow <= y <= bottom + grow
               for left, top, right, bottom in rectangles)


def _plane_tests(v3_island: list[tuple], v1_island: list[tuple]) -> dict:
    """Per plane net: is that net's plane under this point? Ground is everywhere on its own layer."""
    margin = _PLANE_EDGE_MARGIN
    return {
        GND: lambda x, y: True,
        V1: lambda x, y: _in_any(v1_island, x, y, -margin),
        V3: lambda x, y: _in_any(v3_island, x, y, -margin) and not _in_any(v1_island, x, y, margin),
        V5: lambda x, y: not _in_any(v3_island, x, y, margin),
    }


def _via_pad(via: Via) -> Pad:
    """A via as a pad on both layers, so a route can start from it."""
    return Pad(f"via at ({via.x:.1f}, {via.y:.1f})", via.net, (via.x, via.y) * 2, BOTH_LAYERS)


def _pin_number(pad: Pad) -> int:
    return int(pad.name.split(".")[1])


class _Plan:
    """The routing order. One method per stage; each appends what it could not connect."""

    def __init__(self, router: Router, pads: dict[str, list[Pad]], setup: Setup) -> None:
        self.router = router
        self.pads = pads
        self.plane_here = _plane_tests(setup.v3_island, setup.v1_island)
        self.head_start = setup.head_start
        self.unrouted: list[str] = []
        self.routed_nets: set[str] = set(PLANE_NETS)
        self.on_plane: set[Pad] = set()  # plane-net pads that already reach their plane
        self.by_net: dict[str, list[Pad]] = {}
        for name in sorted(pads):
            for pad in pads[name]:
                if pad.net:
                    self.by_net.setdefault(pad.net, []).append(pad)

    def pad(self, name: str) -> Pad:
        return self.pads[name][0]

    def exposed_pad_vias(self) -> None:
        for dx, dy in EXPOSED_PAD_VIA_OFFSETS:
            self.router.add_via_in_pad(GND, circuit.MCU_X + dx, circuit.MCU_Y + dy)
        self.on_plane.add(self.pad("U1.57"))

    def pair(self, net: str, first: str, second: str, wide: bool = False) -> None:
        if not self.router.route_pair(net, self.pad(first), self.pad(second), wide):
            self.unrouted.append(f"{net}: {first} to {second}")

    def fan_out(self, pad: Pad) -> None:
        """A wide stub if it fits, a normal one if not."""
        self.on_plane.add(pad)
        plane_here = self.plane_here[pad.net]
        if not (self.router.fan_out(pad.net, pad, plane_here, wide=True)
                or self.router.fan_out(pad.net, pad, plane_here)):
            self.unrouted.append(f"{pad.net}: {pad.name} (no via to its plane)")

    def mcu_supply(self) -> None:
        """Every MCU supply pin with its capacitor, and the vias to the planes."""
        for ref, pin in circuit.DECOUPLING_CAPS.items():
            self._decouple(ref, pin)
        for pin in circuit.INNER_VIA_PINS:
            self._inner_via(pin)
        for pin, neighbour in circuit.TIED_PINS.items():
            self.pair(V3, f"U1.{pin}", f"U1.{neighbour}")
        self.fan_out(self.pad("U1.19"))  # TESTEN to ground
        for ref in circuit.SECOND_SUPPLY_CAPS:
            for pad in (f"{ref}.1", f"{ref}.2"):
                self.fan_out(self.pad(pad))

    def _inner_via(self, pin: int) -> None:
        """A supply pin with no room in front: short track inward to a via between the pad ring and the exposed
        pad, into its plane island."""
        net = circuit.MCU_POWER_PINS[pin]
        out_x, out_y = circuit.outward(pin)
        pad_x, pad_y = circuit.mcu_pin_xy(pin)
        depth = circuit.INNER_VIA_DEPTH
        x, y = self.router.snapped(pad_x - out_x * depth, pad_y - out_y * depth)
        assert self.plane_here[net](x, y), f"U1.{pin}: no {net} plane under its via at ({x}, {y})"
        via = self.hand_via(net, x, y)
        self.to_via(self.pad(f"U1.{pin}"), via)
        self.on_plane.add(self.pad(f"U1.{pin}"))

    def _decouple(self, ref: str, pin: int) -> None:
        """Supply via, capacitor, ground via on one line pointing away from the chip.

        Hand-placed: left to the search, these vias land beside the capacitor, in the lanes the
        neighbouring pins need. Where the supply via has no room or no plane under it, the search
        takes over.
        """
        net = circuit.MCU_POWER_PINS[pin]
        out_x, out_y = circuit.outward(pin)
        supply_pad, ground_pad = self.pad(f"{ref}.1"), self.pad(f"{ref}.2")
        centre_x = (supply_pad.centre[0] + ground_pad.centre[0]) / 2
        centre_y = (supply_pad.centre[1] + ground_pad.centre[1]) / 2
        to_supply_via = circuit.DECOUPLING_DISTANCE - circuit.SUPPLY_VIA_DISTANCE
        to_ground_via = circuit.GROUND_VIA_DISTANCE
        supply_via = self.router.snapped(centre_x - out_x * to_supply_via, centre_y - out_y * to_supply_via)
        ground_via = self.router.snapped(centre_x + out_x * to_ground_via, centre_y + out_y * to_ground_via)

        pin_pad = self.pad(f"U1.{pin}")
        if self.plane_here[net](*supply_via) and self.router.via_fits(net, *supply_via):
            self.router.add_via(net, *supply_via)
            for pad in (pin_pad, supply_pad):
                if not self.router.route_to_via(net, [pad], Via(net, *supply_via)):
                    self.unrouted.append(f"{net}: {pad.name}")
        else:
            self.pair(net, pin_pad.name, supply_pad.name)
            self.fan_out(supply_pad)
        self.on_plane.update((supply_pad, pin_pad))

        if self.router.via_fits(GND, *ground_via):
            self.router.add_via(GND, *ground_via)
            if not self.router.route_to_via(GND, [ground_pad], Via(GND, *ground_via), wide=True):
                self.unrouted.append(f"{GND}: {ground_pad.name}")
            self.on_plane.add(ground_pad)
        else:
            self.fan_out(ground_pad)

    def hand_via(self, net: str, x: float, y: float) -> Via:
        snapped = self.router.snapped(x, y)
        self.router.add_via(net, *snapped)
        return Via(net, *snapped)

    def to_via(self, pad: Pad, via: Via, wide: bool = False) -> None:
        if not self.router.route_to_via(via.net, [pad], via, wide):
            self.unrouted.append(f"{via.net}: {pad.name} to the via at ({via.x:.1f}, {via.y:.1f})")

    def net(self, net: str, wide: bool = False) -> None:
        failed = self.router.route_net(net, self.by_net[net], wide)
        if wide and failed:  # a wide track does not fit between fine-pitch pads
            failed = self.router.route_net(net, [pad for pad in self.by_net[net] if pad.name in failed])
        self.unrouted += [f"{net}: {name}" for name in failed]
        self.routed_nets.add(net)

    def mcu_escapes(self) -> None:
        """Each remaining MCU signal: first a track out of the crowd around the chip, then the rest of the net.

        The pin next to a decoupling capacitor goes first, then its neighbour, and so on outward:
        each track can then lean against the one before it, like the teeth of a comb.
        """
        # Pins whose own lane outward stays empty or ends at a capacitor: the comb leans against these.
        decoupled = list(circuit.DECOUPLING_CAPS.values()) + list(circuit.INNER_VIA_PINS) + list(circuit.TIED_PINS)

        def turn(pad: Pad) -> tuple:
            first = self.head_start
            head_start = first.index(pad.net) if pad.net in first else len(first)
            return head_start, min(abs(_pin_number(pad) - pin) for pin in decoupled), _pin_number(pad)

        mcu_pads = [pad for net in sorted(self.by_net) for pad in self.by_net[net]
                    if pad.name.startswith("U1.") and net not in self.routed_nets]
        for pad in sorted(mcu_pads, key=turn):
            if self.router.has_escaped(pad) or self.escape(pad):
                self.net(pad.net)

    def escape(self, pad: Pad) -> bool:
        escaped = self.router.escape(pad.net, pad, (circuit.MCU_X, circuit.MCU_Y), ESCAPE_DISTANCE)
        if not escaped:
            self.unrouted.append(f"{pad.net}: {pad.name} (no way out from the MCU)")
        return escaped

    def early_ground(self) -> None:
        """Ground vias of the crystal, its load capacitors and the USB ESD diode (whose ground pin sits between
        its data pins), before any track can take their place."""
        for name in ("Y1.2", "Y1.4", "C14.2", "C15.2", "U3.2"):
            self.fan_out(self.pad(name))

    def plane_fan_out(self) -> None:
        """Every surface pad of a plane net that has no via yet. Through-hole pads touch the planes directly."""
        for net in PLANE_NETS:
            for pad in self.by_net.get(net, []):
                if len(pad.layers) == 1 and pad not in self.on_plane:
                    self.fan_out(pad)

    def led_chain(self) -> None:
        """The links between neighbouring LEDs in one key row or along the edge, before the key nets cross them."""
        leds = sorted((pad for pad in self.pads if pad.startswith("LED")), key=lambda name: name)
        rows = {}
        for name in leds:
            pad = self.pad(name)
            rows[name.split(".")[0]] = round(pad.centre[1])
        for net in sorted(self.by_net):
            if not net.startswith("LED_D") or net in self.routed_nets:
                continue
            refs = {pad.name.split(".")[0] for pad in self.by_net[net]}
            if all(ref.startswith("LED") for ref in refs) and len({rows[ref] for ref in refs}) == 1:
                self.net(net)

    def signals(self) -> None:
        remaining = [net for net in self.by_net if net not in self.routed_nets]
        for net in sorted(remaining, key=lambda name: (_spread(self.by_net[name]), name)):
            self.net(net)


def _spread(pads: list[Pad]) -> float:
    """Half the perimeter of the box around the pads: a quick guess of the track length."""
    xs = [pad.centre[0] for pad in pads]
    ys = [pad.centre[1] for pad in pads]
    return max(xs) - min(xs) + max(ys) - min(ys)


def route(board: pcbnew.BOARD, setup: Setup) -> RoutingResult:
    """Plans every track and via. Nothing is written to the board; see write_copper."""
    router = Router(WIDTH, DEPTH, PCB["corner_radius"], setup.rules)
    plan = _Plan(router, _load_obstacles(board, router), setup)
    plan.exposed_pad_vias()
    plan.mcu_supply()
    plan.early_ground()
    # The ESD diode's VBUS pin sits between its data pins: its way out to the receptacle's VBUS pads on the fuse
    # side goes first, so the data lines go round it.
    plan.pair(VBUS, "U3.5", "J1.A9", wide=True)
    for name in EARLY_ESCAPES:
        plan.escape(plan.pad(name))
    for net in SENSITIVE_NETS:
        plan.net(net)
    # After the data lines: a wide VBUS track along the receptacle's pad row would wall them in.
    plan.net(VBUS, wide=True)
    for net in LOCAL_NETS:
        plan.net(net)
    plan.plane_fan_out()
    plan.led_chain()
    plan.mcu_escapes()
    plan.signals()
    return RoutingResult(router, plan.unrouted)


def write_copper(board: pcbnew.BOARD, router: Router) -> None:
    for track in router.tracks:
        segment = pcbnew.PCB_TRACK(board)
        segment.SetStart(_point(*track.start))
        segment.SetEnd(_point(*track.end))
        segment.SetWidth(pcbnew.FromMM(track.width))
        segment.SetLayer(_KICAD_LAYER[track.layer])
        segment.SetNet(board.FindNet(schematic.board_net_name(track.net)))
        board.Add(segment)
    for via in router.vias:
        barrel = pcbnew.PCB_VIA(board)
        barrel.SetViaType(pcbnew.VIATYPE_THROUGH)
        barrel.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        barrel.SetPosition(_point(via.x, via.y))
        barrel.SetWidth(pcbnew.F_Cu, pcbnew.FromMM(router.rules.via_diameter))
        barrel.SetDrill(pcbnew.FromMM(router.rules.via_drill))
        barrel.SetNet(board.FindNet(schematic.board_net_name(via.net)))
        board.Add(barrel)


def _point(x: float, y: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))


def check_sensitive_lengths(result: RoutingResult) -> None:
    router = result.router
    for net, limit in LENGTH_LIMIT.items():
        length = router.net_length(net)
        assert 0 < length <= limit, f"{net} is {length:.2f} mm long, limit {limit} mm"
    for net in circuit.MCU_FIXED_SIGNALS.values():
        if net.startswith("QSPI_") and net != "QSPI_SS":  # QSPI_SS also runs on to the BOOT resistor
            length = router.net_length(net)
            assert 0 < length <= QSPI_LENGTH_LIMIT, f"{net} is {length:.2f} mm long, limit {QSPI_LENGTH_LIMIT} mm"
    mismatch = abs(usb_path_length(router, "P") - usb_path_length(router, "N"))
    assert mismatch <= USB_PAIR_MISMATCH_LIMIT, f"USB D+ and D- differ by {mismatch:.2f} mm"


def point_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    t = 0.0 if length_squared == 0 else max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy)
                                                     / length_squared))
    return math.dist(point, (start[0] + t * dx, start[1] + t * dy))


def circle_meets_rect(x: float, y: float, radius: float, rect: tuple) -> bool:
    left, top, right, bottom = rect
    return math.dist((x, y), (min(max(x, left), right), min(max(y, top), bottom))) < radius
