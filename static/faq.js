// หน้า /faq — กรองหมวด ค้นหา ขยาย/ย่อ และลิงก์ตรงถึงคำถาม (#faq-<หมวด>-<ลำดับ>)
(() => {
  const root = document.getElementById('faq-root');
  if (!root) return;
  const items = [...root.querySelectorAll('.faq-item')];
  const groups = [...root.querySelectorAll('.faq-group')];
  const tabs = [...root.querySelectorAll('[data-faq-cat]')].filter((node) => node.tagName === 'BUTTON');
  const input = document.getElementById('faq-q');
  const count = document.getElementById('faq-count');
  const empty = document.getElementById('faq-empty');
  const toggle = document.getElementById('faq-toggle');
  const state = { cat: 'all', q: '' };

  const norm = (text) => String(text || '').toLowerCase().replace(/\s+/g, ' ').trim();
  items.forEach((item) => { item.dataset.text = norm(item.textContent); });

  function matchesQuery(item) {
    const tokens = norm(state.q).split(' ').filter(Boolean);
    return tokens.every((token) => item.dataset.text.includes(token));
  }

  function apply() {
    let shown = 0;
    items.forEach((item) => {
      const visible = (state.cat === 'all' || item.dataset.faqCat === state.cat) && matchesQuery(item);
      item.hidden = !visible;
      if (visible) shown += 1;
    });
    groups.forEach((group) => {
      group.hidden = !group.querySelector('.faq-item:not([hidden])');
    });
    empty.hidden = shown > 0;
    count.textContent = state.q ? `พบ ${shown} คำถาม` : `${shown} คำถาม`;
    const open = items.filter((item) => !item.hidden && item.open).length;
    toggle.textContent = shown && open === shown ? 'ย่อทั้งหมด' : 'ขยายทั้งหมด';
    toggle.hidden = shown === 0;
  }

  function setCategory(cat) {
    state.cat = cat;
    tabs.forEach((tab) => tab.classList.toggle('active', tab.dataset.faqCat === cat));
    apply();
  }

  tabs.forEach((tab) => tab.addEventListener('click', () => setCategory(tab.dataset.faqCat)));

  let timer = null;
  input.addEventListener('input', () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      state.q = input.value;
      // ค้นหาแล้วเปิดคำตอบที่เจอให้อ่านทันที (เมื่อมีผลไม่เกิน 3 ข้อ)
      apply();
      const visible = items.filter((item) => !item.hidden);
      if (state.q.trim() && visible.length <= 3) visible.forEach((item) => { item.open = true; });
      apply();
    }, 160);
  });
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { input.value = ''; state.q = ''; apply(); }
  });

  toggle.addEventListener('click', () => {
    const visible = items.filter((item) => !item.hidden);
    const openAll = visible.some((item) => !item.open);
    visible.forEach((item) => { item.open = openAll; });
    apply();
  });
  items.forEach((item) => item.addEventListener('toggle', apply));

  // ลิงก์ตรง เช่น /faq#faq-search-2 (มาจากช่องค้นหากลาง) — เปิดข้อนั้นและเลื่อนไปหา
  function openFromHash() {
    const id = decodeURIComponent((window.location.hash || '').slice(1));
    const target = id && document.getElementById(id);
    if (!target || !target.classList.contains('faq-item')) return;
    setCategory('all');
    target.open = true;
    target.classList.add('is-flash');
    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
    window.setTimeout(() => target.classList.remove('is-flash'), 2200);
  }
  window.addEventListener('hashchange', openFromHash);

  // เปิดคำถามแรกไว้ให้เห็นรูปแบบ แล้วค่อยดูลิงก์ตรง
  if (items[0]) items[0].open = true;
  apply();
  openFromHash();
})();
