"""The whole pad, case parts and reference parts, at rest or with every key and the knob pressed."""

from functools import cache

from build123d import Part, Pos

from . import parts, reference
from .spec import EC11_PUSH, key_centres

CASE_PARTS = ("top", "base", "knob", "light strip", "lens")


@cache
def case_parts() -> dict[str, Part]:
    built = parts.built_parts()
    return {
        "top": built["top"].solid,
        "base": built["base"].solid,
        "knob": built["knob"].solid,
        "light strip": parts.light_strip(),
        "lens": parts.lens(),
    }


@cache
def _static_references() -> dict[str, Part]:
    return reference.static_parts()


def assembly(pressed: bool = False) -> dict[str, Part]:
    solids = dict(case_parts())
    if pressed:
        solids["knob"] = Pos(0, 0, -EC11_PUSH) * solids["knob"]
    return solids | _static_references() | reference.moving_parts(pressed)


MOVING = {"knob", "encoder shaft", *(f"keycap {index + 1}" for index in range(len(key_centres())))}
