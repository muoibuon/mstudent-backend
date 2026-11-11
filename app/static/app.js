
const $ = (id) => document.getElementById(id);
function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k.startsWith('on')) e[k] = v; else if (v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k instanceof Node ? k : String(k));
  return e;
}
/* ---------- Phiên đăng nhập ----------
   Access token chỉ nằm trong bộ nhớ; refresh token trong sessionStorage (mất khi đóng tab).
   CSP script-src 'self' chặn script lạ nên token không bị đọc trộm qua script chèn vào. */
let ACCESS = '', ME = null, refreshing = null;
const getRefresh = () => { try { return sessionStorage.getItem('mstudent_refresh') || ''; } catch { return ''; } };
const setRefresh = (v) => { try { v ? sessionStorage.setItem('mstudent_refresh', v) : sessionStorage.removeItem('mstudent_refresh'); } catch {} };
function setSession(t) { ACCESS = t.access_token; ME = t.user; setRefresh(t.refresh_token); }
async function tryRefresh() {
  if (!getRefresh()) return false;
  refreshing ??= fetch('/api/auth/refresh', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({refresh_token: getRefresh()})})
    .then(async (r) => { if (!r.ok) { setRefresh(''); return false; } setSession(await r.json()); return true; })
    .catch(() => false).finally(() => { refreshing = null; });
  return refreshing;
}
async function api(path, opts = {}, retry = true) {
  const {headers, ...rest} = opts;
  const auth = ACCESS ? {Authorization: 'Bearer ' + ACCESS} : {};
  const r = await fetch(path, {...rest, headers: {'Content-Type': 'application/json', ...auth, ...(headers || {})}});
  if (r.status === 401 && retry && !path.startsWith('/api/auth/')) {
    if (await tryRefresh()) return api(path, opts, false);
    showLogin(); throw new Error('Hãy đăng nhập lại');
  }
  if (!r.ok) {
    const d = (await r.json().catch(() => ({}))).detail;
    throw new Error(Array.isArray(d) ? d.map((x) => x.msg).join('; ') : d || r.statusText);
  }
  return r.json();
}
const TZ = 'Asia/Ho_Chi_Minh';
const CAT = {deadline:'Hạn nộp', exam:'Thi', class_change:'Đổi lịch', event:'Sự kiện', admin:'Thủ tục', other:'Khác'};
const fmtDT = (s) => s ? new Date(s).toLocaleString('vi-VN', {weekday:'short', day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit', timeZone:TZ}) : 'Không có hạn';
const fmtTime = (s) => new Date(s).toLocaleTimeString('vi-VN', {hour:'2-digit', minute:'2-digit', timeZone:TZ});
const dayKey = (d) => new Date(d).toLocaleDateString('en-CA', {timeZone:TZ}); // YYYY-MM-DD theo giờ VN
let NOW = new Date();

/* ---------- Tabs ---------- */
const TABS = ['chat', 'trace', 'calendar', 'config'];
function openTab(name) {
  for (const t of TABS) $('tab-' + t).classList.toggle('hidden', t !== name);
  document.querySelectorAll('nav button').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === name));
  try { sessionStorage.setItem('tab', name); } catch {}
  if (name === 'trace') loadTraces();
  if (name === 'calendar') renderWeek();
  if (name === 'config') loadConfig();
}
document.querySelectorAll('nav button').forEach((b) => b.onclick = () => openTab(b.dataset.tab));

