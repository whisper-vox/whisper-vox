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
  'remove_capitalization','hide_status_window','noise_on_completion','desktop_icon',
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
    activation_key: $('activation_key').value.trim(),
    recording_mode: getSeg('recording_mode'),
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
  $('activation_key').value = String(c.activation_key || '').toUpperCase();
  setSeg('recording_mode', c.recording_mode || 'hold_to_record');
  selectByValue('sound_device', c.sound_device || '');
  $('silence_duration').value = (c.silence_duration ?? '');
  $('min_duration').value = (c.min_duration ?? '');
  setSeg('input_method', c.input_method || 'clipboard');
  selectByValue('paste_shortcut', c.paste_shortcut || 'ctrl+v');
  $('paste_delay_ms').value = (c.paste_delay_ms ?? '');
  $('writing_key_press_delay').value = (c.writing_key_press_delay ?? '');
  TRACKED_TOGGLES.forEach(k => setToggle(k, c[k]));
  syncRecMode(); syncInputMethod();
}

// ── dependent-field enabling ──────────────────────────────────────────────────
function syncRecMode(){ $('silence_duration').disabled = (getSeg('recording_mode') !== 'continuous'); }
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
let capturing = false; const held = new Set();
function keyToStr(e){
  const k = e.key;
  if (/^F\d{1,2}$/.test(k)) return k.toLowerCase();
  if (k.length === 1 && /[a-z]/i.test(k)) return k.toLowerCase();
  if (/^[0-9]$/.test(k)) return k;
  const map = {' ':'space','Spacebar':'space','Enter':'enter','Backspace':'backspace',
    'Delete':'delete','Tab':'tab','Home':'home','End':'end','PageUp':'page_up',
    'PageDown':'page_down','ArrowLeft':'left','ArrowRight':'right','ArrowUp':'up',
    'ArrowDown':'down','Insert':'insert','Pause':'pause'};
  return map[k] || null;
}
function modPreview(){
  const parts = [];
  if (held.has('Control')) parts.push('CTRL');
  if (held.has('Alt') || held.has('AltGraph')) parts.push('ALT');
  if (held.has('Shift')) parts.push('SHIFT');
  if (held.has('Meta')) parts.push('WIN');
  return parts.length ? parts.join('+') + '+…' : '';
}
function startCapture(){ capturing = true; held.clear(); $('activation_key').classList.add('capturing'); }
function stopCapture(){ capturing = false; held.clear(); $('activation_key').classList.remove('capturing'); }

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
  const key = String(D.config.activation_key || 'f2').toUpperCase();
  $('about_logo').src = 'wv-logo.png';  // shipped inside web/ (file:// can't traverse to ../assets)
  $('about_desc').innerHTML =
    'Voice-to-text dictation.<br>Place your cursor in any app where you type, then press your ' +
    `activation key (<b>${key}</b>) -> speak -> text is typed automatically.`;
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
// One-click update: download the official setup + run it. The app then closes
// (the setup asks it to quit, swaps files, relaunches), so feedback is brief.
function startUpdate(){
  document.querySelectorAll('[data-update]').forEach(el => {
    if (el.tagName === 'BUTTON'){ el.disabled = true; el.textContent = 'Downloading update…'; }
  });
  $('update_status').textContent = 'Downloading the update… the app will restart automatically.';
  window.pywebview.api.start_update();
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
function updateActKeyHint(){
  const key = ($('activation_key').value.trim() || 'F2').toUpperCase();
  $('actkey_hint').innerHTML =
    `Activation key: <b>${key}</b> - press it to start dictation<br>` +
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
  $('paste_shortcut').innerHTML =
    `<option value="ctrl+v">Ctrl+V</option><option value="shift+insert">Shift+Insert</option>`;
  fillMics(D.mics, D.default_mic, c.sound_device);

  apiKeys = {groq:c.api_key_groq||'', openai:c.api_key_openai||'', manual:c.api_key_manual||''};
  manualUrl = c.api_url_manual || '';
  applyValues(c);
  prevProvider = $('provider').value;
  $('api_key').value = apiKeys[keySlot(prevProvider)] || (c.api_key || '');
  setKeyLink(prevProvider);
  updateActKeyHint();

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
      btn.classList.add('on'); syncRecMode(); syncInputMethod(); markDirty(); };
  }));
  TRACKED_TOGGLES.forEach(id => $(id).onclick = () => { $(id).classList.toggle('on'); markDirty(); });
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
  $('rescan_mics').onclick = async () => {
    const r = await window.pywebview.api.rescan_mics();
    fillMics(r.mics, r.default_mic, $('sound_device').value); markDirty();
  };
  // activation key capture
  const keyEl = $('activation_key');
  keyEl.addEventListener('focus', startCapture);
  keyEl.addEventListener('blur', stopCapture);
  keyEl.addEventListener('keydown', (e) => {
    if (!capturing) return; e.preventDefault();
    if (e.key === 'Escape'){ stopCapture(); keyEl.blur(); return; }
    if (['Control','Alt','AltGraph','Shift','Meta'].includes(e.key)){ held.add(e.key); keyEl.value = modPreview(); return; }
    const ks = keyToStr(e); if (!ks) return;
    const parts = [];
    if (e.ctrlKey) parts.push('CTRL'); if (e.altKey) parts.push('ALT');
    if (e.shiftKey) parts.push('SHIFT'); if (e.metaKey) parts.push('WIN');
    parts.push(ks.toUpperCase());
    keyEl.value = parts.join('+'); stopCapture(); keyEl.blur(); updateActKeyHint(); markDirty();
  });
  keyEl.addEventListener('keyup', (e) => { if (!capturing) return; held.delete(e.key); keyEl.value = modPreview(); });
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
