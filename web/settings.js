'use strict';
// Whisper Vox - Settings UI. Data is PULLED once (deferred after load); user
// actions call the bridge on click. Never calls the bridge during page load.

const $ = (id) => document.getElementById(id);
let D = null;
let apiKeys = {groq:'', openai:'', manual:''};
let manualUrl = '';
let prevProvider = 'groq';
let baseline = '';
const TRACKED_TOGGLES = ['clipboard_restore','add_trailing_space','remove_trailing_period',
  'remove_capitalization','hide_status_window','noise_on_completion','noise_on_recording','desktop_icon',
  'run_on_startup','auto_check_updates'];
const DONATE_REAL = 'https://nowpayments.io/donation/PekelniBoroshnaLab';

const keySlot = (p) => (['groq','openai','manual'].includes(p) ? p : 'groq');

// ── toggles / segments / selects ──────────────────────────────────────────────
function setToggle(id, on){ $(id).classList.toggle('on', !!on); }
function getToggle(id){ return $(id).classList.contains('on'); }
function setSeg(id, val){ $(id).querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.v === val)); }
function getSeg(id){ const b = $(id).querySelector('button.on'); return b ? b.dataset.v : null; }
function selectByValue(id, val){
  const sel = $(id); val = (val == null ? '' : String(val));
  for (const o of sel.options){ if (o.value === val){ sel.value = val; return; } }
  sel.selectedIndex = 0;
}
function fillModel(list, current){
  const sel = $('model');
  const cur = (current != null) ? String(current) : sel.value;
  const items = [];
  (list || []).forEach(m => { if (m && !items.includes(m)) items.push(m); });
  if (cur && !items.includes(cur)) items.unshift(cur);
  sel.innerHTML = items.map(m => `<option value="${m}">${m}</option>`).join('');
  if (cur) sel.value = cur;
}

// ── collect (gather every UI control into a config-shaped object) ──────────────
function micValue(){ const v = $('sound_device').value; return v === '' ? null : v; }
function collect(){
  const provider = $('provider').value;
  const data = {
    provider,
    api_url: $('api_url').value.trim(),
    api_key: $('api_key').value.trim(),
    model: $('model').value.trim(),
    language: $('language').value,
    initial_prompt: $('initial_prompt').value.trim(),
    activation_key: actKey(),
    recording_mode: getSeg('recording_mode'),
    recording_sound: getSeg('recording_sound'),
    sound_device: micValue(),
    silence_duration: $('silence_duration').value.trim(),
    min_duration: $('min_duration').value.trim(),
    input_method: getSeg('input_method'),
    paste_shortcut: $('paste_shortcut').value,
    paste_delay_ms: $('paste_delay_ms').value.trim(),
    writing_key_press_delay: $('writing_key_press_delay').value.trim(),
  };
  TRACKED_TOGGLES.forEach(k => data[k] = getToggle(k));
  const keys = Object.assign({}, apiKeys);
  keys[keySlot(provider)] = data.api_key;
  data.api_key_groq = keys.groq;
  data.api_key_openai = keys.openai;
  data.api_key_manual = keys.manual;
  data.api_url_manual = (provider === 'manual') ? data.api_url : manualUrl;
  return data;
}
function markDirty(){ $('save_btn').disabled = (JSON.stringify(collect()) === baseline); }

// ── apply a config-like object (load + reset) ─────────────────────────────────
function applyValues(c){
  selectByValue('provider', c.provider || 'groq');
  $('api_url').value = c.api_url || '';
  const prov = D.providers[c.provider || 'groq'] || D.providers.groq;
  fillModel(prov.stt, c.model);
  selectByValue('language', c.language || '');
  $('initial_prompt').value = c.initial_prompt || '';
  setActKey(c.activation_key);
  setSeg('recording_mode', c.recording_mode || 'hold_to_record');
  // Always keep one choice accented. Fall back to the default when the stored
  // value is missing or stale (e.g. an old sound id that no longer exists).
  const rsDef = (D.defaults && D.defaults.recording_sound) || 'classic';
  const rsOpts = ['classic', 'pencil', 'knock'];
  setSeg('recording_sound', rsOpts.includes(c.recording_sound) ? c.recording_sound : rsDef);
  selectByValue('sound_device', c.sound_device || '');
  $('silence_duration').value = (c.silence_duration ?? '');
  $('min_duration').value = (c.min_duration ?? '');
  setSeg('input_method', c.input_method || 'clipboard');
  selectByValue('paste_shortcut', c.paste_shortcut || 'ctrl+v');
  $('paste_delay_ms').value = (c.paste_delay_ms ?? '');
  $('writing_key_press_delay').value = (c.writing_key_press_delay ?? '');
  TRACKED_TOGGLES.forEach(k => setToggle(k, c[k]));
  syncRecMode(); syncInputMethod(); syncRecSound();
}

