"""Trang chat của `qctool ui` (đường dẫn `/`). Bảng điều khiển chi tiết cũ ở `/console`.

HTML/JS tĩnh, không template: dữ liệu đến từ `/api/chat/*` (logic ở `web/chat.py`).
"""

CHAT_PAGE = r"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>qc-tool · Trợ lý QC</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --ink: #1d2330; --muted: #6b7280; --line: #e3e6eb;
  --accent: #2f6fde; --accent-ink: #ffffff; --user: #2f6fde; --user-ink: #ffffff;
  --ok: #1f8a4c; --bad: #c43d3d; --warn: #a86a00; --warn-bg: #fff6e0; --bad-bg: #fdecec; --ok-bg: #e7f6ee;
  --chip: #eef1f6; --code: #f1f3f6;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #12151b; --panel: #1a1f27; --ink: #e5e8ee; --muted: #9aa3b2; --line: #2a313c;
    --accent: #5b8ff0; --user: #3d6fd0; --chip: #232a35; --code: #232a35;
    --warn-bg: #3a2f14; --bad-bg: #3b1d1d; --ok-bg: #16331f; --warn: #f0b84a; --bad: #f07a7a; --ok: #5cc98a;
  }
}
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body { background: var(--bg); color: var(--ink); font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
a { color: var(--accent); }
button { font: inherit; cursor: pointer; border-radius: 8px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); padding: 7px 12px; }
button.primary { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); }
button:disabled { opacity: .55; cursor: default; }
input, select, textarea { font: inherit; color: var(--ink); background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; width: 100%; }
.muted { color: var(--muted); }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font-size: 13px; }
.app { display: grid; grid-template-columns: 260px 1fr; height: 100%; }
.side { border-right: 1px solid var(--line); background: var(--panel); display: flex; flex-direction: column; min-height: 0; }
.side .top { padding: 14px; border-bottom: 1px solid var(--line); display: grid; gap: 8px; }
.brand { font-weight: 700; font-size: 17px; }
.brand small { font-weight: 400; color: var(--muted); }
.sessions { overflow-y: auto; padding: 8px; flex: 1; }
.sess { padding: 8px 10px; border-radius: 8px; cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 14px; }
.sess:hover { background: var(--chip); }
.sess.on { background: var(--chip); font-weight: 600; }
.side .foot { padding: 12px 14px; border-top: 1px solid var(--line); font-size: 13px; display: grid; gap: 4px; }
.main { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.head { display: flex; gap: 10px; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--line); background: var(--panel); flex-wrap: wrap; }
.head .title { font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--chip); color: var(--muted); white-space: nowrap; }
.badge.ok { background: var(--ok-bg); color: var(--ok); }
.badge.bad { background: var(--bad-bg); color: var(--bad); }
.menu { display: none; }
.msgs { flex: 1; overflow-y: auto; padding: 20px 16px 8px; }
.wrap { max-width: 860px; margin: 0 auto; display: grid; gap: 10px; }
.bubble { padding: 10px 14px; border-radius: 14px; max-width: 85%; overflow-wrap: anywhere; }
.u { justify-self: end; background: var(--user); color: var(--user-ink); border-bottom-right-radius: 4px; white-space: pre-wrap; }
.a { justify-self: start; background: var(--panel); border: 1px solid var(--line); border-bottom-left-radius: 4px; }
.a p { margin: 0 0 6px; } .a p:last-child { margin: 0; } .a ul, .a ol { margin: 4px 0 6px; padding-left: 20px; }
.meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
.tool { font-size: 13px; color: var(--muted); padding-left: 6px; }
.tool.err { color: var(--bad); }
.note { justify-self: center; font-size: 13px; color: var(--muted); background: var(--chip); padding: 4px 12px; border-radius: 999px; text-align: center; }
.note.error { background: var(--bad-bg); color: var(--bad); border-radius: 10px; }
.thinking { font-size: 13px; color: var(--muted); display: flex; gap: 8px; align-items: center; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 1s infinite alternate; }
@keyframes pulse { from { opacity: .25 } to { opacity: 1 } }
.plan { background: var(--panel); border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 12px; padding: 14px 16px; display: grid; gap: 10px; }
.plan h3 { margin: 0; font-size: 16px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.plan .why { color: var(--muted); font-size: 13px; }
.items { display: grid; gap: 6px; }
.item { border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; }
.item summary { cursor: pointer; display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; list-style: none; }
.item summary::-webkit-details-marker { display: none; }
.item .n { color: var(--muted); font-variant-numeric: tabular-nums; }
.item table { width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 6px; }
.item td { border-top: 1px solid var(--line); padding: 4px 6px; vertical-align: top; }
.warns { display: grid; gap: 4px; }
.warn { background: var(--warn-bg); color: var(--warn); padding: 6px 10px; border-radius: 8px; font-size: 13px; }
.oos { font-size: 13px; color: var(--muted); }
.actions { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.case { border-top: 1px dashed var(--line); padding: 6px 0 2px; display: grid; gap: 6px; }
.shots { display: flex; gap: 8px; flex-wrap: wrap; }
.shots img { height: 120px; max-width: 100%; border: 1px solid var(--line); border-radius: 6px; object-fit: cover; object-position: top; }
.sens { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; font-size: 14px; align-items: start; }
.sens input { width: auto; margin-top: 4px; }
.sens small { grid-column: 2; color: var(--muted); font-size: 12px; }
.runrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 14px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip { font-size: 12px; padding: 2px 8px; border-radius: 999px; background: var(--chip); }
.chip.Pass { background: var(--ok-bg); color: var(--ok); } .chip.Fail { background: var(--bad-bg); color: var(--bad); }
.chip.Blocked { background: var(--warn-bg); color: var(--warn); }
.composer { border-top: 1px solid var(--line); background: var(--panel); padding: 10px 16px 14px; }
.composer .wrap { grid-template-columns: auto 1fr auto; align-items: end; gap: 8px; }
.composer textarea { resize: none; min-height: 44px; max-height: 180px; }
.hint { font-size: 12px; color: var(--muted); max-width: 860px; margin: 6px auto 0; }
.welcome { text-align: center; padding: 40px 10px; color: var(--muted); }
.welcome h2 { color: var(--ink); margin: 0 0 6px; }
.sugg { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; margin-top: 16px; }
.sugg button { font-size: 14px; }
.drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(440px, 100%); background: var(--panel); border-left: 1px solid var(--line); transform: translateX(100%); transition: transform .2s; z-index: 20; display: flex; flex-direction: column; }
.drawer.on { transform: none; box-shadow: -8px 0 30px rgba(0,0,0,.15); }
.drawer .dh { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; border-bottom: 1px solid var(--line); font-weight: 600; }
.drawer .db { overflow-y: auto; padding: 14px 16px 30px; display: grid; gap: 18px; }
.sec { display: grid; gap: 8px; }
.sec h4 { margin: 0; font-size: 14px; }
.sec label { font-size: 13px; color: var(--muted); display: grid; gap: 4px; }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.drop { border: 2px dashed var(--line); border-radius: 10px; padding: 18px; text-align: center; color: var(--muted); cursor: pointer; font-size: 14px; }
.drop.over { border-color: var(--accent); color: var(--accent); }
.flist { font-size: 13px; display: grid; gap: 4px; }
.sec label.chk { display: flex; gap: 8px; align-items: center; color: var(--ink); }
.chk input { width: auto; }
.fcfg { display: grid; gap: 8px; border-top: 1px solid var(--line); padding-top: 10px; }
.acrow { display: grid; gap: 4px; padding: 8px; border: 1px solid var(--line); border-radius: 8px; font-size: 13px; }
.acrow.on { border-color: var(--accent); }
.acrow .acx { color: var(--muted); }
.acrow input.tv { font-size: 13px; padding: 6px 8px; }
details.adv summary { cursor: pointer; font-size: 13px; color: var(--muted); }
details.adv textarea { font-family: ui-monospace, monospace; font-size: 12px; min-height: 180px; margin: 6px 0; }
.msg-ok { color: var(--ok); font-size: 13px; } .msg-err { color: var(--bad); font-size: 13px; white-space: pre-wrap; }
.scrim { position: fixed; inset: 0; background: rgba(0,0,0,.25); z-index: 15; display: none; }
.scrim.on { display: block; }
@media (max-width: 760px) {
  .app { grid-template-columns: 1fr; }
  .side { position: fixed; top: 0; bottom: 0; left: 0; width: 260px; z-index: 18; transform: translateX(-100%); transition: transform .2s; }
  .side.on { transform: none; }
  .menu { display: inline-block; }
  #b-web { display: none; }
  .bubble { max-width: 94%; }
  .row2 { grid-template-columns: 1fr; }
  .msgs, .composer, .head { padding-left: 16px; padding-right: 16px; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="side" id="side">
    <div class="top">
      <div class="brand">qc-tool <small>trợ lý QC</small></div>
      <select id="project" aria-label="Project"></select>
      <button class="primary" id="new-chat">+ Cuộc trò chuyện mới</button>
    </div>
    <div class="sessions" id="sessions"></div>
    <div class="foot">
      <a href="/console" target="_blank">Bảng điều khiển chi tiết ↗</a>
      <span class="muted" id="llm-state"></span>
    </div>
  </aside>
  <main class="main">
    <div class="head">
      <button class="menu" id="menu" aria-label="Menu">☰</button>
      <div class="title" id="title">qc-tool</div>
      <span class="badge" id="b-web"></span>
      <span class="badge" id="b-acc"></span>
      <button id="open-input">📎 Dữ liệu đầu vào</button>
    </div>
    <div class="msgs" id="msgs"><div class="wrap" id="list"></div></div>
    <div class="composer">
      <div class="wrap">
        <button id="attach" title="Tải tài liệu, nhập URL và tài khoản">📎</button>
        <textarea id="text" rows="1" placeholder="Muốn test gì? Ví dụ: test luồng mua hàng từ đăng nhập tới thanh toán"></textarea>
        <button class="primary" id="send">Gửi</button>
      </div>
      <div class="hint">Trợ lý chỉ lập kế hoạch từ tài liệu đã tải; bạn duyệt rồi bấm <b>▶ Chạy QC</b> trên thẻ kế hoạch. Enter để gửi, Shift+Enter xuống dòng.</div>
    </div>
  </main>
</div>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer" aria-label="Dữ liệu đầu vào">
  <div class="dh"><span>Dữ liệu đầu vào</span><button id="close-input">✕</button></div>
  <div class="db">
    <div class="sec">
      <h4>1. Project và địa chỉ hệ thống</h4>
      <label>Project <select id="d-project"></select></label>
      <label id="d-newname-wrap">Tên project mới (chữ thường, số, - _) <input id="d-newname" placeholder="vd: salonhub"></label>
      <label>URL web <input id="d-web" placeholder="https://app.example.com"></label>
      <label>URL API (nếu khác web) <input id="d-api" placeholder="https://api.example.com"></label>
      <div class="row2">
        <label>Ảnh bằng chứng <select id="d-evidence"><option value="on-fail">Chỉ case lỗi</option><option value="always">Mọi case</option><option value="off">Tắt</option></select></label>
        <label>Timeout mỗi bước (giây) <input id="d-timeout" type="number" min="1" max="600" value="30"></label>
      </div>
      <label class="chk"><input type="checkbox" id="d-trace"> Lưu trace Playwright (xem lại từng bước)</label>
      <div class="actions"><button class="primary" id="d-save-proj">Lưu project</button><span id="d-proj-msg"></span></div>
      <details class="adv" id="d-proj-adv" hidden><summary>Nâng cao: sửa project.yaml (safe_controls, write.deny…)</summary>
        <textarea id="d-proj-yaml" spellcheck="false"></textarea>
        <div class="actions"><button id="d-save-proj-yaml">Lưu YAML</button><span id="d-proj-yaml-msg"></span></div>
      </details>
    </div>
    <div class="sec">
      <h4>2. Tài liệu yêu cầu</h4>
      <label>Chức năng (feature) <select id="d-feature"></select></label>
      <label id="d-newfeat-wrap">Tên chức năng mới <input id="d-newfeat" placeholder="vd: dang-nhap"></label>
      <div class="drop" id="drop">Thả file vào đây hoặc bấm để chọn<br><small>URD/SRS (.md), OpenAPI (.yaml/.json) — tên chứa “urd”, “srs”, “openapi” được tự nhận</small></div>
      <input type="file" id="files" multiple accept=".md,.yaml,.yml,.json" hidden>
      <div id="d-doc-msg"></div>
      <div class="flist" id="d-feats"></div>
      <div class="fcfg" id="d-featcfg" hidden></div>
    </div>
    <div class="sec">
      <h4>3. Tài khoản test</h4>
      <div class="row2">
        <label>Email / username <input id="d-user" autocomplete="off"></label>
        <label>Mật khẩu <input id="d-pass" type="password" autocomplete="new-password"></label>
      </div>
      <label>Vai trò tài khoản (lưu vào project) <select id="d-role"><option value="">— chưa chọn —</option>
        <option>customer</option><option>staff</option><option>admin</option><option>warehouse_staff</option><option>service_staff</option><option>accountant</option></select></label>
      <div class="actions"><button id="d-save-acc">Lưu vào .env</button><span id="d-acc-msg"></span></div>
      <small class="muted">Chỉ lưu trong <code>.env</code> trên máy này; không đưa vào chat hay gửi cho model. Chỉ AC khai trong <code>account.login_for</code> của feature mới được dùng tài khoản thật.</small>
    </div>
    <div class="sec">
      <h4>4. Mô hình AI (LLM)</h4>
      <div id="d-llm-state"></div>
      <label>Base URL <input id="d-llm-url" placeholder="https://api.deepseek.com/v1"></label>
      <div class="row2">
        <label>Model <input id="d-llm-model" placeholder="deepseek-chat"></label>
        <label>API key <input id="d-llm-key" type="password" autocomplete="new-password"></label>
      </div>
      <div class="actions"><button id="d-save-llm">Lưu</button><button id="d-test-llm">Kiểm tra</button><span id="d-llm-msg"></span></div>
    </div>
  </div>
</aside>
<script>
const $ = id => document.getElementById(id);
const S = { project: '', session: null, data: null, timer: null, status: null, catalog: null };
const store = { get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} } };
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
async function api(path, body) {
  const opt = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  const r = await fetch(path, opt);
  const d = await r.json().catch(() => ({error: 'Máy chủ trả dữ liệu lạ (' + r.status + ')'}));
  if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
  return d;
}
function md(text) {
  const lines = esc(text).split('\n'); let out = '', list = '';
  const inline = s => s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  for (const raw of lines) {
    const ul = /^\s*[-*•]\s+(.*)/.exec(raw), ol = /^\s*\d+[.)]\s+(.*)/.exec(raw);
    const kind = ul ? 'ul' : ol ? 'ol' : '';
    if (list && kind !== list) { out += '</' + list + '>'; list = ''; }
    if (kind) { if (!list) { out += '<' + kind + '>'; list = kind; } out += '<li>' + inline((ul || ol)[1]) + '</li>'; }
    else if (raw.trim()) out += '<p>' + inline(raw) + '</p>';
  }
  return out + (list ? '</' + list + '>' : '');
}
const SCOPE = {system: 'Cả hệ thống', feature: 'Chức năng', requirement: 'Yêu cầu cụ thể', flow: 'Luồng nghiệp vụ'};
const PLAN_STATE = {proposed: 'Chờ duyệt', running: 'Đang chạy', done: 'Đã chạy xong', cancelled: 'Đã bỏ', interrupted: 'Bị ngắt (ui đã tắt)'};
const ICON = {list_features: '📚', get_requirements: '📄', search_requirements: '🔎', propose_test_plan: '🗺', get_last_results: '📊'};

