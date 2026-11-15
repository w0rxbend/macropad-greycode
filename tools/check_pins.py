#!/usr/bin/env python3
"""Fail if the QMK keyboard files disagree with board.toml."""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KB = ROOT / "firmware/greycode"


def gp(n: int) -> str:
    return f"GP{n}"


def main() -> int:
    board = tomllib.loads((ROOT / "board.toml").read_text())
    kb = json.loads((KB / "keyboard.json").read_text())
    config = (KB / "config.h").read_text()
    define = lambda name: re.search(rf"#define\s+{name}\s+(\S+)", config).group(1)  # noqa: E731

    keys, knob, disp, leds = board["keys"], board["knob"], board["display"], board["leds"]
    direct = kb["matrix_pins"]["direct"]
    enc = kb["encoder"]["rotary"][0]
    layout = kb["rgb_matrix"]["layout"]
    usb = board["board"]["usb"]
    host_hid_id = re.search(r'HID_ID: &str = "([^"]+)"', (ROOT / "host/src/device.rs").read_text()).group(1)
    expect = {
        "key GPIOs": ([gp(n) for n in keys["gpio"]], [p for row in direct[1:] for p in row]),
        "knob push": (gp(knob["gpio_push"]), direct[0][2]),
        "knob A/B": ((gp(knob["gpio_a"]), gp(knob["gpio_b"])), (enc["pin_a"], enc["pin_b"])),
        "knob resolution": (knob["pulses_per_detent"], enc["resolution"]),
        "OLED SDA/SCL": ((gp(disp["gpio_sda"]), gp(disp["gpio_scl"])), (define("I2C1_SDA_PIN"), define("I2C1_SCL_PIN"))),
        "OLED I2C bus": (f"I2CD{disp['i2c']}", define("I2C_DRIVER")),
        "LED data": (gp(leds["gpio_data"]), kb["ws2812"]["pin"]),
        "LED count": (leds["per_key"] + leds["edge"], len(layout)),
        "per-key LEDs first": (leds["per_key"], int(define("GREYCODE_EDGE_FIRST"))),
        "edge LEDs": (leds["edge"], int(define("GREYCODE_EDGE_COUNT"))),
        "USB IDs": ((usb["vid"], usb["pid"]), (int(kb["usb"]["vid"], 16), int(kb["usb"]["pid"], 16))),
        "greyd USB IDs": (f"HID_ID=0003:{usb['vid']:08X}:{usb['pid']:08X}", host_hid_id),
    }
    bad = [f"{what}: board.toml {want!r}, firmware {got!r}" for what, (want, got) in expect.items() if want != got]
    print("\n".join(bad) or f"check_pins: {len(expect)} checks match board.toml")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