// ── dependent-field enabling ──────────────────────────────────────────────────
function syncRecMode(){ $('silence_duration').disabled = (getSeg('recording_mode') !== 'continuous'); }
function syncRecSound(){ $('recording_sound').classList.toggle('disabled', !getToggle('noise_on_recording')); }
function syncInputMethod(){
  const clip = (getSeg('input_method') === 'clipboard');
  ['paste_shortcut','paste_delay_ms'].forEach(id => $(id).disabled = !clip);
  $('clipboard_restore').style.opacity = clip ? '1' : '.4';
  $('clipboard_restore').style.pointerEvents = clip ? 'auto' : 'none';
  $('writing_key_press_delay').disabled = clip;
}

// ── provider / model / language ───────────────────────────────────────────────
function setKeyLink(pid){
  const [text, url] = (D.provider_links[pid] || D.provider_links.groq);
  $('key_link').innerHTML = url
    ? `<a href="#" data-ext="${url}" style="font-size:16px;font-weight:700">${text} ↗</a>`
    : `<span style="color:#8a94a3">${text}</span>`;
}
function onProviderChange(){
  const pid = $('provider').value;
  if (prevProvider === 'manual') manualUrl = $('api_url').value.trim();
  apiKeys[keySlot(prevProvider)] = $('api_key').value.trim();
  const p = D.providers[pid];
  $('api_url').value = (pid === 'manual') ? manualUrl : p.url;
  fillModel(p.stt, p.stt_default || '');
  setKeyLink(pid);
  $('api_key').value = apiKeys[keySlot(pid)] || '';
  prevProvider = pid;
  syncNextStep();
  markDirty();
}

// ── microphones ───────────────────────────────────────────────────────────────
function fillMics(mics, defaultName, current){
  const sel = $('sound_device');
  sel.innerHTML = '';
  const def = document.createElement('option');
  def.value = ''; def.textContent = 'Default microphone' + (defaultName ? `  (${defaultName})` : '');
  sel.appendChild(def);
  (mics || []).forEach(name => {
    const o = document.createElement('option'); o.value = name; o.textContent = name; sel.appendChild(o);
  });
  selectByValue('sound_device', current || '');
}

// ── activation-key capture ────────────────────────────────────────────────────
// Capture reads e.code - the PHYSICAL key - and never e.key. e.key is what the
// keystroke would type, which is a different thing entirely: hold Option on a
// Mac and D reports '∂', every punctuation key reports its symbol, and Escape
// reported itself whether or not a modifier was down. That is why Ctrl+Escape,
// Shift+Escape, Ctrl+` and Option+Space could all be pressed here and none of
// them could be assigned.
const CODE_TO_NAME = (() => {
  const map = {
    Escape:'ESC', Space:'SPACE', Enter:'ENTER', Tab:'TAB', Backspace:'BACKSPACE',
    Delete:'DELETE', Insert:'INSERT', Home:'HOME', End:'END',
    PageUp:'PAGE_UP', PageDown:'PAGE_DOWN',
    ArrowUp:'UP', ArrowDown:'DOWN', ArrowLeft:'LEFT', ArrowRight:'RIGHT',
    Backquote:'BACKQUOTE', Minus:'MINUS', Equal:'EQUALS',
    BracketLeft:'LEFT_BRACKET', BracketRight:'RIGHT_BRACKET',
    Semicolon:'SEMICOLON', Quote:'QUOTE', Backslash:'BACKSLASH',
    Comma:'COMMA', Period:'PERIOD', Slash:'SLASH',
    NumpadAdd:'NUMPAD_ADD', NumpadSubtract:'NUMPAD_SUBTRACT',
    NumpadMultiply:'NUMPAD_MULTIPLY', NumpadDivide:'NUMPAD_DIVIDE',
    NumpadDecimal:'NUMPAD_DECIMAL', NumpadEnter:'NUMPAD_ENTER',
  };
  const DIGIT = ['ZERO','ONE','TWO','THREE','FOUR','FIVE','SIX','SEVEN','EIGHT','NINE'];
  for (let i = 0; i < 26; i++){ const c = String.fromCharCode(65 + i); map['Key' + c] = c; }
  for (let i = 0; i < 10; i++){ map['Digit' + i] = DIGIT[i]; map['Numpad' + i] = 'NUMPAD_' + i; }
  for (let i = 1; i <= 20; i++) map['F' + i] = 'F' + i;
  return map;
})();

