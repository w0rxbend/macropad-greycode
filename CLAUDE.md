# CLAUDE.md

Guidance for Claude Code in this repository.

## What this is

A 3 x 3 + knob + OLED macropad. RP2040, QMK/Vial firmware, and `greyd`, a Rust daemon that switches
the pad's layer to the focused app's profile, shows labels and alerts, and runs HOST key actions.
Nothing has been built; every document says so where it matters.

- `board.toml` is the single source of truth for pins and parts. `tools/check_pins.py` holds the
  firmware and greyd to it. The PCB and case (not started) must read it too.
- `firmware/greycode/` is a QMK keyboard directory, symlinked into `.build/vial-qmk` (pinned commit in
  `justfile`). `hostlink.c` is pure C with no QMK headers; keep it that way so `just test-firmware`
  runs natively.
- `host/` is the `greyd` crate. `bridge.rs` holds the rules and does no I/O; keep logic there.
- The wire format is `docs/protocol.md`. Change a frame: update `hostlink.c`, `protocol.rs`,
  `firmware/test/vectors.txt` and the doc together.
- `pcb/gen/` generates the KiCad project (Docker `kicad/kicad:9.0.9`); everything in `pcb/kicad/`,
  `pcb/fab/` and `docs/images/pcb/` is generated. `cad/` is the build123d case; `cad/exports/` and
  `docs/images/cad/` are generated. Change a `board.toml` [pcb] or [case] value, then run
  `just pcb cad firmware` and keep every check green.
- `configurator/` edits greyd's TOML through `toml_edit` and validates with `greyd::config::parse`;
  keep that signature, `control::socket_path` and `control::call` stable.
- `freecad/` is the FreeCAD add-on; its logic module must not import FreeCAD.

## Commands

```bash
just test        # C tests (ASan/UBSan), greyd tests + clippy + fmt, pin check
just firmware    # UF2 into firmware/dist/ (Docker, ghcr.io/qmk/qmk_cli)
just host-run    # greyd with host/config.example.toml
just cad         # case checks, exports, renders
just pcb         # board, DRC, contract, order files (Docker)
```

## Rules

- Never weaken a check or a test to get green. Add a check for what you add.
- Status numbers in `README.md` come from command output; update them in the same change.
- Label every guess as a guess; keep `MEASURE` tags until someone measures.
