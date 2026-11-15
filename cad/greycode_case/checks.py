"""Every check on the case, and a self-test that feeds the same measurements known-bad shapes.

`run_all()` returns the report written to cad/exports/checks.json; `failures()` lists what failed.
"""

from math import hypot, inf

from build123d import Box, Compound, Part, Pos, Rectangle

from . import measure, parts
from .assembly import CASE_PARTS, MOVING, assembly, case_parts
from .reference import screw_tip
from .shapes import Hole, box, cylinder, rounded, slab
from .spec import (
    BASE_BOSS_DIAMETER,
    CASE,
    EC11_SHAFT,
    KNOB_BORE_CLEARANCE,
    KNOB_DIAMETER,
    KNOB_FLUTE_DEPTH,
    M2_MAJOR,
    M2_TAP_DRILL,
    M2_THREAD_DEPTH,
    PCB,
    PCB_TOP,
    STANDOFF_DIAMETER,
    drill_point_length,
)

MIN_WALL = 1.0
MIN_CORNER_RADIUS = 0.5  # 1 mm end mill
DEEP_POCKET = 3.0  # mm; a corner taller than this ...
MIN_DEEP_CORNER_RADIUS = 1.5  # ... gets a bigger tool radius
MIN_HOLE_METAL = 1.0
MIN_KEYCAP_CLEARANCE = 0.4
MIN_KNOB_CLEARANCE = 0.2  # guess at enough for anodise, flatness and a wobbling knob
MIN_SOCKET_CLEARANCE = 0.3
MIN_PLUG_CLEARANCE = 0.2
MIN_THREAD_MARGIN = 0.2  # screw tip below the end of the full thread
MIN_ENGAGEMENT = M2_MAJOR  # 1 x d of thread in 6061; a guess at enough for a part that is not loaded


def _from_knob_axis(point) -> float:
    return hypot(point.X - PCB.knob[0], point.Y - PCB.knob[1])


def _in_flutes(point) -> bool:
    low, high = parts.flute_band()
    return low - 0.05 <= point.Z <= high + 0.05 and _from_knob_axis(point) > KNOB_DIAMETER / 2 - KNOB_FLUTE_DEPTH - 0.05


def _at_d_flat_corner(point) -> bool:
    flat = EC11_SHAFT[1] - EC11_SHAFT[0] / 2 + KNOB_BORE_CLEARANCE
    on_circle = abs(_from_knob_axis(point) - (EC11_SHAFT[0] / 2 + KNOB_BORE_CLEARANCE)) < 0.05
    return on_circle and abs(point.X - PCB.knob[0] - flat) < 0.05


# Designed features the inside-corner rule does not apply to, with the reason the shop needs.
CORNER_EXEMPT = {
    "top": {},
    "base": {},
    "knob": {
        "flutes: ball end mill along the knob axis (4th axis or live tooling), not a vertical cutter": _in_flutes,
        "D-bore flat corners: broached": _at_d_flat_corner,
    },
}


def run_all() -> dict:
    built = parts.built_parts()
    solids = case_parts()
    return {
        "soundness": [{"part": name, **measure.soundness(solids[name])} for name in CASE_PARTS]
        + [{"part": name, **measure.soundness(part)} for name, part in assembly().items() if name not in solids],
        "interference": _interference(),
        "clearances": _clearances(),
        "walls": [_wall(name, built[name].solid) for name in parts.MACHINED],
        "feature_gaps": [_feature_gap(name, built[name]) for name in parts.MACHINED],
        "corners": [_corners(name, built[name]) for name in parts.MACHINED],
        "screw_holes": [_hole(name, built[name].solid, hole) for name in parts.MACHINED for hole in built[name].holes],
        "self_test": self_test(),
    }


def _interference() -> list[dict]:
    rest_pairs, rest = measure.clashes(assembly(pressed=False))
    pressed_pairs, pressed = measure.clashes(assembly(pressed=True), only=MOVING)
    return [
        {"state": "at rest", "pairs": rest_pairs, "clashes": rest},
        {"state": "keys and knob pressed (moving parts only)", "pairs": pressed_pairs, "clashes": pressed},
    ]


def _row(name: str, value: float, minimum: float) -> dict:
    return {"name": name, "value_mm": round(value, 3), "minimum_mm": minimum, "ok": value >= minimum - 1e-6}