const MOD_KEYS = new Set(['Control','Alt','AltGraph','Shift','Meta']);
let capturing = false; const held = new Set();

function isMac(){ return !!(D && D.platform && D.platform.platform === 'darwin'); }
// macOS registers the chord with the OS, and it will only take an ordinary key
// with a modifier. Windows watches the keyboard itself and takes anything.
function needsKey(){ return !!(D && D.platform && D.platform.chord_needs_key); }

function modPreview(){
  const parts = [];
  if (held.has('Control')) parts.push('CTRL');
  if (held.has('Alt') || held.has('AltGraph')) parts.push('ALT');
  if (held.has('Shift')) parts.push('SHIFT');
  if (held.has('Meta')) parts.push('CMD');
  return parts.length ? prettyKey(parts.join('+')) + '+…' : '';
}
function startCapture(){
  capturing = true; held.clear(); actKeyMsg('');
  $('activation_key').classList.add('capturing');
}
function stopCapture(){
  capturing = false; held.clear();
  $('activation_key').classList.remove('capturing');
  setActKey(actKey());   // put the stored chord back over any half-typed preview
}
function actKeyMsg(text){
  const el = $('actkey_msg');
  el.textContent = text || '';
  el.style.display = text ? '' : 'none';
}

// Modifiers as the config spells them. Sides are kept on Windows, where the
// listener can tell them apart; macOS collapses them, so the capture there
// never produces one.
const MOD_CODE = {AltLeft:'ALT_L', AltRight:'ALT_R', ControlLeft:'CTRL_L',
  ControlRight:'CTRL_R', ShiftLeft:'SHIFT_L', ShiftRight:'SHIFT_R',
  MetaLeft:'CMD_L', MetaRight:'CMD_R'};

// What the config stores ('CTRL+ALT+D') and what a person reads
// ('Control+Option+D') are not the same string, and the second differs per OS.
// The field shows the name and keeps the stored value in dataset.v;
// setActKey/actKey are the only two places allowed to touch it.
const MOD_NAME = {ALT:'Alt', CTRL:'Ctrl', SHIFT:'Shift', CMD:'Win', META:'Win', WIN:'Win'};
const MOD_NAME_MAC = {ALT:'Option', CTRL:'Control', SHIFT:'Shift', CMD:'Command',
  META:'Command', WIN:'Command'};
const SIDE_NAME = {L:'Left', LEFT:'Left', R:'Right', RIGHT:'Right'};
const KEY_LABEL = {
  BACKQUOTE:'`', MINUS:'-', EQUALS:'=', LEFT_BRACKET:'[', RIGHT_BRACKET:']',
  SEMICOLON:';', QUOTE:"'", BACKSLASH:'\\', COMMA:',', PERIOD:'.', SLASH:'/',
  ESC:'Escape', SPACE:'Space', ENTER:'Enter', TAB:'Tab', BACKSPACE:'Backspace',
  DELETE:'Delete', INSERT:'Insert', HOME:'Home', END:'End',
  PAGE_UP:'Page Up', PAGE_DOWN:'Page Down',
  UP:'Up', DOWN:'Down', LEFT:'Left', RIGHT:'Right',
  ZERO:'0', ONE:'1', TWO:'2', THREE:'3', FOUR:'4',
  FIVE:'5', SIX:'6', SEVEN:'7', EIGHT:'8', NINE:'9',
};

function partLabel(part){
  const p = String(part).trim().toUpperCase();
  const names = isMac() ? MOD_NAME_MAC : MOD_NAME;
  const bits = p.split('_');
  if (bits.length === 2 && names[bits[0]] && SIDE_NAME[bits[1]]){
    return `${SIDE_NAME[bits[1]]} ${names[bits[0]]}`;
  }
  return names[p] || KEY_LABEL[p] || p;
}
function prettyKey(value){
  const v = String(value || '').trim();
  return v ? v.split('+').map(partLabel).join('+') : '';
}

// The chord this keystroke stands for, or null for a key we have no name for.
function chordFromEvent(e){
  const name = CODE_TO_NAME[e.code];
  if (!name) return null;
  const parts = [];
  if (e.ctrlKey) parts.push('CTRL');
  if (e.altKey) parts.push('ALT');
  if (e.shiftKey) parts.push('SHIFT');
  if (e.metaKey) parts.push('CMD');
  parts.push(name);
  return parts.join('+');
}
function setActKey(value){
  const el = $('activation_key');
  el.dataset.v = String(value || '');
  el.value = prettyKey(value);
}
function actKey(){
  const el = $('activation_key');
  return (el.dataset.v || el.value || '').trim();
}

