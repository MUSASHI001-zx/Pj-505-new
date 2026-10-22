const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let currentSession = null;
let supabaseClient = null;

window.addEventListener('DOMContentLoaded', () => {
  window.setTimeout(() => $('#app-loading')?.classList.add('hide'), 420);
  $('#mobile-menu')?.addEventListener('click', () => $('#sidebar')?.classList.toggle('open'));
  const modal = $('#login-modal');
  $('#login-btn')?.addEventListener('click', () => {
    if (currentSession) $('#account-menu')?.toggleAttribute('hidden');
    else modal?.classList.add('open');
  });
  document.addEventListener('click', (event) => {
    const menu = $('#account-menu');
    if (menu && !menu.hidden && !menu.contains(event.target) && !$('#login-btn')?.contains(event.target)) menu.hidden = true;
  });
  $('#logout-btn')?.addEventListener('click', signOut);
  $('#account-profile')?.addEventListener('click', () => { window.location.href = '/account'; });
  rememberInviteFromUrl();
  $$('[data-account-role]').forEach((button) => button.addEventListener('click', () => changeAccountRole(button.dataset.accountRole)));
  $$('[data-close-modal]').forEach((button) => button.addEventListener('click', () => modal?.classList.remove('open')));
  modal?.addEventListener('click', (event) => { if (event.target === modal) modal.classList.remove('open'); });
  $('#google-login')?.addEventListener('click', startGoogleLogin);
  $('#google-login-page')?.addEventListener('click', startGoogleLogin);
  $$('.bookmark').forEach((button) => button.addEventListener('click', () => { button.textContent = button.textContent.trim() === '♡' ? '♥' : '♡'; button.classList.toggle('saved'); }));
  $$('.choice-grid button').forEach((button) => button.addEventListener('click', () => { $$('.choice-grid button').forEach((item) => item.classList.remove('selected')); button.classList.add('selected'); button.style.background = '#f1efff'; button.style.borderColor = '#9383de'; }));
  $('#follow-news')?.addEventListener('click', (event) => { event.currentTarget.textContent = '✓ กำลังติดตามข่าว'; event.currentTarget.classList.add('primary'); });
  $('#news-more')?.addEventListener('click', () => {
    newsState.limit += NEWS_PAGE_SIZE;
    loadNews();
  });
  $('#global-search')?.addEventListener('keydown', (event) => { if (event.key === 'Enter' && event.currentTarget.value.trim()) window.location.href = `/news?q=${encodeURIComponent(event.currentTarget.value.trim())}`; });
  loadNews();
  loadInstitutes();
  initInstituteSearch();
  initQuotaSearch();
  initScholarshipSearch();
  initMetrics();
  restoreSupabaseSession();
});

// ---------- จำหน้าที่ผู้ใช้ต้องการเข้า (กรณี login แล้วถูกพาไปหน้าแรก) ----------
// Google OAuth อาจ redirect กลับมาที่ Site URL ของโปรเจกต์เสมอ ไม่ใช่หน้าที่กด login
// เราจึงเก็บ path ไว้ใน localStorage แล้วพากลับไปหลัง login สำเร็จ
const DESIRED_PATH_KEY = 'tcas_buddy_desired_path';

function rememberDesiredPath() {
  try {
    const path = window.location.pathname + window.location.search;
    // อย่าเก็บหน้า login เอง (จะวนลูปไม่จบ)
    if (!path || path.startsWith('/login')) return;
    // ถ้ามีค่าเดิมอยู่แล้วและเป็นหน้าเดียวกัน ไม่ต้องเขียนทับ (กันการวนลูป)
    if (window.localStorage.getItem(DESIRED_PATH_KEY) === path) return;
    window.localStorage.setItem(DESIRED_PATH_KEY, path);
  } catch { /* storage ใช้ไม่ได้ */ }
}

function pendingRedirectPath() {
  const saved = readDesiredPath();
  try { window.localStorage.removeItem(DESIRED_PATH_KEY); } catch { /* ignore */ }
  return saved || '/';
}

// อ่าน path ที่บันทึกไว้ (พร้อมตรวจว่าปลอดภัย)
function readDesiredPath() {
  let saved = '';
  try { saved = window.localStorage.getItem(DESIRED_PATH_KEY) || ''; } catch { /* ignore */ }
  // ต้องเป็น path ภายในเว็บเท่านั้น ป้องกันการ redirect ออกไปข้างนอก
  if (!saved || !saved.startsWith('/') || saved.startsWith('//')) return '';
  if (saved.startsWith('/login')) return '';
  return saved;
}

// ถ้าอยู่หน้าที่ต้องล็อกอิน (เช่น /admin ที่ยังไม่มีสิทธิ์) ให้จำ path ไว้ก่อน
window.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page;
  if (page !== 'admin' && page !== 'account') return;
  // ถ้า path ที่บันทึกไว้คือหน้านี้อยู่แล้ว แปลว่ากลับมาถึงเป้าหมายแล้ว — เคลียร์ทิ้ง
  if (readDesiredPath() === window.location.pathname) {
    try { window.localStorage.removeItem(DESIRED_PATH_KEY); } catch { /* ignore */ }
    return;
  }
  rememberDesiredPath();
});

