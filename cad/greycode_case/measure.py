"""Measurements on finished solids. They look at the geometry, not at how it was built, so the
self-test can feed them deliberately bad shapes."""

from collections.abc import Callable
from itertools import combinations
from math import cos, pi, sin

import numpy as np
import trimesh
from build123d import GeomType, Part, Vector
from OCP.BRepAdaptor import BRepAdaptor_Surface

from .shapes import Hole

CLASH_VOLUME = 1e-3  # mm^3; booleans of touching faces leave numerical slivers smaller than this
WALL_SAMPLES = 6000  # surface points probed per part, fixed seed
WALL_MESH_TOLERANCE = 0.02
PARALLEL = 0.9  # cosine: the exit face must be within about 25 degrees of parallel to the entry face
RAY_START = 1e-4
PROBE = 0.02  # mm from an edge or a face, for the inside/outside probes
PROBES_PER_EDGE = 8
HOLE_SEARCH = (0.0, 2.0)  # mm; range the metal round a hole is searched in
HOLE_STEPS = 7

Exempt = Callable[[Vector], bool]


def soundness(part: Part) -> dict:
    solids = len(part.solids())
    return {
        "solids": solids,
        "valid": bool(part.is_valid),
        "volume_mm3": round(part.volume, 2),
        "ok": solids == 1 and part.is_valid and part.volume > 0,
    }


def _boxes_overlap(first: Part, second: Part) -> bool:
    a, b = first.bounding_box(), second.bounding_box()
    return all(
        low_a < high_b and low_b < high_a
        for low_a, high_a, low_b, high_b in zip(a.min, a.max, b.min, b.max, strict=True)
    )


def overlap_volume(first: Part, second: Part) -> float:
    if not _boxes_overlap(first, second):
        return 0.0
    common = first & second
    return sum(solid.volume for solid in common.solids()) if common else 0.0


def clashes(parts: dict[str, Part], only: set[str] | None = None) -> tuple[int, list[dict]]:
    """Every pair (or every pair touching a name in `only`): bounding boxes first, then the common volume."""
    found, checked = [], 0
    for (name_a, part_a), (name_b, part_b) in combinations(parts.items(), 2):
        if only is not None and name_a not in only and name_b not in only:
            continue
        checked += 1
        volume = overlap_volume(part_a, part_b)
        if volume > CLASH_VOLUME:
            found.append({"parts": [name_a, name_b], "volume_mm3": round(volume, 3)})
    return checked, found


def clearance(first: Part, second: Part) -> float:
    return float(first.distance_to(second))


def mesh_of(part: Part, tolerance: float = WALL_MESH_TOLERANCE) -> trimesh.Trimesh:
    vertices, triangles = part.tessellate(tolerance, 0.2)
    mesh = trimesh.Trimesh([tuple(vertex) for vertex in vertices], triangles, process=True)
    mesh.fix_normals()
    return mesh


def thinnest_wall(part: Part, exempt: dict[str, Exempt]) -> dict:
    """Ray method: from surface points sampled by area, straight into the material along the inward
    normal, to where the ray leaves through a roughly parallel face. A sample can miss a very small
    thin spot. Samples inside a named exempt feature are measured separately."""
    mesh = mesh_of(part)
    points, source = trimesh.sample.sample_surface_even(mesh, WALL_SAMPLES, seed=0)
    inward = -mesh.face_normals[source]
    triangles, rays, hits = mesh.ray.intersects_id(
        points + inward * RAY_START, inward, multiple_hits=False, return_locations=True
    )
    distance = np.full(len(points), np.inf)
    parallel = (mesh.face_normals[triangles] * inward[rays]).sum(axis=1) > PARALLEL
    distance[rays[parallel]] = np.linalg.norm(hits[parallel] - points[rays[parallel]], axis=1) + RAY_START
    owner = np.array([next((name for name, test in exempt.items() if test(Vector(*point))), "") for point in points])
    result = {"samples": len(points)}
    for name in ["", *exempt]:
        chosen = (owner == name) & np.isfinite(distance)
        if not chosen.any():
            continue
        index = np.flatnonzero(chosen)[distance[chosen].argmin()]
        row = {"thinnest_mm": round(float(distance[index]), 3), "at": [round(float(c), 2) for c in points[index]]}
        if name:
            result.setdefault("exempt", {})[name] = row
        else:
            result.update(row)
    return result


def feature_gaps(cutters: dict[str, Part]) -> list[dict]:
    """Metal between every two cuts that do not meet, smallest first. Cuts that meet are one opening."""
    gaps = []
    for (name_a, cut_a), (name_b, cut_b) in combinations(cutters.items(), 2):
        distance = cut_a.distance_to(cut_b)
        if distance > 1e-6:
            gaps.append({"between": [name_a, name_b], "metal_mm": round(float(distance), 3)})
    return sorted(gaps, key=lambda gap: gap["metal_mm"])