// ── platform differences (what this OS does not have, or calls something else) ─
// Name, and the shortest true reason. Anything longer is read by nobody: what
// the user needs here is the button, not an explanation of how macOS works.
const PERM_TEXT = {
  microphone:    ['Microphone', 'to hear you'],
  accessibility: ['Accessibility', 'to type the text for you'],
};

function applyPlatform(){
  const p = D.platform || {};
  $('paste_shortcut').innerHTML = (p.paste_shortcuts || [['ctrl+v', 'Ctrl+V']])
    .map(([v, label]) => `<option value="${v}">${label}</option>`).join('');
  // Options this OS has no concept of are hidden rather than left to do nothing.
  (p.hidden_options || []).forEach(id => {
    const row = $(id) && $(id).closest('.toggle');
    if (row) row.style.display = 'none';
  });
  if (p.minimized_label){
    const t = $('start_minimized').closest('.toggle').querySelector('.t-txt');
    t.innerHTML = `${p.minimized_label} <button class="help" data-h="start_minimized">?</button>`;
  }
  if (p.show_quit) $('quit_row').style.display = '';
  if (p.startup_label){
    const txt = $('run_on_startup').closest('.toggle').querySelector('.t-txt');
    // Rebuilt before the help buttons are wired up in boot(), so the new one works.
    txt.innerHTML = `${p.startup_label} <button class="help" data-h="run_on_startup">?</button>`;
  }
  renderPermissions(D.permissions);
}

function permsMissing(perms){
  return Object.entries(perms || {})
    .filter(([k, v]) => PERM_TEXT[k] && v === false).length;
}

function renderPermissions(perms){
  const known = Object.entries(perms || {}).filter(([k, v]) => PERM_TEXT[k] && v !== null);
  if (!known.length){ $('perm_card').style.display = 'none'; return; }
  // Running from the .dmg or a translocated copy makes every grant below
  // pointless, so say that before anything else.
  const warn = $('install_warning');
  if (D.install_warning){
    warn.style.display = ''; warn.innerHTML = `<b>Move the app first.</b><br>${esc(D.install_warning)}`;
  } else { warn.style.display = 'none'; }
  // Offered whenever the OS gates anything: it is the way out of "the list says
  // it is allowed and the app says it is not".
  $('perm_reset_row').style.display = '';
  $('signing_note').textContent = D.signing_note || '';
  const missing = known.filter(([, v]) => !v);
  $('perm_card').style.display = '';
  $('perm_card').classList.toggle('needs-attention', missing.length > 0);
  $('perm_intro').textContent = missing.length
    ? 'Whisper Vox needs both of these to work. Press Allow, then switch it on in the window that opens.'
    : 'Both granted - Whisper Vox can work.';
  $('perm_list').innerHTML = known.map(([k, v]) => {
    const [name, why] = PERM_TEXT[k];
    return `<div class="row" style="align-items:center;justify-content:space-between;margin:8px 0">
      <div>${v ? '✅' : '⚠️'} <b>${name}</b> <span style="color:#8a94a3">- ${why}</span></div>
      ${v ? '' : `<button class="btn ghost sm" data-perm="${k}">Allow…</button>`}</div>`;
  }).join('');
  // The way on to the first setup step, offered only once there is nothing left
  // to grant - before that, the API key is not what the user should be doing.
  $('perm_done').style.display = missing.length ? 'none' : '';
  syncNextStep();
}

// Emphasise that link only while it is the outstanding task. With a key in
// place it stays exactly as it was - still there to click, not asking to be.
// Read from the FIELD, not the saved config, so Reset to Defaults lights it up
// at once instead of waiting for a Save that has not happened yet.
function syncNextStep(){
  $('perm_done').classList.toggle('urgent', !$('api_key').value.trim());
}

async function waitForMics(tries = 6){
  if (tries <= 0) return;
  try {
    const r = await window.pywebview.api.mics();
    if (r && r.mics && r.mics.length){
      D.mics = r.mics; D.default_mic = r.default_mic;
      fillMics(r.mics, r.default_mic, $('sound_device').value);
      baseline = JSON.stringify(collect());   // filling the list is not a user edit
      return;
    }
  } catch (e){ /* try again below */ }
  setTimeout(() => waitForMics(tries - 1), 2000);
}

async function refreshPermissions(){
  if (!D || !D.permissions || !Object.keys(D.permissions).length) return;
  try {
    D.permissions = await window.pywebview.api.permissions();
    renderPermissions(D.permissions);
  } catch (e){ /* nothing to do - leave the last known state on screen */ }
}

