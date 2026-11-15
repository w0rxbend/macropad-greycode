"""Small build123d helpers in case coordinates, and the hole description the checks reuse."""

from dataclasses import dataclass

from build123d import Align, Axis, Box, Cylinder, Kind, Part, Plane, Polygon, Pos, Rectangle, RectangleRounded, Sketch
from build123d import extrude, offset, revolve

from .spec import PCB

MIN_ALIGN = (Align.CENTER, Align.CENTER, Align.MIN)
FAR = 500.0


def box(x: tuple[float, float], y: tuple[float, float], z: tuple[float, float]) -> Part:
    return Pos((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2) * Box(x[1] - x[0], y[1] - y[0], z[1] - z[0])


def cylinder(centre: tuple[float, float], diameter: float, z: tuple[float, float]) -> Part:
    return Pos(centre[0], centre[1], z[0]) * Cylinder(diameter / 2, z[1] - z[0], align=MIN_ALIGN)


def rounded(centre: tuple[float, float], size: tuple[float, float], radius: float) -> Sketch:
    return Pos(*centre) * RectangleRounded(size[0], size[1], radius)


def pcb_outline(grow: float, radius: float | None = None) -> Sketch:
    """The PCB outline grown by `grow`; its corner radius grows with it unless one is given."""
    corner = PCB.corner_radius + grow if radius is None else radius
    return rounded((PCB.width / 2, PCB.depth / 2), (PCB.width + 2 * grow, PCB.depth + 2 * grow), corner)


def slab(profile: Sketch, z: tuple[float, float]) -> Part:
    return Pos(0, 0, z[0]) * extrude(profile, z[1] - z[0])


@dataclass(frozen=True)
class Hole:
    """A round hole as a stack of frustums from its mouth inward: (start radius, end radius, length).

    `cut` is what the part loses. `metal` is the envelope that must keep metal round it: for a tapped
    hole the thread's major diameter, not the tap drill. Only the stretch `guard` (distances along the
    axis from the mouth) is checked, so the faces a hole opens into do not count as thin walls."""

    name: str
    mouth: tuple[float, float, float]
    axis: tuple[float, float, float]
    cut: tuple[tuple[float, float, float], ...]
    metal: tuple[tuple[float, float, float], ...]
    guard: tuple[float, float]

    def body(self, grow: float = 0.0, metal: bool = False) -> Part:
        """The hole solid, or with `grow` > 0 everything within `grow` of it: the hole is round, so
        that is its half-section offset in 2D and turned round the axis."""
        section = _half_section(self.metal if metal else self.cut)
        if grow > 0:
            section = offset(section, grow, kind=Kind.ARC) & Pos(FAR / 2, 0) * Rectangle(FAR, FAR)
        return Plane(origin=self.mouth, z_dir=self.axis) * revolve(Plane.XZ * section, Axis.Z)

    def guard_zone(self, size: float) -> Part:
        plane = Plane(origin=self.mouth, z_dir=self.axis)
        near, far = self.guard
        return plane * (Pos(0, 0, near) * Box(size, size, far - near, align=MIN_ALIGN))


def _half_section(profile: tuple[tuple[float, float, float], ...]) -> Sketch:
    """The hole's section through its axis: x is the radius, y the distance from the mouth."""
    points, depth = [(0.0, 0.0)], 0.0
    for first, last, length in profile:
        points += [(first, depth), (last, depth + length)]
        depth += length
    points.append((0.0, depth))
    distinct = [point for index, point in enumerate(points) if index == 0 or point != points[index - 1]]
    return Sketch() + Polygon(*distinct, align=None)
