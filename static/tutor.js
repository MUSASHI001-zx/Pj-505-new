// หน้า AI Tutor / Notebook — สมุดโน้ตเรียนรายวิชา คุยกับ AI ในบริบทของสมุด
// ประกาศตัวช่วยเอง เพราะ app.js เป็น IIFE (ตัวแปร $ / $$ ไม่ได้อยู่ใน window)
(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const toast = (message) => {
    const node = document.querySelector('#toast');
    if (!node) return;
    node.textContent = message;
    node.hidden = false;
    window.setTimeout(() => { node.hidden = true; }, 2600);
  };

  const state = {
    subject: 'TCAS',
    notebooks: [],
    sources: [],
    messages: [],
    starters: [],
    sending: false,
  };

  const MAX_HISTORY = 12;

  // ---------- เรียก API ที่ต้องล็อกอิน ----------
  // ใช้ window.myAccount เป็นสัญญาณว่าล็อกอินแล้ว (app.js ตั้งไว้หลังโหลดโปรไฟล์สำเร็จ)
  async function tutorFetch(path, options = {}) {
    if (!window.myAccount) throw new Error('ยังไม่ได้เข้าสู่ระบบ');
    const token = await getToken();
    if (!token) throw new Error('ยังไม่ได้เข้าสู่ระบบ');
    const response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}), Authorization: `Bearer ${token}` },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `เกิดข้อผิดพลาด (${response.status})`);
    return data;
  }

  async function getToken() {
    // app.js เก็บ client ไว้ใน window.supabase — ใช้ session จากที่นั่น
    try {
      if (window.supabase?.auth) {
        const { data } = await window.supabase.auth.getSession();
        if (data.session?.access_token) return data.session.access_token;
      }
    } catch { /* ignore */ }
    return null;
  }

  // ---------- แสดงข้อความแชท ----------
  function formatContent(text) {
    const lines = String(text || '').split('\n');
    const nodes = [];
    let list = null;
    let listType = '';

    const inline = (value) => value
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    const flush = () => { if (list) { nodes.push(list); list = null; listType = ''; } };

    lines.forEach((line) => {
      const trimmed = line.trim();
      if (!trimmed) { flush(); return; }
      const unordered = trimmed.match(/^[-*•]\s+(.*)$/);
      const ordered = trimmed.match(/^\d+[.)]\s+(.*)$/);
      if (unordered || ordered) {
        const type = unordered ? 'ul' : 'ol';
        if (!list || listType !== type) { flush(); list = el(type); listType = type; }
        const item = el('li');
        item.innerHTML = inline((unordered || ordered)[1]);
        list.append(item);
        return;
      }
      flush();
      const paragraph = el('p');
      paragraph.innerHTML = inline(trimmed);
      nodes.push(paragraph);
    });
    flush();
    return nodes.length ? nodes : [el('p', '', String(text || ''))];
  }

  function renderMessage(role, content, model) {
    const row = el('div', `chat-bubble-row ${role}`);
    row.append(el('div', `chat-avatar ${role}`, role === 'user' ? 'คุณ' : '✦'));
    const bubble = el('div', 'chat-bubble');
    bubble.append(...formatContent(content));
    if (model) bubble.append(el('small', 'chat-model-tag', model));
    row.append(bubble);
    return row;
  }

  function showThinking() {
    const box = $('#tutor-messages');
    if (!box) return null;
    const row = el('div', 'chat-bubble-row assistant');
    row.append(el('div', 'chat-avatar assistant', '✦'));
    const bubble = el('div', 'chat-bubble chat-thinking');
    bubble.append(el('i'), el('i'), el('i'));
    row.append(bubble);
    box.append(row);
    scrollDown();
    return row;
  }

  function showError(message) {
    const box = $('#tutor-messages');
    if (box) { box.append(el('div', 'chat-error', message)); scrollDown(); }
  }

  function scrollDown() {
    const box = $('#tutor-messages');
    if (box) box.scrollTop = box.scrollHeight;
  }

  function renderWelcome() {
    const box = $('#tutor-messages');
    if (!box) return;
    box.replaceChildren();
    const welcome = el('div', 'chat-welcome');
    welcome.append(el('div', 'advisor-orb', '✦'));
    welcome.append(el('h3', '', 'สวัสดี! ฉันคือ AI Tutor'));
    welcome.append(el('p', '', 'ถามเรื่องเรียนในวิชานี้ได้เลย ฉันจะอ้างอิงบทเรียนที่คุณเก็บไว้ในสมุดโน้ตด้วย'));
    if (state.starters.length) {
      const suggestions = el('div', 'chat-suggestions');
      state.starters.forEach((text) => {
        const button = el('button', '', text);
        button.type = 'button';
        button.addEventListener('click', () => { const input = $('#tutor-input'); if (input) { input.value = text; growInput(); send(); } });
        suggestions.append(button);
      });
      welcome.append(suggestions);
    }
    box.append(welcome);
  }

  // ---------- สมุดโน้ต ----------
  function renderSubjectTabs() {
    $$('[data-tutor-subject]').forEach((button) => {
      button.classList.toggle('active', button.dataset.tutorSubject === state.subject);
    });
  }

  function renderSourceCards() {
    const box = $('#tutor-source-list');
    if (!box) return;
    if (!state.sources.length) {
      box.replaceChildren(el('p', 'acc-empty', 'ยังไม่มีบทเรียน — กด + เพิ่ม'));
      return;
    }
    box.replaceChildren(...state.sources.map((source) => {
      const card = el('div', 'tutor-source');
      card.append(el('b', '', source.title));
      const kind = el('span', `tutor-kind ${source.kind || 'note'}`, source.is_ai_generated ? 'AI สรุปให้' : (source.kind === 'practice' ? 'แบบฝึก' : 'บันทึกเอง'));
      card.append(kind);
      if (source.created_at) {
        const date = new Date(source.created_at);
        if (!Number.isNaN(date.getTime())) {
          card.append(el('small', '', date.toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' })));
        }
      }
      const del = el('button', 'tutor-source-del', '×');
      del.type = 'button';
      del.setAttribute('aria-label', `ลบ ${source.title}`);
      del.addEventListener('click', async () => {
        if (!window.confirm(`ลบ "${source.title}" ?`)) return;
        try {
          await tutorFetch(`/api/tutor/sources/${source.id}`, { method: 'DELETE' });
          await loadSources();
          toast('ลบบทเรียนแล้ว');
        } catch (error) { toast(error.message); }
      });
      card.append(del);
      return card;
    }));
  }

  function renderSources() {
    const count = $('#tutor-source-count');
    if (count) count.textContent = state.sources.length ? `${state.sources.length} บทเรียน` : 'ยังไม่มีบทเรียน';

    // หน้าหลัก — แสดงเป็นรายการแบบเดิม
    const list = $('#tutor-note-list');
    if (list) {
      if (!state.sources.length) {
        list.replaceChildren(el('p', 'acc-empty', 'ยังไม่มีบทเรียนในสมุดนี้ — กด "เปิดสมุดโน้ต" เพื่อเพิ่ม'));
      } else {
        list.replaceChildren(...state.sources.slice(0, 6).map((source) => {
          const row = el('div', 'note-row');
          row.append(el('span', 'note-icon', state.subject));
          const copy = el('div');
          copy.append(el('b', '', source.title));
          const kind = source.is_ai_generated ? 'AI สรุปให้' : (source.kind === 'practice' ? 'แบบฝึก' : 'บันทึกเอง');
          copy.append(el('small', '', kind));
          row.append(copy);
          const open = el('button', 'button soft', 'เปิดอ่าน');
          open.addEventListener('click', () => openChat());
          row.append(open);
          return row;
        }));
      }
    }
    renderSourceCards();
  }

  function renderMessages() {
    const box = $('#tutor-messages');
    if (!box) return;
    if (!state.messages.length) { renderWelcome(); return; }
    box.replaceChildren(...state.messages.map((message) => renderMessage(message.role, message.content, message.model)));
    scrollDown();
  }

  // ---------- โหลดข้อมูล ----------
  async function loadNotebooks() {
    try {
      const data = await tutorFetch('/api/tutor/notebooks');
      state.notebooks = data.items || [];
      state.starters = data.starter_questions?.[state.subject] || [];
      renderSubjectTabs();
      await loadSources();
      await loadMessages();
    } catch (error) {
      if (/ยังไม่ได้เข้าสู่ระบบ/.test(error.message)) {
        showSignedOut(error.message);
        return;
      }
      const box = $('#tutor-source-list');
      if (box) box.replaceChildren(el('p', 'acc-empty', error.message));
    }
  }

  async function loadSources() {
    try {
      const data = await tutorFetch(`/api/tutor/notebooks/${encodeURIComponent(state.subject)}`);
      state.sources = data.sources || [];
      state.starters = data.starter_questions?.length ? data.starter_questions : (state.starters || []);
      renderSources();
      const title = $('#tutor-chat-title');
      if (title) title.textContent = `AI Tutor · ${state.subject}`;
    } catch (error) {
      const box = $('#tutor-source-list');
      if (box) box.replaceChildren(el('p', 'acc-empty', error.message));
    }
  }

  async function loadMessages() {
    try {
      const data = await tutorFetch(`/api/tutor/notebooks/${encodeURIComponent(state.subject)}/messages`);
      state.messages = data.items || [];
      renderMessages();
    } catch (error) {
      renderWelcome();
    }
  }

  async function selectSubject(subject) {
    if (state.subject === subject) return;
    state.subject = subject;
    state.messages = [];
    renderSubjectTabs();
    await loadSources();
    await loadMessages();
  }

  // ---------- ส่งคำถาม ----------
  async function send() {
    const input = $('#tutor-input');
    const box = $('#tutor-messages');
    if (!input || !box || state.sending) return;
    const message = input.value.trim();
    if (!message) return;

    state.sending = true;
    const sendButton = $('#tutor-send');
    if (sendButton) sendButton.disabled = true;

    box.querySelector('.chat-welcome')?.remove();
    box.append(renderMessage('user', message));
    input.value = '';
    growInput();
    scrollDown();

    const thinking = showThinking();
    try {
      const data = await tutorFetch(`/api/tutor/notebooks/${encodeURIComponent(state.subject)}/chat`, {
        method: 'POST',
        body: { message },
      });
      thinking?.remove();
      if (data.error) {
        showError(data.error);
        return;
      }
      const answer = data.answer || 'ขออภัย ยังไม่มีคำตอบ ลองถามใหม่อีกครั้งนะ';
      box.append(renderMessage('assistant', answer, data.model));
      const status = $('#tutor-status');
      if (status) {
        const count = data.context_count ? ` · อ้างอิงบทเรียน ${data.context_count} ชิ้น` : '';
        status.textContent = `พร้อมคุย${count}`;
      }
      scrollDown();
    } catch (error) {
      thinking?.remove();
      showError(error.message || 'ส่งคำถามไม่สำเร็จ ลองใหม่อีกครั้ง');
    } finally {
      state.sending = false;
      if (sendButton) sendButton.disabled = false;
      input.focus();
    }
  }

  // ---------- ช่องพิมพ์ ----------
  function growInput() {
    const input = $('#tutor-input');
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
  }

  // ---------- modal แชท ----------
  function openChat() {
    const modal = $('#tutor-chat-modal');
    if (!modal) return;
    modal.classList.add('open');
    const title = $('#tutor-chat-title');
    if (title) title.textContent = `AI Tutor · ${state.subject}`;
    loadSources();
    loadMessages();
  }

  function closeChat() {
    $('#tutor-chat-modal')?.classList.remove('open');
  }

  // ---------- กล่องเพิ่มบทเรียน ----------
  function openModal() {
    const modal = $('#tutor-modal');
    if (!modal) return;
    $('#tutor-source-title').value = '';
    $('#tutor-source-content').value = '';
    $('#tutor-source-url').value = '';
    $('#tutor-modal-status').textContent = '';
    modal.classList.add('open');
    $('#tutor-source-title').focus();
  }

  function closeModal() {
    $('#tutor-modal')?.classList.remove('open');
  }

  async function saveNote(aiSummarize) {
    const status = $('#tutor-modal-status');
    const title = $('#tutor-source-title').value.trim();
    const content = $('#tutor-source-content').value.trim();
    const url = $('#tutor-source-url').value.trim();
    if (!content) {
      if (status) status.textContent = 'กรุณาใส่เนื้อหาก่อน';
      return;
    }
    if (status) status.textContent = aiSummarize ? 'กำลังให้ AI สรุป...' : 'กำลังบันทึก...';
    try {
      if (aiSummarize) {
        await tutorFetch(`/api/tutor/notebooks/${encodeURIComponent(state.subject)}/summarize`, {
          method: 'POST',
          body: { title, content, source_url: url },
        });
      } else {
        await tutorFetch(`/api/tutor/notebooks/${encodeURIComponent(state.subject)}/sources`, {
          method: 'POST',
          body: { title: title || 'บทเรียน', content, source_url: url, kind: 'note' },
        });
      }
      closeModal();
      await loadSources();
      toast(aiSummarize ? 'ให้ AI สรุปแล้ว' : 'บันทึกบทเรียนแล้ว');
    } catch (error) {
      if (status) status.textContent = error.message;
    }
  }

  // ---------- ยังไม่ได้เข้าสู่ระบบ ----------
  function showSignedOut(message) {
    const box = $('#tutor-source-list');
    if (box) {
      box.replaceChildren();
      const wrap = el('div', 'tutor-signed-out');
      wrap.append(el('p', '', message || 'เข้าสู่ระบบเพื่อใช้สมุดโน้ตของคุณ'));
      const button = el('button', 'button primary', 'เข้าสู่ระบบด้วย Google');
      button.type = 'button';
      button.addEventListener('click', () => { $('#login-btn')?.click(); });
      wrap.append(button);
      box.append(wrap);
    }
    const status = $('#tutor-status');
    if (status) status.textContent = 'ยังไม่ได้เข้าสู่ระบบ';
    const subjects = $('#tutor-subjects');
    if (subjects) subjects.replaceChildren();
    const input = $('#tutor-input');
    if (input) input.disabled = true;
    const sendButton = $('#tutor-send');
    if (sendButton) sendButton.disabled = true;
  }

  // ---------- เริ่ม ----------
  function init() {
    if (!$('#tutor-form')) return;
    const input = $('#tutor-input');

    $('#tutor-form').addEventListener('submit', (event) => { event.preventDefault(); send(); });
    input?.addEventListener('input', growInput);
    input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); }
    });

    $('#tutor-new-source')?.addEventListener('click', openModal);
    $('#tutor-modal-close')?.addEventListener('click', closeModal);
    $('#tutor-modal')?.addEventListener('click', (event) => { if (event.target.id === 'tutor-modal') closeModal(); });
    $('#tutor-save-note')?.addEventListener('click', () => saveNote(false));
    $('#tutor-ai-summarize')?.addEventListener('click', () => saveNote(true));

    // ปุ่มโหมดการ์ด 3 ใบ — เปิดหน้าต่างแชท
    $$('[data-tutor-mode]').forEach((card) => {
      card.addEventListener('click', () => openChat());
    });
    // แท็บวิชา
    $$('[data-tutor-subject]').forEach((button) => {
      button.addEventListener('click', () => selectSubject(button.dataset.tutorSubject));
    });

    $('#tutor-chat-close')?.addEventListener('click', closeChat);
    $('#tutor-chat-modal')?.addEventListener('click', (event) => { if (event.target.id === 'tutor-chat-modal') closeChat(); });

    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape') return;
      closeModal();
      closeChat();
    });

    loadNotebooks();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
