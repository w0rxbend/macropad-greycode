# Host link protocol

How `greyd` on the PC and the firmware on the pad talk. Version 1.

The pad has one raw HID interface: the one VIA and Vial use (usage page `0xFF60`, usage `0x61`,
32-byte reports, no report IDs). Vial's own commands start with `0x01`-`0x15` or `0xFE`.
Every host-link frame starts with `0xC7`, which VIA hands to the keyboard code
(`raw_hid_receive_kb` in `firmware/greycode/greycode.c`).

Code: `firmware/greycode/hostlink.c` (pad) and `host/src/protocol.rs` (PC). Both are tested
against the same frames in [`firmware/test/vectors.txt`](../firmware/test/vectors.txt).

## Frames

Byte 0 is `0xC7`, byte 1 the command. Unused bytes are zero. Text is printable ASCII,
zero-padded; the pad turns any other byte into `?`.

| Cmd | Name | Bytes 2.. |
|---|---|---|
| `0x01` | HELLO | `[2]` host protocol version |
| `0x02` | HEARTBEAT | - |
| `0x03` | PROFILE | `[2]` layer (`0xFF` = none, base layer), `[3..5]` accent RGB, `[6..21]` name (16) |
| `0x04` | LABEL | `[2]` key 0-8, `[3..8]` label (6) |
| `0x05` | ALERT | `[2]` level (0 clear, 1 info, 2 ok, 3 warn, 4 error), `[3]` pattern (0 solid, 1 pulse, 2 blink), `[4..6]` RGB (all 0 = level colour), `[7..8]` timeout s, little-endian (0 = until cleared), `[9..28]` text (20) |
| `0x06` | KEY_LEDS | `[2..3]` key mask, little-endian (bit n = key n, row by row), `[4]` 1 set / 0 give back to the RGB effect, `[5..7]` RGB |

## Replies

VIA sends every frame back. The pad overwrites bytes 2.. with the reply:

- `[2]` status: `0` ok, `1` unknown command, `2` bad argument (layer not on the pad, key index > 8, level or pattern out of range).
- HELLO also fills `[3]` pad protocol version, `[4]` layer count, `[5]` key count.

## Events from the pad

| Byte 1 | Name | Bytes 2.. |
|---|---|---|
| `0x81` | HOST_KEY | `[2]` n (HOST_0..HOST_7), `[3]` 1 pressed / 0 released |

## Rules

- **Liveness.** The pad drops the host after 5 s without a frame: base layer, no labels, no alert,
  no key colours. greyd sends HEARTBEAT every second.
- **PROFILE resets** the labels and the key colours. Send LABEL frames after it.
- **Layers.** The profile layer becomes QMK's default layer. FN is layer 15 and momentary, so it stays
  on top. `KC_TRNS` in a profile falls through to layer 0. Layers 1-14 are for profiles.
- **Vial in front.** greyd sends nothing while a `pause_apps` window has focus, so replies do not
  reach Vial while it talks to the pad. The pad times out and shows its base layer.
- **Brightness.** Key and edge colours are scaled by the RGB matrix brightness. With RGB off, the host
  colours do not show either.

## Colours

| Level | Default RGB | Default pattern (greyctl) |
|---|---|---|
| info | `#0078ff` | solid |
| ok | `#00c83c` | solid |
| warn | `#ff8c00` | solid |
| error | `#ff0000` | blink |

Pulse is a 1 s triangle; blink is 500 ms on, 500 ms off.

## App states (host side only)

`{"cmd":"state","app":"freecad","state":"Sketcher"}` on greyd's control socket stores what an app is
doing; `"state": null` or no `state` clears it, an empty `app` is refused, and it works without a pad.
greyd keeps one state per app, in memory only. While a window whose app id contains `app`
(case-insensitive) is in front and its profile has a `[[profile.state]]` of exactly that name, the
state's layer, labels and colour replace the profile's. They reach the pad as ordinary PROFILE and
LABEL frames: the pad protocol does not change. `{"cmd":"status"}` also returns `state` and
`app_states`. The FreeCAD add-on in `freecad/` sends these.
