"""Tell greyd what FreeCAD is doing, so the greycode pad can switch to that state's layer.

No FreeCAD imports here: the FreeCAD side (greycode_freecad.py) passes in plain strings, so this
module runs and is tested without FreeCAD.
"""

import json
import os
import socket
import threading
import time

APP = "freecad"
POLL_MS = 500
# greyd forgets states when it restarts; resending now and then brings them back.
RESEND_S = 5.0
REPLY_TIMEOUT_S = 1.0
SKETCH_TYPE_PREFIX = "Sketcher::Sketch"
WORKBENCH_SUFFIX = "Workbench"


def socket_path():
    """greyd's control socket; the same rule as socket_path() in host/src/control.rs."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime is not None:
        return os.path.join(runtime, "greyd.sock")
    # Rust's std::env::temp_dir() on Unix: an empty TMPDIR stays empty (a relative socket path)
    temp = os.environ.get("TMPDIR", "/tmp")
    return os.path.join(temp, "greyd-%s.sock" % os.environ.get("USER", ""))


def state_for(workbench, editing_type):
    """The state to report: "Sketcher" while a sketch is open for editing, else the workbench
    without its suffix ("PartDesignWorkbench" -> "PartDesign"); None without a workbench."""
    if editing_type.startswith(SKETCH_TYPE_PREFIX):
        return "Sketcher"
    if workbench.endswith(WORKBENCH_SUFFIX):
        workbench = workbench[: -len(WORKBENCH_SUFFIX)]
    return workbench or None


def request_line(state):
    return (json.dumps({"cmd": "state", "app": APP, "state": state}) + "\n").encode()


def send_state(path, state, timeout=REPLY_TIMEOUT_S):
    """Send one state request; True when greyd accepted it. False when greyd is not running,
    is too slow or refuses: the pad is optional, FreeCAD carries on either way."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout)
            conn.connect(path)
            conn.sendall(request_line(state))
            with conn.makefile("rb") as replies:
                reply = json.loads(replies.readline())
        return isinstance(reply, dict) and reply.get("ok") is True
    except (OSError, ValueError):
        return False


class Reporter:
    """Sends the state when it changes and every RESEND_S, each time from a background thread,
    so the FreeCAD GUI never waits on greyd. One request at a time."""

    def __init__(self, send, clock=time.monotonic):
        self._send = send
        self._clock = clock
        self._last = None
        self._sent_at = None
        self.thread = None

    def update(self, state):
        now = self._clock()
        if self.thread is not None and self.thread.is_alive():
            return
        fresh = self._sent_at is not None and now - self._sent_at < RESEND_S
        if state == self._last and fresh:
            return
        self._last, self._sent_at = state, now
        self.thread = threading.Thread(target=self._send, args=(state,), daemon=True)
        self.thread.start()
