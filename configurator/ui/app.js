// DOM and backend calls. Every edit goes to the Rust core, which returns the new view; nothing
// here writes the config. Pure helpers live in model.js.
import {
  HEIGHT, KEYS, LABEL_CHARS, WIDTH,
  joinList, oledLines, padLabels, rasterize, serial, splitList, withItem,
} from './model.js';

const $ = (id) => document.getElementById(id);
const STATUS_EVERY_MS = 2000;
const HOST_KEYS = 8;
const RELOAD_CONFIRM_MS = 3000;
const OWN_APP = 'greycode'; // this app's own window; never offered as "the focused app"
const PIXEL = [0xdc, 0xe8, 0xff];

const state = { view: null, selected: 0, link: null, lastApp: '' }; // selected: index or 'global'
const keyInputs = [];
const profileActionInputs = [];
const globalActionInputs = [];

const invoke = (cmd, args) => window.__TAURI__.core.invoke(cmd, args);

function say(text, kind = '') {
  $('message').textContent = text;
  $('message').className = kind;
}

function setValue(el, value) {
  if (el !== document.activeElement) el.value = value;
}

function profile() {
  return typeof state.selected === 'number' ? state.view.profiles[state.selected] : undefined;
}

// Backend calls run one at a time, in order, so a save always follows the edits queued before it.
const backend = serial();
const load = (cmd, args) => backend(() => loadNow(cmd, args));

async function loadNow(cmd, args) {
  try {
    state.view = await invoke(cmd, args);
    return true;
  } catch (e) {
    say(String(e), 'error');
    return false;
  } finally {
    if (state.view) render();
  }
}

const edit = (op) => load('apply', { edit: op });
const setField = (field) => edit({ op: 'set_profile', index: state.selected, field });

async function open() {
  if (await load('open')) say(`Opened ${state.view.path}`);
}

// A field commits on 'change' (blur or Enter). Ctrl+S, or a click that does not move focus, can come
// while one still holds typed text: blurring it fires the change, which queues its edit first.
function commitFocusedField() {
  const field = document.activeElement;
  if (!(field instanceof HTMLInputElement)) return;
  field.blur();
  field.focus();
}

async function save() {
  commitFocusedField();
  await backend.idle();
  if (!state.view?.dirty) {
    say('No changes to save.');
    return;
  }
  if (await load('save')) say('Saved. greyd applies it within a second.', 'ok');
}

// ---- rendering --------------------------------------------------------------------------------

function render() {
  const { view } = state;
  const count = view.profiles.length;
  if (typeof state.selected === 'number' && state.selected >= count) state.selected = count ? count - 1 : 'global';
  renderList();
  renderMessages();
  $('txt-path').textContent = view.path;
  $('btn-save').disabled = !view.dirty || view.problem != null;
  $('profile-view').hidden = !profile();
  $('global-view').hidden = state.selected !== 'global';
  $('btn-global').setAttribute('aria-current', String(state.selected === 'global'));
  if (profile()) renderProfile(profile());
  else renderGlobal();
}

function renderList() {
  const list = $('profile-list');
  const hadFocus = list.contains(document.activeElement);
  list.replaceChildren(...state.view.profiles.map((p, i) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('aria-current', String(i === state.selected));
    button.style.setProperty('--c', p.color ?? '#ffffff');
    const clash = p.shares_layer_with.length > 0;
    button.innerHTML = '<span class="swatch"></span><span class="name"></span><span class="layer"></span>';
    button.querySelector('.name').textContent = p.name || '(no name)';
    const layer = button.querySelector('.layer');
    layer.textContent = `L${p.layer ?? '?'}`;
    layer.classList.toggle('clash', clash);
    if (clash) layer.title = `Also on this layer: ${p.shares_layer_with.join(', ')}`;
    button.addEventListener('click', () => select(i));
    const item = document.createElement('li');
    item.append(button);
    return item;
  }));
  if (hadFocus && typeof state.selected === 'number') list.querySelectorAll('button')[state.selected]?.focus();
}

