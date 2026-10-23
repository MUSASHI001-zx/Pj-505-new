// หน้า /exams — คลังข้อสอบจาก myTCAS (ใช้ $, $$, el, toast จาก app.js)
(() => {
  const list = document.getElementById('exm-list');
  if (!list) return;
  const state = { kind: 'answer', group: '', q: '', seq: 0 };
  let timer = null;
  const presetQ = new URLSearchParams(window.location.search).get('q');
  if (presetQ) { state.q = presetQ.trim().slice(0, 80); const box = document.getElementById('exm-q'); if (box) box.value = state.q; }

  const el2 = (tag, cls, text) => el(tag, cls, text);

  function card(item) {
    const node = el2('article', 'exm-card');
    const badge = el2('span', 'exm-badge', item.level);
    const head = el2('div', 'exm-card-head');
    head.append(badge, el2('span', 'exm-year', item.year || item.group));
    const title = el2('h3', '', item.title);
    const meta = el2('p', 'exm-meta', `${item.group} · ${item.format}`);
    const actions = el2('div', 'exm-actions');
    if (item.download) {
      const dl = el2('a', 'button primary exm-dl', '⬇ ดาวน์โหลด PDF');
      dl.href = `/api/exams/${encodeURIComponent(item.id)}/download`;
      dl.setAttribute('download', '');
      actions.append(dl);
      const src = el2('a', 'exm-src', 'ดูไฟล์ต้นฉบับ');
      src.href = item.url; src.target = '_blank'; src.rel = 'noopener noreferrer';
      actions.append(src);
    } else {
      const open = el2('a', 'button soft exm-dl', 'เปิดอ่านบน myTCAS ↗');
      open.href = item.url; open.target = '_blank'; open.rel = 'noopener noreferrer';
      actions.append(open);
    }
    node.append(head, title, meta, actions);
    return node;
  }

  function renderChips(groups) {
    const wrap = document.getElementById('exm-groups');
    wrap.replaceChildren();
    const all = el2('button', `exm-chip${state.group ? '' : ' active'}`, 'ทั้งหมด');
    all.type = 'button';
    all.addEventListener('click', () => { state.group = ''; load(); });
    wrap.append(all);
    groups.forEach(({ group, count }) => {
      const chip = el2('button', `exm-chip${state.group === group ? ' active' : ''}`, `${group} (${count})`);
      chip.type = 'button';
      chip.addEventListener('click', () => { state.group = group; load(); });
      wrap.append(chip);
    });
  }

  async function load() {
    const seq = ++state.seq;
    const status = document.getElementById('exm-status');
    status.hidden = false;
    status.textContent = 'กำลังโหลดรายการข้อสอบจาก myTCAS…';
    const params = new URLSearchParams({ kind: state.kind });
    if (state.q) params.set('q', state.q);
    if (state.group) params.set('group', state.group);
    try {
      const response = await fetch(`/api/exams?${params}`);
      const data = await response.json();
      if (seq !== state.seq) return;           // มีคำค้นใหม่กว่าแล้ว ทิ้งผลเก่า
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'โหลดไม่สำเร็จ');
      renderChips(data.groups || []);
      list.replaceChildren(...data.items.map(card));
      if (!data.items.length) {
        list.append(el2('p', 'acc-empty', 'ไม่พบข้อสอบที่ตรงกับคำค้นหา'));
        status.textContent = '';
      } else {
        status.textContent = `พบ ${data.items.length} รายการ` + (data.live ? '' : ' · ตอนนี้เชื่อมต่อ myTCAS ไม่ได้ จึงแสดงรายการสำรอง ไฟล์บางรายการอาจโหลดไม่ได้');
      }
    } catch (error) {
      if (seq !== state.seq) return;
      list.replaceChildren(el2('p', 'acc-empty', 'โหลดรายการข้อสอบไม่สำเร็จ ลองรีเฟรชหน้าอีกครั้ง'));
      status.textContent = error.message || '';
    }
  }

  $$('[data-exm-kind]').forEach((tab) => tab.addEventListener('click', () => {
    state.kind = tab.dataset.exmKind; state.group = '';
    $$('[data-exm-kind]').forEach((t) => t.classList.toggle('active', t === tab));
    load();
  }));
  $('#exm-q').addEventListener('input', (event) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { state.q = event.target.value.trim(); load(); }, 250);
  });

  load();
})();