/* ---------- Dữ liệu chung ---------- */
let TASKS = [];
async function loadTasks() {
  TASKS = await api('/api/tasks');
  renderSide();
  if (!$('tab-calendar').classList.contains('hidden')) renderWeek();
}
function taskRow(t) {
  return h('div', {class:'task'},
    h('span', {class:'dot ' + t.priority, title:'Ưu tiên ' + t.priority}),
    h('div', {}, h('div', {}, `#${t.id} · ${t.title}`),
      h('div', {class:'meta'}, h('span', {class:'tag'}, CAT[t.category]), ' ', fmtDT(t.due_at), t.location ? ' · ' + t.location : '')),
    h('button', {class:'ghost sm', onclick: () => markDone(t.id)}, 'Xong'));
}
function renderSide() {
  const box = $('sideTasks');
  box.replaceChildren(...(TASKS.length ? TASKS.slice(0, 8).map(taskRow) : [h('div', {class:'meta'}, 'Chưa có việc nào. Bấm “Nạp dữ liệu demo” hoặc dán một thông báo.')]));
  $('taskCount').textContent = TASKS.length ? `${TASKS.length} việc` : '';
}
async function markDone(id) { await api(`/api/tasks/${id}/done`, {method:'POST'}); await refreshAll(); }
async function loadDigest() { $('digest').textContent = '…'; $('digest').textContent = (await api('/api/digest')).text; }
async function refreshAll() { await loadTasks(); loadDigest(); }

/* ---------- Chat ---------- */
let HISTORY = [];
const CHIPS = ['Tuần này có gì?', 'Hôm nay cần làm gì?', 'Lịch thi sắp tới', 'Bản tin', 'Thêm: thứ 6 tuần sau nộp đồ án OOP'];
$('chips').replaceChildren(...CHIPS.map((c) => h('button', {onclick: () => sendChat(c)}, c)));
function addMsg(role, text, calls = [], mode) {
  const box = h('div', {class:'msg ' + (role === 'user' ? 'user' : 'bot')}, text);
  if (calls.length) {
    box.append(h('details', {}, h('summary', {}, `🔧 ${calls.length} lần gọi tool${mode ? ' · ' + mode : ''}`),
      ...calls.map((c) => h('pre', {}, `${c.tool}(${JSON.stringify(c.args)})\n→ ${c.result}`))));
  }
  $('chatLog').append(box); $('chatLog').scrollTop = $('chatLog').scrollHeight;
  return box;
}
function greet() {
  $('chatLog').replaceChildren();
  addMsg('bot', 'Chào bạn! Mình là trợ lý MStudent. Hỏi mình về việc sắp tới, dán thông báo để mình ghi lại, hoặc nói “xong 3” khi làm xong việc #3.');
}
async function sendChat(text) {
  text = (text ?? $('chatInput').value).trim(); if (!text) return;
  $('chatInput').value = ''; addMsg('user', text);
  const typing = h('div', {class:'msg bot typing'}, 'Đang suy nghĩ…'); $('chatLog').append(typing);
  $('chatSend').disabled = true;
  try {
    const r = await api('/api/chat', {method:'POST', body: JSON.stringify({message:text, history:HISTORY})});
    typing.remove(); addMsg('bot', r.reply, r.tool_calls, r.mode);
    HISTORY.push({role:'user', content:text}, {role:'assistant', content:r.reply}); HISTORY = HISTORY.slice(-20);
    if (r.tool_calls.some((c) => c.tool !== 'list_tasks')) refreshAll();
  } catch (e) { typing.remove(); addMsg('bot', '⚠️ Lỗi: ' + e.message); }
  $('chatSend').disabled = false; $('chatInput').focus();
}
$('chatSend').onclick = () => sendChat();
$('chatInput').onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } };
$('clearChat').onclick = () => { HISTORY = []; greet(); };