def concave_corners(part: Part, exempt: dict[str, Exempt], features: dict[str, Part]) -> dict:
    """Inside corners a vertical end mill leaves: every concave vertical cylinder face that is not a
    full hole (radius, wall height, tool reach, which cut it belongs to), plus vertical edges with no
    radius at all."""
    mesh, extent = mesh_of(part), part.bounding_box()
    rounds, exempted = [], {}
    for face in part.faces().filter_by(GeomType.CYLINDER):
        axis = face.axis_of_rotation
        if abs(axis.direction.Z) < 0.999 or _is_full_turn(face):
            continue
        on_face = face.position_at(0.5, 0.5)
        toward_axis = Vector(axis.position.X - on_face.X, axis.position.Y - on_face.Y, 0).normalized()
        if part.is_inside(on_face + toward_axis * PROBE):
            continue  # material on the axis side: an outside corner
        name = _exempt_name(on_face, exempt)
        if name:
            exempted[name] = exempted.get(name, 0) + 1
            continue
        span = face.bounding_box()
        rounds.append(
            {
                "radius_mm": round(_radius(face), 3),
                "wall_mm": round(span.size.Z, 3),
                **_reach(
                    mesh,
                    (extent.min.Z, extent.max.Z),
                    (span.min.Z, span.max.Z),
                    on_face + toward_axis * (_radius(face) / 2),
                ),
                "feature": _owner(on_face, features),
            }
        )
    sharp = [edge for edge in _vertical_lines(part) if _is_internal(part, edge.position_at(0.5))]
    sharp_named = [edge for edge in sharp if not _exempt_name(edge.position_at(0.5), exempt)]
    for edge in sharp:
        name = _exempt_name(edge.position_at(0.5), exempt)
        if name:
            exempted[name] = exempted.get(name, 0) + 1
    return {
        "rounds": rounds,
        "sharp_edges": [[round(c, 2) for c in edge.position_at(0.5)] for edge in sharp_named],
        "exempt": exempted,
    }


def _reach(mesh: trimesh.Trimesh, part_z: tuple[float, float], corner_z: tuple[float, float], column: Vector) -> dict:
    """How far a vertical end mill must reach below the face it enters through to finish the corner:
    from the part's top face down to the corner's low end, or from its bottom face up to the corner's
    high end. A side counts only if the air column over the corner (at `column`) is open to it; nested
    pockets therefore add up. Both open: the shorter reach. Neither: no vertical tool gets there."""
    options = []
    if _column_open(mesh, column, 1.0):
        options.append((part_z[1] - corner_z[0], "top"))
    if _column_open(mesh, column, -1.0):
        options.append((corner_z[1] - part_z[0], "bottom"))
    if not options:
        return {"reach_mm": None, "from": "enclosed"}
    reach, side = min(options)
    return {"reach_mm": round(reach, 3), "from": side}


def _column_open(mesh: trimesh.Trimesh, point: Vector, direction: float) -> bool:
    return not bool(mesh.ray.intersects_any([tuple(point)], [(0.0, 0.0, direction)])[0])


def _exempt_name(point: Vector, exempt: dict[str, Exempt]) -> str:
    return next((name for name, test in exempt.items() if test(point)), "")


def _owner(point: Vector, features: dict[str, Part]) -> str:
    return min(features, key=lambda name: features[name].distance_to(point)) if features else ""


def _radius(face) -> float:
    """Cylinder radius, also for faces on a trimmed surface, where build123d's `radius` is None."""
    return BRepAdaptor_Surface(face.wrapped).Cylinder().Radius()


def _is_full_turn(face) -> bool:
    return abs(face.area - 2 * pi * _radius(face) * face.bounding_box().size.Z) < 1e-3 * face.area


def _vertical_lines(part: Part):
    for edge in part.edges().filter_by(GeomType.LINE):
        start, end = edge.position_at(0), edge.position_at(1)
        if edge.length > 0.05 and abs(start.X - end.X) < 1e-6 and abs(start.Y - end.Y) < 1e-6:
            yield edge


def _is_internal(part: Part, middle: Vector) -> bool:
    """On a small circle round the edge, most probes in material means an inside corner."""
    angles = (2 * pi * (step + 0.5) / PROBES_PER_EDGE for step in range(PROBES_PER_EDGE))
    inside = sum(part.is_inside(middle + Vector(PROBE * cos(a), PROBE * sin(a), 0)) for a in angles)
    return inside > PROBES_PER_EDGE * 0.6


def hole_metal(part: Part, hole: Hole) -> float:
    """Largest t (searched up to 2 mm) for which everything within t of the hole's metal envelope, along
    its guarded stretch, is material or the hole itself."""
    region = hole.body(HOLE_SEARCH[1] + 0.5, metal=True)
    local = part & region
    low, high = HOLE_SEARCH
    if _metal_holds(local, hole, high):
        return high
    for _ in range(HOLE_STEPS):
        middle = (low + high) / 2
        low, high = (middle, high) if _metal_holds(local, hole, middle) else (low, middle)
    return low


def _metal_holds(local: Part, hole: Hole, grow: float) -> bool:
    ring = (hole.body(grow, metal=True) & hole.guard_zone(200.0)) - hole.body(metal=True) - hole.body()
    missing = ring - local
    return sum(solid.volume for solid in missing.solids()) <= CLASH_VOLUME if missing else True