async function restoreSupabaseSession() {
  const hasOAuthReturn = window.location.hash.includes('access_token') || window.location.hash.includes('code=');
  const status = $('#login-page-status') || $('#login-status');
  try {
    const configResponse = await fetch('/api/config');
    const config = await configResponse.json();
    if (!config.configured || !config.supabase_url || !config.supabase_anon_key) { announceGuest('not_configured'); return; }
    if (!window.supabase) {
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';
        script.onload = resolve;
        script.onerror = reject;
        document.head.appendChild(script);
      });
    }
    supabaseClient = window.supabase.createClient(config.supabase_url, config.supabase_anon_key);
    const { data, error } = await supabaseClient.auth.getSession();
    if (error) throw error;
    if (!data.session) {
      if (hasOAuthReturn) throw new Error('ไม่พบ session');
      announceGuest('signed_out');
      return;
    }
    currentSession = data.session;
    applyUserIdentity(data.session.user);
    await syncUserToBackend(data.session);
    await loadMyAccount();
    adminHeartbeat();  // บอกระบบว่าแอดมินออนไลน์ (ถ้าเป็นแอดมิน)
    const inviteMessage = await redeemPendingInvite();
    if (inviteMessage) {
      if (hasOAuthReturn) { try { window.localStorage.setItem('tcas_buddy_toast', inviteMessage); } catch { /* ignore */ } }
      else toast(inviteMessage);
    }
    if (hasOAuthReturn) {
      // กลับไปหน้าที่ผู้ใช้พยายามเข้าจริง ๆ (เช่น /admin, /account) ไม่ใช่หน้าหลักเสมอ
      const target = pendingRedirectPath();
      window.history.replaceState({}, document.title, window.location.pathname);
      // ถ้ากลับมาที่หน้าเดิมอยู่แล้ว ไม่ต้อง reload ซ้ำ
      if (target !== window.location.pathname) {
        window.location.replace(target);
      }
    } else {
      // OAuth อาจ redirect กลับมาที่หน้าแรกโดยไม่มี hash — ถ้าผู้ใช้เคยขอหน้าอื่น ให้พากลับไป
      const saved = readDesiredPath();
      if (saved && saved !== window.location.pathname) {
        window.location.replace(saved);
      }
    }
  } catch {
    if (status) status.textContent = 'ยืนยันบัญชีไม่สำเร็จ โปรดลองเข้าสู่ระบบอีกครั้ง';
    announceGuest('error');
  }
}

async function syncUserToBackend(session, role = null) {
  try {
    const response = await fetch('/api/auth/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${session.access_token}` },
      body: JSON.stringify(role ? { role } : {}),
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `sync failed (${response.status})`);
    }
  } catch (e) {
    console.error('user sync failed:', e);
  }
}

function applyUserIdentity(user) {
  const metadata = user.user_metadata || {};
  const name = metadata.full_name || metadata.name || user.email?.split('@')[0] || 'ผู้ใช้';
  const initial = name.trim().charAt(0).toUpperCase() || 'U';
  $('#header-name') && ($('#header-name').textContent = name);
  $('#header-email') && ($('#header-email').textContent = user.email || 'บัญชีของฉัน');
  ['#header-avatar', '#menu-avatar'].forEach((selector) => { const node = $(selector); if (node) node.textContent = initial; });
  $('#menu-name') && ($('#menu-name').textContent = name);
  $('#menu-email') && ($('#menu-email').textContent = user.email || '');
}

async function changeAccountRole(role) {
  if (!currentSession || !['student', 'parents', 'teacher'].includes(role)) return;
  await syncUserToBackend(currentSession, role);
  $('#account-menu')?.toggleAttribute('hidden');
}

async function signOut() {
  if (supabaseClient) await supabaseClient.auth.signOut();
  currentSession = null;
  window.location.href = '/login';
}

async function loadStats() {
  const cards = $$('[data-stat]');
  if (!cards.length) return;
  try {
    const response = await fetch('/api/stats');
    const data = await response.json();
    cards.forEach((card) => {
      const key = card.dataset.stat;
      card.textContent = data.configured && data[key] !== null ? Number(data[key]).toLocaleString('th-TH') : '—';
    });
    if (data.configured && data.database_ready === false) {
      const banner = $('#setup-banner');
      const copy = $('#setup-banner-copy');
      if (banner) banner.style.display = 'flex';
      if (copy) copy.textContent = 'เชื่อมต่อ Supabase แล้ว แต่ยังต้องรันไฟล์ migration เพื่อสร้างตารางข้อมูล';
    }
  } catch { cards.forEach((card) => { card.textContent = '—'; }); }
}

async function initMetrics() {
  await Promise.all([recordView(), recordPresence()]);
  await loadStats();
  window.setInterval(recordPresence, 30000);
  if ($$('[data-stat]').length) window.setInterval(loadStats, 30000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) recordPresence(); });
}

// นับ 1 ครั้งต่อการเข้าเว็บ 1 รอบ (ต่อแท็บ) และจะจำว่า "นับแล้ว" ก็ต่อเมื่อบันทึกลงฐานข้อมูลสำเร็จจริง
async function recordView() {
  const key = 'tcas_buddy_view_counted_v2';
  try { if (window.sessionStorage.getItem(key)) return; } catch { /* sessionStorage unavailable */ }
  try {
    const response = await fetch('/api/page-view', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ path: window.location.pathname }) });
    const data = await response.json().catch(() => ({}));
    if (response.ok && data.ok) { try { window.sessionStorage.setItem(key, '1'); } catch { /* ignore */ } }
  } catch { /* analytics is non-blocking */ }
}

