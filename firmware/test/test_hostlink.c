// Native tests for hostlink.c. Build and run: make -C firmware test
#include "hostlink.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define LAYERS 16

static int failures;

#define CHECK(cond)                                                            \
	do {                                                                   \
		if (!(cond)) {                                                 \
			fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__,     \
				#cond);                                        \
			failures++;                                            \
		}                                                              \
	} while (0)

// Frame `name` from vectors.txt, zero-padded to HL_REPORT.
static void vector(const char* name, uint8_t frame[HL_REPORT]) {
	FILE* f = fopen(VECTORS, "r");
	char line[256];
	memset(frame, 0, HL_REPORT);
	while (f && fgets(line, sizeof(line), f)) {
		char* tok = strtok(line, " \t\n");
		if (!tok || tok[0] == '#' || strcmp(tok, name) != 0) {
			continue;
		}
		for (int i = 0; (tok = strtok(NULL, " \t\n")); i++) {
			frame[i] = (uint8_t)strtoul(tok, NULL, 16);
		}
		fclose(f);
		return;
	}
	fprintf(stderr, "vector %s missing from %s\n", name, VECTORS);
	exit(2);
}

static uint8_t send(hl_state_t* s, const char* name, uint32_t now,
		    uint8_t reply[HL_REPORT]) {
	vector(name, reply);
	return hl_handle(s, reply, LAYERS, now);
}

static void test_hello_reply(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT];
	hl_init(&s);
	send(&s, "hello", 0, f);
	CHECK(f[0] == HL_ID && f[1] == HL_HELLO && f[2] == HL_OK);
	CHECK(f[3] == HL_PROTO && f[4] == LAYERS && f[5] == HL_KEYS);
	CHECK(s.connected);
}

static void test_profile_sets_layer_and_resets_overrides(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT];
	hl_init(&s);
	send(&s, "keys_set_0_2", 0, f);
	send(&s, "label_4_pad", 0, f);
	uint8_t changed = send(&s, "profile_freecad", 0, f);
	CHECK(changed & HL_CHANGED_LAYER);
	CHECK(s.layer == 1 && strcmp(s.name, "FreeCAD") == 0);
	CHECK(s.accent.r == 0xff && s.accent.g == 0x88 && s.accent.b == 0);
	CHECK(s.key_mask == 0 && s.labels[4][0] == '\0');
	send(&s, "profile_none", 0, f);
	CHECK(s.layer == HL_NO_LAYER);
}

static void test_profile_rejects_missing_layer(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT] = {HL_ID, HL_PROFILE, LAYERS};
	hl_init(&s);
	CHECK(hl_handle(&s, f, LAYERS, 0) ==
	      HL_CHANGED_SCREEN); // first contact only
	CHECK(f[2] == HL_BAD_ARG && s.layer == HL_NO_LAYER);
}

static void test_label_bounds_and_sanitising(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT];
	hl_init(&s);
	send(&s, "label_4_pad", 0, f);
	CHECK(strcmp(s.labels[4], "Pad") == 0);
	uint8_t bad[HL_REPORT] = {HL_ID, HL_LABEL, HL_KEYS, 'x'};
	hl_handle(&s, bad, LAYERS, 0);
	CHECK(bad[2] == HL_BAD_ARG);
	uint8_t odd[HL_REPORT] = {HL_ID, HL_LABEL, 0,	'a', 0x07, 0xC3,
				  'b',	 'c',	   'd', 'e', 'f'};
	hl_handle(&s, odd, LAYERS, 0);
	CHECK(strcmp(s.labels[0], "a??bcd") ==
	      0); // 6 chars max, bytes outside ASCII replaced
}

static void test_unknown_command(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT] = {HL_ID, 0x7F};
	hl_init(&s);
	hl_handle(&s, f, LAYERS, 0);
	CHECK(f[2] == HL_BAD_CMD);
}

static void test_alert_lifecycle(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT];
	hl_rgb_t c;
	hl_init(&s);
	send(&s, "alert_warn", 1000, f);
	CHECK(s.alert.level == HL_LEVEL_WARN && s.alert.pattern == HL_BLINK);
	CHECK(strcmp(s.alert.text, "Build failed") == 0);
	CHECK(hl_edge_color(&s, 1000, &c) && c.r == 255 &&
	      c.g == 140); // default warn amber
	CHECK(hl_edge_color(&s, 1600, &c) && c.r == 0 &&
	      c.g == 0); // blink off phase
	send(&s, "heartbeat", 10000, f);
	CHECK(hl_tick(&s, 10999) == 0);
	CHECK(hl_tick(&s, 11000) == HL_CHANGED_SCREEN); // 10 s timeout
	CHECK(s.alert.level == HL_LEVEL_NONE);
	send(&s, "alert_warn", 0, f);
	send(&s, "alert_clear", 0, f);
	CHECK(s.alert.level == HL_LEVEL_NONE);
}

static void test_pulse_ramps(void) {
	hl_state_t s;
	hl_rgb_t c;
	uint8_t f[HL_REPORT] = {HL_ID, HL_ALERT, HL_LEVEL_ERROR, HL_PULSE};
	hl_init(&s);
	hl_handle(&s, f, LAYERS, 0);
	hl_edge_color(&s, 0, &c);
	CHECK(c.r == 0);
	hl_edge_color(&s, 500, &c);
	CHECK(c.r == 255);
	hl_edge_color(&s, 750, &c);
	CHECK(c.r > 100 && c.r < 155);
}

static void test_key_leds_mask(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT];
	hl_init(&s);
	send(&s, "keys_set_0_2", 0, f);
	CHECK(s.key_mask == 0x005 && s.key_rgb[2].g == 0xff);
	send(&s, "keys_clear_all", 0, f);
	CHECK(s.key_mask == 0);
}

static void test_host_silence_drops_profile(void) {
	hl_state_t s;
	uint8_t f[HL_REPORT];
	hl_rgb_t c;
	hl_init(&s);
	send(&s, "profile_freecad", 0xFFFFF000u, f); // across the 32-bit wrap
	CHECK(hl_edge_color(&s, 0, &c));
	CHECK(hl_tick(&s, 0xFFFFF000u + HL_TIMEOUT_MS - 1) == 0);
	CHECK(hl_tick(&s, 0xFFFFF000u + HL_TIMEOUT_MS) ==
	      (HL_CHANGED_SCREEN | HL_CHANGED_LAYER));
	CHECK(!s.connected && s.layer == HL_NO_LAYER);
	CHECK(!hl_edge_color(&s, 0, &c));
}

static void test_host_key_event(void) {
	uint8_t f[HL_REPORT], want[HL_REPORT];
	hl_encode_host_key(f, 3, true);
	vector("host_key_3_down", want);
	CHECK(memcmp(f, want, HL_REPORT) == 0);
}

int main(void) {
	test_hello_reply();
	test_profile_sets_layer_and_resets_overrides();
	test_profile_rejects_missing_layer();
	test_label_bounds_and_sanitising();
	test_unknown_command();
	test_alert_lifecycle();
	test_pulse_ramps();
	test_key_leds_mask();
	test_host_silence_drops_profile();
	test_host_key_event();
	if (failures) {
		fprintf(stderr, "%d check(s) failed\n", failures);
		return 1;
	}
	puts("hostlink: all tests pass");
	return 0;
}