// ── help: hover tooltip + click modal, with **bold** rendering ─────────────────
function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function helpHTML(key){
  return esc((D && D.help && D.help[key]) || '').replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/\n/g, '<br>');
}
function showTip(btn){
  const tip = $('tip'); tip.innerHTML = helpHTML(btn.dataset.h); tip.style.display = 'block';
  const r = btn.getBoundingClientRect();
  let left = r.left; const tw = tip.offsetWidth;
  if (left + tw > window.innerWidth - 8) left = window.innerWidth - 8 - tw;
  let top = r.bottom + 6;
  if (top + tip.offsetHeight > window.innerHeight - 8) top = r.top - tip.offsetHeight - 6;
  tip.style.left = Math.max(8, left) + 'px';
  tip.style.top = Math.max(8, top) + 'px';
}
function hideTip(){ $('tip').style.display = 'none'; }
function showHelp(key){ $('help_text').innerHTML = helpHTML(key); $('help_modal').classList.add('show'); }
function showMsg(text){ $('help_text').innerHTML = esc(text).replace(/\n/g, '<br>'); $('help_modal').classList.add('show'); }
function closeModal(){ $('help_modal').classList.remove('show'); }

// ── About / Updates ───────────────────────────────────────────────────────────
function renderAbout(){
  const key = prettyKey(D.config.activation_key || D.defaults.activation_key);
  $('about_logo').src = 'wv-logo.png';  // shipped inside web/ (file:// can't traverse to ../assets)
  // Same wording trap as the hint on the first tab: "press" gets taken
  // literally, and a tapped key looks like an app that does nothing.
  const held = (D.config.recording_mode || 'hold_to_record') === 'hold_to_record';
  $('about_desc').innerHTML =
    'Voice-to-text dictation.<br>Place your cursor in any app where you type, then ' +
    `${held ? 'hold' : 'press'} your activation key (<b>${key}</b>) -> speak -> ` +
    'text is typed automatically.';
  $('about_version').textContent = `Version ${D.version}`;
  renderUpdate(D.update_available);
}
function renderUpdate(latest){
  const rel = D.links.releases;
  $('about_update').innerHTML = latest
    ? `Version ${latest} is available.<br><button class="btn primary sm" data-update="1" style="margin-top:8px">⬇ Update now</button>`
    : `You have the latest version - <a href="#" data-ext="${rel}">Whisper Vox on GitHub</a>`;
  $('update_status').textContent = latest
    ? `Whisper Vox ${latest} is available.`
    : `You have the latest version (v${D.version}).`;
  $('download_link').style.display = latest ? 'block' : 'none';
  $('download_link').innerHTML = latest
    ? `<button class="btn primary sm" data-update="1">⬇ Download &amp; install update</button>` +
      `<a href="#" data-ext="${rel}" style="margin-left:10px">or get it from GitHub</a>`
    : '';
  const ur = $('update_reminder');
  if (latest){ ur.style.display = 'block';
    ur.innerHTML = `A new version (${latest}) is available - <a href="#" data-update="1">update now</a> ` +
      `or <a href="#" data-ext="${rel}">view on GitHub</a>`; }
  else ur.style.display = 'none';
}
// One-click update where the platform can install over itself (Windows): the
// setup downloads, runs, swaps the files and relaunches, so feedback is brief.
// Everywhere else the browser opens on the releases page instead - and the
// wording has to follow, or the user waits for a restart that is never coming.
async function startUpdate(){
  const buttons = [...document.querySelectorAll('[data-update]')].filter(el => el.tagName === 'BUTTON');
  const labels = buttons.map(b => b.textContent);
  buttons.forEach(b => { b.disabled = true; b.textContent = 'Starting…'; });
  $('update_status').textContent = 'Starting the update…';
  let mode = 'browser';
  try { mode = await window.pywebview.api.start_update(); } catch (e){ /* treat as browser */ }
  if (mode === 'install'){
    buttons.forEach(b => b.textContent = 'Downloading update…');
    $('update_status').textContent = 'Downloading the update… the app will restart automatically.';
    return;
  }
  buttons.forEach((b, i) => { b.disabled = false; b.textContent = labels[i]; });
  $('update_status').textContent =
    'Opened the releases page in your browser - download the new version from there.';
}
// Shared by the "Check now" buttons on both Misc and About. renderUpdate refreshes
// every update-related element (About line, Misc status, reminders) at once.
async function runCheckUpdate(btnId){
  const btn = $(btnId), label = btn.textContent;
  $('check_now').disabled = true; $('about_check_now').disabled = true;
  btn.textContent = 'Checking…'; $('update_status').textContent = 'Checking…';
  const r = await window.pywebview.api.check_update();
  $('check_now').disabled = false; $('about_check_now').disabled = false;
  btn.textContent = label;
  if (r.ok){ D.update_available = r.latest; renderUpdate(r.latest); }
  else $('update_status').textContent = "Couldn't check for updates - try again later.";
}
// What to DO with the key, in the words of the mode that is actually selected.
// "Press it" was read literally - people tapped the key, got nothing, and
// concluded the app was broken. Holding is the default, so it has to say so.
const ACT_KEY_VERB = {
  hold_to_record: 'press and <b>hold</b> it while you speak',
  press_to_toggle: 'press it to start, press it again to stop',
  continuous: 'press it once and speak; it stops when you go quiet',
};