function visitorId() {
  const key = 'tcas_buddy_visitor_id';
  let id = window.localStorage.getItem(key);
  if (!id) { id = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`; window.localStorage.setItem(key, id); }
  return id;
}

async function recordPresence() {
  if (document.hidden) return;
  try { await fetch('/api/presence', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ visitor_id: visitorId() }) }); } catch { /* presence is non-blocking */ }
}

// ---------- ข่าวจากตาราง tcas_news (GET /api/news) ----------
const TONES = ['purple', 'blue', 'pink'];

function safeUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
  } catch { return null; }
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function newsDate(item) {
  if (item.news_date) return item.news_date;
  if (item.date_text) return item.date_text;
  if (item.date) {
    // วันที่ myTCAS ใช้ พ.ศ. และไม่มีปี พ.ศ. ในบางกรณี — แสดงวันที่แบบไทย
    const parts = String(item.date).split('-');
    const months = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
    if (parts.length === 3) return `${Number(parts[2])} ${months[Number(parts[1]) - 1] || parts[1]}`;
  }
  const created = item.created_at ? new Date(item.created_at) : null;
  return created && !Number.isNaN(created.getTime()) ? created.toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' }) : (item.created_at || '');
}

function openSource(url) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer');
}

// ทำให้ทั้งการ์ดคลิกเปิด source_url ได้ (ยกเว้นเมื่อกดปุ่ม/ลิงก์ย่อยข้างใน)
function makeClickable(node, url) {
  if (!url) return;
  node.classList.add('live');
  node.addEventListener('click', (event) => {
    if (event.target.closest('a, button')) return;
    openSource(url);
  });
}

function titleLink(tag, item, url) {
  const heading = el(tag);
  if (url) {
    const link = el('a', '', item.title || '(ไม่มีหัวข้อ)');
    link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    heading.append(link);
  } else heading.textContent = item.title || '(ไม่มีหัวข้อ)';
  return heading;
}

const NEWS_FALLBACK_COVER = 'https://www.mytcas.com/cover70.jpg';

function imageNode(imageUrl, alt, fallbackUrl) {
  const img = el('img');
  img.src = imageUrl; img.alt = alt || ''; img.loading = 'lazy';
  img.addEventListener('error', () => {
    // รูปโหลดไม่ขึ้น — สลับไปใช้พื้นหลัง myTCAS แทน
    if (fallbackUrl && img.src !== fallbackUrl) {
      img.src = fallbackUrl;
      img.classList.add('is-fallback-img');
      return;
    }
    img.parentElement?.classList.remove('has-image') || img.remove();
  });
  return img;
}

function bookmarkButton() {
  const button = el('button', 'bookmark', '♡');
  button.type = 'button';
  button.addEventListener('click', () => { button.textContent = button.textContent.trim() === '♡' ? '♥' : '♡'; button.classList.toggle('saved'); });
  return button;
}

function newsPdf(item) {
  // myTCAS ใช้ pdfs[] (ลิงก์ไฟล์ประกาศ) — ข่าวจากฐานข้อมูลใช้ pdf_url
  if (item.pdf_url) return safeUrl(item.pdf_url);
  const list = item.pdfs || [];
  return list.length ? safeUrl(list[0]) : null;
}

function buildNewsCard(item, index) {
  const url = safeUrl(item.source_url);
  const image = item.image_url && safeUrl(item.image_url);
  const pdf = newsPdf(item);
  const tone = TONES[index % TONES.length];
  const card = el('article', 'news-card');
  card.dataset.newsCard = '';
  card.dataset.search = `${item.title || ''} ${item.summary || ''}`;
  card.dataset.category = 'TCAS';
  const cover = el('div', `news-cover ${tone}`);
  if (image) {
    cover.classList.add('has-image');
    // ข่าวที่ไม่มีรูปของตัวเอง ใช้พื้นหลัง myTCAS แบบเบลอ + โลโกอีมจาง ๆ ทับ
    if (item.has_own_image === false) {
      cover.classList.add('is-fallback');
      cover.append(imageNode(image, item.title, NEWS_FALLBACK_COVER));
      cover.append(el('div', 'cover-fallback-mark', 'myTCAS'));
    } else {
      cover.append(imageNode(image, item.title, NEWS_FALLBACK_COVER));
    }
  }
  else { cover.append(el('span', '', 'TCAS'), el('div', 'cover-orbit', '✦')); }
  const body = el('div', 'news-card-body');
  const meta = el('div', 'card-meta');
  meta.append(el('span', `tag-pill ${tone}`, item.source_label || 'TCAS'), bookmarkButton());
  const footer = el('div', 'card-footer');
  footer.append(el('small', '', newsDate(item)));
  const actions = el('span');
  if (pdf) {
    const pdfLink = el('a', 'pdf-link', 'PDF');
    pdfLink.href = pdf; pdfLink.target = '_blank'; pdfLink.rel = 'noopener noreferrer';
    actions.append(pdfLink);
  }
  if (url) actions.append('อ่านต่อ →');
  footer.append(actions);
  body.append(meta, titleLink('h3', item, url), el('p', '', item.summary || ''), footer);
  card.append(cover, body);
  makeClickable(card, url);
  return card;
}

function buildNewsRow(item, index) {
  const url = safeUrl(item.source_url);
  const image = item.image_url && safeUrl(item.image_url);
  const tone = TONES[index % TONES.length];
  const row = el('article', 'news-row');
  const thumb = el('div', `news-thumb ${tone}`);
  if (image) { thumb.classList.add('has-image'); thumb.append(imageNode(image, item.title)); }
  else { thumb.append(el('span', '', 'TCAS')); const b = el('b'); b.append('TCAS', document.createElement('br'), 'Buddy'); thumb.append(b); }
  const text = el('div');
  text.append(el('span', `tag-pill ${tone}`, item.source_label || 'TCAS'), titleLink('h4', item, url), el('p', '', item.summary || ''), el('small', '', newsDate(item)));
  row.append(thumb, text, bookmarkButton());
  makeClickable(row, url);
  return row;
}

const NEWS_PAGE_SIZE = 24;
const newsState = { limit: NEWS_PAGE_SIZE, total: 0, loading: false };

async function loadNews() {
  const grid = $('#news-grid');
  const homeList = $('#home-news-list');
  if (!grid && !homeList) return;
  const query = new URLSearchParams(window.location.search).get('q') || '';
  const status = $('#news-status');
  if (newsState.loading) return;
  newsState.loading = true;
  try {
    const response = await fetch(`/api/news?limit=${grid ? newsState.limit : 3}${query && grid ? `&q=${encodeURIComponent(query)}` : ''}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (data.sample_mode) return; // myTCAS โหลดไม่สำเร็จ: คงข่าวตัวอย่างที่ server render ไว้
    const items = data.items || [];
    newsState.total = data.total || items.length;
    if (grid) {
      grid.replaceChildren(...items.map(buildNewsCard));
      if (status) {
        status.hidden = items.length > 0;
        status.textContent = items.length
          ? `พบ ${newsState.total} ข่าว · ข้อมูลจาก myTCAS`
          : (query ? `ไม่พบข่าวที่ตรงกับ “${query}”` : 'ยังไม่มีข่าวในระบบ');
      }
      const more = $('#news-more');
      if (more) more.hidden = items.length >= newsState.total;
    }
    if (homeList && items.length) homeList.replaceChildren(...items.slice(0, 3).map(buildNewsRow));
  } catch (error) {
    console.warn('โหลดข่าวไม่สำเร็จ ใช้ข่าวตัวอย่างแทน', error);
    if (status && grid) { status.hidden = false; status.textContent = 'โหลดข่าวล่าสุดไม่สำเร็จ กำลังแสดงข่าวตัวอย่าง'; }
  } finally {
    newsState.loading = false;
  }
}

