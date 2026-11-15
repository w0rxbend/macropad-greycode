// Host link: the PC tells the pad which app has focus, what to light and what
// to show. Pure C, no QMK headers, so firmware/test can run it natively.
// Wire format: docs/protocol.md. Vectors shared with host/:
// firmware/test/vectors.txt.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#define HL_REPORT 32
#define HL_ID                                                                  \
	0xC7 // first byte of every host-link frame; unused by VIA (0x01-0x15)
	     // and Vial (0xFE)
#define HL_PROTO 1
#define HL_KEYS 9
#define HL_NAME_LEN 16
#define HL_LABEL_LEN 6
#define HL_TEXT_LEN 20
#define HL_NO_LAYER 0xFF
#define HL_TIMEOUT_MS 5000 // host sends a heartbeat every 1000 ms

enum hl_cmd {
	HL_HELLO = 0x01,
	HL_HEARTBEAT = 0x02,
	HL_PROFILE = 0x03,
	HL_LABEL = 0x04,
	HL_ALERT = 0x05,
	HL_KEY_LEDS = 0x06,
};

enum hl_event {
	HL_EVT_HOST_KEY = 0x81,
};

enum hl_status {
	HL_OK = 0x00,
	HL_BAD_CMD = 0x01,
	HL_BAD_ARG = 0x02,
};

enum hl_level {
	HL_LEVEL_NONE = 0,
	HL_LEVEL_INFO,
	HL_LEVEL_OK,
	HL_LEVEL_WARN,
	HL_LEVEL_ERROR,
	HL_LEVEL_COUNT,
};

enum hl_pattern {
	HL_SOLID = 0,
	HL_PULSE,
	HL_BLINK,
	HL_PATTERN_COUNT,
};

typedef struct {
	uint8_t r, g, b;
} hl_rgb_t;

typedef struct {
	uint8_t level;
	uint8_t pattern;
	hl_rgb_t rgb;
	uint32_t started;
	bool timed; // false = until cleared
	uint32_t until;
	char text[HL_TEXT_LEN + 1];
} hl_alert_t;

typedef struct {
	bool connected;
	uint32_t last_seen;
	uint8_t layer; // HL_NO_LAYER = no app profile, keymap base layer
	hl_rgb_t accent;
	char name[HL_NAME_LEN + 1];
	char labels[HL_KEYS][HL_LABEL_LEN + 1];
	uint16_t key_mask; // keys whose colour the host overrides
	hl_rgb_t key_rgb[HL_KEYS];
	hl_alert_t alert;
} hl_state_t;

// What hl_handle changed, so the glue only does the work it must.
enum hl_change {
	HL_CHANGED_LAYER = 1 << 0,
	HL_CHANGED_SCREEN = 1 << 1,
};

void hl_init(hl_state_t* s);

// Handle one frame in place: frame[0] is HL_ID, the reply overwrites the
// payload (frame[2] = status). `layer_count` bounds HL_PROFILE.
// Returns hl_change bits.
uint8_t hl_handle(hl_state_t* s, uint8_t frame[HL_REPORT], uint8_t layer_count,
		  uint32_t now);

// Expire alerts and drop the host after HL_TIMEOUT_MS of silence.
// Returns hl_change bits.
uint8_t hl_tick(hl_state_t* s, uint32_t now);

// Colour of the edge light now: the alert if any, else the profile accent.
// Returns false when the host has nothing to show there (no host, no profile,
// no alert): the RGB effect keeps the edge. A blink's off phase is black.
bool hl_edge_color(const hl_state_t* s, uint32_t now, hl_rgb_t* out);

// Device-to-host event for a HOST(n) key.
void hl_encode_host_key(uint8_t frame[HL_REPORT], uint8_t n, bool pressed);