def _clearances() -> list[dict]:
    rest, pressed = assembly(False), assembly(True)
    caps = [name for name in rest if name.startswith("keycap")]
    sockets = [name for name in rest if name.startswith("socket")]
    thread_end = PCB_TOP + M2_THREAD_DEPTH
    wall_y = PCB.depth + CASE.pcb_clearance  # inner face of the back wall
    in_wall = rest["usb plug"] & box((0.0, PCB.width), (wall_y, wall_y + 100.0), (0.0, 100.0))
    return [
        _row(
            "keycaps at rest to top shell",
            min(measure.clearance(rest[c], rest["top"]) for c in caps),
            MIN_KEYCAP_CLEARANCE,
        ),
        _row(
            "keycaps pressed to top shell",
            min(measure.clearance(pressed[c], pressed["top"]) for c in caps),
            MIN_KEYCAP_CLEARANCE,
        ),
        _row("knob pressed to top shell", measure.clearance(pressed["knob"], pressed["top"]), MIN_KNOB_CLEARANCE),
        _row(
            "hot-swap sockets to base",
            min(measure.clearance(rest[s], rest["base"]) for s in sockets),
            MIN_SOCKET_CLEARANCE,
        ),
        _row(
            "USB plug overmold to top shell",
            measure.clearance(rest["usb plug"], rest["top"]),
            MIN_PLUG_CLEARANCE,
        ),
        _row("USB plug overmold to base", measure.clearance(rest["usb plug"], rest["base"]), MIN_PLUG_CLEARANCE),
        _row(
            "USB plug overmold above the case underside (table plane, feet excluded)",
            rest["usb plug"].bounding_box().min.Z,
            0.0,
        ),
        _row(
            "USB plug overmold in the opening (radial, inside the back wall)",
            min(measure.clearance(in_wall, rest[shell]) for shell in ("top", "base")),
            MIN_PLUG_CLEARANCE,
        ),
        _row(
            "standoff and base boss inside pcb.hole_keepout_diameter (radial margin)",
            (PCB.hole_keepout_diameter - max(STANDOFF_DIAMETER, BASE_BOSS_DIAMETER)) / 2,
            0.0,
        ),
        _row("M2 screw tip below end of thread", thread_end - screw_tip(), MIN_THREAD_MARGIN),
        _row("M2 thread engagement in standoff", screw_tip() - PCB_TOP, MIN_ENGAGEMENT),
    ]


def _wall(name: str, solid: Part) -> dict:
    found = measure.thinnest_wall(solid, {})
    return {"part": name, **found, "minimum_mm": MIN_WALL, "ok": found["thinnest_mm"] >= MIN_WALL}


def _feature_gap(name: str, built: parts.Built) -> dict:
    """Between every two cuts, and between each screw hole's metal envelope (thread major diameter or
    countersink) and every cut, e.g. the knob's M3 thread and its flutes."""
    envelopes = {f"{hole.name} envelope": hole.body(metal=True) for hole in built.holes}
    gaps = measure.feature_gaps(built.cutters | envelopes)
    if not gaps:  # every cut meets another: nothing to measure between them
        return {"part": name, "between": [], "metal_mm": None, "minimum_mm": MIN_WALL, "ok": True, "next": []}
    return {"part": name, **gaps[0], "minimum_mm": MIN_WALL, "ok": gaps[0]["metal_mm"] >= MIN_WALL, "next": gaps[1:4]}


def _corners(name: str, built: parts.Built) -> dict:
    found = measure.concave_corners(built.solid, CORNER_EXEMPT.get(name, {}), built.cutters)
    failing = [corner for corner in found["rounds"] if _corner_fault(corner)]
    return {
        "part": name,
        "features": _by_feature(found["rounds"]),
        "failing": _by_feature(failing),
        "sharp_edges": found["sharp_edges"],
        "exempt": found["exempt"],
        "minimum_mm": MIN_CORNER_RADIUS,
        "deep_minimum_mm": MIN_DEEP_CORNER_RADIUS,
        "ok": not failing and not found["sharp_edges"],
    }


def _corner_fault(corner: dict) -> bool:
    """Too small for a 1 mm end mill, reached by no vertical tool, or deep with a small tool radius."""
    radius, reach = corner["radius_mm"], corner["reach_mm"]
    if radius < MIN_CORNER_RADIUS - 1e-6 or reach is None:
        return True
    return reach > DEEP_POCKET and radius < MIN_DEEP_CORNER_RADIUS - 1e-6


def _reach_key(corner: dict) -> float:
    return inf if corner["reach_mm"] is None else corner["reach_mm"]


def _by_feature(corners: list[dict]) -> list[dict]:
    """One row per cut: smallest radius, tallest wall, and the deepest tool reach among its corners."""
    groups: dict[str, list[dict]] = {}
    for corner in corners:
        groups.setdefault(corner["feature"], []).append(corner)
    rows = []
    for feature, group in groups.items():
        deepest = max(group, key=_reach_key)
        rows.append(
            {
                "feature": feature,
                "corners": len(group),
                "radius_mm": min(corner["radius_mm"] for corner in group),
                "wall_mm": max(corner["wall_mm"] for corner in group),
                "reach_mm": deepest["reach_mm"],
                "from": deepest["from"],
            }
        )
    return sorted(rows, key=lambda row: (row["radius_mm"], row["feature"]))


