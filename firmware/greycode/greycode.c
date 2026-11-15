// QMK glue for the host link: raw HID in, default layer, LEDs and OLED out.
#include "greycode.h"

#include <stdio.h>

#include "hostlink.h"
#include "raw_hid.h"
#include "via.h"

static hl_state_t host;

void keyboard_post_init_kb(void) {
	hl_init(&host);
	keyboard_post_init_user();
}

// The app profile is the default layer, so FN (layer 15, momentary) stays on
// top and KC_TRNS in a profile falls through to layer 0.
static void apply_profile_layer(void) {
	uint8_t layer = host.layer == HL_NO_LAYER ? 0 : host.layer;
	default_layer_set((layer_state_t)1 << layer);
}

void raw_hid_receive_kb(uint8_t* data, uint8_t length) {
	if (length != HL_REPORT || data[0] != HL_ID) {
		data[0] = id_unhandled;
		return;
	}
	uint8_t changed =
	    hl_handle(&host, data, DYNAMIC_KEYMAP_LAYER_COUNT, timer_read32());
	if (changed & HL_CHANGED_LAYER) {
		apply_profile_layer();
	}
}

void housekeeping_task_kb(void) {
	if (hl_tick(&host, timer_read32()) & HL_CHANGED_LAYER) {
		apply_profile_layer();
	}
	housekeeping_task_user();
}

bool process_record_kb(uint16_t keycode, keyrecord_t* record) {
	if (keycode >= HOST_0 && keycode <= HOST_LAST) {
		uint8_t frame[HL_REPORT];
		hl_encode_host_key(frame, keycode - HOST_0,
				   record->event.pressed);
		raw_hid_send(frame, HL_REPORT);
		return false;
	}
	if (keycode >= SK_LINE && keycode <= SK_CONSTR) {
		static const char *const sketcher[] = {"gl", "gc", "gr", "gn"};
		if (record->event.pressed) {
			send_string(sketcher[keycode - SK_LINE]);
		}
		return false;
	}
	return process_record_user(keycode, record);
}

static void set_led(uint8_t index, hl_rgb_t c, uint8_t val) {
	rgb_matrix_set_color(index, c.r * val / 255, c.g * val / 255,
			     c.b * val / 255);
}

static bool in_range(uint8_t index, uint8_t led_min, uint8_t led_max) {
	return index >= led_min && index < led_max;
}

bool rgb_matrix_indicators_advanced_kb(uint8_t led_min, uint8_t led_max) {
	if (!rgb_matrix_indicators_advanced_user(led_min, led_max)) {
		return false;
	}
	uint8_t val = rgb_matrix_get_val();
	for (uint8_t k = 0; k < HL_KEYS; k++) {
		if ((host.key_mask & (1u << k)) &&
		    in_range(k, led_min, led_max)) {
			set_led(k, host.key_rgb[k], val);
		}
	}
	hl_rgb_t edge;
	if (!hl_edge_color(&host, timer_read32(), &edge)) {
		return true;
	}
	for (uint8_t i = 0; i < GREYCODE_EDGE_COUNT; i++) {
		uint8_t index = GREYCODE_EDGE_FIRST + i;
		if (in_range(index, led_min, led_max)) {
			set_led(index, edge, val);
		}
	}
	return true;
}

// 21 x 8 characters: name and layer, three label rows, alert on the last row.
static void render_header(void) {
	char line[22];
	uint8_t layer = get_highest_layer(layer_state | default_layer_state);
	const char* name = host.name[0] ? host.name : "greycode";
	snprintf(line, sizeof(line), "%-15.15s L%-2u%c", name, layer,
		 host.connected ? '*' : ' ');
	oled_write_ln(line, false);
}

static void render_labels(void) {
	char line[22];
	for (uint8_t row = 0; row < 3; row++) {
		const char (*l)[HL_LABEL_LEN + 1] = &host.labels[row * 3];
		snprintf(line, sizeof(line), "%-6s %-6s %-6s", l[0], l[1],
			 l[2]);
		oled_write_ln("", false);
		oled_write_ln(line, false);
	}
}

static void render_alert(void) {
	char line[22];
	snprintf(line, sizeof(line), "%-21s", host.alert.text);
	oled_write_ln("", false);
	oled_write(line, host.alert.level >= HL_LEVEL_WARN);
}

bool oled_task_kb(void) {
	if (!oled_task_user()) {
		return false;
	}
	oled_set_cursor(0, 0);
	render_header();
	if (host.connected) {
		render_labels();
		render_alert();
	} else {
		oled_write_ln("", false);
		oled_write_ln("", false);
		oled_write_ln("   waiting for greyd", false);
		for (uint8_t i = 0; i < 4; i++) {
			oled_write_ln("", false);
		}
	}
	return false;
}