/* ---------- Trace ---------- */
let TRACES = [], SEL = null;
async function loadTraces() {
  TRACES = await api('/api/traces');
  const list = $('traceList');
  if (!TRACES.length) { list.replaceChildren(h('div', {class:'meta'}, 'Chưa có lượt chạy nào.')); $('traceDetail').replaceChildren('Chọn một lượt chạy bên trái.'); return; }
  if (!TRACES.some((t) => t.id === SEL)) SEL = TRACES[0].id;
  list.replaceChildren(...TRACES.map((t) => {
    const tri = t.steps.find((s) => s.agent === 'Triage');
    const rel = tri?.output?.relevant;
    return h('div', {class:'traceItem' + (t.id === SEL ? ' sel' : ''), onclick: () => { SEL = t.id; loadTraces(); }},
      h('div', {}, t.summary),
      h('div', {class:'meta'}, h('span', {class:'tag ' + (t.mode === 'llm' ? 'llm' : 'rules')}, t.mode), ' ',
        rel === false ? '✗ bỏ qua' : '✓ ' + (CAT[tri?.output?.category] || ''), ' · ', fmtDT(t.created_at)));
  }));
  showTrace(TRACES.find((t) => t.id === SEL));
}
function showTrace(t) {
  const total = t.steps.reduce((a, s) => a + s.ms, 0);
  $('traceDetail').replaceChildren(
    h('p', {class:'meta'}, `${t.summary} · tổng ${total.toFixed(1)} ms · message ${t.message_id}`),
    ...t.steps.map((s) => h('div', {class:'step' + (s.error ? ' err' : '')},
      h('div', {class:'row'}, h('b', {}, s.agent), h('span', {class:'tag ' + s.kind}, s.kind), h('span', {class:'meta'}, s.ms + ' ms')),
      h('pre', {}, s.error ? s.error : JSON.stringify(s.output, null, 2)))));
}
$('trRefresh').onclick = loadTraces;
$('trSend').onclick = async () => {
  const body = $('trBody').value.trim(); if (!body) return;
  $('trSend').disabled = true;
  try { await api('/api/ingest', {method:'POST', body: JSON.stringify({source:$('trSource').value, body})}); $('trBody').value = ''; SEL = null; await loadTraces(); refreshAll(); }
  catch (e) { $('trBody').value = ''; $('trBody').placeholder = '⚠️ ' + e.message; }
  $('trSend').disabled = false;
};
$('trBody').onkeydown = (e) => { if (e.key === 'Enter') $('trSend').click(); };

