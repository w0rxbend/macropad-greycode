# greycode configurator

A desktop editor for greyd's profiles: which app selects which layer, the profile colour, the nine
OLED labels and the HOST_0..HOST_7 commands. It edits `~/.config/greycode/config.toml`, the file
greyd already watches. Keymaps stay in Vial; the app has a button that starts it.

> **Status: the core and the UI logic are tested; the Tauri window has never been built or run.**
> `webkit2gtk-4.1` is not installed on the development machine, so `src-tauri/` stops at its
> `javascriptcore-rs-sys` build script. The UI was only looked at in a browser with a fake backend.
> No pad exists, so the pad lamp and the test alert have only been tested against a fake greyd.

## What it does

- Lists the `[[profile]]` entries in file order. Add, delete, move up and down.
- Edits name, apps, window titles, layer, colour (picker) and
  the nine labels (6 characters each), with a 128 x 64 preview drawn in the firmware's font and
  layout: header row with the name and layer, then three label rows.
- Warns when two profiles share a layer, counting the layers of `[[profile.state]]` blocks: a
  profile on the FreeCAD "Sketcher" state's layer shares that keymap in Vial. A state on its own
  profile's layer is not flagged.
- Edits each profile's HOST actions and the global ones, and `pause_apps`. Clearing the field
  removes the key, so greyd's default (pause while Vial is in front) applies again; an explicit
  `pause_apps = []` has to be written by hand.
- Shows whether greyd is running, whether it has the pad, and the app in front. "Add focused app"
  adds the last app id greyd reported that is not this window.
- Sends a test alert through greyd (`{"cmd":"alert",...}` on its control socket).
- "Open Vial" starts `vial` if it is on `PATH`.

## Saving is the hot reload

1. Every edit goes to the Rust core, which changes the parsed document with `toml_edit`. Comments,
   key order and keys the editor does not know (for example `[[profile.state]]`) stay as written.
   Moving a profile moves its nested tables and the comments above it.
2. Before saving, the text goes through greyd's own parser, `greyd::config::parse` (path dependency
   on `../host`). If greyd would reject it, Save is disabled and the footer says why.
3. If the file changed on disk since it was opened (say, in an editor), Save refuses; Reload reads
   it again.
4. Save writes a temp file in the same directory, fsyncs it, keeps the old file's permissions and
   renames it over the config. greyd sees the new modification time and reloads within a second.
   If `config.toml` is a symlink (stow, chezmoi in symlink mode), the file it points to is
   replaced and the link stays; a dangling link is an error, not a new file.
5. Ctrl+S and the Save button first commit the field being typed in, and every backend call runs
   in order, so the save includes it.

The validation uses greyd as built from this repository. A greyd binary installed from an older
checkout may still reject a field the source accepts; its log says so (`journalctl --user -u greyd`).

## Layout

| Path | What |
|---|---|
| `core/` | `greyconf` library: `document.rs` (toml_edit edits and the view), `session.rs` (open, validate, conflict check, save), `atomic.rs`, `client.rs` (greyd socket), `vial.rs`. No Tauri. |
| `src-tauri/` | Thin Tauri 2 shell: six commands over `greyconf` (`open`, `apply`, `save`, `status`, `alert`, `open_vial`) |
| `ui/` | Plain HTML, CSS and ES modules, no build step. `model.js` (OLED layout, raster, list helpers) has no DOM and is unit tested; `font.js` is the firmware's OLED font |

## Build

The core and the UI tests need only Rust and Node:

```bash
cd configurator/core && cargo test && cargo clippy --all-targets -- -D warnings && cargo fmt --check
cd configurator/ui && node --test test/
```

The window needs WebKitGTK 4.1. On Arch, `webkit2gtk-4.1` is the only package missing here (it
also provides `javascriptcoregtk-4.1`); Tauri's Arch list also names `base-devel`, `openssl`,
`librsvg` (present) and, for tray icons this app does not use, `libappindicator-gtk3`:

```bash
sudo pacman -S --needed webkit2gtk-4.1 base-devel openssl librsvg
cd configurator/src-tauri && cargo build --release
./target/release/greycode-configurator
```

`tauri.conf.json` turns bundling off and embeds `ui/` at compile time, so plain `cargo build`
works without the `tauri` CLI. Debian/Ubuntu: `libwebkit2gtk-4.1-dev build-essential libssl-dev
librsvg2-dev`. Resolved versions in `src-tauri/Cargo.lock`: tauri 2.12.5, wry 0.57.2.

## Status

| Part | State | Check |
|---|---|---|
| Core (`greyconf`) | 32 tests pass; clippy and rustfmt clean | `cargo test` in `core/` |
| UI logic | 9 tests pass (OLED layout and raster, list helpers, call ordering) | `node --test test/` in `ui/` |
| UI wiring (`app.js`) | **Not tested**: no DOM test harness; Ctrl+S commit relies on `blur()` firing `change` synchronously (HTML spec), not tried in WebKitGTK | - |
| Tauri shell | **Not built**: needs `webkit2gtk-4.1` | `cargo build` in `src-tauri/` |
| Real greyd, real pad | **Not tried** | - |

## Open points

- **Firmware OLED row 7.** `render_alert` in `firmware/greycode/greycode.c` writes an empty line
  before the alert, but the cursor is already on row 7 after the last label row. Reading QMK's
  `oled_advance_page`, the alert then wraps to row 0 and overwrites the header on every frame.
  The preview draws the intended layout. Needs a fix in `firmware/` and a check on hardware.
- **Font licence.** `ui/font.js` holds the printable glyphs of QMK's `drivers/oled/glcdfont.c`
  (GPL-2.0; the glyphs are the classic Adafruit GFX 5x7 font). Settle before giving the app away.
- Arrays the editor rewrites (`apps`, `labels`) come out on one line; a hand-wrapped array loses its
  wrapping. Comments next to the key are kept.
- No warning when the window closes with unsaved changes.
- `[[profile.state]]` entries are kept but not editable here.
- Removing `pause_apps` also drops the comment lines directly above it.
- Moving a profile keeps blank lines in place and carries the comments above each header with it.
  A comment that sits above a header but is about the table before it moves too.
