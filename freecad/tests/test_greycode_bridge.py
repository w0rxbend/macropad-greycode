"""Tests for greycode_bridge against a fake greyd socket. Run: python3 -m unittest discover -s freecad/tests"""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "GreycodeBridge"))

import greycode_bridge as bridge  # noqa: E402


class FakeGreyd:
    """Accepts one connection at a time, records each request line and answers `reply` (None: never answers)."""

    def __init__(self, path, reply=b'{"ok":true}\n'):
        self.requests = []
        self.reply = reply
        self.done = threading.Event()  # set to let a silent server close its connection
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn, conn.makefile("rb") as lines:
                self.requests.append(json.loads(lines.readline()))
                if self.reply is None:
                    self.done.wait(5)
                else:
                    conn.sendall(self.reply)

    def close(self):
        self.done.set()
        self.server.close()


class SocketTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()  # short path: unix socket paths are limited to 108 bytes
        self.path = os.path.join(self.dir, "greyd.sock")
        self.addCleanup(shutil.rmtree, self.dir)

    def greyd(self, **kwargs):
        server = FakeGreyd(self.path, **kwargs)
        self.addCleanup(server.close)
        return server


class SocketPathTest(unittest.TestCase):
    def test_runtime_dir(self):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": "/run/user/1000"}):
            self.assertEqual(bridge.socket_path(), "/run/user/1000/greyd.sock")

    def test_temp_dir_fallback(self):
        env = {k: v for k, v in os.environ.items() if k not in ("XDG_RUNTIME_DIR", "TMPDIR")}
        with mock.patch.dict(os.environ, dict(env, USER="ada"), clear=True):
            self.assertEqual(bridge.socket_path(), "/tmp/greyd-ada.sock")
        with mock.patch.dict(os.environ, dict(env, USER="ada", TMPDIR="/var/tmp"), clear=True):
            self.assertEqual(bridge.socket_path(), "/var/tmp/greyd-ada.sock")
        # empty TMPDIR: Rust's temp_dir() returns "", so greyd binds a relative path; match it
        with mock.patch.dict(os.environ, dict(env, USER="ada", TMPDIR=""), clear=True):
            self.assertEqual(bridge.socket_path(), "greyd-ada.sock")


class StateForTest(unittest.TestCase):
    def test_workbench_names(self):
        self.assertEqual(bridge.state_for("PartDesignWorkbench", ""), "PartDesign")
        self.assertEqual(bridge.state_for("TechDrawWorkbench", ""), "TechDraw")
        self.assertEqual(bridge.state_for("SketcherWorkbench", ""), "Sketcher")
        self.assertIsNone(bridge.state_for("", ""))

    def test_open_sketch_wins_over_workbench(self):
        self.assertEqual(bridge.state_for("PartDesignWorkbench", "Sketcher::SketchObject"), "Sketcher")
        self.assertEqual(bridge.state_for("PartDesignWorkbench", "PartDesign::Pad"), "PartDesign")


class SendStateTest(SocketTest):
    def test_sends_one_request_line(self):
        server = self.greyd()
        self.assertTrue(bridge.send_state(self.path, "Sketcher"))
        self.assertTrue(bridge.send_state(self.path, None))
        self.assertEqual(
            server.requests,
            [
                {"cmd": "state", "app": "freecad", "state": "Sketcher"},
                {"cmd": "state", "app": "freecad", "state": None},
            ],
        )

    def test_refused_or_garbled_reply_is_false(self):
        server = self.greyd(reply=b'{"ok":false,"error":"no"}\n')
        self.assertFalse(bridge.send_state(self.path, "Part"))
        server.reply = b"not json\n"
        self.assertFalse(bridge.send_state(self.path, "Part"))
        server.reply = b"[]\n"  # valid JSON, not an object: something other than greyd
        self.assertFalse(bridge.send_state(self.path, "Part"))

    def test_no_greyd_is_false(self):
        self.assertFalse(bridge.send_state(self.path, "Part"))

    def test_silent_greyd_times_out(self):
        self.greyd(reply=None)
        self.assertFalse(bridge.send_state(self.path, "Part", timeout=0.2))


class ReporterTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.sent = []
        self.reporter = bridge.Reporter(self.sent.append, clock=lambda: self.now)

    def update(self, state):
        self.reporter.update(state)
        if self.reporter.thread is not None:
            self.reporter.thread.join(5)

    def test_sends_on_change_and_resends_after_a_while(self):
        self.update("PartDesign")
        self.now = 1.0
        self.update("PartDesign")
        self.update("Sketcher")
        self.now = 1.0 + bridge.RESEND_S
        self.update("Sketcher")
        self.assertEqual(self.sent, ["PartDesign", "Sketcher", "Sketcher"])

    def test_skips_while_a_request_is_in_flight(self):
        release = threading.Event()
        reporter = bridge.Reporter(lambda state: release.wait(5), clock=lambda: self.now)
        reporter.update("Part")
        first = reporter.thread
        reporter.update("Sketcher")
        self.assertIs(reporter.thread, first)
        release.set()
        first.join(5)
        reporter.update("Sketcher")
        self.assertIsNot(reporter.thread, first, "the change goes out on the next poll")
        reporter.thread.join(5)


class EndToEndTest(SocketTest):
    def test_reporter_reaches_greyd(self):
        server = self.greyd()
        reporter = bridge.Reporter(lambda state: bridge.send_state(self.path, state))
        reporter.update("Sketcher")
        reporter.thread.join(5)
        self.assertEqual(server.requests, [{"cmd": "state", "app": "freecad", "state": "Sketcher"}])


if __name__ == "__main__":
    unittest.main()