// ── Khởi động ──
async function boot() {
  try { S.status = await api('/api/chat/status'); } catch (e) { $('list').innerHTML = '<div class="note error">' + esc(e.message) + '</div>'; return; }
  const names = S.status.projects.map(p => p.name);
  const saved = store.get('qc.project');
  S.project = names.includes(saved) ? saved : (names[0] || '');
  fillProjects();
  $('llm-state').textContent = S.status.llm_ready ? 'LLM: đã cấu hình' : 'LLM: chưa cấu hình';
  if (!S.project) { renderWelcome(); return; }
  await selectProject(S.project);
}
function fillProjects() {
  const names = S.status.projects.map(p => p.name);
  $('project').innerHTML = names.map(n => '<option' + (n === S.project ? ' selected' : '') + '>' + esc(n) + '</option>').join('')
    + '<option value="__new">+ Project mới…</option>';
  $('d-project').innerHTML = names.map(n => '<option' + (n === S.project ? ' selected' : '') + '>' + esc(n) + '</option>').join('')
    + '<option value="__new"' + (S.project ? '' : ' selected') + '>+ Project mới…</option>';
  $('d-newname-wrap').style.display = S.project ? 'none' : '';
}
async function selectProject(name) {
  S.project = name; store.set('qc.project', name);
  try { S.catalog = await api('/api/chat/catalog?project=' + encodeURIComponent(name)); } catch (e) { S.catalog = null; }
  renderHead();
  const list = await api('/api/chat/sessions?project=' + encodeURIComponent(name)).catch(() => []);
  renderSessions(list);
  const want = store.get('qc.session.' + name);
  const pick = list.find(s => s.id === want) || list[0];
  if (pick) await openSession(pick.id); else { S.session = null; S.data = null; renderMessages(); }
}
function renderHead() {
  const c = S.catalog;
  $('title').textContent = S.project ? S.project + (S.data ? ' · ' + S.data.title : '') : 'qc-tool';
  $('b-web').textContent = c && (c.web || c.api) ? (c.web || c.api).replace(/^https?:\/\//, '') : 'chưa có URL';
  $('b-web').className = 'badge ' + (c && (c.web || c.api) ? 'ok' : 'bad');
  $('b-acc').textContent = c && c.account_set ? 'có tài khoản test' : 'chưa có tài khoản';
  $('b-acc').className = 'badge ' + (c && c.account_set ? 'ok' : '');
}
function renderSessions(list) {
  $('sessions').innerHTML = list.length ? list.map(s => '<div class="sess' + (S.session === s.id ? ' on' : '') + '" data-id="' + esc(s.id) + '" title="' + esc(s.title) + '">' + esc(s.title || '(trống)') + '</div>').join('')
    : '<div class="muted" style="padding:8px;font-size:13px">Chưa có cuộc trò chuyện.</div>';
  document.querySelectorAll('.sess').forEach(el => el.onclick = () => { openSession(el.dataset.id); $('side').classList.remove('on'); });
}
async function refreshSessions() {
  renderSessions(await api('/api/chat/sessions?project=' + encodeURIComponent(S.project)).catch(() => []));
}
async function openSession(id) {
  S.session = id; store.set('qc.session.' + S.project, id);
  await refresh();
  document.querySelectorAll('.sess').forEach(el => el.classList.toggle('on', el.dataset.id === id));
}
async function newSession() {
  if (!S.project) { openDrawer(); return null; }
  const d = await api('/api/chat/new', {project: S.project});
  S.session = d.id; S.data = d; store.set('qc.session.' + S.project, d.id);
  await refreshSessions(); renderMessages(); renderHead();
  return d.id;
}

// ── Vẽ cuộc trò chuyện ──
function renderWelcome() {
  const has = S.catalog && S.catalog.features.length;
  const feats = has ? S.catalog.features.map(f => f.title).slice(0, 3) : [];
  const ideas = has ? ['Test toàn bộ hệ thống', 'Test chức năng ' + (feats[0] || ''), 'Test luồng nghiệp vụ chính từ đầu tới cuối', 'Lần chạy gần nhất có lỗi gì?']
                    : [];
  $('list').innerHTML = '<div class="welcome"><h2>Muốn kiểm thử gì hôm nay?</h2>'
    + (has ? '<div>Project <b>' + esc(S.project) + '</b> có ' + S.catalog.features.length + ' chức năng, '
        + S.catalog.features.reduce((a, f) => a + f.ac_count, 0) + ' tiêu chí chấp nhận (AC).</div>'
        + '<div class="sugg">' + ideas.map(t => '<button data-t="' + esc(t) + '">' + esc(t) + '</button>').join('') + '</div>'
      : '<div>Bắt đầu bằng cách tạo project, nhập URL hệ thống và tải tài liệu yêu cầu (URD/SRS/OpenAPI).</div>'
        + '<div class="sugg"><button class="primary" id="w-input">📎 Mở Dữ liệu đầu vào</button></div>')
    + (S.status && !S.status.llm_ready ? '<div class="warn" style="margin-top:16px">Chưa cấu hình LLM — điền mục 4 trong Dữ liệu đầu vào.</div>' : '')
    + '</div>';
  document.querySelectorAll('.sugg button[data-t]').forEach(b => b.onclick = () => { $('text').value = b.dataset.t; sendMessage(); });
  if ($('w-input')) $('w-input').onclick = openDrawer;
}
// Bằng chứng một testcase: ảnh (bấm để phóng to), trace (mở Playwright Trace Viewer trên máy này).
function caseEvidence(c) {
  const ev = c.evidence || [];
  const pngs = ev.filter(f => f.endsWith('.png')), traces = ev.filter(f => f.endsWith('.trace.zip'));
  const dl = f => '/api/download?inline=1&path=' + encodeURIComponent(f);
  return '<div class="case"><div class="runrow"><span class="chip ' + esc(String(c.status).replace(' ', '')) + '">' + esc(c.status) + '</span><code>' + esc(c.case_id) + '</code> ' + esc(c.title) + '</div>'
    + (pngs.length ? '<div class="shots">' + pngs.map(f => '<a href="' + dl(f) + '" target="_blank" title="' + esc(f.split('/').pop()) + '"><img src="' + dl(f) + '" alt="' + esc(f.split('/').pop()) + '" loading="lazy"></a>').join('') + '</div>' : '')
    + '<div class="actions">' + traces.map(f => '<button data-trace="' + esc(f) + '">▶ Mở trace Playwright</button><a href="/api/download?path=' + encodeURIComponent(f) + '">tải .trace.zip</a>').join('')
    + (!pngs.length && !traces.length ? '<span class="muted" style="font-size:13px">Không có ảnh/trace — bật ui.evidence: always / ui.trace: true trong project.yaml.</span>' : '')
    + (pngs.length && !traces.length ? '<span class="muted" style="font-size:13px">Không có trace (case nhập mật khẩu — tick “Ghi trace cả case nhập tài khoản” khi chạy).</span>' : '') + '</div></div>';
}
function planCard(p) {
  const total = p.items.reduce((a, i) => a + i.ac_count, 0);
  let h = '<div class="plan"><h3><span class="badge">' + esc(SCOPE[p.scope] || p.scope) + '</span>' + esc(p.title)
    + ' <span class="badge">' + esc(p.id) + ' · ' + esc(PLAN_STATE[p.status] || p.status) + '</span></h3>';
  if (p.understanding) h += '<div class="why">' + esc(p.understanding) + '</div>';
  h += '<div class="items">' + p.items.map((it, i) => {
    const run = (p.runs || [])[i];
    const acs = it.acs.length ? it.acs.join(', ') : 'tất cả';
    let state = '';
    if (run) {
      const icon = {queued: '⏳', running: '<span class="dot"></span>', done: '✅', error: '⚠'}[run.status] || '';
      const counts = run.result && run.result.counts ? Object.entries(run.result.counts).filter(([k, v]) => v).map(([k, v]) => '<span class="chip ' + esc(k.replace(' ', '')) + '">' + esc(k) + ' ' + v + '</span>').join('') : '';
      state = '<div class="runrow">' + icon + ' ' + esc({queued: 'chờ', running: 'đang chạy', done: 'xong', error: 'lỗi'}[run.status] || run.status)
        + (run.artifacts ? ' · <a href="/console#run=' + encodeURIComponent(run.artifacts) + '" target="_blank">xem log chi tiết ↗</a>' : '')
        + '<span class="chips">' + counts + '</span>'
        + (run.error ? '<span class="msg-err">' + esc(run.error) + '</span>' : '') + '</div>'
        + (run.cases || []).map(caseEvidence).join('');
    }
    return '<details class="item"><summary><span class="n">' + (i + 1) + '.</span><b>' + esc(it.title) + '</b><code>' + esc(it.feature) + '</code>'
      + '<span class="muted">' + it.ac_count + ' AC (' + esc(acs) + ')</span></summary>'
      + (it.why ? '<div class="why">' + esc(it.why) + '</div>' : '')
      + '<table>' + Object.entries(it.ac_text || {}).map(([k, v]) => '<tr><td><code>' + esc(k) + '</code></td><td>' + esc(v) + '</td></tr>').join('') + '</table>'
      + '</details>' + state;
  }).join('') + '</div>';
  if ((p.out_of_scope || []).length) h += '<div class="oos"><b>Không có trong tài liệu (không test):</b> ' + p.out_of_scope.map(esc).join('; ') + '</div>';
  if ((p.warnings || []).length) h += '<div class="warns">' + p.warnings.map(w => '<div class="warn">' + esc(w) + '</div>').join('') + '</div>';
  if (p.status === 'proposed') {
    h += '<label class="sens"><input type="checkbox" id="sens-' + esc(p.id) + '"> Ghi trace Playwright <b>cả case nhập tài khoản/mật khẩu</b>'
      + '<small>Trace lưu nguyên văn mật khẩu thật → chỉ xem trên máy này, không gửi file trace cho ai. Không tick: case đăng nhập vẫn có ảnh chụp (ô mật khẩu bị che) và nhật ký từng bước, chỉ thiếu trace.</small></label>'
      + '<div class="actions"><button class="primary" data-run="' + esc(p.id) + '">▶ Chạy QC — ' + total + ' AC</button>'
      + '<button data-cancel="' + esc(p.id) + '">Bỏ kế hoạch</button><span class="muted" style="font-size:13px">Chạy ở chế độ chỉ đọc (safe).</span></div>';
  } else if (p.options && p.options.trace_sensitive) {
    h += '<div class="warn">Lượt này ghi trace cả case có mật khẩu — file .trace.zip chứa mật khẩu thật.</div>';
  } else if (p.status === 'done') {
    const t = p.totals || {};
    h += '<div class="actions"><span class="chips">' + Object.entries(t).filter(([k, v]) => v).map(([k, v]) => '<span class="chip ' + esc(k.replace(' ', '')) + '">' + esc(k) + ' ' + v + '</span>').join('') + '</span>'
      + '<button data-analyze="' + esc(p.id) + '">Phân tích kết quả</button>'
      + (p.summary ? '<a href="/api/download?inline=1&path=' + encodeURIComponent(p.summary + '/summary.md') + '" target="_blank">Báo cáo tổng hợp ↗</a>' : '') + '</div>';
  }
  return h + '</div>';
}
function renderMessages() {
  renderHead();
  const d = S.data;
  if (!d || !d.messages.length) { renderWelcome(); return; }
  const box = $('msgs'), near = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  let h = '';
  for (const m of d.messages) {
    if (m.role === 'user') h += '<div class="bubble u">' + esc(m.text) + '</div>';
    else if (m.role === 'assistant') h += '<div class="bubble a">' + md(m.text) + '<div class="meta">' + esc(m.at || '') + (m.seconds ? ' · ' + m.seconds + 's' : '') + '</div></div>';
    else if (m.role === 'tool') {
      const arg = Object.values(m.args || {}).filter(v => typeof v === 'string').join(' · ');
      h += '<div class="tool' + (m.ok ? '' : ' err') + '">' + (ICON[m.name] || '⚙') + ' ' + esc(m.name) + (arg ? ' <i>' + esc(arg) + '</i>' : '') + ' → ' + esc(m.summary) + '</div>';
    }
    else if (m.role === 'plan') h += planCard(m.plan);
    else if (m.role === 'note') h += '<div class="note' + (m.level === 'error' ? ' error' : '') + '">' + esc(m.text) + '</div>';
  }
  if (d.busy) h += '<div class="thinking"><span class="dot"></span>' + esc(d.activity || 'Đang suy nghĩ…') + '</div>';
  $('list').innerHTML = h;
  if (near) box.scrollTop = box.scrollHeight;
  document.querySelectorAll('[data-run]').forEach(b => b.onclick = () => runPlan(b.dataset.run, b));
  document.querySelectorAll('[data-trace]').forEach(b => b.onclick = () => openTrace(b.dataset.trace, b));
  document.querySelectorAll('[data-cancel]').forEach(b => b.onclick = () => act('/api/chat/cancel', {plan: b.dataset.cancel}));
  document.querySelectorAll('[data-analyze]').forEach(b => b.onclick = () => { $('text').value = 'Phân tích kết quả kế hoạch ' + b.dataset.analyze + ': case nào không đạt, vì sao, đâu là lỗi sản phẩm và đâu là do thiếu môi trường?'; sendMessage(); });
  $('send').disabled = !!d.busy;
}
async function refresh() {
  if (!S.session) return;
  clearTimeout(S.timer);
  try {
    S.data = await api('/api/chat/session?project=' + encodeURIComponent(S.project) + '&id=' + S.session);
    renderMessages();
  } catch (e) { $('list').innerHTML = '<div class="note error">' + esc(e.message) + '</div>'; return; }
  const live = S.data.busy || S.data.messages.some(m => m.plan && m.plan.status === 'running');
  if (live) S.timer = setTimeout(refresh, 1000);
}
async function act(path, body) {
  try { S.data = await api(path, Object.assign({project: S.project, id: S.session}, body)); renderMessages(); refresh(); }
  catch (e) { alert(e.message); }
}
async function runPlan(id, btn) {
  const sens = $('sens-' + id);
  if (sens && sens.checked && !confirm('Trace sẽ chứa mật khẩu thật của tài khoản test. Chỉ xem trên máy này. Tiếp tục?')) return;
  btn.disabled = true; btn.textContent = 'Đang khởi động…';
  await act('/api/chat/run', {plan: id, trace_sensitive: !!(sens && sens.checked)});
}
async function openTrace(path, btn) {
  btn.disabled = true; const old = btn.textContent; btn.textContent = 'Đang mở Trace Viewer…';
  try { await api('/api/trace/open', {path: path}); btn.textContent = 'Đã mở (cửa sổ Playwright)'; }
  catch (e) { alert(e.message); btn.textContent = old; }
  setTimeout(() => { btn.disabled = false; btn.textContent = old; }, 4000);
}
async function sendMessage() {
  const text = $('text').value.trim();
  if (!text) return;
  if (S.status && !S.status.llm_ready) { openDrawer(); $('d-llm-msg').innerHTML = '<span class="msg-err">Cần cấu hình LLM trước.</span>'; return; }
  if (!S.session && !(await newSession())) return;
  $('text').value = ''; autosize();
  $('send').disabled = true;
  try { S.data = await api('/api/chat/message', {project: S.project, id: S.session, text: text}); renderMessages(); refreshSessions(); }
  catch (e) { $('text').value = text; alert(e.message); }
  refresh();
}
function autosize() { const t = $('text'); t.style.height = 'auto'; t.style.height = Math.min(180, t.scrollHeight) + 'px'; }

// ── Dữ liệu đầu vào ──
function openDrawer() { $('drawer').classList.add('on'); $('scrim').classList.add('on'); loadDrawer(); }
function closeDrawer() { $('drawer').classList.remove('on'); $('scrim').classList.remove('on'); }
async function loadDrawer() {
  // fillProjects() dựng lại <option> và chọn S.project — giữ lựa chọn người dùng vừa bấm (vd "+ Project mới…").
  const keep = $('d-project').value;
  fillProjects();
  if (keep && [...$('d-project').options].some(o => o.value === keep)) $('d-project').value = keep;
  const proj = $('d-project').value;
  $('d-newname-wrap').style.display = proj === '__new' ? '' : 'none';
  $('d-web').value = ''; $('d-api').value = '';
  let feats = [];
  if (proj !== '__new') {
    const c = await api('/api/chat/catalog?project=' + encodeURIComponent(proj)).catch(() => null);
    if (c) { $('d-web').value = c.web || ''; $('d-api').value = c.api || ''; feats = c.features; }
  }
  const pj = proj !== '__new' ? await api('/api/setup/project?project=' + encodeURIComponent(proj)).catch(() => null) : null;
  const pf = (pj && pj.form) || {};
  $('d-evidence').value = pf.evidence || 'on-fail'; $('d-trace').checked = !!pf.trace; $('d-timeout').value = pf.timeout_seconds || 30;
  $('d-role').value = pf.role || ''; $('d-role').disabled = !pj;
  S.projComments = !!(pj && pj.has_comments);
  $('d-proj-adv').hidden = !pj; $('d-proj-yaml').value = pj ? pj.yaml : ''; $('d-proj-yaml-msg').innerHTML = '';
  $('d-feature').innerHTML = feats.map(f => '<option value="' + esc(f.feature) + '">' + esc(f.feature) + ' — ' + esc(f.title) + '</option>').join('') + '<option value="__new"' + (feats.length ? '' : ' selected') + '>+ Chức năng mới…</option>';
  $('d-newfeat-wrap').style.display = feats.length ? 'none' : '';
  $('d-feats').innerHTML = feats.map(f => '<div>• <b>' + esc(f.feature) + '</b> — ' + esc(f.title) + ': ' + f.ac_count + ' AC</div>').join('');
  const env = await api('/api/setup/env').catch(() => []);
  const get = k => env.find(e => e.key === k) || {};
  $('d-user').value = get('QCTOOL_USERNAME').value || '';
  $('d-pass').placeholder = get('QCTOOL_PASSWORD').set ? 'đã đặt — để trống để giữ nguyên' : '';
  $('d-llm-url').value = get('QCTOOL_LLM_BASE_URL').value || '';
  $('d-llm-model').value = get('QCTOOL_LLM_MODEL').value || '';
  $('d-llm-key').placeholder = get('QCTOOL_LLM_API_KEY').set ? 'đã đặt — để trống để giữ nguyên' : '';
  $('d-llm-state').innerHTML = get('QCTOOL_LLM_MODEL').value && get('QCTOOL_LLM_API_KEY').set
    ? '<span class="msg-ok">Đã cấu hình: ' + esc(get('QCTOOL_LLM_MODEL').value) + '</span>' : '<span class="msg-err">Chưa cấu hình — trợ lý cần LLM để hiểu yêu cầu.</span>';
  await loadFeatureCfg();
}
// Cấu hình chức năng (qctool.yaml): AC nào dùng tài khoản thật (account.login_for), giá trị giả (account.test_values).
async function loadFeatureCfg() {
  const box = $('d-featcfg'), proj = $('d-project').value, feat = $('d-feature').value;
  if (proj === '__new' || !feat || feat === '__new') { box.hidden = true; box.innerHTML = ''; return; }
  let f;
  try { f = await api('/api/setup/feature?project=' + encodeURIComponent(proj) + '&feature=' + encodeURIComponent(feat)); }
  catch (e) { box.hidden = false; box.innerHTML = '<div class="msg-err">' + esc(e.message) + '</div>'; return; }
  S.feat = f;
  const pairs = v => Object.entries(v || {}).map(([k, x]) => k + '=' + x).join('; ');
  const cut = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
  box.hidden = false;
  box.innerHTML = '<h4>Cấu hình chức năng “' + esc(f.name) + '”</h4>'
    + (f.error ? '<div class="warn">qctool.yaml lỗi: ' + esc(f.error) + '</div>' : '')
    + (f.acs.length
      ? '<small class="muted">Tick AC cần <b>đăng nhập bằng tài khoản thật</b> (mục 3). AC kiểu “sai mật khẩu” <b>không</b> tick — '
        + 'điền giá trị giả dạng <code>email=a@example.com; password=Sai123</code>. Rê chuột lên AC để xem Given/When/Then.</small>'
      : '<small class="muted">Chưa đọc được AC nào — tải urd.md trước.</small>')
    + (f.unknown_login.length ? '<div class="warn">login_for có AC không còn trong tài liệu: ' + esc(f.unknown_login.join(', ')) + '</div>' : '')
    + f.acs.map(a => '<div class="acrow' + (a.login ? ' on' : '') + '" title="' + esc('Given: ' + (a.given || '') + '\nWhen: ' + (a.when || '') + '\nThen: ' + (a.then || '')) + '">'
        + '<label class="chk"><input type="checkbox" class="lg" data-ac="' + esc(a.short) + '"' + (a.login ? ' checked' : '') + '> <b>AC-' + esc(a.short) + '</b>&nbsp;dùng tài khoản thật</label>'
        + '<div class="acx">' + esc(cut((a.when || '') + ' → ' + (a.then || ''), 150)) + '</div>'
        + '<input class="tv" data-ac="' + esc(a.short) + '" placeholder="Giá trị giả (tuỳ chọn): field=giá trị; …" value="' + esc(pairs(a.test_values)) + '">'
      + '</div>').join('')
    + (f.acs.length ? '<div class="actions"><button class="primary" id="d-save-feat">Lưu cấu hình chức năng</button><span id="d-feat-msg"></span></div>' : '')
    + (f.has_comments ? '<div class="warn">qctool.yaml có comment viết tay — lưu bằng nút trên sẽ bỏ comment. Muốn giữ thì sửa ở mục Nâng cao.</div>' : '')
    + '<details class="adv"><summary>Nâng cao: sửa qctool.yaml của chức năng</summary><textarea id="d-feat-yaml" spellcheck="false">' + esc(f.yaml) + '</textarea>'
    + '<div class="actions"><button id="d-save-feat-yaml">Lưu YAML</button><span id="d-feat-yaml-msg"></span></div></details>';
  box.querySelectorAll('input.lg').forEach(c => c.onchange = () => c.closest('.acrow').classList.toggle('on', c.checked));
  if ($('d-save-feat')) $('d-save-feat').onclick = saveFeatureCfg;
  $('d-save-feat-yaml').onclick = saveFeatureYaml;
}
async function afterFeatureSave(msgId, text) {
  await loadFeatureCfg();
  $(msgId).innerHTML = '<span class="msg-ok">' + text + '</span>';
  if (S.feat && S.feat.project === S.project) {
    S.catalog = await api('/api/chat/catalog?project=' + encodeURIComponent(S.project)).catch(() => S.catalog); renderHead();
  }
}
async function saveFeatureCfg() {
  const m = $('d-feat-msg'), box = $('d-featcfg');
  const login = [...box.querySelectorAll('input.lg:checked')].map(c => c.dataset.ac);
  const values = {};
  for (const i of box.querySelectorAll('input.tv')) {
    const kv = {};
    for (const part of i.value.split(';').map(s => s.trim()).filter(Boolean)) {
      const at = part.indexOf('=');
      if (at < 1) { m.innerHTML = '<span class="msg-err">AC-' + esc(i.dataset.ac) + ': “' + esc(part) + '” cần dạng field=giá trị.</span>'; return; }
      kv[part.slice(0, at).trim()] = part.slice(at + 1).trim();
    }
    if (Object.keys(kv).length) values[i.dataset.ac] = kv;
  }
  try {
    await api('/api/setup/feature/account', {project: S.feat.project, feature: S.feat.name, login_for: login, test_values: values});
    await afterFeatureSave('d-feat-msg', 'Đã lưu qctool.yaml.' + (login.length && !S.status.account_set ? ' Nhớ nhập tài khoản ở mục 3.' : ''));
  } catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
async function saveFeatureYaml() {
  const m = $('d-feat-yaml-msg');
  try {
    await api('/api/setup/feature/yaml', {project: S.feat.project, feature: S.feat.name, yaml: $('d-feat-yaml').value});
    await afterFeatureSave('d-feat-msg', 'Đã lưu YAML.');
  } catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
async function saveProjectYaml() {
  const m = $('d-proj-yaml-msg'), name = $('d-project').value;
  try {
    await api('/api/setup/project/yaml', {project: name, yaml: $('d-proj-yaml').value});
    await afterProjectChange(name); await loadDrawer();
    $('d-proj-yaml-msg').innerHTML = '<span class="msg-ok">Đã lưu project.yaml.</span>';
  } catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
function projectName() {
  const v = $('d-project').value;
  return v === '__new' ? $('d-newname').value.trim() : v;
}
async function afterProjectChange(name) {
  S.status = await api('/api/chat/status');
  const switched = name !== S.project;
  if (switched) { await selectProject(name); } else { S.catalog = await api('/api/chat/catalog?project=' + encodeURIComponent(name)).catch(() => S.catalog); renderHead(); if (!S.data || !S.data.messages.length) renderWelcome(); else refresh(); }
  fillProjects(); $('d-project').value = name;
}
async function upload(files) {
  const name = projectName();
  const feat = $('d-feature').value === '__new' ? $('d-newfeat').value.trim() : $('d-feature').value;
  const msg = $('d-doc-msg');
  if (!name) { msg.innerHTML = '<span class="msg-err">Nhập tên project trước.</span>'; return; }
  if (!feat) { msg.innerHTML = '<span class="msg-err">Nhập tên chức năng cho bộ tài liệu này.</span>'; return; }
  const list = [];
  for (const f of files) {
    if (f.size > 1024 * 1024) { msg.innerHTML = '<span class="msg-err">' + esc(f.name) + ' lớn hơn 1 MB.</span>'; return; }
    list.push({name: f.name, content: await f.text()});
  }
  msg.innerHTML = '<span class="muted">Đang tải và đọc tài liệu…</span>';
  try {
    const sess = name === S.project ? S.session : null;
    const d = await api('/api/chat/upload', {project: name, feature: feat, files: list, session: sess, web: $('d-web').value.trim(), api: $('d-api').value.trim()});
    const f = d.feature;
    msg.innerHTML = '<span class="msg-ok">Đã lưu ' + esc(d.saved.join(', ')) + (f ? ' → ' + f.acs + ' AC đọc được' : '') + '</span>'
      + (f && f.warnings.length ? '<div class="warn">' + f.warnings.map(esc).join('<br>') + '</div>' : '')
      + (f && !f.acs ? '<div class="warn">Không đọc được AC nào. URD cần mục “### US-001 — …” và bảng “| AC-001-1 | Given | When | Then |”.</div>' : '');
    await afterProjectChange(name);
    await loadDrawer(); $('d-feature').value = feat; await loadFeatureCfg();
    if (S.session) refresh();
  } catch (e) { msg.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
async function saveProject() {
  const name = projectName(), m = $('d-proj-msg');
  if (!name) { m.innerHTML = '<span class="msg-err">Nhập tên project.</span>'; return; }
  if ($('d-project').value !== '__new' && S.projComments
      && !confirm('project.yaml có comment viết tay — lưu bằng form sẽ bỏ comment. Tiếp tục? (Muốn giữ thì sửa ở mục Nâng cao.)')) return;
  try {
    await api('/api/chat/upload', {project: name, feature: 'main', files: [], session: name === S.project ? S.session : null, web: $('d-web').value.trim(), api: $('d-api').value.trim()});
    const pj = await api('/api/setup/project?project=' + encodeURIComponent(name));
    await api('/api/setup/project/form', {project: name, form: {...(pj.form || {}), web: $('d-web').value.trim(), api: $('d-api').value.trim(),
      evidence: $('d-evidence').value, trace: $('d-trace').checked, timeout_seconds: Number($('d-timeout').value) || 30}});
    await afterProjectChange(name); await loadDrawer();
    $('d-proj-msg').innerHTML = '<span class="msg-ok">Đã lưu.</span>';
  } catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
async function saveAccount() {
  const m = $('d-acc-msg');
  try {
    await api('/api/chat/account', {username: $('d-user').value, password: $('d-pass').value, project: S.project, session: S.session});
    const proj = $('d-project').value;
    if (proj !== '__new') {
      const pj = await api('/api/setup/project?project=' + encodeURIComponent(proj));
      if ((pj.form || {}).role !== $('d-role').value)
        await api('/api/setup/project/form', {project: proj, form: {...(pj.form || {}), role: $('d-role').value}});
    }
    $('d-pass').value = ''; m.innerHTML = '<span class="msg-ok">Đã lưu vào .env' + (proj !== '__new' ? ' + vai trò vào project' : '') + '.</span>';
    S.catalog = await api('/api/chat/catalog?project=' + encodeURIComponent(S.project)).catch(() => S.catalog); renderHead(); loadDrawer();
    if (S.session) refresh();
  } catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
async function saveLLM() {
  const m = $('d-llm-msg');
  const updates = {QCTOOL_LLM_BASE_URL: $('d-llm-url').value, QCTOOL_LLM_MODEL: $('d-llm-model').value};
  if ($('d-llm-key').value) updates.QCTOOL_LLM_API_KEY = $('d-llm-key').value;
  try { await api('/api/setup/env', {updates: updates}); $('d-llm-key').value = ''; m.innerHTML = '<span class="msg-ok">Đã lưu.</span>';
        S.status = await api('/api/chat/status'); $('llm-state').textContent = S.status.llm_ready ? 'LLM: đã cấu hình' : 'LLM: chưa cấu hình'; loadDrawer(); }
  catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}
async function testLLM() {
  const m = $('d-llm-msg'); m.innerHTML = '<span class="muted">Đang gọi thử…</span>';
  try { const d = await api('/api/setup/llm-test', {});
        m.innerHTML = d.ok ? '<span class="msg-ok">OK sau ' + d.seconds + 's' + (d.tool_calling ? ', có tool calling' : ' — model KHÔNG gọi tool, trợ lý sẽ không hoạt động') + '</span>' : '<span class="msg-err">' + esc(d.error) + '</span>'; }
  catch (e) { m.innerHTML = '<span class="msg-err">' + esc(e.message) + '</span>'; }
}

// ── Sự kiện ──
$('send').onclick = sendMessage;
$('text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendMessage(); } });
$('text').addEventListener('input', autosize);
$('new-chat').onclick = () => { newSession().catch(e => alert(e.message)); $('side').classList.remove('on'); };
$('project').onchange = e => { if (e.target.value === '__new') { e.target.value = S.project; openDrawer(); $('d-project').value = '__new'; loadDrawer(); } else selectProject(e.target.value); };
$('open-input').onclick = openDrawer; $('attach').onclick = openDrawer;
$('close-input').onclick = closeDrawer; $('scrim').onclick = () => { closeDrawer(); $('side').classList.remove('on'); };
$('menu').onclick = () => { $('side').classList.add('on'); $('scrim').classList.add('on'); };
$('d-project').onchange = loadDrawer;
$('d-feature').onchange = () => { $('d-newfeat-wrap').style.display = $('d-feature').value === '__new' ? '' : 'none'; loadFeatureCfg(); };
$('d-save-proj').onclick = saveProject; $('d-save-acc').onclick = saveAccount; $('d-save-proj-yaml').onclick = saveProjectYaml;
$('d-save-llm').onclick = saveLLM; $('d-test-llm').onclick = testLLM;
const drop = $('drop');
drop.onclick = () => $('files').click();
$('files').onchange = e => { upload([...e.target.files]); e.target.value = ''; };
drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); upload([...e.dataTransfer.files]); });
boot();
</script>
</body>
</html>
"""