function updateActKeyHint(){
  const key = prettyKey(actKey() || D.defaults.activation_key);
  const verb = ACT_KEY_VERB[getSeg('recording_mode')] || ACT_KEY_VERB.hold_to_record;
  $('actkey_hint').innerHTML =
    `Activation key: <b>${key}</b> - ${verb}<br>` +
    `<span style="font-size:13px;color:#8a94a3">` +
    `<a href="#" data-goto="rec" style="color:#8a94a3">change it on the Recording tab</a></span>`;
}

// ── boot ──────────────────────────────────────────────────────────────────────
async function boot(){
  D = await window.pywebview.api.get_init_data();
  const c = D.config;

  $('provider').innerHTML = Object.entries(D.providers)
    .map(([pid, p]) => `<option value="${pid}">${p.label}</option>`).join('');
  $('language').innerHTML = `<option value="">Auto-detect</option>` +
    D.languages.map(([name, code]) => `<option value="${code}">${name}  (${code})</option>`).join('');
  applyPlatform();   // paste chord, options this OS lacks, permission card
  // The user grants permissions in System Settings, and WKWebView does not
  // reliably report the window regaining focus, so just keep asking. The call
  // is a local one - no I/O, nothing to save.
  if (Object.keys(D.permissions || {}).length) setInterval(refreshPermissions, 2000);
  // On a system that gates the app, permissions come before everything else:
  // an API key is no use while the app cannot hear you or type for you. Open
  // where the work is, and let the card itself say so.
  if (permsMissing(D.permissions)) gotoTab('misc');
  // The audio stack can take a few seconds to wake up on the first run, so the
  // list may not have existed yet when this page asked. Fill it in when it does.
  if (!D.mics || !D.mics.length) waitForMics();
  fillMics(D.mics, D.default_mic, c.sound_device);

  apiKeys = {groq:c.api_key_groq||'', openai:c.api_key_openai||'', manual:c.api_key_manual||''};
  manualUrl = c.api_url_manual || '';
  applyValues(c);
  prevProvider = $('provider').value;
  $('api_key').value = apiKeys[keySlot(prevProvider)] || (c.api_key || '');
  setKeyLink(prevProvider);
  updateActKeyHint();
  syncNextStep();   // renderPermissions ran before the key was on screen

  setToggle('start_minimized', c.start_minimized);
  setToggle('show_splash', c.show_splash);
  setToggle('enable_logging', c.enable_logging);
  setToggle('donated_hidden', c.donated_hidden);
  // visibility (not display) so the flex spacer keeps its width → Save stays right
  $('donation_reminder').style.visibility = c.donated_hidden ? 'hidden' : 'visible';

  renderAbout();
  wire();
  baseline = JSON.stringify(collect());
  markDirty();
}

