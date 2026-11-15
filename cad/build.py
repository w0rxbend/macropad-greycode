"""Build the greycode case: `python cad/build.py check | export | render | all`."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from greycode_case import checks, export, render  # noqa: E402

EXPORTS = Path(__file__).resolve().parent / "exports"
IMAGES = Path(__file__).resolve().parents[1] / "docs" / "images" / "cad"


def check() -> int:
    report = checks.run_all()
    EXPORTS.mkdir(exist_ok=True)
    (EXPORTS / "checks.json").write_text(json.dumps(report, indent=2) + "\n")
    print(checks.summary(report))
    problems = checks.failures(report)
    for problem in problems:
        print(f"FAIL {problem}")
    return 1 if problems else 0


COMMANDS = {
    "check": check,
    "export": lambda: export.export_all(EXPORTS),
    "render": lambda: render.render_all(IMAGES),
}


def main(arguments: list[str]) -> int:
    command = arguments[0] if arguments else "all"
    if command == "all":
        return max(run() for run in COMMANDS.values())
    if command not in COMMANDS:
        print(f"usage: build.py [{' | '.join([*COMMANDS, 'all'])}]", file=sys.stderr)
        return 2
    return COMMANDS[command]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