// ---------- มหาวิทยาลัย + เกณฑ์รับ (ข้อมูลจากตาราง ซึ่งหลังบ้านแอดมินจัดการได้) ----------
const INSTITUTE_TONES = ['rose', 'violet', 'teal', 'gold', 'indigo', 'green', 'blue', 'pink'];

function buildInstituteCard(item, index) {
  const card = el('article', 'institute-card');
  const logo = el('div', `uni-logo ${INSTITUTE_TONES[index % INSTITUTE_TONES.length]}`);
  if (item.logo_url) {
    const img = el('img');
    img.src = item.logo_url;
    img.alt = '';
    img.loading = 'lazy';
    img.addEventListener('error', () => { logo.textContent = (item.short_name || (item.name || '?').slice(0, 2)); });
    logo.append(img);
  } else {
    logo.textContent = item.short_name || (item.name || '?').slice(0, 2);
  }
  const text = el('div');
  text.append(el('h3', '', item.name || '(ไม่มีชื่อ)'));
  const meta = [item.city, item.kind].filter(Boolean).join(' · ');
  text.append(el('p', '', meta || item.name_en || 'สถาบันอุดมศึกษา'));
  card.append(logo, text, el('button', 'round-arrow', '→'));
  return card;
}

const instState = { items: [], kind: '', query: '' };

async function loadInstitutes() {
  const grid = $('#inst-grid');
  if (!grid) return;
  try {
    const response = await fetch('/api/institutes?limit=200');
    const data = await response.json();
    if (!data.configured || !(data.items || []).length) return;  // คงข้อมูลตัวอย่างที่ server render ไว้
    instState.items = data.items;
    renderInstitutes();
  } catch { /* คงข้อมูลตัวอย่างไว้ */ }
}

function renderInstitutes() {
  const grid = $('#inst-grid');
  const status = $('#inst-status');
  if (!grid || !instState.items.length) return;
  const needle = instState.query.toLowerCase();
  const items = instState.items.filter((item) => {
    const matchKind = !instState.kind || item.kind === instState.kind;
    const haystack = `${item.name || ''} ${item.short_name || ''} ${item.city || ''} ${item.kind || ''}`.toLowerCase();
    return matchKind && (!needle || haystack.includes(needle));
  });
  if (!items.length) {
    grid.replaceChildren(el('p', 'acc-empty', 'ไม่พบสถาบันที่ตรงกับเงื่อนไข'));
    if (status) { status.hidden = false; status.textContent = 'ไม่พบสถาบันที่ตรงกับเงื่อนไข'; }
    return;
  }
  grid.replaceChildren(...items.map(buildInstituteCard));
  if (status) { status.hidden = true; }
}

function initInstituteSearch() {
  const search = $('#inst-search');
  if (!search) return;
  let timer = null;
  search.addEventListener('input', (event) => {
    window.clearTimeout(timer);
    const value = event.target.value.trim();
    timer = window.setTimeout(() => { instState.query = value; renderInstitutes(); }, 250);
  });
  $$('[data-inst-kind]').forEach((button) => button.addEventListener('click', () => {
    $$('[data-inst-kind]').forEach((item) => item.classList.remove('active'));
    button.classList.add('active');
    instState.kind = button.dataset.instKind;
    renderInstitutes();
  }));
}

function buildAdmissionRow(item) {
  const row = el('article', 'admission-row');
  row.append(el('div', 'admission-symbol', '⌘'));
  const copy = el('div', 'admission-copy');
  copy.append(el('h3', '', item.institution || '(ไม่ระบุ)'));
  copy.append(el('p', '', [item.faculty, item.program].filter(Boolean).join(' · ')));
  copy.append(el('small', '', [item.round, item.criteria].filter(Boolean).join(' — ') || 'ตรวจสอบกับประกาศทางการ'));
  row.append(copy);
  if (item.source_url) {
    const link = el('a', 'status-pill', 'เปิดดูรายละเอียด');
    link.href = item.source_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    row.append(link);
  } else {
    row.append(el('span', 'status-pill', 'ดูแหล่งอ้างอิง'));
  }
  row.append(el('span', 'row-arrow', '→'));
  return row;
}

// ---------- ค้นหาโควตา / รอบรับสมัคร (ข้อมูลสดจาก myTCAS) ----------
const QUOTA_PAGE_SIZE = 24;
const quotaState = { items: [], total: 0, limit: QUOTA_PAGE_SIZE, loading: false };