// ── wiring ────────────────────────────────────────────────────────────────────
function wire(){
  document.querySelectorAll('.nav button').forEach(b => b.onclick = () => gotoTab(b.dataset.t));
  document.querySelectorAll('.content input, .content select, .content textarea').forEach(el => {
    el.addEventListener('input', markDirty); el.addEventListener('change', markDirty);
  });
  $('api_key').addEventListener('input', syncNextStep);
  $('provider').addEventListener('change', onProviderChange);
  $('language').addEventListener('change', async () => {
    $('initial_prompt').value = await window.pywebview.api.default_prompt_for($('language').value);
    markDirty();
  });
  $('key_toggle').onclick = () => {
    const f = $('api_key');
    if (f.type === 'password'){ f.type = 'text'; $('key_toggle').textContent = 'Hide'; }
    else { f.type = 'password'; $('key_toggle').textContent = 'Show'; }
  };
  $('refresh_models').onclick = async () => {
    $('refresh_models').textContent = 'Refreshing…'; $('refresh_models').disabled = true;
    const r = await window.pywebview.api.refresh_models($('api_url').value.trim(), $('api_key').value.trim());
    $('refresh_models').disabled = false;
    if (r.ok && r.models && r.models.length){ fillModel(r.models, $('model').value); $('refresh_models').textContent = '✓ Updated'; markDirty(); }
    else { $('refresh_models').textContent = '↻ Refresh'; showMsg(r.error || 'The provider returned no speech-to-text models.'); }
  };
  document.querySelectorAll('.seg').forEach(seg => seg.querySelectorAll('button').forEach(btn => {
    btn.onclick = () => { seg.querySelectorAll('button').forEach(x => x.classList.remove('on'));
      btn.classList.add('on');
      syncRecMode(); syncInputMethod(); updateActKeyHint(); markDirty(); };
  }));
  // Recording-sound picker: clicking a choice also auditions it (fires alongside
  // the generic .seg select/markDirty handler above).
  $('recording_sound').querySelectorAll('button').forEach(btn => {
    btn.addEventListener('click', () => window.pywebview.api.preview_sound(btn.dataset.v));
  });
  TRACKED_TOGGLES.forEach(id => $(id).onclick = () => { $(id).classList.toggle('on'); markDirty(); });
  // Grey out the sound picker when the recording-start cue is off.
  $('noise_on_recording').addEventListener('click', syncRecSound);
  $('start_minimized').onclick = () => { $('start_minimized').classList.toggle('on');
    window.pywebview.api.set_start_minimized(getToggle('start_minimized')); };
  $('show_splash').onclick = () => { $('show_splash').classList.toggle('on');
    window.pywebview.api.set_show_splash(getToggle('show_splash')); };
  $('enable_logging').onclick = () => { $('enable_logging').classList.toggle('on');
    window.pywebview.api.set_enable_logging(getToggle('enable_logging')); };
  $('donated_hidden').onclick = () => { $('donated_hidden').classList.toggle('on');
    const hidden = getToggle('donated_hidden');
    window.pywebview.api.set_donated_hidden(hidden);
    $('donation_reminder').style.visibility = hidden ? 'hidden' : 'visible'; };
  $('quit_app').onclick = () => { window.pywebview.api.quit_app(); };
  $('perm_reset').onclick = async () => {
    $('perm_reset').disabled = true;
    $('perm_reset_msg').textContent = 'Clearing…';
    const r = await window.pywebview.api.reset_permissions();
    $('perm_reset').disabled = false;
    $('perm_reset_msg').textContent = r && r.ok
      ? 'Cleared. Quit Whisper Vox, start it again, and allow them once more.'
      : 'Nothing was recorded to clear.';
    refreshPermissions();
  };
  $('rescan_mics').onclick = async () => {
    const r = await window.pywebview.api.rescan_mics();
    fillMics(r.mics, r.default_mic, $('sound_device').value); markDirty();
  };
  // activation key capture
  const keyEl = $('activation_key');
  keyEl.addEventListener('focus', startCapture);
  keyEl.addEventListener('blur', stopCapture);
  keyEl.addEventListener('keydown', (e) => {
    if (!capturing) return;
    e.preventDefault();
    if (MOD_KEYS.has(e.key)){ held.add(e.key); keyEl.value = modPreview(); return; }
    const noMods = !(e.ctrlKey || e.altKey || e.shiftKey || e.metaKey);
    // Escape alone backs out of capturing. With a modifier it is a chord like
    // any other - and a good one, since Escape types nothing.
    if (e.code === 'Escape' && noMods){ stopCapture(); keyEl.blur(); return; }
    const chord = chordFromEvent(e);
    if (!chord){ actKeyMsg('That key cannot be used - try another.'); return; }
    // A bare key is taken globally away from every app, so on macOS only the
    // F-row (which types nothing) may be used without a modifier.
    if (needsKey() && noMods && !/^F\d{1,2}$/.test(CODE_TO_NAME[e.code])){
      actKeyMsg('Hold Control, Option, Shift or Command as well - on its own '
        + 'this key would stop working everywhere else.');
      return;
    }
    setActKey(chord); stopCapture(); keyEl.blur(); updateActKeyHint(); markDirty();
  });
  keyEl.addEventListener('keyup', (e) => {
    if (!capturing) return;
    held.delete(e.key);
    // Released a modifier and nothing else is down -> take it as the key itself.
    // macOS cannot register a bare modifier as a hotkey, so there it is refused
    // rather than stored as a chord that would never fire.
    const bare = MOD_CODE[e.code];
    if (bare && !held.size){
      if (needsKey()){
        actKeyMsg('A modifier on its own cannot be used here - press it '
          + 'together with a key, for example Control+Option+D.');
        keyEl.value = '';
        return;
      }
      setActKey(bare);
      stopCapture(); keyEl.blur(); updateActKeyHint(); markDirty();
      return;
    }
    keyEl.value = modPreview();
  });
  // help: hover tooltip + click modal
  document.querySelectorAll('.help').forEach(b => {
    b.addEventListener('mouseenter', () => showTip(b));
    b.addEventListener('mouseleave', hideTip);
    b.addEventListener('click', (e) => { e.preventDefault(); hideTip(); showHelp(b.dataset.h); });
  });
  $('help_ok').onclick = closeModal;
  $('help_modal').onclick = (e) => { if (e.target === $('help_modal')) closeModal(); };
  // goto-tab + external links (delegated)
  document.body.addEventListener('click', (e) => {
    const g = e.target.closest('[data-goto]'); if (g){ e.preventDefault(); gotoTab(g.dataset.goto); return; }
    const u = e.target.closest('[data-update]'); if (u){ e.preventDefault(); startUpdate(); return; }
    const perm = e.target.closest('[data-perm]');
    if (perm){
      e.preventDefault();
      perm.disabled = true; perm.textContent = 'Opening…';
      window.pywebview.api.request_permission(perm.dataset.perm).then(() => {
        // The user grants it in System Settings, so the answer arrives whenever
        // they come back - refresh now and again on focus.
        setTimeout(refreshPermissions, 1500);
      });
      return;
    }
    const x = e.target.closest('[data-ext]'); if (x){ e.preventDefault(); window.pywebview.api.open_url(x.dataset.ext); }
  });
  $('open_log').onclick = async () => { const r = await window.pywebview.api.open_log();
    if (!r.ok) showMsg('No log yet.\n\nTick "Write Log File", use the app for a bit, then open it here.'); };
  $('check_now').onclick = () => runCheckUpdate('check_now');
  $('about_check_now').onclick = () => runCheckUpdate('about_check_now');
  $('copy_link').onclick = async () => { await window.pywebview.api.copy_repo_link();
    $('copy_link').textContent = '✓ Copied'; setTimeout(() => $('copy_link').textContent = '⧉ Copy link', 1500); };
  $('feedback_link').onclick = (e) => { e.preventDefault(); window.pywebview.api.open_url(D.links.issues); };
  $('donate_btn').onclick = () => window.pywebview.api.open_url(DONATE_REAL);
  $('save_btn').onclick = onSave;
  $('reset_btn').onclick = onReset;
}

