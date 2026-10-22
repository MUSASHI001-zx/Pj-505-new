// คลังชุดข้อมูลเรื่องสอบ/ข่าว TCAS จากเด็กดี (dek-d.com) — อยู่ในหน้า AI Tutor / Notebook
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

  const state = {
    category: '',
    query: '',
    items: [],
    total: 0,
    pages: 2,
    loading: false,
  };

  function safeUrl(value) {
    try {
      const url = new URL(value, window.location.origin);
      return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
    } catch { return null; }
  }

  function renderCategories(categories) {
    const row = $('#library-cats');
    if (!row) return;
    const all = [{ key: '', label: 'ทั้งหมด' }, ...categories];
    row.replaceChildren(...all.map((category) => {
      const button = el('button', `filter${state.category === category.key ? ' active' : ''}`, category.label);
      button.type = 'button';
      button.addEventListener('click', () => {
        state.category = category.key;
        state.pages = 2;
        renderCategories(categories);
        load();
      });
      return button;
    }));
  }

  function buildCard(item) {
    const url = safeUrl(item.url);
    const card = el('article', 'library-card');
    if (item.image_url) {
      const image = safeUrl(item.image_url);
      if (image) {
        const cover = el('div', 'library-cover');
        const img = el('img');
        img.src = image;
        img.alt = '';
        img.loading = 'lazy';
        img.addEventListener('error', () => cover.remove());
        cover.append(img);
        card.append(cover);
      }
    }
    const body = el('div', 'library-body');
    const meta = el('div', 'library-meta');
    if (item.category_label) meta.append(el('span', 'library-tag', item.category_label));
    (item.tags || []).slice(0, 3).forEach((tag) => meta.append(el('span', 'library-chip', tag)));
    if (item.date_text) meta.append(el('small', '', item.date_text.replace('ข่าวใหม่', '').trim()));
    body.append(meta);
    const title = el('h4', '', item.title || '(ไม่มีหัวข้อ)');
    if (url) {
      const link = el('a', '', item.title || '(ไม่มีหัวข้อ)');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      title.replaceChildren(link);
    }
    body.append(title);
    if (item.article_category) body.append(el('small', 'library-sub', item.article_category));
    if (url) {
      const link = el('a', 'library-link', 'อ่านต่อ →');
      link.href = url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      body.append(link);
    }
    card.append(body);
    return card;
  }

  function render() {
    const grid = $('#library-grid');
    const status = $('#library-status');
    if (!grid) return;
    if (!state.items.length) {
      grid.replaceChildren(el('p', 'acc-empty', state.query
        ? 'ไม่พบเรื่องที่ตรงกับคำค้นหา — ลองคำอื่น'
        : 'ยังไม่มีข้อมูลในคลังชุดนี้'));
      if (status) status.hidden = true;
      const more = $('#library-more');
      if (more) more.hidden = true;
      return;
    }
    grid.replaceChildren(...state.items.map(buildCard));
    if (status) { status.hidden = true; }
    const more = $('#library-more');
    if (more) more.hidden = state.items.length >= state.total;
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    const grid = $('#library-grid');
    const status = $('#library-status');
    if (status) { status.hidden = false; status.textContent = 'กำลังโหลดคลังข้อมูลจากเด็กดี…'; }
    try {
      const params = new URLSearchParams({ pages: String(state.pages) });
      if (state.category) params.set('cat', state.category);
      if (state.query) params.set('q', state.query);
      const response = await fetch(`/api/dekd/library?${params}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      state.items = data.items || [];
      state.total = data.total || state.items.length;
      renderCategories(data.categories || []);
      render();
    } catch (error) {
      if (grid) grid.replaceChildren(el('p', 'acc-empty', 'โหลดคลังข้อมูลไม่สำเร็จ — ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต'));
      if (status) { status.hidden = false; status.textContent = 'โหลดคลังข้อมูลไม่สำเร็จ'; }
    } finally {
      state.loading = false;
    }
  }

  function init() {
    if (!$('#library-grid')) return;

    let timer = null;
    $('#library-q')?.addEventListener('input', (event) => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        state.query = event.target.value.trim();
        state.pages = 2;
        load();
      }, 350);
    });

    $('#library-more')?.addEventListener('click', () => {
      state.pages += 1;
      load();
    });

    load();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