/* ---------- Lịch tuần ---------- */
let WEEK_OFFSET = 0;
function renderWeek() {
  const start = new Date(NOW); start.setHours(0, 0, 0, 0); start.setDate(start.getDate() + WEEK_OFFSET * 7);
  const days = [...Array(7)].map((_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
  const keys = days.map(dayKey), todayKey = dayKey(NOW);
  const week = $('week'); week.replaceChildren();
  for (const [i, d] of days.entries()) {
    const col = h('div', {class:'day' + (keys[i] === todayKey ? ' today' : '')},
      h('h3', {}, d.toLocaleDateString('vi-VN', {weekday:'short', day:'2-digit', month:'2-digit', timeZone:TZ})));
    col.ondragover = (e) => { e.preventDefault(); col.classList.add('over'); };
    col.ondragleave = () => col.classList.remove('over');
    col.ondrop = (e) => { e.preventDefault(); col.classList.remove('over'); moveTask(+e.dataTransfer.getData('text/plain'), keys[i]); };
    for (const t of TASKS.filter((t) => t.due_at && dayKey(t.due_at) === keys[i])) {
      const ev = h('div', {class:'ev ' + t.priority, draggable:'true'},
        h('button', {class:'ghost sm', title:'Đánh dấu xong', onclick: () => markDone(t.id)}, '✓'),
        h('div', {class:'t'}, fmtTime(t.due_at)), h('div', {}, t.title),
        h('div', {class:'meta'}, CAT[t.category] + (t.location ? ' · ' + t.location : '')));
      ev.ondragstart = (e) => e.dataTransfer.setData('text/plain', t.id);
      col.append(ev);
    }
    week.append(col);
  }
  const others = TASKS.filter((t) => !t.due_at || !keys.includes(dayKey(t.due_at)));
  $('otherTasks').replaceChildren(...(others.length ? others.map(taskRow) : [h('div', {class:'meta'}, 'Không có.')]));
}
async function moveTask(id, newKey) {
  const t = TASKS.find((x) => x.id === id); if (!t?.due_at) return;
  const time = t.due_at.slice(10); // giữ nguyên "THH:MM:SS+07:00"
  await api(`/api/tasks/${id}`, {method:'PATCH', body: JSON.stringify({due_at: newKey + time})});
  await refreshAll();
}
$('wkPrev').onclick = () => { WEEK_OFFSET--; renderWeek(); };
$('wkNext').onclick = () => { WEEK_OFFSET++; renderWeek(); };
$('wkToday').onclick = () => { WEEK_OFFSET = 0; renderWeek(); };

/* ---------- Cấu hình + eval ---------- */
const CFG_KEYS = ['model', 'triage_prompt', 'extract_prompt', 'digest_prompt', 'assistant_prompt'];
async function loadConfig() {
  const r = await api('/api/agents/config');
  for (const k of CFG_KEYS) { $('cfg-' + k).value = r.config[k] ?? '(chỉ quản trị viên xem được)'; $('cfg-' + k).disabled = !r.can_edit; }
  for (const id of ['cfgSave', 'cfgReset', 'evalBtn']) $(id).disabled = !r.can_edit;
  $('cfgOffline').classList.toggle('hidden', r.llm);
  $('cfgNotAdmin').classList.toggle('hidden', r.can_edit);
}
$('cfgSave').onclick = async () => {
  const body = Object.fromEntries(CFG_KEYS.map((k) => [k, $('cfg-' + k).value]));
  try { await api('/api/agents/config', {method:'PUT', body: JSON.stringify(body)}); $('cfgStatus').textContent = '✓ Đã lưu lúc ' + new Date().toLocaleTimeString('vi-VN'); loadHealth(); }
  catch (e) { $('cfgStatus').textContent = '⚠️ ' + e.message; }
};
$('cfgReset').onclick = async () => {
  if ($('cfgReset').dataset.armed !== '1') { $('cfgReset').dataset.armed = '1'; $('cfgReset').textContent = 'Bấm lần nữa để xác nhận'; setTimeout(() => { $('cfgReset').dataset.armed = ''; $('cfgReset').textContent = 'Khôi phục mặc định'; }, 4000); return; }
  $('cfgReset').dataset.armed = ''; $('cfgReset').textContent = 'Khôi phục mặc định';
  try { await api('/api/agents/config/reset', {method:'POST'}); await loadConfig(); $('cfgStatus').textContent = '✓ Đã khôi phục mặc định'; loadHealth(); }
  catch (e) { $('cfgStatus').textContent = '⚠️ ' + e.message; }
};
const SCORE_LABEL = {relevant:'Lọc đúng', category:'Phân loại', due:'Hạn/giờ', course:'Mã môn'};
$('evalBtn').onclick = async () => {
  $('evalBtn').disabled = true; $('evalOut').replaceChildren(h('p', {class:'meta'}, 'Đang chạy…'));
  try {
    const r = await api('/api/eval', {method:'POST'});
    $('evalOut').replaceChildren(
      h('p', {class:'meta'}, 'Chế độ: ', h('span', {class:'tag ' + (r.mode === 'llm' ? 'llm' : 'rules')}, r.mode)),
      h('div', {class:'scores'}, ...Object.entries(r.scores).map(([k, s]) =>
        h('div', {class:'score'}, h('span', {class:'meta'}, SCORE_LABEL[k] || k), h('b', {class: s.pct === 100 ? 'ok' : s.pct < 80 ? 'bad' : ''}, s.pct == null ? '–' : s.pct + '%'), h('span', {class:'meta'}, `${s.ok}/${s.n}`)))),
      h('div', {class:'tablewrap'}, h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, ''), h('th', {}, 'Thông báo'), h('th', {}, 'Lỗi'))),
        h('tbody', {}, ...r.cases.map((c) => h('tr', {},
          h('td', {class: c.ok ? 'ok' : 'bad'}, c.ok ? '✓' : '✗'), h('td', {}, c.body), h('td', {class:'meta'}, c.fails.join('; '))))))));
  } catch (e) { $('evalOut').replaceChildren(h('p', {class:'bad'}, '⚠️ ' + e.message)); }
  $('evalBtn').disabled = false;
};

