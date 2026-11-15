# greyd

Linux daemon for the greycode pad. It watches which window has focus (sway, Hyprland or X11),
switches the pad to that app's layer, shows labels on its OLED, lights alerts and runs commands for
HOST keys. Apps can report what they are doing (FreeCAD: workbench, open sketch) to pick a
sub-state of their profile. `greyctl` talks to it.

> Not yet run against a pad: no hardware exists. The daemon runs, reads focus from sway, and its
> frames match the firmware's test vectors. The Hyprland backend has never run against Hyprland.
> The X11 backend ran once against XWayland under sway: it read `_NET_ACTIVE_WINDOW`, which named a
> window without `WM_CLASS` (a native Wayland window was in front), so it reported no app. It has
> not yet been seen following a focus change between X11 windows. The Hyprland reader was run
> against fake Hyprland sockets only (including a title that is not UTF-8).

## Focus backends

greyd picks one at start and logs it (`greyd: focus from ...`):

| Set in the environment | Backend | Source |
|---|---|---|
| `SWAYSOCK` | sway (and i3 IPC) | GET_TREE, then window events |
| `HYPRLAND_INSTANCE_SIGNATURE` (+ `XDG_RUNTIME_DIR`) | Hyprland | `j/activewindow` on `.socket.sock`, then `activewindow>>class,title` on `.socket2.sock` under `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/` |
| `DISPLAY` | X11 | `_NET_ACTIVE_WINDOW` on the root window, then `WM_CLASS` and `_NET_WM_NAME` of that window, following PropertyNotify |

sway and Hyprland come first because they also set `DISPLAY` for XWayland, which sees only X11
windows. On X11 the app is the `WM_CLASS` class (`FreeCAD`, `firefox`). Titles that are not UTF-8
are decoded lossily on every backend. A backend that fails is retried every 5 s.

No KDE or GNOME Wayland backend yet. There greyd falls back to X11 through XWayland and logs
`greyd: warning: WAYLAND_DISPLAY is set but greyd has no backend for this compositor ...`:
profiles then follow X11 apps only, never native Wayland windows.

## Install

```bash
just host-install                          # greyd and greyctl into ~/.cargo/bin
mkdir -p ~/.config/greycode
cp host/config.example.toml ~/.config/greycode/config.toml
sudo cp host/udev/70-greycode.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
cp host/systemd/greyd.service ~/.config/systemd/user/
systemctl --user enable --now greyd
```

The udev rule also lets Vial open the pad without root.

## Configure

Edit `~/.config/greycode/config.toml`; greyd reloads it within a second of saving. A broken file is
reported in the log (`journalctl --user -u greyd`) and the last good one stays active.
See [`config.example.toml`](config.example.toml) for every field.

Find an app's id: focus it, then run `greyctl status`.

The FreeCAD `Sketcher` state in the example selects layer 4, the stock firmware's SKETCHER layer
(line, circle, rectangle / coincident, horizontal, vertical / dimension, construction, Esc).

### App states

A profile can have sub-states that replace its layer, labels and colour while the app in front
reports that state:

```toml
[[profile.state]]
name = "Sketcher"          # matched exactly
layer = 4                  # required, 1-14
labels = ["Line", "Circle"] # optional, default none
color = "#ff8800"          # optional, default the profile's
```

An app reports with `greyctl state freecad Sketcher` (or the control socket request below); the
FreeCAD add-on in [`../freecad/`](../freecad/README.md) does it by itself. greyd keeps the last state
of each app. It applies while a window whose app id contains that app name (case-insensitive, like
`apps`) is in front and its profile defines a state of that name; the OLED then shows the state's
name. Otherwise the profile shows as usual. A pause app still wins. States live in memory: a restarted greyd knows none until apps report
again (the FreeCAD add-on resends every 5 s).

## greyctl

```bash
greyctl status                                    # pad, focused app, active profile
greyctl alert warn "Build failed" --timeout 30    # edge light + OLED text
greyctl alert error "Prod down" --pulse
greyctl clear
greyctl keys 0,4,8 '#00ff00'                      # colour keys (0-8, row by row)
greyctl keys 0,4,8 off
greyctl state freecad Sketcher                    # FreeCAD reports a state (the add-on does this)
greyctl state freecad --clear
```

Example: `make || greyctl alert error "make failed" --timeout 60`.

## Control socket

`$XDG_RUNTIME_DIR/greyd.sock`, else `$TMPDIR/greyd-$USER.sock` (`/tmp` without `TMPDIR`). One JSON
request per line, one JSON reply per line: `{"ok":true}`, with `"status"` for `status`, or
`{"ok":false,"error":"..."}`.

| Request | Does |
|---|---|
| `{"cmd":"status"}` | Pad, focused app and title, profile, active `state`, reported `app_states` |
| `{"cmd":"alert","level":"warn","text":"...","timeout":30,"color":"#rrggbb","pattern":"pulse"}` | Edge light and OLED text; only `level` is required |
| `{"cmd":"clear"}` | Clear the alert |
| `{"cmd":"keys","keys":[0,4,8],"color":"#00ff00"}` | Colour keys; no `color` gives them back to the RGB effect |
| `{"cmd":"state","app":"freecad","state":"Sketcher"}` | Store an app's state; `"state":null` or no `state` clears it. Works without a pad; an empty `app` is refused |

## Develop

```bash
just test-host       # unit tests, clippy, rustfmt
just host-run        # greyd with config.example.toml
```

Layout: `protocol.rs` (frames), `bridge.rs` (what to send, no I/O), `config.rs`, `focus.rs`
(backend choice; `focus/sway.rs`, `focus/hyprland.rs`, `focus/x11.rs`), `device.rs` (hidraw),
`control.rs` (socket requests), `daemon.rs` (threads and the main loop).

Dependency: `x11rb` for the X11 backend (pure Rust, no default features, no libxcb; brings
`x11rb-protocol`, `rustix`, `gethostname`). It is the maintained X11 binding the Rust ecosystem
uses; hand-written X11 wire code would be more code to get wrong.
Protocol: [docs/protocol.md](../docs/protocol.md).
