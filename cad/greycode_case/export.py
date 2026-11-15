"""STEP and STL per made part, one assembly STEP with the reference parts. Every file is read back."""

from pathlib import Path

import trimesh
from build123d import Compound, Part, export_step, export_stl, import_step

from .assembly import CASE_PARTS, assembly, case_parts

STL_TOLERANCE = 0.01  # mm chord error
STL_VOLUME_SHARE = 0.005  # an STL may differ from the solid by this share of its volume


def export_all(folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    faults = 0
    for name, solid in case_parts().items():
        stem = folder / name.replace(" ", "_")
        solid.label = name
        export_step(solid, stem.with_suffix(".step"))
        _write_stl(solid, stem.with_suffix(".stl"))
        faults += _verify_step(stem.with_suffix(".step"), solid, 1) + _verify_stl(stem.with_suffix(".stl"), solid)
    pad = Compound(label="greycode", children=[_labelled(name, solid) for name, solid in assembly().items()])
    export_step(pad, folder / "assembly.step")
    faults += _verify_step(folder / "assembly.step", pad, len(pad.solids()))
    print(f"exported {len(CASE_PARTS)} parts and assembly.step to {folder}; {faults} faults reading them back")
    return 1 if faults else 0


def _write_stl(solid: Part, path: Path) -> None:
    """The mesher leaves zero-area triangles where a drill point ends in an apex, and a mesh with them
    is not watertight. They are dropped; the surface does not change."""
    export_stl(solid, path, tolerance=STL_TOLERANCE)
    mesh = trimesh.load_mesh(path)
    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.remove_unreferenced_vertices()
    mesh.export(path)


def _labelled(name: str, solid: Part) -> Part:
    solid.label = name
    return solid


def _verify_step(path: Path, original, solids: int) -> int:
    back = import_step(path)
    volume_error = abs(back.volume - original.volume) / original.volume
    ok = len(back.solids()) == solids and back.is_valid and volume_error < 1e-4
    print(f"  {path.name}: {len(back.solids())} solids, valid {back.is_valid}, volume off by {volume_error:.1e}")
    return 0 if ok else 1


def _verify_stl(path: Path, original: Part) -> int:
    mesh = trimesh.load_mesh(path)
    volume_error = abs(mesh.volume - original.volume) / original.volume
    ok = mesh.is_watertight and volume_error < STL_VOLUME_SHARE
    print(
        f"  {path.name}: {len(mesh.faces)} triangles, watertight {mesh.is_watertight}, volume off by {volume_error:.1e}"
    )
    return 0 if ok else 1