function renderMessages() {
  const { problem, warnings } = state.view;
  const items = warnings.map((w) => Object.assign(document.createElement('li'), { textContent: w }));
  if (problem) {
    items.unshift(Object.assign(document.createElement('li'), {
      textContent: `Cannot save, greyd would reject this: ${problem}`,
      className: 'problem',
    }));
  }
  $('warnings').replaceChildren(...items);
}

function renderProfile(p) {
  const i = state.selected;
  $('profile-title').textContent = p.name || '(no name)';
  setValue($('f-name'), p.name);
  setValue($('f-layer'), p.layer ?? '');
  setValue($('f-color'), /^#[0-9a-f]{6}$/i.test(p.color ?? '') ? p.color : '#ffffff');
  setValue($('f-apps'), joinList(p.apps));
  setValue($('f-titles'), joinList(p.titles));
  padLabels(p.labels).forEach((label, k) => setValue(keyInputs[k], label));
  profileActionInputs.forEach((input, k) => {
    setValue(input, p.actions[k] ?? '');
    input.placeholder = state.view.actions[k] ? `global: ${state.view.actions[k]}` : 'nothing';
  });
  $('btn-up').disabled = i === 0;
  $('btn-down').disabled = i === state.view.profiles.length - 1;
  const others = p.shares_layer_with;
  $('layer-note').hidden = others.length === 0;
  $('layer-note').textContent = `Layer ${p.layer} is also used by ${others.join(', ')}: they share one keymap in Vial.`;
  $('other-keys').hidden = p.other_keys.length === 0;
  $('other-keys').textContent = `Also in this profile, kept as written: ${p.other_keys.join(', ')}.`;
  renderFocused();
  preview();
}

function renderGlobal() {
  const pause = state.view.pause_apps;
  setValue($('f-pause'), pause ? joinList(pause) : '');
  $('f-pause').placeholder = pause ? '' : "not set: greyd's default applies";
  globalActionInputs.forEach((input, k) => setValue(input, state.view.actions[k] ?? ''));
}

function renderFocused() {
  const button = $('btn-focused');
  button.disabled = !state.lastApp;
  button.textContent = state.lastApp ? `Add focused app: ${state.lastApp}` : 'Use focused app (needs greyd)';
}

// Draws from the inputs, so typing shows at once, before the edit is committed.
function preview() {
  const lines = oledLines({
    name: $('f-name').value,
    layer: $('f-layer').value || null,
    labels: keyInputs.map((k) => k.value),
  }, true);
  const pixels = rasterize(lines);
  const ctx = $('oled').getContext('2d');
  const image = ctx.createImageData(WIDTH, HEIGHT);
  pixels.forEach((lit, n) => {
    if (lit) image.data.set(PIXEL, n * 4);
    image.data[n * 4 + 3] = 255;
  });
  ctx.putImageData(image, 0, 0);
  document.documentElement.style.setProperty('--accent', $('f-color').value);
}

function renderLink(link) {
  state.link = link;
  if (link.app && !link.app.toLowerCase().includes(OWN_APP)) state.lastApp = link.app;
  $('lamp-greyd').className = link.greyd ? 'lamp on' : 'lamp';
  $('txt-greyd').textContent = link.greyd ? 'greyd running' : 'greyd not running';
  $('txt-greyd').title = link.error ?? '';
  $('lamp-pad').className = link.linked ? 'lamp on' : link.pad ? 'lamp half' : 'lamp';
  $('txt-pad').textContent = link.linked ? 'pad linked' : link.pad ? 'pad found, no reply' : 'pad not connected';
  $('txt-app').textContent = link.app || '-';
  if (profile()) renderFocused();
}

async function pollStatus() {
  try {
    renderLink(await invoke('status'));
  } finally {
    setTimeout(pollStatus, STATUS_EVERY_MS);
  }
}

// ---- events -----------------------------------------------------------------------------------

function select(index) {
  state.selected = index;
  render();
}

function buildKeys() {
  for (let k = 0; k < KEYS; k++) {
    const input = document.createElement('input');
    input.maxLength = LABEL_CHARS;
    input.placeholder = `key ${k + 1}`;
    input.setAttribute('aria-label', `Key ${k + 1} label, row ${Math.floor(k / 3) + 1}`);
    input.spellcheck = false;
    input.addEventListener('input', preview);
    input.addEventListener('change', () => setField({ labels: keyInputs.map((i) => i.value) }));
    keyInputs.push(input);
  }
  $('keys').replaceChildren(...keyInputs);
}

function buildActions(container, inputs, profileIndex) {
  for (let k = 0; k < HOST_KEYS; k++) {
    const input = document.createElement('input');
    input.id = `${container.id}-${k}`;
    input.spellcheck = false;
    input.addEventListener('change', () => edit({
      op: 'set_action', profile: profileIndex(), key: k, command: input.value.trim(),
    }));
    const label = Object.assign(document.createElement('label'), { htmlFor: input.id, textContent: `HOST ${k}` });
    container.append(label, input);
    inputs.push(input);
  }
}

function wireFields() {
  $('f-name').addEventListener('input', preview);
  $('f-name').addEventListener('change', (e) => setField({ name: e.target.value.trim() }));
  $('f-layer').addEventListener('input', preview);
  $('f-layer').addEventListener('change', (e) => {
    const layer = Number(e.target.value);
    if (e.target.validity.valid && e.target.value !== '') setField({ layer });
    else { say('Layer must be a whole number from 1 to 14.', 'error'); render(); }
  });
  $('f-color').addEventListener('input', preview);
  $('f-color').addEventListener('change', (e) => setField({ color: e.target.value }));
  $('f-apps').addEventListener('change', (e) => setField({ apps: splitList(e.target.value) }));
  $('f-titles').addEventListener('change', (e) => setField({ titles: splitList(e.target.value) }));
  $('btn-focused').addEventListener('click', () => setField({ apps: withItem(profile().apps, state.lastApp) }));
  $('f-pause').addEventListener('change', (e) => edit({ op: 'set_pause_apps', apps: splitList(e.target.value) }));
}

function wireProfileButtons() {
  $('btn-add').addEventListener('click', async () => {
    if (await edit({ op: 'add_profile' })) select(state.view.profiles.length - 1);
  });
  $('btn-global').addEventListener('click', () => select('global'));
  $('btn-delete').addEventListener('click', () => edit({ op: 'delete_profile', index: state.selected }));
  const move = async (by) => {
    const from = state.selected;
    if (await edit({ op: 'move_profile', from, to: from + by })) select(from + by);
  };
  $('btn-up').addEventListener('click', () => move(-1));
  $('btn-down').addEventListener('click', () => move(1));
}

function wireBar() {
  $('btn-save').addEventListener('click', save);
  // typed text is not committed yet, so the view cannot know it is dirty; let Save take the click
  for (const view of [$('profile-view'), $('global-view')]) {
    view.addEventListener('input', () => { $('btn-save').disabled = false; });
  }
  let armed = null;
  $('btn-reload').addEventListener('click', () => {
    if (state.view?.dirty && !armed) {
      $('btn-reload').textContent = 'Drop changes?';
      armed = setTimeout(() => { armed = null; $('btn-reload').textContent = 'Reload'; }, RELOAD_CONFIRM_MS);
      return;
    }
    clearTimeout(armed);
    armed = null;
    $('btn-reload').textContent = 'Reload';
    open();
  });
  $('btn-vial').addEventListener('click', async () => {
    try { await invoke('open_vial'); say('Vial started. greyd pauses while it is in front.'); }
    catch (e) { say(String(e), 'error'); }
  });
  $('alert-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await invoke('alert', { level: $('a-level').value, text: $('a-text').value, timeout: 5 });
      say('Alert sent; it clears after 5 s.', 'ok');
    } catch (err) { say(String(err), 'error'); }
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      save(); // save() commits the focused field and checks for changes itself
    }
  });
}

function start() {
  if (!window.__TAURI__) {
    say('This page needs the configurator app around it; open it with the greycode-configurator binary.', 'error');
    return;
  }
  buildKeys();
  buildActions($('profile-actions'), profileActionInputs, () => state.selected);
  buildActions($('global-actions'), globalActionInputs, () => null);
  wireFields();
  wireProfileButtons();
  wireBar();
  open();
  pollStatus();
}

start();