function buildQuotaRow(item) {
  const row = el('article', 'admission-row quota-row');
  // โลโก้มหาวิทยาลัย (จาก myTCAS)
  const logo = el('div', 'quota-logo');
  if (item.logo_url) {
    const img = el('img');
    img.src = item.logo_url;
    img.alt = '';
    img.loading = 'lazy';
    img.addEventListener('error', () => { logo.textContent = (item.institution || '?').slice(0, 2); });
    logo.append(img);
  } else {
    logo.textContent = (item.institution || '?').slice(0, 2);
  }
  row.append(logo);

  const copy = el('div', 'admission-copy');
  copy.append(el('h3', '', item.institution || '(ไม่ระบุ)'));
  const sub = [item.faculty, item.program].filter(Boolean).join(' · ');
  if (sub) copy.append(el('p', '', sub));
  copy.append(el('small', '', item.round || 'รอบรับสมัคร'));

  // ── แถวตัวเลขสำคัญ: โควตา / วันปิดรับ ──
  const highlights = el('div', 'quota-highlights');
  if (item.quota) {
    const box = el('div', 'quota-chip');
    box.append(el('b', '', String(item.quota)));
    box.append(el('span', '', 'คน'));
    box.append(el('small', '', 'โควตา'));
    highlights.append(box);
  }
  if (item.closed_date) {
    const days = daysUntil(item.closed_date);
    const box = el('div', 'quota-chip');
    box.append(el('b', '', formatDate(item.closed_date)));
    box.append(el('small', '', days == null ? 'ปิดรับ' : days < 0 ? 'ปิดแล้ว' : `เหลือ ${days} วัน`));
    if (days != null && days < 0) box.classList.add('is-closed');
    else if (days != null && days <= 30) box.classList.add('is-urgent');
    highlights.append(box);
  }
  if (highlights.childElementCount) copy.append(highlights);

  // ── ตารางเกณฑ์ (อ่านง่ายกว่าข้อความยาว) ──
  const scoreItems = item.score_items || [];
  if (scoreItems.length) {
    const table = el('div', 'quota-table');
    scoreItems.forEach((entry) => {
      const line = el('div', 'quota-table-row');
      line.append(el('span', 'quota-table-label', entry.label));
      line.append(el('span', 'quota-table-value', `${entry.value}${entry.unit ? ' ' + entry.unit : ''}`));
      table.append(line);
    });
    copy.append(table);
  }

  // ── เงื่อนไขเพิ่มเติม (ซ่อนไว้ก่อน) ──
  const notes = item.notes || [];
  const hasInterview = item.interview_location && item.interview_location !== 'ไม่มีสอบสัมภาษณ์';
  if (notes.length || hasInterview) {
    const details = el('details', 'quota-details');
    details.append(el('summary', '', notes.length ? 'เงื่อนไขและรายละเอียดเพิ่มเติม' : 'รายละเอียดการสัมภาษณ์'));
    const body = el('div', 'quota-details-body');
    if (notes.length) {
      const noteList = el('ol', 'quota-note-list');
      notes.forEach((note) => noteList.append(el('li', '', note)));
      body.append(noteList);
    }
    if (hasInterview) {
      const interview = el('div', 'quota-interview-box');
      interview.append(el('b', '', 'สัมภาษณ์'));
      interview.append(el('p', '', item.interview_location));
      if (item.interview_date) interview.append(el('p', '', `วันที่: ${item.interview_date}`));
      if (item.interview_time) interview.append(el('p', '', `เวลา: ${item.interview_time}`));
      body.append(interview);
    }
    details.append(body);
    copy.append(details);
  }
  row.append(copy);

  if (item.source_url) {
    const link = el('a', 'status-pill', 'เปิดประกาศ');
    link.href = item.source_url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    row.append(link);
  }
  row.append(el('span', 'row-arrow', '→'));
  return row;
}

function daysUntil(dateStr) {
  const target = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(target.getTime())) return null;
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((target - today) / 86400000);
}

function formatDate(dateStr) {
  const parts = String(dateStr).split('-');
  if (parts.length !== 3) return dateStr;
  const months = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
  const month = months[Number(parts[1]) - 1] || parts[1];
  return `${Number(parts[2])} ${month}`;
}

