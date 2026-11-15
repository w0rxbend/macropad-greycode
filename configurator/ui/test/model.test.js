import { test } from 'node:test';
import assert from 'node:assert/strict';

import { FONT } from '../font.js';
import {
  HEIGHT,
  WIDTH,
  joinList,
  oledLines,
  padLabels,
  printable,
  rasterize,
  serial,
  splitList,
  withItem,
} from '../model.js';

const freecad = {
  name: 'FreeCAD',
  layer: 1,
  labels: ['Iso', 'Front', 'Right', 'Top', 'Hide', 'Delete', 'Undo', 'Redo', 'Esc'],
};

test('font holds 95 printable glyphs of 6 columns', () => {
  assert.equal(FONT.length, 95 * 6);
  assert.deepEqual(FONT.slice(('A'.charCodeAt(0) - 32) * 6, ('A'.charCodeAt(0) - 31) * 6), [0x7c, 0x12, 0x11, 0x12, 0x7c, 0x00]);
});

test('lines follow the firmware layout', () => {
  const lines = oledLines(freecad, true);
  assert.equal(lines.length, 8);
  assert.equal(lines[0], 'FreeCAD         L1 *');
  assert.equal(lines[2], 'Iso    Front  Right ');
  assert.equal(lines[4], 'Top    Hide   Delete');
  assert.equal(lines[6], 'Undo   Redo   Esc   ');
  assert.deepEqual([lines[1], lines[3], lines[5], lines[7]], ['', '', '', '']);
  for (const line of lines) assert.ok(line.length <= 21);
});

test('header clips long names, marks missing layers and the link', () => {
  const [header] = oledLines({ name: 'A very long profile name', layer: 12, labels: [] }, false);
  assert.equal(header, 'A very long pro L12 ');
  assert.equal(oledLines({ name: '', layer: null, labels: [] }, true)[0], 'greycode        L? *');
});

test('labels clip to 6 and non-ASCII shows as ?', () => {
  const lines = oledLines({ name: 'Zoom°', layer: 3, labels: ['Zoom+++', 'Ünter'] }, true);
  assert.equal(lines[0].slice(0, 5), 'Zoom?');
  assert.equal(lines[2], 'Zoom++ ?nter        ');
  assert.equal(printable('a\tb'), 'a?b');
});

test('rasterize draws glyph columns top bit first', () => {
  const px = rasterize(['A']);
  assert.equal(px.length, WIDTH * HEIGHT);
  const column = (x) => Array.from({ length: 8 }, (_, y) => px[y * WIDTH + x]);
  assert.deepEqual(column(0), [0, 0, 1, 1, 1, 1, 1, 0]); // 0x7c
  assert.deepEqual(column(1), [0, 1, 0, 0, 1, 0, 0, 0]); // 0x12
  assert.equal(px.reduce((a, b) => a + b, 0), 16); // 5 + 2 + 2 + 2 + 5 bits
});

test('rasterize places rows 8 px apart and ignores text past 21 columns', () => {
  const px = rasterize(['', '!', '', '', '', '', '', '', 'beyond the screen']);
  const lit = [...px.keys()].filter((i) => px[i]);
  assert.deepEqual(lit.map((i) => [i % WIDTH, Math.floor(i / WIDTH)]), [8, 9, 10, 11, 12, 14].map((y) => [2, y])); // "!" is 0x5f
  const wide = rasterize(['~'.repeat(30)]);
  for (let y = 0; y < 8; y++) assert.equal(wide[y * WIDTH + 126] + wide[y * WIDTH + 127], 0);
});

test('list fields', () => {
  assert.deepEqual(splitList(' firefox, ,chromium ,'), ['firefox', 'chromium']);
  assert.equal(joinList(['a', 'b']), 'a, b');
  assert.deepEqual(withItem(['a'], 'a'), ['a']);
  assert.deepEqual(withItem(['a'], 'b'), ['a', 'b']);
  assert.deepEqual(padLabels(['x']), ['x', '', '', '', '', '', '', '', '']);
});

test('serial runs tasks in call order, past a rejection', async () => {
  const run = serial();
  const log = [];
  const slow = run(() => new Promise((resolve) => setTimeout(() => { log.push('edit'); resolve(1); }, 20)));
  const failing = run(async () => { log.push('bad'); throw new Error('refused'); });
  const save = run(async () => { log.push('save'); return 2; });
  await assert.rejects(failing, /refused/);
  assert.deepEqual([await slow, await save], [1, 2]);
  assert.deepEqual(log, ['edit', 'bad', 'save']);
});

test('serial idle waits for every queued task', async () => {
  const run = serial();
  let done = false;
  run(() => new Promise((resolve) => setTimeout(() => { done = true; resolve(); }, 20)));
  await run.idle();
  assert.equal(done, true);
});
