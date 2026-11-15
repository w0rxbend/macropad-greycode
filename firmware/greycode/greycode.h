#pragma once

#include "quantum.h"

// HOST(n) keys: the pad tells greyd, greyd runs the focused profile's action n.
// Order must match customKeycodes in keymaps/vial/vial.json.
enum greycode_keycodes {
	HOST_0 = QK_KB_0,
	HOST_1,
	HOST_2,
	HOST_3,
	HOST_4,
	HOST_5,
	HOST_6,
	HOST_7,
	// FreeCAD Sketcher two-key shortcuts (FreeCAD 1.x defaults, a guess: check
	// Tools > Customize > Keyboard)
	SK_LINE,
	SK_CIRCLE,
	SK_RECT,
	SK_CONSTR,
	HOST_LAST = HOST_7,
};