async function loadQuota() {
  if (quotaState.loading) return;
  const list = $('#quota-results');
  const status = $('#quota-status');
  if (!list) return;
  quotaState.loading = true;
  if (status) { status.hidden = false; status.textContent = 'กำลังโหลดข้อมูลรอบรับสมัครจาก myTCAS…'; }

  const inst = ($('#quota-inst')?.value || '').trim();
  const fac = ($('#quota-faculty')?.value || '').trim();
  const round = ($('#quota-round')?.value || '').trim();
  const query = [inst, fac, round].filter(Boolean).join(' ');

  try {
    const params = new URLSearchParams({ limit: String(quotaState.limit) });
    if (query) params.set('q', query);
    const response = await fetch(`/api/tcas/quota?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const items = data.items || [];
    quotaState.total = data.total || 0;
    if (!items.length) {
      list.replaceChildren(el('p', 'acc-empty', query
        ? 'ไม่พบรอบรับสมัครที่ตรงกับคำค้นหา — ลองเปลี่ยนคำค้นหา'
        : 'ไม่พบข้อมูลรอบรับสมัครจาก myTCAS'));
    } else {
      list.replaceChildren(...items.map(buildQuotaRow));
    }
    if (status) {
      status.textContent = `พบ ${quotaState.total} รายการ จาก ${data.programs || 0} หลักสูตร · ข้อมูลจาก myTCAS`;
    }
    const more = $('#quota-more');
    if (more) more.hidden = items.length >= quotaState.total;
  } catch (error) {
    console.warn('โหลดข้อมูลรอบรับสมัครไม่สำเร็จ', error);
    list.replaceChildren(el('p', 'acc-empty', 'โหลดข้อมูลจาก myTCAS ไม่สำเร็จ — ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต'));
    if (status) { status.hidden = false; status.textContent = 'โหลดข้อมูลจาก myTCAS ไม่สำเร็จ'; }
  } finally {
    quotaState.loading = false;
  }
}

function initQuotaSearch() {
  const button = $('#quota-search');
  if (!button) return;
  const run = () => { quotaState.limit = QUOTA_PAGE_SIZE; loadQuota(); };
  button.addEventListener('click', run);
  ['#quota-inst', '#quota-faculty', '#quota-round'].forEach((selector) => {
    $(selector)?.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); run(); } });
  });
  $('#quota-more')?.addEventListener('click', () => {
    quotaState.limit += QUOTA_PAGE_SIZE;
    loadQuota();
  });
  // โหลดข้อมูลครั้งแรกตอนเปิดหน้า
  run();
}

// ---------- ค้นหาทุนการศึกษา (ข้อมูลจากกสศ. + Scholarship.in.th) ----------
const SCHOLAR_PAGE_SIZE = 24;
const scholarState = { status: '', level: '', source: '', genre: '', limit: SCHOLAR_PAGE_SIZE, total: 0, loading: false };

function scholarQuery() {
  const params = new URLSearchParams();
  const q = ($('#scholar-q')?.value || '').trim();
  if (q) params.set('q', q);
  if (scholarState.status) params.set('status', scholarState.status);
  if (scholarState.level) params.set('level', scholarState.level);
  if (scholarState.source) params.set('source', scholarState.source);
  if (scholarState.genre) params.set('genre', scholarState.genre);
  params.set('limit', String(scholarState.limit));
  return params.toString();
}

function buildScholarCard(item) {
  const url = safeUrl(item.url);
  const image = item.image_url ? safeUrl(item.image_url) : null;
  const card = el('article', 'scholar-card');
  const cover = el('div', 'scholar-cover');
  if (image) { cover.classList.add('has-image'); cover.append(imageNode(image, item.title)); }
  else cover.append(el('span', '', 'ทุน'), el('div', 'cover-orbit', '◈'));
  const body = el('div', 'scholar-body');
  const meta = el('div', 'scholar-meta');
  meta.append(el('span', `scholar-source ${item.source}`, item.source_label));
  (item.levels || []).forEach((level) => meta.append(el('span', 'scholar-level', level)));
  body.append(meta);
  body.append(titleLink('h3', item, url));
  if (item.summary) body.append(el('p', 'scholar-summary', item.summary));
  const facts = el('ul', 'scholar-facts');
  if (item.sponsor) facts.append(el('li', '', `ผู้ให้ทุน: ${item.sponsor}`));
  if (item.amount) facts.append(el('li', '', `มูลค่าทุน: ${item.amount}`));
  if (item.deadline) facts.append(el('li', '', `ปิดรับสมัคร: ${item.deadline}`));
  if (item.channel) facts.append(el('li', '', `ช่องทาง: ${item.channel}`));
  if (facts.childElementCount) body.append(facts);
  const status = item.status;
  if (status) {
    const badge = el('span', `scholar-status ${status === 'เปิดรับสมัคร' ? 'open' : status === 'ใกล้ปิดรับ' ? 'closing' : status === 'ปิดรับแล้ว' ? 'closed' : 'unknown'}`, status);
    body.append(badge);
  }
  const tags = (item.tags || []).filter((tag) => tag && tag !== 'บทความ');
  if (tags.length) {
    const tagRow = el('div', 'scholar-tags');
    tags.slice(0, 4).forEach((tag) => tagRow.append(el('span', 'scholar-tag', tag)));
    body.append(tagRow);
  }
  const footer = el('div', 'scholar-footer');
  footer.append(el('small', '', item.published_at ? new Date(item.published_at).toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' }) : ''));
  const actions = el('span', 'scholar-actions');
  if (url) {
    const link = el('a', 'scholar-link', 'ดูรายละเอียด →');
    link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
    actions.append(link);
  }
  const applyUrl = item.apply_url ? safeUrl(item.apply_url) : null;
  if (applyUrl && applyUrl !== url) {
    const applyLink = el('a', 'scholar-link', 'ไปสมัคร →');
    applyLink.href = applyUrl; applyLink.target = '_blank'; applyLink.rel = 'noopener noreferrer';
    actions.append(applyLink);
  }
  if (actions.childElementCount) footer.append(actions);
  body.append(footer);
  card.append(cover, body);
  makeClickable(card, url);
  return card;
}

// ---------- ตัวกรองแบบ dropdown (กดออกมาเลือก — บรรทัดเดียว กระชับ) ----------
const SCHOLAR_SELECTS = {
  status: { menu: '#scholar-status-menu', trigger: '#scholar-status-trigger', value: '#scholar-status-value' },
  level: { menu: '#scholar-level-menu', trigger: '#scholar-level-trigger', value: '#scholar-level-value' },
  source: { menu: '#scholar-source-menu', trigger: '#scholar-source-trigger', value: '#scholar-source-value' },
  genre: { menu: '#scholar-genre-menu', trigger: '#scholar-genre-trigger', value: '#scholar-genre-value' },
};

function closeScholarSelects(except) {
  Object.entries(SCHOLAR_SELECTS).forEach(([key, config]) => {
    if (key === except) return;
    const menu = $(config.menu);
    const trigger = $(config.trigger);
    if (menu) menu.hidden = true;
    if (trigger) trigger.setAttribute('aria-expanded', 'false');
  });
}

function toggleScholarSelect(key) {
  const config = SCHOLAR_SELECTS[key];
  const menu = $(config.menu);
  const trigger = $(config.trigger);
  if (!menu || !trigger) return;
  const willOpen = menu.hidden;
  closeScholarSelects(key);
  menu.hidden = !willOpen;
  trigger.setAttribute('aria-expanded', String(willOpen));
  if (willOpen) {
    const active = menu.querySelector('.scholar-select-option.is-active') || menu.querySelector('.scholar-select-option');
    active?.scrollIntoView({ block: 'nearest' });
  }
}

function buildScholarSelect(key, items) {
  const config = SCHOLAR_SELECTS[key];
  const menu = $(config.menu);
  const valueBox = $(config.value);
  if (!menu) return;
  const options = [{ key: '', label: 'ทั้งหมด', count: null }, ...items];
  menu.replaceChildren(...options.map((item) => {
    const option = el('button', 'scholar-select-option', item.count != null ? `${item.label} (${item.count})` : item.label);
    option.type = 'button';
    option.setAttribute('role', 'option');
    option.dataset.key = item.key;
    if (scholarState[key] === item.key) option.classList.add('is-active');
    return option;
  }));
  const selected = options.find((item) => item.key === scholarState[key]) || options[0];
  if (valueBox) {
    valueBox.textContent = selected.count != null ? `${selected.label} (${selected.count})` : selected.label;
    valueBox.classList.toggle('is-set', Boolean(scholarState[key]));
  }
  const trigger = $(config.trigger);
  if (trigger) trigger.classList.toggle('is-set', Boolean(scholarState[key]));
}

function renderScholarFilters(facets) {
  buildScholarSelect('status', facets.statuses || []);
  buildScholarSelect('level', facets.levels || []);
  buildScholarSelect('source', facets.sources || []);
  buildScholarSelect('genre', facets.genres || []);
  const clear = $('#scholar-clear');
  if (clear) clear.hidden = !(scholarState.status || scholarState.level || scholarState.source || scholarState.genre);
}

async function loadScholarships() {
  if (scholarState.loading) return;
  const list = $('#scholar-list');
  const status = $('#scholar-status');
  if (!list) return;
  scholarState.loading = true;
  if (status) { status.hidden = false; status.textContent = 'กำลังค้นหาทุนจากกสศ. และ Scholarship.in.th…'; }
  try {
    const response = await fetch(`/api/scholarships?${scholarQuery()}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const items = data.items || [];
    scholarState.total = data.total || 0;
    renderScholarFilters(data.facets || {});
    if (!items.length) {
      list.replaceChildren(el('p', 'acc-empty', 'ไม่พบทุนที่ตรงกับคำค้นหา — ลองเปลี่ยนคำค้นหาหรือล้างตัวกรอง'));
    } else {
      list.replaceChildren(...items.map(buildScholarCard));
    }
    if (status) {
      const errorText = Object.values(data.errors || {}).join(' · ');
      status.textContent = errorText
        ? `พบ ${scholarState.total} รายการ (บางแหล่งข้อมูลโหลดไม่สำเร็จ: ${errorText})`
        : `พบ ${scholarState.total} รายการ จากกสศ. และ Scholarship.in.th`;
    }
    const more = $('#scholar-more');
    if (more) more.hidden = items.length >= scholarState.total;
  } catch (error) {
    console.warn('โหลดข้อมูลทุนไม่สำเร็จ', error);
    list.replaceChildren(el('p', 'acc-empty', 'โหลดข้อมูลทุนไม่สำเร็จ กรุณาลองใหม่อีกครั้ง'));
    if (status) { status.hidden = false; status.textContent = 'โหลดข้อมูลทุนไม่สำเร็จ — ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต'; }
  } finally {
    scholarState.loading = false;
  }
}

function initScholarshipSearch() {
  const input = $('#scholar-q');
  const list = $('#scholar-list');
  if (!list) return;
  const run = () => { scholarState.limit = SCHOLAR_PAGE_SIZE; loadScholarships(); };

  $('#scholar-search-btn')?.addEventListener('click', run);
  input?.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); run(); } });

  // เปิด/ปิด dropdown
  Object.entries(SCHOLAR_SELECTS).forEach(([key, config]) => {
    $(config.trigger)?.addEventListener('click', (event) => { event.stopPropagation(); toggleScholarSelect(key); });
    $(config.menu)?.addEventListener('click', (event) => {
      const option = event.target.closest('.scholar-select-option');
      if (!option) return;
      scholarState[key] = option.dataset.key;
      closeScholarSelects();
      run();
    });
  });
  document.addEventListener('click', (event) => {
    if (event.target.closest('.scholar-select')) return;
    closeScholarSelects();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeScholarSelects();
  });

  // ล้างตัวกรองทั้งหมด
  $('#scholar-clear')?.addEventListener('click', () => {
    scholarState.status = '';
    scholarState.level = '';
    scholarState.source = '';
    scholarState.genre = '';
    run();
  });

  $('#scholar-more')?.addEventListener('click', () => {
    scholarState.limit += SCHOLAR_PAGE_SIZE;
    loadScholarships();
  });
  // รองรับการเข้าผ่าน ?q=... จากช่องค้นหาด้านบน
  const preset = new URLSearchParams(window.location.search).get('q');
  if (preset && input) { input.value = preset; }
  run();
}

