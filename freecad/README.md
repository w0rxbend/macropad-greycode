# GreycodeBridge (FreeCAD add-on)

Tells `greyd` what FreeCAD is doing, so the pad follows it: the Sketcher layer while a sketch is
open, the FreeCAD profile otherwise.

> **Not yet run inside FreeCAD.** FreeCAD is not installed where this was written. The logic in
> `greycode_bridge.py` is unit-tested against a fake greyd socket and was sent to a real greyd
> once; `greycode_freecad.py` and `InitGui.py` (the parts that touch FreeCAD) have only been
> byte-compiled.

## What it sends

Every 500 ms it reads the active workbench and whether a sketch is in edit mode, and sends greyd
`{"cmd":"state","app":"freecad","state":"..."}` when that changes, and again every 5 s so a
restarted greyd catches up:

| FreeCAD | `state` |
|---|---|
| A sketch open for editing (any workbench) | `Sketcher` |
| Otherwise, the active workbench without "Workbench" | `PartDesign`, `Part`, `TechDraw`, `Sketcher`, ... |

greyd applies the state only while FreeCAD is in front and only if the FreeCAD profile has a
`[[profile.state]]` of that name; see [`host/config.example.toml`](../host/config.example.toml).

Each request runs on its own background thread with a 1 s timeout, so the GUI never waits. When
greyd is not running the add-on stays silent. Plain Python and FreeCAD's own PySide; nothing to
install.

## Install

Link (or copy) `GreycodeBridge` into FreeCAD's user `Mod` folder and restart FreeCAD:

| FreeCAD on Linux | User `Mod` folder |
|---|---|
| 1.0 | `~/.local/share/FreeCAD/Mod` |
| 1.1 | `~/.local/share/FreeCAD/v1-1/Mod` (guess: 1.1 keeps user data per version; not checked here) |

```bash
mod=~/.local/share/FreeCAD/Mod   # FreeCAD 1.0; use the 1.1 row above for 1.1
mkdir -p "$mod"
ln -s "$PWD/freecad/GreycodeBridge" "$mod/GreycodeBridge"
```

Flatpak and Snap builds keep their own folder. To be sure, type this in FreeCAD's Python console
and use its `Mod` subfolder:

```python
App.getUserAppDataDir()
```

Check it works: with greyd running, open a sketch, then `greyctl status` shows
`"app_states": {"freecad": "Sketcher"}`. FreeCAD's report view logs the socket path at log level
(View > Panels > Report view; enable log messages in its context menu).

## Test

```bash
python3 -B -m unittest discover -s freecad/tests
```

## Files

| File | Imports FreeCAD | Does |
|---|---|---|
| `GreycodeBridge/InitGui.py` | via the next file | Starts the poller at GUI start |
| `GreycodeBridge/greycode_freecad.py` | yes | Qt timer, reads workbench and edit mode |
| `GreycodeBridge/greycode_bridge.py` | no | Socket path, state rule, request, throttling |
| `tests/test_greycode_bridge.py` | no | unittest against a fake greyd |
