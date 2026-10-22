// แท็บ "AI ที่ปรึกษา" ในหน้า /community — แชทกับ AI แบบเว็บคุยกับ AI ทั่วไป
// ใช้ตัวช่วยกลางจาก app.js: $, $$, el, toast
(() => {
  const state = {
    history: [],
    model: '',
    sending: false,
    configured: false,
  };

  const MAX_HISTORY = 20;

  // ---------- แสดงข้อความ ----------
  function renderWelcome() {
    // หน้าต้อนรับอยู่ใน template แล้ว — ไม่ต้องสร้างซ้ำ
    const box = $('#advisor-messages');
    if (!box) return;
    if (!box.querySelector('.chat-welcome')) {
      const welcome = el('div', 'chat-welcome');
      welcome.append(el('div', 'advisor-orb', '✦'));
      welcome.append(el('h3', '', 'สวัสดี! ฉันคือ TCAS Buddy'));
      welcome.append(el('p', '', 'ถามเรื่องการเตรียมตัว TCAS การเลือกคณะ เกณฑ์รับ ทุนการศึกษา หรืออะไรก็ได้ที่เกี่ยวกับการสมัครมหาวิทยาลัย'));
      box.replaceChildren(welcome);
    }
  }

  function renderMessage(role, content) {
    const row = el('div', `chat-bubble-row ${role}`);
    row.append(el('div', `chat-avatar ${role}`, role === 'user' ? 'คุณ' : '✦'));
    const bubble = el('div', 'chat-bubble');
    bubble.append(...formatContent(content));
    row.append(bubble);
    return row;
  }

  // แปลง Markdown พื้นฐานเป็น HTML อย่างปลอดภัย (ไม่ใช้ innerHTML กับข้อมูลดิบ)
  function formatContent(text) {
    const lines = String(text || '').split('\n');
    const nodes = [];
    let list = null;
    let listType = '';

    const inline = (value) => {
      // escape ก่อน แล้วค่อยแปลง **bold** / `code` / [link](url)
      const escaped = value
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      return escaped;
    };

    const flush = () => {
      if (list) { nodes.push(list); list = null; listType = ''; }
    };

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

  function showThinking() {
    const box = $('#advisor-messages');
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
    const box = $('#advisor-messages');
    if (!box) return;
    box.append(el('div', 'chat-error', message));
    scrollDown();
  }

  function scrollDown() {
    const box = $('#advisor-messages');
    if (box) box.scrollTop = box.scrollHeight;
  }

  // ---------- ส่งคำถาม ----------
  async function submit() {
    const input = $('#advisor-input');
    const box = $('#advisor-messages');
    if (!input || !box) return;
    const message = input.value.trim();
    if (!message || state.sending) return;

    state.sending = true;
    const sendButton = $('#advisor-send');
    if (sendButton) sendButton.disabled = true;

    // เอาข้อความต้อนรับออก (ครั้งแรก) แล้วแสดงข้อความผู้ใช้
    box.querySelector('.chat-welcome')?.remove();

    box.append(renderMessage('user', message));
    input.value = '';
    growInput();
    scrollDown();

    state.history.push({ role: 'user', content: message });
    if (state.history.length > MAX_HISTORY) state.history.splice(0, state.history.length - MAX_HISTORY);

    const thinking = showThinking();
    try {
      const response = await fetch('/api/ai/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          model: state.model,
          history: state.history.slice(0, -1),
        }),
      });
      const data = await response.json().catch(() => ({}));
      thinking?.remove();

      if (!response.ok) {
        showError(data.detail || 'ส่งคำถามไม่สำเร็จ ลองใหม่อีกครั้ง');
        return;
      }
      if (data.error) {
        showError(data.error);
        // แสดงคำแนะนำเพิ่มเติมสำหรับกรณีโควตาหมด
        if (/โควตา/.test(data.error)) {
          showError('ลองใหม่อีกครั้งในอีกสักครู่ หรือกดปุ่ม "ล้างแชท" แล้วถามใหม่');
        }
        return;
      }
      const answer = data.answer || 'ขออภัย ยังไม่มีคำตอบ ลองถามใหม่อีกครั้งนะ';
      const messageNode = renderMessage('assistant', answer);
      // แสดงชื่อโมเดลที่ตอบจริง (อาจต่างจากที่เลือก ถ้าโมเดลแรกคนเยอะแล้วสลับให้อัตโนมัติ)
      if (data.model) {
        const tag = el('small', 'chat-model-tag', data.model);
        messageNode.querySelector('.chat-bubble')?.append(tag);
      }
      box.append(messageNode);
      state.history.push({ role: 'assistant', content: answer });
      if (state.history.length > MAX_HISTORY) state.history.splice(0, state.history.length - MAX_HISTORY);
      scrollDown();
    } catch (error) {
      thinking?.remove();
      showError('เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ ลองใหม่อีกครั้ง');
    } finally {
      state.sending = false;
      if (sendButton) sendButton.disabled = false;
      input.focus();
    }
  }

  // ---------- ช่องพิมพ์ ----------
  function growInput() {
    const input = $('#advisor-input');
    if (!input) return;
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 150)}px`;
  }

  // ---------- โหลดการตั้งค่า ----------
  async function loadConfig() {
    const status = $('#advisor-status');
    try {
      const response = await fetch('/api/ai/config');
      const data = await response.json();
      state.configured = Boolean(data.configured);
      // ใช้โมเดลหลักตัวเดียว (ผู้ใช้ไม่ต้องเลือก)
      state.model = data.model || '';
      if (status) {
        status.textContent = state.configured
          ? `พร้อมคุยเรื่องการเรียนและการเตรียมตัว · ${data.model_label || ''}`.trim()
          : 'ยังไม่ได้เชื่อมต่อบริการ AI — เจ้าหน้าที่ต้องตั้งค่า API key';
      }
    } catch (error) {
      if (status) status.textContent = 'ตรวจสอบการเชื่อมต่อไม่สำเร็จ';
    }
  }

  function init() {
    if (!$('#advisor-form')) return;
    const input = $('#advisor-input');
    const form = $('#advisor-form');

    form.addEventListener('submit', (event) => { event.preventDefault(); submit(); });
    input?.addEventListener('input', growInput);
    input?.addEventListener('keydown', (event) => {
      // Enter ส่ง / Shift+Enter ขึ้นบรรทัดใหม่
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        submit();
      }
    });

    $('#advisor-clear')?.addEventListener('click', () => {
      state.history = [];
      renderWelcome();
      toast('ล้างแชทแล้ว');
    });

    // ---------- ไม่เก็บข้อมูลการคุยไว้เลย ----------
    // ประวัติสนทนาอยู่แค่ในหน่วยความจำของหน้านี้ (ไม่มีการเขียนลง localStorage,
    // sessionStorage, cookie หรือฐานข้อมูล) — เมื่อออกจากหน้า/ปิดแท็บ ข้อมูลจะหายทันที
    const clearChat = () => {
      state.history = [];
      const box = $('#advisor-messages');
      if (box) {
        // ล้างข้อความทั้งหมด แล้วคืนหน้าต้อนรับ (เผื่อกลับเข้าแท็บนี้อีก)
        box.replaceChildren();
        const welcome = el('div', 'chat-welcome');
        welcome.append(el('div', 'advisor-orb', '✦'));
        welcome.append(el('h3', '', 'สวัสดี! ฉันคือ TCAS Buddy'));
        welcome.append(el('p', '', 'ถามเรื่องการเตรียมตัว TCAS การเลือกคณะ เกณฑ์รับ ทุนการศึกษา หรืออะไรก็ได้ที่เกี่ยวกับการสมัครมหาวิทยาลัย'));
        box.append(welcome);
      }
    };
    // ออกจากหน้า (ปิดแท็บ/ปิดหน้าต่าง/กลับไปหน้าอื่น) — ล้างทิ้งทันที
    window.addEventListener('pagehide', clearChat);
    window.addEventListener('beforeunload', clearChat);
    // เปลี่ยนหน้าในแอป (ไม่ใช่การโหลดหน้าใหม่) — เช่นกดเมนูข้าง ๆ
    window.addEventListener('popstate', clearChat);
    // สลับออกจากแท็บ AI (ส่งจาก community.js)
    document.addEventListener('advisor:clear', clearChat);

    renderWelcome();
    loadConfig();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
