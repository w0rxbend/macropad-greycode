"""FreeCAD side of the bridge: polls the active workbench and sketch edit mode on a Qt timer.

Polling covers both workbench switches and entering or leaving a sketch with one code path;
it costs one cheap lookup every POLL_MS.
"""

import functools

import FreeCAD
import FreeCADGui
from PySide import QtCore

import greycode_bridge

_timer = None  # module global: the timer must outlive InitGui.py


def current_state():
    workbench = FreeCADGui.activeWorkbench()
    document = FreeCADGui.ActiveDocument
    in_edit = document.getInEdit() if document else None
    editing = getattr(getattr(in_edit, "Object", None), "TypeId", "")
    return greycode_bridge.state_for(workbench.name() if workbench else "", editing)


def start():
    global _timer
    if _timer is not None:
        return
    path = greycode_bridge.socket_path()
    reporter = greycode_bridge.Reporter(functools.partial(greycode_bridge.send_state, path))
    _timer = QtCore.QTimer()
    _timer.timeout.connect(lambda: reporter.update(current_state()))
    _timer.start(greycode_bridge.POLL_MS)
    FreeCAD.Console.PrintLog("GreycodeBridge: reporting to %s\n" % path)
