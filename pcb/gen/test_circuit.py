"""circuit.py against board.toml and the firmware. Plain Python, no KiCad.

    python3 -m unittest discover -s pcb/gen -p 'test_*.py'

The routed board itself is checked against board.toml by `build.py contract` (needs KiCad).
"""

from __future__ import annotations

import json
import math
import tomllib
import unittest

import circuit

SPEC = tomllib.loads((circuit.REPO_ROOT / "board.toml").read_text())
KEYBOARD = json.loads((circuit.REPO_ROOT / "firmware" / "greycode" / "keyboard.json").read_text())


def _parts() -> dict[str, circuit.Part]:
    return {part.ref: part for part in circuit.all_parts()}


def _mcu_net(gpio: int) -> str:
    return _parts()["U1"].nets[str(circuit.gpio_pin(gpio))]


class GpioTest(unittest.TestCase):
    def test_each_key_socket_is_on_its_gpio_and_ground(self) -> None:
        parts = _parts()
        for index, gpio in enumerate(SPEC["keys"]["gpio"]):
            socket = parts[f"SW{index + 1}"]
            self.assertEqual(socket.nets["1"], _mcu_net(gpio), f"key {index}")
            self.assertEqual(socket.nets["2"], circuit.GND)

    def test_knob_pins_are_on_their_gpios(self) -> None:
        encoder, knob = _parts()["ENC1"], SPEC["knob"]
        self.assertEqual(encoder.nets["A"], _mcu_net(knob["gpio_a"]))
        self.assertEqual(encoder.nets["B"], _mcu_net(knob["gpio_b"]))
        self.assertEqual(encoder.nets["S1"], _mcu_net(knob["gpio_push"]))
        self.assertEqual({encoder.nets[pin] for pin in ("C", "S2")}, {circuit.GND})

    def test_display_header_carries_i2c_power_and_pull_ups(self) -> None:
        parts, display = _parts(), SPEC["display"]
        sda, scl = _mcu_net(display["gpio_sda"]), _mcu_net(display["gpio_scl"])
        # The brief's order GND, VCC, SCL, SDA on pads 1 to 4 (MEASURE against the module).
        header = [parts["J2"].nets[str(pad)] for pad in range(1, 5)]
        self.assertEqual(header, [circuit.GND, circuit.V3, scl, sda])
        pulled_up = {part.nets["1"] for part in parts.values() if part.value == "4.7k" and part.nets["2"] == circuit.V3}
        self.assertEqual(pulled_up, {sda, scl})

    def test_led_data_goes_through_the_level_shifter_to_the_first_led(self) -> None:
        parts = _parts()
        shifter = parts["U4"]
        self.assertEqual(shifter.nets["3"], _mcu_net(SPEC["leds"]["gpio_data"]))
        self.assertEqual((shifter.nets["1"], shifter.nets["5"], shifter.nets["6"]), (circuit.V3, circuit.V3, circuit.V5))
        self.assertEqual(parts["R9"].nets["1"], shifter.nets["4"])
        self.assertEqual(parts["LED1"].nets["4"], parts["R9"].nets["2"])

    def test_no_gpio_is_used_twice_and_the_rest_stay_open(self) -> None:
        used = [*SPEC["keys"]["gpio"], *(SPEC["knob"][k] for k in ("gpio_a", "gpio_b", "gpio_push")),
                SPEC["display"]["gpio_sda"], SPEC["display"]["gpio_scl"], SPEC["leds"]["gpio_data"]]
        self.assertEqual(len(used), len(set(used)))
        mcu = _parts()["U1"]
        for gpio in range(30):
            pin = str(circuit.gpio_pin(gpio))
            self.assertEqual(pin in mcu.nets, gpio in used, f"GPIO{gpio}")


class PlacementTest(unittest.TestCase):
    def test_keys_knob_and_usb_sit_where_board_toml_says(self) -> None:
        parts, pcb = _parts(), SPEC["pcb"]
        for index in range(len(SPEC["keys"]["gpio"])):
            row, column = divmod(index, len(pcb["key_x"]))
            socket = parts[f"SW{index + 1}"]
            self.assertEqual((socket.x, socket.y), (pcb["key_x"][column], pcb["depth"] - pcb["key_y"][row]))
        encoder = parts["ENC1"]
        dx, dy = circuit.ENCODER_SHAFT_OFFSET
        self.assertEqual((encoder.x + dx, encoder.y + dy), (pcb["knob"][0], pcb["depth"] - pcb["knob"][1]))
        self.assertEqual(parts["J1"].x, pcb["usb_x"])

    def test_holes_are_board_toml_holes_and_no_part_centre_is_in_a_keep_out(self) -> None:
        pcb = SPEC["pcb"]
        holes = [(part.x, part.y) for part in circuit.all_parts() if part.footprint_key == "HOLE_M2"]
        self.assertEqual(sorted(holes), sorted((x, pcb["depth"] - y) for x, y in pcb["holes"]))
        for part in circuit.all_parts():
            if part.footprint_key == "HOLE_M2":
                continue
            for hole in holes:
                self.assertGreater(math.dist((part.x, part.y), hole), pcb["hole_keepout_diameter"] / 2, part.ref)

    def test_every_part_is_on_the_board(self) -> None:
        pcb = SPEC["pcb"]
        for part in circuit.all_parts():
            self.assertTrue(0 < part.x < pcb["width"] and 0 < part.y < pcb["depth"], part.ref)


class FirmwareOrderTest(unittest.TestCase):
    def test_led_chain_follows_the_firmware_layout(self) -> None:
        """keyboard.json lists the per-key LEDs row by row from the top-left, then the edge LEDs left to right.
        The chain on the board must run in the same order, or the firmware lights the wrong LED."""
        layout = KEYBOARD["rgb_matrix"]["layout"]
        parts = _parts()
        per_key, edge = SPEC["leds"]["per_key"], SPEC["leds"]["edge"]
        self.assertEqual(len(layout), per_key + edge)
        columns = len(SPEC["pcb"]["key_x"])
        for index in range(per_key):
            row, column = layout[index]["matrix"]
            self.assertEqual((row - 1) * columns + column, index, f"firmware LED {index}")
            led_x, _ = circuit.key_centre(index)
            self.assertEqual(parts[f"LED{index + 1}"].x, led_x)
        edge_firmware_x = [entry["x"] for entry in layout[per_key:]]
        self.assertEqual(edge_firmware_x, sorted(edge_firmware_x))
        edge_board_x = [parts[f"LED{per_key + n + 1}"].x for n in range(edge)]
        self.assertEqual(edge_board_x, sorted(edge_board_x))
        for n in range(per_key + edge - 1):
            self.assertEqual(parts[f"LED{n + 1}"].nets[_dout(parts[f"LED{n + 1}"])],
                             parts[f"LED{n + 2}"].nets[_din(parts[f"LED{n + 2}"])], f"LED{n + 1} to LED{n + 2}")


def _dout(led: circuit.Part) -> str:
    return "2" if led.value == "SK6812MINI-E" else "3"


def _din(led: circuit.Part) -> str:
    return "4" if led.value == "SK6812MINI-E" else "1"


class SourcingTest(unittest.TestCase):
    def test_every_part_has_a_jlcpcb_number_and_a_manufacturer_part(self) -> None:
        circuit.check_sourcing(circuit.all_parts())

    def test_every_net_has_two_pads(self) -> None:
        circuit.check_netlist(circuit.all_parts())


if __name__ == "__main__":
    unittest.main()