function gotoTab(t){
  document.querySelectorAll('.nav button').forEach(b => b.classList.toggle('active', b.dataset.t === t));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.dataset.p === t));
}

async function onSave(){
  const data = collect();
  $('save_btn').disabled = true;
  try {
    const r = await window.pywebview.api.save_config(data);
    if (r && r.ok){ baseline = JSON.stringify(collect()); markDirty(); flashSaved(); }
    else { showMsg((r && r.error) || 'Save failed.'); markDirty(); }
  } catch (e) {
    showMsg('Save failed: ' + e); markDirty();
  }
}
function onReset(){
  apiKeys = {groq:'', openai:'', manual:''}; manualUrl = '';
  applyValues(D.defaults);
  prevProvider = $('provider').value;
  $('api_key').value = '';
  setKeyLink(prevProvider);
  updateActKeyHint();
  syncNextStep();
  // Instant-save Misc toggles are excluded from TRACKED_TOGGLES (they persist on
  // click, not via Save), so applyValues() doesn't touch them. Reset them here
  // too — set the default visually AND persist it via their bridge. donated_hidden
  // is intentionally left alone (resetting a donation reminder on Reset is odd).
  setToggle('start_minimized', D.defaults.start_minimized);
  window.pywebview.api.set_start_minimized(D.defaults.start_minimized);
  setToggle('show_splash', D.defaults.show_splash);
  window.pywebview.api.set_show_splash(D.defaults.show_splash);
  setToggle('enable_logging', D.defaults.enable_logging);
  window.pywebview.api.set_enable_logging(D.defaults.enable_logging);
  markDirty();
}
function flashSaved(){ const s = $('saved_msg'); s.classList.add('show'); setTimeout(() => s.classList.remove('show'), 2000); }

// The bridge must NOT be called during load - defer until just after ready.
window.addEventListener('pywebviewready', () => setTimeout(() => {
  boot().catch(e => showMsg('Failed to load settings: ' + e));
}, 60));
