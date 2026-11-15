// Pure helpers for the UI: the OLED preview and list fields. No DOM, so `node --test` covers them.
import { FIRST, FONT, GLYPH_WIDTH } from './font.js';

export const WIDTH = 128;
export const HEIGHT = 64;
export const KEYS = 9;
export const LABEL_CHARS = 6; // LABEL frame, docs/protocol.md
const COLS = 21;
const ROW_PX = 8;
const NAME_CHARS = 15; // render_header in firmware/greycode/greycode.c: "%-15.15s L%-2u%c"

// The pad turns every byte outside printable ASCII into '?'.
export function printable(text) {
  return [...text].map((c) => (c >= ' ' && c <= '~' ? c : '?')).join('');
}

function cell(text, width) {
  return printable(text).slice(0, width).padEnd(width);
}

// The eight 21-character rows the firmware draws while greyd is linked: header, then the three
// label rows on every other line (oled_task_kb in greycode.c). The alert row is left out.
export function oledLines({ name, layer, labels }, connected) {
  const header = `${cell(name || 'greycode', NAME_CHARS)} L${cell(String(layer ?? '?'), 2)}${connected ? '*' : ' '}`;
  const row = (r) => [0, 1, 2].map((c) => cell(labels[r * 3 + c] ?? '', LABEL_CHARS)).join(' ');
  return [header, '', row(0), '', row(1), '', row(2), ''];
}

// 1 = lit pixel, row-major, WIDTH x HEIGHT.
export function rasterize(lines) {
  const pixels = new Uint8Array(WIDTH * HEIGHT);
  lines.slice(0, HEIGHT / ROW_PX).forEach((line, row) => {
    [...line.slice(0, COLS)].forEach((ch, col) => {
      const glyph = (ch.charCodeAt(0) - FIRST) * GLYPH_WIDTH;
      for (let x = 0; x < GLYPH_WIDTH; x++) {
        const column = FONT[glyph + x];
        for (let y = 0; y < ROW_PX; y++) {
          if ((column >> y) & 1) pixels[(row * ROW_PX + y) * WIDTH + col * GLYPH_WIDTH + x] = 1;
        }
      }
    });
  });
  return pixels;
}

// Always nine entries, for the nine key inputs.
export function padLabels(labels) {
  return Array.from({ length: KEYS }, (_, i) => labels[i] ?? '');
}

export function splitList(text) {
  return text
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

export function joinList(list) {
  return list.join(', ');
}

export function withItem(list, item) {
  return list.includes(item) ? list : [...list, item];
}

// Runs async tasks one at a time, in call order. A rejection reaches only its own caller; later tasks
// still run. `idle()` settles once every task queued so far has.
export function serial() {
  let tail = Promise.resolve();
  const run = (task) => {
    const result = tail.then(task);
    tail = result.catch(() => {});
    return result;
  };
  run.idle = () => tail;
  return run;
}