async function startGoogleLogin() {
  const status = $('#login-page-status') || $('#login-status');
  if (status) status.textContent = 'กำลังตรวจสอบการตั้งค่า Google Login...';
  // จำหน้าที่ผู้ใช้ต้องการเข้าจริง ๆ ไว้ เผื่อ Google redirect กลับมาที่หน้าแรก
  rememberDesiredPath();
  try {
    const response = await fetch('/api/config');
    const config = await response.json();
    if (!config.configured || !config.supabase_url || !config.supabase_anon_key) {
      if (status) status.textContent = 'ยังไม่ได้ตั้งค่า Supabase/Google provider — ดูขั้นตอนได้ที่ FAQ';
      return;
    }
    if (!window.supabase) {
      const script = document.createElement('script');
      script.src = 'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2';
      script.onload = () => launchSupabase(config);
      script.onerror = () => { if (status) status.textContent = 'โหลดตัวเชื่อมต่อ Supabase ไม่สำเร็จ'; };
      document.head.appendChild(script);
    } else launchSupabase(config);
  } catch { if (status) status.textContent = 'เชื่อมต่อการตั้งค่าไม่ได้ โปรดลองใหม่'; }
}

async function launchSupabase(config) {
  const status = $('#login-page-status') || $('#login-status');
  try {
    const client = window.supabase.createClient(config.supabase_url, config.supabase_anon_key);
    if (status) status.textContent = 'กำลังพาไปหน้า Google...';
    const { error } = await client.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin + window.location.pathname },
    });
    if (error) throw error;
  } catch (e) {
    console.error('Google login failed:', e);
    if (status) status.textContent = 'Login ไม่สำเร็จ: ' + (e.message || e);
  }
}