def _hole(name: str, solid: Part, hole: Hole) -> dict:
    metal = measure.hole_metal(solid, hole)
    return {
        "part": name,
        "hole": hole.name,
        "metal_mm": round(metal, 3),
        "minimum_mm": MIN_HOLE_METAL,
        "ok": metal >= MIN_HOLE_METAL - 1e-6,
    }


def failures(report: dict) -> list[str]:
    problems = [f"{row['part']} is not one valid closed solid" for row in report["soundness"] if not row["ok"]]
    for state in report["interference"]:
        problems += [
            f"clash ({state['state']}): {' / '.join(c['parts'])} {c['volume_mm3']} mm^3" for c in state["clashes"]
        ]
    problems += [
        f"{row['name']}: {row['value_mm']} mm < {row['minimum_mm']}" for row in report["clearances"] if not row["ok"]
    ]
    problems += [
        f"{row['part']} wall {row['thinnest_mm']} mm at {row['at']}" for row in report["walls"] if not row["ok"]
    ]
    problems += [
        f"{row['part']} metal between {' and '.join(row['between'])}: {row['metal_mm']} mm"
        for row in report["feature_gaps"]
        if not row["ok"]
    ]
    for row in report["corners"]:
        if not row["ok"]:
            failing = [
                f"{f['feature']} R{f['radius_mm']} reach {f['reach_mm']} from {f['from']}" for f in row["failing"]
            ]
            problems.append(f"{row['part']} inside corners: {failing} sharp edges {row['sharp_edges'][:3]}")
    problems += [
        f"{row['part']} {row['hole']}: {row['metal_mm']} mm of metal" for row in report["screw_holes"] if not row["ok"]
    ]
    problems += [f"self-test: {row['name']} judged wrong" for row in report["self_test"] if not row["ok"]]
    return problems


# ---- Self-test ---------------------------------------------------------------------------------------


def _block() -> Part:
    return box((0, 20), (0, 20), (0, 10))


def _pocketed(wall: float, radius: float, depth: float = 2.0) -> Part:
    """A 20 x 20 x 10 block with a pocket from the top that leaves `wall` on the +x side."""
    size = 10.0
    centre = (20 - wall - size / 2, 10.0)
    return _block() - slab(
        rounded(centre, (size, size), radius) if radius else _square(centre, size), (10 - depth, 10.01)
    )


def _nested(radius: float) -> Part:
    """A 2 mm pocket (R2) with a smaller pocket 2 mm deeper in its floor: the inner corners sit only
    2 mm high, but the tool reaches 4 mm below the top face to cut them."""
    outer = slab(rounded((10, 10), (14, 14), 2.0), (8.0, 10.01))
    return _block() - outer - slab(rounded((10, 10), (6, 6), radius), (6.0, 8.01))


def _square(centre: tuple[float, float], size: float):
    return Pos(*centre) * Rectangle(size, size)


def _tapped(distance_to_side: float) -> tuple[Part, Hole]:
    drill = M2_TAP_DRILL / 2
    hole = Hole(
        "test M2",
        (20 - distance_to_side, 10, -0.01),
        (0, 0, 1),
        ((drill, drill, 5.01), (drill, 0.0, drill_point_length(M2_TAP_DRILL))),
        ((M2_MAJOR / 2, M2_MAJOR / 2, 4.01), (drill, drill, 1.0), (drill, 0.0, drill_point_length(M2_TAP_DRILL))),
        (0.01, 100.0),
    )
    return _block() - hole.body(), hole


def _verdict(name: str, faulty: bool, expected_faulty: bool, value) -> dict:
    return {
        "name": name,
        "value": value,
        "expected_fault": expected_faulty,
        "found_fault": faulty,
        "ok": faulty == expected_faulty,
    }


