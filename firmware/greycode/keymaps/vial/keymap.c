// Stock keymap. Vial edits it live and stores it on the pad; this file is the
// state after a reset. Layer N is the app profile greyd selects with layer = N.
#include QMK_KEYBOARD_H

enum layers {
	BASE = 0,
	FREECAD = 1,
	KICAD = 2,
	BROWSER = 3,
	SKETCHER = 4, // greyd selects it for FreeCAD while a sketch is open
	FN = 15,
};

#define KNOB LT(FN, KC_MUTE) // tap: mute, hold: FN
#define FREE_LAYER                                                             \
	LAYOUT(_______, _______, _______, _______, _______, _______, _______,  \
	       _______, _______, _______)

// clang-format off
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
	[BASE] = LAYOUT(
		                          KNOB,
		KC_MPRV,    KC_MPLY,    KC_MNXT,
		C(KC_C),    C(KC_V),    C(KC_Z),
		HOST_0,     HOST_1,     HOST_2
	),
	// FreeCAD 1.x defaults: 0 isometric, 1 front, 2 top, 3 right; Space toggles visibility
	[FREECAD] = LAYOUT(
		                          _______,
		KC_0,       KC_1,       KC_3,
		KC_2,       KC_SPC,     KC_DEL,
		C(KC_Z),    C(KC_Y),    KC_ESC
	),
	// KiCad 9 PCB editor: route, drag, move / rotate, via, properties / fill zones
	[KICAD] = LAYOUT(
		                          _______,
		KC_X,       KC_D,       KC_M,
		KC_R,       KC_V,       KC_E,
		KC_B,       KC_DEL,     KC_ESC
	),
	[BROWSER] = LAYOUT(
		                          _______,
		C(S(KC_T)), C(KC_T),    C(KC_W),
		A(KC_LEFT), C(KC_L),    A(KC_RGHT),
		C(KC_MINS), C(KC_0),    C(KC_EQL)
	),
	// FreeCAD Sketcher: line, circle, rectangle / coincident, horizontal, vertical / dimension, construction, Esc
	[SKETCHER] = LAYOUT(
		                          _______,
		SK_LINE,    SK_CIRCLE,  SK_RECT,
		KC_C,       KC_H,       KC_V,
		KC_D,       SK_CONSTR,  KC_ESC
	),
	[5] = FREE_LAYER, [6] = FREE_LAYER, [7] = FREE_LAYER,
	[8] = FREE_LAYER, [9] = FREE_LAYER, [10] = FREE_LAYER, [11] = FREE_LAYER,
	[12] = FREE_LAYER, [13] = FREE_LAYER, [14] = FREE_LAYER,
	// Hold the knob: lighting, and the bootloader on the bottom-right key
	[FN] = LAYOUT(
		                          _______,
		RM_TOGG,    RM_NEXT,    RM_HUEU,
		RM_SATU,    RM_SPDU,    RM_VALU,
		XXXXXXX,    XXXXXXX,    QK_BOOT
	),
};

#define FREE_KNOB { ENCODER_CCW_CW(_______, _______) }

const uint16_t PROGMEM encoder_map[][NUM_ENCODERS][NUM_DIRECTIONS] = {
	[BASE]    = { ENCODER_CCW_CW(KC_VOLD, KC_VOLU) },
	[FREECAD] = { ENCODER_CCW_CW(C(KC_PMNS), C(KC_PPLS)) }, // zoom
	[KICAD]   = { ENCODER_CCW_CW(KC_F2, KC_F1) },           // zoom
	[BROWSER] = { ENCODER_CCW_CW(C(S(KC_TAB)), C(KC_TAB)) },
	[SKETCHER] = { ENCODER_CCW_CW(C(KC_PMNS), C(KC_PPLS)) }, // zoom
	[5] = FREE_KNOB, [6] = FREE_KNOB, [7] = FREE_KNOB,
	[8] = FREE_KNOB, [9] = FREE_KNOB, [10] = FREE_KNOB, [11] = FREE_KNOB,
	[12] = FREE_KNOB, [13] = FREE_KNOB, [14] = FREE_KNOB,
	[FN]      = { ENCODER_CCW_CW(RM_VALD, RM_VALU) },
};
// clang-format on
