#include "hostlink.h"

#include <string.h>

#define BLINK_HALF_MS 500
#define PULSE_PERIOD_MS 1000

static const hl_rgb_t level_rgb[HL_LEVEL_COUNT] = {
    [HL_LEVEL_NONE] = {0, 0, 0},    [HL_LEVEL_INFO] = {0, 120, 255},
    [HL_LEVEL_OK] = {0, 200, 60},   [HL_LEVEL_WARN] = {255, 140, 0},
    [HL_LEVEL_ERROR] = {255, 0, 0},
};

void hl_init(hl_state_t* s) {
	memset(s, 0, sizeof(*s));
	s->layer = HL_NO_LAYER;
}

// Host text is untrusted: stop at NUL, keep printable ASCII, always terminate.
static void copy_text(char* dst, const uint8_t* src, uint8_t max) {
	uint8_t i = 0;
	for (; i < max && src[i] != 0; i++) {
		dst[i] =
		    (src[i] >= 0x20 && src[i] <= 0x7E) ? (char)src[i] : '?';
	}
	dst[i] = '\0';
}

static hl_rgb_t rgb_at(const uint8_t* p) {
	return (hl_rgb_t){p[0], p[1], p[2]};
}

static bool is_black(hl_rgb_t c) { return c.r == 0 && c.g == 0 && c.b == 0; }

static bool reached(uint32_t now, uint32_t deadline) {
	return (int32_t)(now - deadline) >= 0;
}

static uint8_t set_profile(hl_state_t* s, const uint8_t* in,
			   uint8_t layer_count, uint8_t* status) {
	uint8_t layer = in[0];
	if (layer != HL_NO_LAYER && layer >= layer_count) {
		*status = HL_BAD_ARG;
		return 0;
	}
	s->layer = layer;
	s->accent = rgb_at(&in[1]);
	copy_text(s->name, &in[4], HL_NAME_LEN);
	memset(s->labels, 0, sizeof(s->labels));
	s->key_mask = 0;
	return HL_CHANGED_LAYER | HL_CHANGED_SCREEN;
}

static uint8_t set_label(hl_state_t* s, const uint8_t* in, uint8_t* status) {
	if (in[0] >= HL_KEYS) {
		*status = HL_BAD_ARG;
		return 0;
	}
	copy_text(s->labels[in[0]], &in[1], HL_LABEL_LEN);
	return HL_CHANGED_SCREEN;
}

static uint8_t set_alert(hl_state_t* s, const uint8_t* in, uint32_t now,
			 uint8_t* status) {
	uint8_t level = in[0], pattern = in[1];
	if (level >= HL_LEVEL_COUNT || pattern >= HL_PATTERN_COUNT) {
		*status = HL_BAD_ARG;
		return 0;
	}
	hl_alert_t* a = &s->alert;
	memset(a, 0, sizeof(*a));
	if (level == HL_LEVEL_NONE) {
		return HL_CHANGED_SCREEN;
	}
	uint16_t timeout_s = (uint16_t)(in[5] | (in[6] << 8));
	a->level = level;
	a->pattern = pattern;
	a->rgb = is_black(rgb_at(&in[2])) ? level_rgb[level] : rgb_at(&in[2]);
	a->started = now;
	a->timed = timeout_s != 0;
	a->until = now + (uint32_t)timeout_s * 1000u;
	copy_text(a->text, &in[7], HL_TEXT_LEN);
	return HL_CHANGED_SCREEN;
}

static void set_key_leds(hl_state_t* s, const uint8_t* in) {
	uint16_t mask =
	    (uint16_t)(in[0] | (in[1] << 8)) & ((1u << HL_KEYS) - 1);
	if (in[2] == 0) {
		s->key_mask &= (uint16_t)~mask;
		return;
	}
	s->key_mask |= mask;
	for (uint8_t k = 0; k < HL_KEYS; k++) {
		if (mask & (1u << k)) {
			s->key_rgb[k] = rgb_at(&in[3]);
		}
	}
}

uint8_t hl_handle(hl_state_t* s, uint8_t frame[HL_REPORT], uint8_t layer_count,
		  uint32_t now) {
	uint8_t in[HL_REPORT - 2];
	memcpy(in, &frame[2], sizeof(in));
	memset(&frame[2], 0, HL_REPORT - 2);

	uint8_t status = HL_OK, changed = 0;
	switch (frame[1]) {
	case HL_HELLO:
		frame[3] = HL_PROTO;
		frame[4] = layer_count;
		frame[5] = HL_KEYS;
		break;
	case HL_HEARTBEAT:
		break;
	case HL_PROFILE:
		changed = set_profile(s, in, layer_count, &status);
		break;
	case HL_LABEL:
		changed = set_label(s, in, &status);
		break;
	case HL_ALERT:
		changed = set_alert(s, in, now, &status);
		break;
	case HL_KEY_LEDS:
		set_key_leds(s, in);
		break;
	default:
		status = HL_BAD_CMD;
	}
	frame[2] = status;
	if (!s->connected) {
		changed |= HL_CHANGED_SCREEN;
	}
	s->connected = true;
	s->last_seen = now;
	return changed;
}

uint8_t hl_tick(hl_state_t* s, uint32_t now) {
	if (s->connected && reached(now, s->last_seen + HL_TIMEOUT_MS)) {
		bool had_layer = s->layer != HL_NO_LAYER;
		hl_init(s);
		return HL_CHANGED_SCREEN | (had_layer ? HL_CHANGED_LAYER : 0);
	}
	if (s->alert.level && s->alert.timed && reached(now, s->alert.until)) {
		memset(&s->alert, 0, sizeof(s->alert));
		return HL_CHANGED_SCREEN;
	}
	return 0;
}

static uint8_t scale(uint8_t c, uint16_t k) {
	return (uint8_t)((c * k) / 255u);
}

bool hl_edge_color(const hl_state_t* s, uint32_t now, hl_rgb_t* out) {
	const hl_alert_t* a = &s->alert;
	if (a->level == HL_LEVEL_NONE) {
		*out = s->accent;
		return s->connected && s->layer != HL_NO_LAYER;
	}
	uint32_t t = now - a->started;
	uint16_t k = 255;
	if (a->pattern == HL_BLINK) {
		k = ((t / BLINK_HALF_MS) % 2) ? 0 : 255;
	} else if (a->pattern == HL_PULSE) {
		uint32_t p = t % PULSE_PERIOD_MS, half = PULSE_PERIOD_MS / 2;
		k = (uint16_t)((p < half ? p : PULSE_PERIOD_MS - p) * 255u /
			       half);
	}
	*out = (hl_rgb_t){scale(a->rgb.r, k), scale(a->rgb.g, k),
			  scale(a->rgb.b, k)};
	return true;
}

void hl_encode_host_key(uint8_t frame[HL_REPORT], uint8_t n, bool pressed) {
	memset(frame, 0, HL_REPORT);
	frame[0] = HL_ID;
	frame[1] = HL_EVT_HOST_KEY;
	frame[2] = n;
	frame[3] = pressed ? 1 : 0;
}