def self_test() -> list[dict]:
    rows = []
    for name, offset, expected in (("overlapping boxes", 9.0, True), ("touching boxes", 10.0, False)):
        _, found = measure.clashes({"a": Box(10, 10, 10), "b": Pos(offset, 0, 0) * Box(10, 10, 10)})
        rows.append(_verdict(f"clash: {name}", bool(found), expected, found))
    for wall, expected in ((0.6, True), (1.5, False)):
        thinnest = measure.thinnest_wall(_pocketed(wall, 2.0, depth=6.0), {})["thinnest_mm"]
        rows.append(_verdict(f"wall: pocket {wall} mm from a side", thinnest < MIN_WALL, expected, thinnest))
    for radius, depth, expected in (
        (0.0, 2.0, True),
        (0.3, 2.0, True),
        (1.0, 2.0, False),
        (1.0, 4.0, True),
        (1.5, 4.0, False),
    ):
        built = parts.Built(_pocketed(3.0, radius, depth))
        result = _corners("self-test", built)
        rows.append(
            _verdict(f"corner: pocket R{radius} {depth} mm deep", not result["ok"], expected, result["features"][:1])
        )
    for radius, expected in ((1.0, True), (1.5, False)):
        result = _corners("self-test", parts.Built(_nested(radius)))
        rows.append(
            _verdict(
                f"corner: R{radius} pocket 2 mm deep in a 2 mm pocket", not result["ok"], expected, result["failing"]
            )
        )
    for distance, expected in ((1.6, True), (4.0, False)):
        solid, hole = _tapped(distance)
        metal = measure.hole_metal(solid, hole)
        rows.append(
            _verdict(f"screw hole: M2 {distance} mm from a side", metal < MIN_HOLE_METAL, expected, round(metal, 3))
        )
    for name, shape, expected in (
        ("one box", Box(5, 5, 5), False),
        ("two separate boxes", Compound([Box(5, 5, 5), Pos(10, 0, 0) * Box(5, 5, 5)]), True),
    ):
        rows.append(_verdict(f"soundness: {name}", not measure.soundness(shape)["ok"], expected, None))
    for gap, expected in ((0.5, True), (2.0, False)):
        cuts = {"a": box((0, 5), (0, 5), (5, 11)), "b": box((5 + gap, 10), (0, 5), (5, 11))}
        metal = measure.feature_gaps(cuts)[0]["metal_mm"]
        rows.append(_verdict(f"metal between two pockets {gap} mm apart", metal < MIN_WALL, expected, metal))
    for gap, expected in ((0.3, True), (0.6, False)):
        distance = measure.clearance(Box(5, 5, 5), Pos(5 + gap, 0, 0) * Box(5, 5, 5))
        rows.append(
            _verdict(f"clearance: parts {gap} mm apart", distance < MIN_KEYCAP_CLEARANCE, expected, round(distance, 3))
        )
    _, found = measure.clashes({"plate": box((0, 10), (0, 10), (0, 1)), "pin": cylinder((5, 5), 2, (-1, 2))})
    rows.append(_verdict("clash: pin through a plate", bool(found), True, found))
    return rows


def summary(report: dict) -> str:
    """The report as the lines `build.py check` prints."""
    tests, sound = report["self_test"], report["soundness"]
    lines = [
        f"self-test: {sum(r['ok'] for r in tests)} of {len(tests)} known faults and sound shapes judged right",
        f"soundness: {sum(r['ok'] for r in sound)} of {len(sound)} parts are one valid closed solid",
    ]
    lines += [
        f"interference ({r['state']}): {r['pairs']} pairs, {len(r['clashes'])} clashes" for r in report["interference"]
    ]
    lines += [f"  {r['name']}: {r['value_mm']} mm (min {r['minimum_mm']})" for r in report["clearances"]]
    lines += [
        f"wall {r['part']}: thinnest {r['thinnest_mm']} mm at {r['at']} ({r['samples']} samples, min {MIN_WALL})"
        for r in report["walls"]
    ]
    lines += [
        f"metal between cuts {r['part']}: {r['metal_mm']} mm, {' / '.join(r['between'])} (min {MIN_WALL})"
        for r in report["feature_gaps"]
        if r["between"]
    ]
    lines += [_corner_line(row) for row in report["corners"]]
    for part in parts.MACHINED:
        mine = [row for row in report["screw_holes"] if row["part"] == part]
        if mine:
            least = min(mine, key=lambda row: row["metal_mm"])
            lines.append(
                f"screw holes {part}: {len(mine)}, least metal {least['metal_mm']} mm "
                f"({least['hole']}, min {MIN_HOLE_METAL})"
            )
    return "\n".join(lines)


def _corner_line(row: dict) -> str:
    smallest = row["features"][0] if row["features"] else {"radius_mm": "-", "feature": "-"}
    deep = [
        f"{f['feature']} R{f['radius_mm']} ({f['reach_mm']} from {f['from']})"
        for f in row["features"]
        if _reach_key(f) > DEEP_POCKET
    ]
    return (
        f"inside corners {row['part']}: smallest R{smallest['radius_mm']} ({smallest['feature']}), "
        f"{len(row['sharp_edges'])} sharp, tool reach over {DEEP_POCKET} mm: {', '.join(deep) or 'none'}; "
        f"exempt {row['exempt'] or 'none'}"
    )