/* ---------- Khởi động ---------- */
async function loadHealth() {
  const s = await (await fetch('/api/health')).json();
  NOW = new Date(s.now);
  const label = s.mode === 'llm' ? '🟢 LLM · ' + s.model : '🟡 Offline (luật)';
  $('modePill').textContent = label; $('modePillLogin').textContent = label;
  $('nowPill').textContent = '🕒 ' + fmtDT(s.now);
}
$('seedBtn').onclick = async () => {
  $('seedBtn').disabled = true;
  const rs = await api('/api/demo/seed', {method:'POST'});
  const made = rs.reduce((a, r) => a + r.created.length, 0), upd = rs.reduce((a, r) => a + r.updated.length, 0), skip = rs.filter((r) => !r.relevant).length;
  addMsg('bot', `Đã nạp ${rs.length} thông báo demo: tạo ${made} việc, cập nhật ${upd}, bỏ qua ${skip} tin không liên quan. Xem tab “Agent trace” để thấy từng agent chạy.`);
  $('seedBtn').disabled = false; SEL = null;
  await refreshAll();
  if (!$('tab-trace').classList.contains('hidden')) loadTraces();
};
/* ---------- Đăng nhập ---------- */
let REGISTER = false;
function showLogin() { $('login').classList.remove('hidden'); $('app').classList.add('hidden'); $('loginEmail').focus(); }
function renderLoginMode() {
  $('loginTitle').textContent = REGISTER ? 'Tạo tài khoản' : 'Đăng nhập';
  $('loginSubmit').textContent = REGISTER ? 'Đăng ký' : 'Đăng nhập';
  $('loginToggle').textContent = REGISTER ? 'Đã có tài khoản? Đăng nhập' : 'Chưa có tài khoản? Đăng ký';
  $('loginNameRow').classList.toggle('hidden', !REGISTER);
  $('loginPassword').autocomplete = REGISTER ? 'new-password' : 'current-password';
}
$('loginToggle').onclick = () => { REGISTER = !REGISTER; $('loginError').textContent = ''; renderLoginMode(); };
$('loginForm').onsubmit = async (e) => {
  e.preventDefault(); $('loginError').textContent = ''; $('loginSubmit').disabled = true;
  try {
    const body = {email: $('loginEmail').value, password: $('loginPassword').value, device: 'web console'};
    if (REGISTER) body.name = $('loginName').value;
    setSession(await api(REGISTER ? '/api/auth/register' : '/api/auth/login', {method:'POST', body: JSON.stringify(body)}));
    $('loginPassword').value = '';
    await enterApp();
  } catch (err) { $('loginError').textContent = '⚠️ ' + err.message; }
  $('loginSubmit').disabled = false;
};
$('logoutBtn').onclick = async () => {
  const rt = getRefresh();
  if (rt) await fetch('/api/auth/logout', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({refresh_token: rt})}).catch(() => {});
  ACCESS = ''; ME = null; setRefresh(''); HISTORY = []; TASKS = [];
  showLogin();
};
async function enterApp() {
  $('login').classList.add('hidden'); $('app').classList.remove('hidden');
  $('userPill').textContent = '👤 ' + ME.email + (ME.is_admin ? ' · admin' : '');
  greet();
  await loadHealth();
  await refreshAll();
  let tab = 'chat'; try { tab = sessionStorage.getItem('tab') || 'chat'; } catch {}
  openTab(TABS.includes(tab) ? tab : 'chat');
}
(async () => {
  renderLoginMode();
  loadHealth().catch(() => {});
  if (await tryRefresh()) await enterApp(); else showLogin();
})();