// ---------- ระบบบัญชี: ตัวช่วยกลาง (ใช้ร่วมกับ account.js) ----------
window.myAccount = null;

function announceGuest(reason) {
  document.dispatchEvent(new CustomEvent('account:guest', { detail: { reason } }));
}

async function accessToken() {
  if (supabaseClient) {
    const { data } = await supabaseClient.auth.getSession();
    if (data.session?.access_token) return data.session.access_token;
  }
  return currentSession?.access_token || null;
}

// เรียก API ที่ต้องล็อกอิน: แนบ Bearer token และโยน Error พร้อมข้อความภาษาไทยจาก backend
async function authFetch(path, options = {}) {
  const token = await accessToken();
  if (!token) throw new Error('ยังไม่ได้เข้าสู่ระบบ');
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}), Authorization: `Bearer ${token}` },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `เกิดข้อผิดพลาด (${response.status})`);
  return data;
}

function applyAvatar(profile) {
  ['#header-avatar', '#menu-avatar'].forEach((selector) => {
    const node = $(selector);
    if (!node) return;
    if (profile.avatar_url) {
      node.classList.add('has-img');
      node.style.backgroundImage = `url("${profile.avatar_url}")`;
    } else {
      node.classList.remove('has-img');
      node.style.backgroundImage = '';
      node.textContent = (profile.display_name || 'U').trim().charAt(0).toUpperCase();
    }
  });
  const name = profile.display_name;
  if (name) {
    ['#header-name', '#menu-name'].forEach((selector) => { const node = $(selector); if (node) node.textContent = name; });
  }
}

async function loadMyAccount() {
  try {
    const data = await authFetch('/api/account');
    window.myAccount = data.profile;
    applyAvatar(data.profile);
    document.dispatchEvent(new CustomEvent('account:ready', { detail: data.profile }));
  } catch (error) {
    console.warn('โหลดข้อมูลบัญชีไม่สำเร็จ', error);
    document.dispatchEvent(new CustomEvent('account:error', { detail: { message: error.message } }));
  }
}

let toastTimer = null;
function toast(message) {
  const node = $('#toast');
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => { node.hidden = true; }, 3200);
}

// ลิงก์คำเชิญ: /invite/CODE -> /login?invite=CODE เก็บรหัสไว้จนกว่าจะล็อกอินสำเร็จ
const INVITE_KEY = 'tcas_buddy_pending_invite';
function rememberInviteFromUrl() {
  const code = new URLSearchParams(window.location.search).get('invite');
  if (!code || !/^[A-Za-z0-9_-]{4,40}$/.test(code)) return;
  try { window.localStorage.setItem(INVITE_KEY, code); } catch { /* storage unavailable */ }
  const status = $('#login-page-status');
  if (status) status.textContent = 'คุณได้รับคำเชิญ เข้าสู่ระบบเพื่อรับคำเชิญนี้';
}

async function redeemPendingInvite() {
  let code = null;
  try { code = window.localStorage.getItem(INVITE_KEY); } catch { return null; }
  if (!code) return null;
  let message;
  try {
    const result = await authFetch('/api/account/invites/redeem', { method: 'POST', body: JSON.stringify({ code }) });
    message = result.already ? 'คุณรับคำเชิญนี้ไว้แล้ว' : 'รับคำเชิญเรียบร้อย ยินดีต้อนรับ!';
  } catch (error) { message = error.message; }
  try { window.localStorage.removeItem(INVITE_KEY); } catch { /* ignore */ }
  return message;
}

window.addEventListener('DOMContentLoaded', () => {
  try {
    const pending = window.localStorage.getItem('tcas_buddy_toast');
    if (pending) { window.localStorage.removeItem('tcas_buddy_toast'); toast(pending); }
  } catch { /* ignore */ }
});

// ---------- สถานะออนไลน์ของแอดมิน ----------
// แอดมินต้องส่ง heartbeat เป็นระยะ ๆ ไม่ว่าจะอยู่หน้าไหน ระบบถึงจะรู้ว่ามีคนตอบ Ticket ได้
// (ถ้าเรียกจากผู้ใช้ทั่วไปจะได้ 403 ซึ่งไม่เป็นไร — ไม่ต้องแสดง error)
async function adminHeartbeat() {
  try {
    const response = await fetch('/api/tickets/status/admin', { method: 'POST', headers: { Authorization: `Bearer ${await accessToken()}` } });
    if (response.ok) document.dispatchEvent(new CustomEvent('admin:online'));
  } catch { /* ไม่ใช่แอดมิน หรือยังไม่ได้ล็อกอิน */ }
}

window.addEventListener('DOMContentLoaded', () => {
  window.setTimeout(adminHeartbeat, 1500);
  window.setInterval(adminHeartbeat, 60000);
});
