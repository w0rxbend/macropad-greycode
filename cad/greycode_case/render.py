"""Pictures of the case for docs/images/cad/, drawn from the same solids the checks and exports use."""

from pathlib import Path

import matplotlib.pyplot as plt
from build123d import Part, Pos

from .assembly import assembly
from .parts import MACHINED
from .raster import Camera, Look, Mesh, mesh_of, render
from .shapes import box
from .spec import PCB

SIZE = (1600, 1100)
GRAPHITE = Look((0.27, 0.28, 0.30))
CLEAR = Look((0.66, 0.67, 0.69))
SECTIONS = {"top": (0.86, 0.36, 0.22), "base": (0.74, 0.3, 0.2), "knob": (0.93, 0.62, 0.35)}
LOOKS = {
    "top": GRAPHITE,
    "base": GRAPHITE,
    "knob": CLEAR,
    "light strip": Look((1.0, 0.56, 0.18), glow=True),
    "lens": Look((0.07, 0.07, 0.08)),
    "pcb": Look((0.12, 0.22, 0.16)),
    "encoder": Look((0.58, 0.58, 0.6)),
    "encoder shaft": Look((0.7, 0.7, 0.72)),
    "oled module": Look((0.12, 0.2, 0.45)),
    "usb receptacle": Look((0.78, 0.78, 0.8)),
    "usb plug": Look((0.13, 0.13, 0.14)),
}
PREFIX_LOOKS = {
    "switch": Look((0.16, 0.16, 0.17)),
    "socket": Look((0.1, 0.1, 0.1)),
    "keycap": Look((0.86, 0.85, 0.81)),
    "screw": Look((0.22, 0.22, 0.24)),
}
CENTRE = (PCB.width / 2, PCB.depth / 2, 8.0)
# Exploded view: lift per part group, mm.
LIFT = {
    "base": 0.0,
    "screw": -14.0,
    "pcb": 14.0,
    "socket": 14.0,
    "switch": 14.0,
    "encoder": 14.0,
    "oled module": 14.0,
    "usb receptacle": 14.0,
    "light strip": 8.0,
    "top": 34.0,
    "lens": 46.0,
    "keycap": 50.0,
    "knob": 62.0,
    "encoder shaft": 14.0,
}


def look_of(name: str) -> Look:
    return LOOKS.get(name) or PREFIX_LOOKS[name.split(" ")[0]]


def render_all(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    solids = {name: part for name, part in assembly().items() if name != "usb plug"}
    views = {
        "hero": (solids, Camera(eye=(CENTRE[0] + 150, CENTRE[1] - 210, 190), target=CENTRE, field_of_view=24)),
        "exploded": (
            _exploded(solids),
            Camera(eye=(CENTRE[0] + 230, CENTRE[1] - 300, 210), target=(CENTRE[0], CENTRE[1], 26), field_of_view=26),
        ),
        "top": (
            solids,
            Camera(eye=(CENTRE[0], CENTRE[1], 400), target=(CENTRE[0], CENTRE[1], 0), up=(0, 1, 0), ortho_height=118),
        ),
        "underside": (
            {"base": solids["base"]} | _screws(solids),
            Camera(eye=(CENTRE[0], CENTRE[1], -400), target=(CENTRE[0], CENTRE[1], 0), up=(0, 1, 0), ortho_height=118),
        ),
    }
    for name, (parts, camera) in views.items():
        _save(
            render([mesh_of(part, look_of(key)) for key, part in parts.items()], camera, SIZE), folder / f"{name}.png"
        )
    _save(_section(assembly()), folder / "section_knob_oled.png")
    print(f"rendered {len(views) + 1} pictures to {folder}")
    return 0


def _screws(solids: dict[str, Part]) -> dict[str, Part]:
    return {name: part for name, part in solids.items() if name.startswith("screw")}


def _exploded(solids: dict[str, Part]) -> dict[str, Part]:
    moved = {}
    for name, part in solids.items():
        lift = LIFT.get(name, LIFT.get(name.split(" ")[0], 14.0))
        forward = -14.0 if name == "light strip" else 0.0
        moved[name] = Pos(0, forward, lift) * part
    return moved


def _section(solids: dict[str, Part]):
    """Cut on the plane through the knob axis (y = knob y), seen from the front; the back half stays."""
    cut_at = PCB.knob[1]
    keep = box((-50, 150), (cut_at, 200), (-50, 100))
    meshes: list[Mesh] = []
    for name, part in solids.items():
        if part.bounding_box().max.Y <= cut_at:
            continue
        half = part & keep
        if half.volume > 0:
            meshes.append(mesh_of(half, look_of(name), section=(1, cut_at, _section_colour(name))))
    target = (PCB.width / 2, cut_at, 17.0)
    camera = Camera(eye=(target[0], cut_at - 400, target[2]), target=target, ortho_height=48)
    return render(meshes, camera, (1600, 900))


def _section_colour(name: str) -> tuple[float, float, float]:
    """Machined parts in one accent colour, every other part its own colour lightened."""
    if name in MACHINED:
        return SECTIONS[name]
    return tuple(0.55 * channel + 0.45 for channel in look_of(name).colour)


def _save(picture, path: Path) -> None:
    plt.imsave(path, picture)
