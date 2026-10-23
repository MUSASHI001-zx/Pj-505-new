// หน้า /identity — ข้อสอบจำลองอาชีพ + แบบสำรวจภาพรวม + สรุปรวม
// ใช้ตัวช่วยกลางจาก app.js: $, el, authFetch, toast, startGoogleLogin และตัวแปร currentSession
(() => {
  const root = document.getElementById('identity-stage');
  if (!root) return;

  const STORE_KEY = 'tcas_identity_results_v1';
  const MAX_LOCAL = 40;
  const ENJOY = [
    [1, '😖', 'ไม่ชอบเลย'], [2, '😕', 'ไม่ค่อยชอบ'], [3, '😐', 'เฉย ๆ'], [4, '🙂', 'ค่อนข้างชอบ'], [5, '🤩', 'ชอบมาก'],
  ];
  const FIT_NOTE = 'เปอร์เซ็นต์ในรายการนี้คือความสอดคล้องระหว่างสไตล์ของเธอกับสิ่งที่อาชีพนั้นใช้ ยังไม่ใช่ผลจากการลองสถานการณ์จริง — กดเพื่อลองเล่นอาชีพนั้นให้ภาพชัดขึ้น';

  const state = {
    careers: [],
    groups: [],
    discoverQuestions: [],
    results: [],        // ผลของผู้ใช้ (อาชีพ + แบบสำรวจภาพรวม) เรียงใหม่สุดก่อน
    loggedIn: false,
    play: null,         // { career, index, answers[], enjoyment }
    discover: null,     // { index, answers[] }
    group: 'all',
    query: '',
    busy: false,
  };

  // ---------- เก็บผล ----------
  const isDiscover = (r) => r && r.kind === 'discover';
  function readLocal() {
    try {
      const data = JSON.parse(window.localStorage.getItem(STORE_KEY) || '[]');
      return Array.isArray(data) ? data.filter((r) => r && r.career_id && (isDiscover(r) || Number.isFinite(r.fit))) : [];
    } catch { return []; }
  }
  function writeLocal(list) {
    try { window.localStorage.setItem(STORE_KEY, JSON.stringify(list.slice(0, MAX_LOCAL))); } catch { /* ใช้ storage ไม่ได้ก็ไม่เป็นไร */ }
  }

  async function loadResults() {
    if (currentSession) {
      try {
        const data = await authFetch('/api/identity/results');
        state.results = data.results || [];
        state.loggedIn = true;
        return;
      } catch (error) {
        toast(error.message || 'โหลดประวัติผลไม่สำเร็จ');
      }
    }
    state.loggedIn = Boolean(currentSession);
    state.results = readLocal();
  }

  async function postJson(path, body, withAuth) {
    if (withAuth) return authFetch(path, { method: 'POST', body: JSON.stringify(body) });
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `เกิดข้อผิดพลาด (${response.status})`);
    return data;
  }

  // ผลล่าสุดของแต่ละอาชีพ (ไม่รวมแบบสำรวจภาพรวม) เรียงตามความเหมาะสม
  function latestPerCareer() {
    const seen = new Map();
    state.results.forEach((r) => { if (!isDiscover(r) && !seen.has(r.career_id)) seen.set(r.career_id, r); });
    return [...seen.values()].sort((a, b) => b.fit - a.fit);
  }
  function latestDiscover() { return state.results.find(isDiscover) || null; }

  // ---------- ตัวช่วยวาด ----------
  function clear() { root.replaceChildren(); }
  function button(label, className, onClick) {
    const node = el('button', className, label);
    node.type = 'button';
    node.addEventListener('click', onClick);
    return node;
  }
  function careerOf(id) { return state.careers.find((c) => c.id === id); }
  function bar(label, score, extra) {
    const row = el('div', 'idn-bar');
    const head = el('div', 'idn-bar-head');
    head.append(el('span', '', label), el('b', '', `${score}%`));
    const track = el('div', 'idn-bar-track');
    const fill = el('i');
    fill.style.width = `${Math.max(0, Math.min(100, score))}%`;
    track.append(fill);
    row.append(head, track);
    if (extra) row.append(el('small', '', extra));
    return row;
  }
  function stage(...children) {
    $('#idn-app')?.classList.add('idn-focus');   // ซ่อนแบนเนอร์ด้านบนตอนทำข้อสอบ/ดูผล จะได้เห็นเนื้อหาทันที
    clear();
    root.append(...children);
    root.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }
  function progress(current, total, label) {
    const wrap = el('div', 'idn-progress');
    const text = el('span', '', label);
    const track = el('div', 'idn-progress-track');
    const fill = el('i');
    fill.style.width = `${Math.round((current / total) * 100)}%`;
    track.append(fill);
    wrap.append(text, track);
    return wrap;
  }
  function chipLinks(names) {
    const chips = el('div', 'idn-chips');
    names.forEach((name) => {
      const link = el('a', 'idn-chip', name);
      link.href = `/quota?faculty=${encodeURIComponent(name)}`;
      chips.append(link);
    });
    return chips;
  }
  function listBox(title, items, emptyText, kind) {
    const box = el('div', `idn-list ${kind}`);
    box.append(el('h3', '', title));
    if (!items || !items.length) { box.append(el('p', 'idn-muted', emptyText)); return box; }
    const ul = el('ul');
    items.forEach((item) => {
      const li = el('li');
      li.append(el('b', '', item.label), el('span', '', item.text));
      ul.append(li);
    });
    box.append(ul);
    return box;
  }
  function archetypeBox(archetype) {
    const box = el('div', 'idn-archetype');
    box.append(el('small', '', 'สไตล์ของเธอ'), el('b', '', archetype.name), el('p', '', archetype.desc));
    return box;
  }
  function saveHint(fresh) {
    if (!fresh || state.loggedIn) return null;
    const prompt = el('p', 'idn-note');
    prompt.append('ผลนี้เก็บไว้ในเบราว์เซอร์นี้เท่านั้น ');
    prompt.append(button('เข้าสู่ระบบเพื่อบันทึกถาวร', 'idn-link', () => startGoogleLogin()));
    return prompt;
  }

  // ---------- 1) หน้าเลือก ----------
  function filteredCareers() {
    const q = state.query.trim().toLowerCase();
    return state.careers.filter((c) => (state.group === 'all' || c.group === state.group)
      && (!q || `${c.name} ${c.tagline} ${c.group_label}`.toLowerCase().includes(q)));
  }

  function renderPick(scroll = false) {
    $('#idn-app')?.classList.remove('idn-focus');
    clear();
    const done = new Map(latestPerCareer().map((r) => [r.career_id, r]));
    const disc = latestDiscover();

    const banner = el('div', 'panel idn-discover');
    const copy = el('div');
    copy.append(
      el('b', '', disc ? `🧭 ทำแบบสำรวจภาพรวมแล้ว · สไตล์ “${disc.archetype?.name || ''}”` : '🧭 ยังไม่รู้จะเริ่มอาชีพไหน? เริ่มที่แบบสำรวจภาพรวม'),
      el('p', '', 'ตอบ 18 ข้อสั้น ๆ ไม่ผูกกับอาชีพใด ๆ แล้วเราจะจัดอันดับอาชีพที่เข้ากับสไตล์ของเธอจากทุกอาชีพในระบบ (ใช้เวลาราว 3 นาที)'),
    );
    const bannerActions = el('div', 'idn-banner-actions');
    bannerActions.append(button(disc ? 'ทำใหม่' : 'เริ่มแบบสำรวจภาพรวม', disc ? 'button outline' : 'button primary', startDiscover));
    if (disc) bannerActions.append(button('ดูผลล่าสุด', 'button soft', () => renderDiscoverResult(disc, false)));
    banner.append(copy, bannerActions);

    const head = el('div', 'idn-head');
    const title = el('div');
    title.append(el('h2', '', `เลือกอาชีพที่อยากลองสวมบทบาท (${state.careers.length} อาชีพ)`), el('p', '', 'ลองทีละอาชีพ ใช้เวลาประมาณ 3-5 นาที ลองหลายอาชีพแล้วจะได้สรุปรวมเปรียบเทียบ'));
    head.append(title);
    if (done.size || disc) head.append(button(`ดูสรุปรวม${done.size ? ` (${done.size} อาชีพ)` : ''}`, 'button primary', renderSummary));

    const toolbar = el('div', 'idn-toolbar');
    const search = el('input', 'idn-search');
    search.type = 'search';
    search.placeholder = 'ค้นหาอาชีพ เช่น แพทย์ ออกแบบ ข้อมูล';
    search.value = state.query;
    search.setAttribute('aria-label', 'ค้นหาอาชีพ');
    const filters = el('div', 'idn-filters');
    const count = el('small', 'idn-muted idn-count');
    const grid = el('div', 'idn-careers');

    function fillGrid() {
      const list = filteredCareers();
      count.textContent = `แสดง ${list.length} จาก ${state.careers.length} อาชีพ`;
      grid.replaceChildren();
      if (!list.length) grid.append(el('p', 'acc-empty idn-none', 'ไม่พบอาชีพที่ตรงกับคำค้น ลองเปลี่ยนคำหรือเลือกหมวด “ทั้งหมด”'));
      list.forEach((career) => {
        const result = done.get(career.id);
        const card = el('button', `idn-career tone-${career.tone}`);
        card.type = 'button';
        card.append(el('span', 'idn-career-icon', career.icon), el('b', '', career.name), el('small', '', career.tagline), el('span', 'idn-career-group', career.group_label));
        card.append(result ? el('em', 'idn-career-done', `เล่นแล้ว · เหมาะ ${result.fit}%`) : el('em', 'idn-career-new', 'ยังไม่เคยลอง'));
        card.addEventListener('click', () => startPlay(career));
        grid.append(card);
      });
    }
    function fillFilters() {
      filters.replaceChildren();
      [{ id: 'all', label: 'ทั้งหมด' }, ...state.groups].forEach((group) => {
        const chip = button(group.label, `idn-filter${state.group === group.id ? ' active' : ''}`, () => { state.group = group.id; fillFilters(); fillGrid(); });
        chip.setAttribute('aria-pressed', String(state.group === group.id));
        filters.append(chip);
      });
    }
    search.addEventListener('input', () => { state.query = search.value; fillGrid(); });
    fillFilters();
    fillGrid();
    toolbar.append(search, filters, count);

    root.append(banner, head, toolbar, grid, historyPanel());
    if (scroll) root.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }

  function historyPanel() {
    const panel = el('div', 'panel idn-history');
    panel.append(el('h3', '', 'ผลที่เคยทำ'));
    if (!state.results.length) {
      panel.append(el('p', 'acc-empty', 'ยังไม่มีผลที่บันทึกไว้ — ลองเริ่มจากแบบสำรวจภาพรวมหรือเลือกอาชีพด้านบนได้เลย'));
    } else {
      const list = el('div', 'idn-history-list');
      state.results.slice(0, 10).forEach((r) => {
        const row = el('div', 'idn-history-row');
        const info = el('button', 'idn-history-open');
        info.type = 'button';
        const when = r.created_at ? new Date(r.created_at).toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' }) : '';
        const summary = isDiscover(r) ? `สไตล์ ${r.archetype?.name || ''}` : `เหมาะ ${r.fit}% · ${r.label}`;
        info.append(el('span', '', r.icon || '•'), el('b', '', r.career_name), el('small', '', `${summary}${when ? ` · ${when}` : ''}`));
        info.addEventListener('click', () => (isDiscover(r) ? renderDiscoverResult(r, false) : renderResult(r, false)));
        row.append(info, button('ลบ', 'acc-mini', () => removeResult(r)));
        list.append(row);
      });
      panel.append(list);
    }
    if (!state.loggedIn) {
      const note = el('p', 'idn-note');
      note.append('ตอนนี้ผลเก็บไว้ในเบราว์เซอร์นี้เท่านั้น ');
      note.append(button('เข้าสู่ระบบเพื่อบันทึกถาวร', 'idn-link', () => startGoogleLogin()));
      panel.append(note);
    }
    return panel;
  }

  async function removeResult(result) {
    if (!window.confirm(`ลบผลของ "${result.career_name}" ใช่ไหม?`)) return;
    try {
      if (state.loggedIn && result.id) await authFetch(`/api/identity/results/${encodeURIComponent(result.id)}`, { method: 'DELETE' });
      state.results = state.results.filter((r) => r !== result);
      if (!state.loggedIn) writeLocal(state.results);
      toast('ลบผลแล้ว');
      renderPick();
    } catch (error) { toast(error.message); }
  }

  // บันทึก/คำนวณผลผ่านเซิร์ฟเวอร์ — ล็อกอินแล้วพยายามบันทึก ถ้าไม่สำเร็จยังให้ดูผลได้แต่บอกผู้ใช้ตรง ๆ
  async function computeAndStore(savePath, evalPath, body) {
    let result;
    if (currentSession) {
      try {
        result = (await postJson(savePath, body, true)).result;
        state.loggedIn = true;
        toast('บันทึกผลแล้ว');
      } catch (error) {
        toast(`${error.message} — แสดงผลให้ดูได้แต่ยังไม่ได้บันทึก`);
        result = (await postJson(evalPath, body, false)).result;
        result.created_at = new Date().toISOString();
      }
    } else {
      result = (await postJson(evalPath, body, false)).result;
      result.created_at = new Date().toISOString();
    }
    state.results.unshift(result);
    if (!state.loggedIn) writeLocal(state.results);
    return result;
  }

  // ---------- 2) ทำข้อสอบจำลองอาชีพ ----------
  function startPlay(career) {
    state.play = { career, index: 0, answers: [], enjoyment: null };
    renderQuestion();
  }

  function renderQuestion() {
    const { career, index, answers } = state.play;
    const total = career.scenarios.length;
    if (index >= total) { renderEnjoyment(); return; }
    const scenario = career.scenarios[index];
    const card = el('div', 'panel idn-card');
    const top = el('div', 'idn-card-top');
    top.append(el('span', `idn-badge tone-${career.tone}`, `${career.icon} ${career.name}`), button('← เปลี่ยนอาชีพ', 'idn-link', () => {
      if (!answers.length || window.confirm('ออกจากข้อสอบนี้? คำตอบที่ทำไว้จะหายไป')) { state.play = null; renderPick(true); }
    }));
    card.append(top, progress(index, total + 1, `สถานการณ์ที่ ${index + 1} จาก ${total}`));
    if (index === 0) card.append(el('p', 'idn-intro', career.intro));
    card.append(el('h2', 'idn-situation', scenario.situation));
    const choices = el('div', 'idn-choices');
    scenario.choices.forEach((text, choiceIndex) => {
      const choice = el('button', `idn-choice${answers[index] === choiceIndex ? ' selected' : ''}`);
      choice.type = 'button';
      choice.append(el('span', 'idn-choice-key', 'ABCD'[choiceIndex]), el('span', '', text));
      choice.addEventListener('click', () => {
        answers[index] = choiceIndex;
        state.play.index += 1;
        renderQuestion();
      });
      choices.append(choice);
    });
    card.append(choices);
    const nav = el('div', 'idn-nav');
    if (index > 0) nav.append(button('← ข้อก่อนหน้า', 'button outline', () => { state.play.index -= 1; renderQuestion(); }));
    card.append(nav);
    stage(card);
  }

  function renderEnjoyment() {
    const { career } = state.play;
    const total = career.scenarios.length;
    const card = el('div', 'panel idn-card');
    card.append(progress(total, total + 1, 'ข้อสุดท้าย'));
    card.append(el('h2', 'idn-situation', `หลังจากสวมบทเป็น${career.name}ครบ ${total} สถานการณ์ เธอรู้สึกกับงานแบบนี้อย่างไร?`));
    card.append(el('p', 'idn-intro', 'ตอบตามความรู้สึกจริง — ความชอบมีผลต่อคะแนนความเหมาะสมพอสมควรไม่แพ้สไตล์การทำงาน'));
    const row = el('div', 'idn-enjoy');
    ENJOY.forEach(([value, emoji, label]) => {
      const item = el('button', `idn-enjoy-item${state.play.enjoyment === value ? ' selected' : ''}`);
      item.type = 'button';
      item.append(el('span', '', emoji), el('small', '', label));
      item.addEventListener('click', () => { state.play.enjoyment = value; submit(); });
      row.append(item);
    });
    card.append(row);
    const nav = el('div', 'idn-nav');
    nav.append(button('← กลับไปแก้คำตอบ', 'button outline', () => { state.play.index = total - 1; renderQuestion(); }));
    card.append(nav);
    stage(card);
  }

  async function submit() {
    if (state.busy) return;
    state.busy = true;
    const { career, answers, enjoyment } = state.play;
    stage(el('div', 'panel idn-card idn-loading', 'กำลังสรุปผลให้เธอ…'));
    try {
      const result = await computeAndStore('/api/identity/results', '/api/identity/evaluate', { career_id: career.id, answers, enjoyment });
      state.play = null;
      renderResult(result, true);
    } catch (error) {
      toast(error.message);
      renderEnjoyment();
    } finally {
      state.busy = false;
    }
  }

  // ---------- 3) สรุปผลอาชีพเดียว ----------
  function renderResult(result, fresh) {
    const career = careerOf(result.career_id);
    const card = el('div', 'panel idn-card idn-result');

    const top = el('div', 'idn-result-top');
    const ring = el('div', 'idn-ring');
    ring.style.setProperty('--p', String(result.fit));
    ring.append(el('b', '', `${result.fit}%`), el('small', '', 'ความเหมาะสม'));
    const headline = el('div', 'idn-result-head');
    headline.append(
      el('span', `idn-badge tone-${career?.tone || 'violet'}`, `${result.icon || ''} ${result.career_name}`),
      el('h2', '', result.label),
      el('p', '', `สไตล์การทำงานที่เธอเลือกเข้ากับอาชีพนี้ ${result.style_fit}% และความรู้สึกชอบของเธออยู่ที่ "${result.enjoyment_label}"`),
    );
    top.append(ring, headline);
    card.append(top);

    if (result.archetype) card.append(archetypeBox(result.archetype));
    if (result.insight) card.append(el('p', 'idn-insight', result.insight));

    const traitBox = el('div', 'idn-section');
    traitBox.append(el('h3', '', 'สไตล์การทำงานของเธอในสถานการณ์นี้'));
    (result.traits || []).slice().sort((a, b) => b.score - a.score).forEach((t) => {
      const need = t.weight >= 3 ? 'อาชีพนี้ต้องการมาก' : t.weight === 2 ? 'อาชีพนี้ต้องการพอสมควร' : '';
      traitBox.append(bar(t.label, t.score, need));
    });
    card.append(traitBox);

    const cols = el('div', 'idn-cols');
    cols.append(listBox('จุดแข็งที่เข้ากับอาชีพนี้', result.strengths, 'ยังไม่มีมิติที่เด่นชัด — ลองเล่นอาชีพอื่นเพื่อเปรียบเทียบ', 'good'));
    cols.append(listBox('สิ่งที่น่าฝึกเพิ่ม', result.to_grow, 'ไม่มีมิติสำคัญที่คะแนนต่ำเป็นพิเศษ', 'grow'));
    card.append(cols);
    if (result.unused_strengths?.length) card.append(listBox('จุดแข็งที่อาชีพนี้ใช้ไม่มาก', result.unused_strengths, '', 'note'));

    const fac = el('div', 'idn-section');
    fac.append(el('h3', '', 'คณะ/สาขาที่น่าสำรวจ'), chipLinks(result.faculties || []), el('small', 'idn-muted', 'กดชื่อคณะเพื่อดูรอบรับสมัครจริงจาก myTCAS'));
    card.append(fac);

    const reality = el('div', 'idn-reality');
    reality.append(el('b', '', 'ความจริงที่ควรรู้ก่อนเลือก'), el('p', '', result.reality));
    card.append(reality);

    if (result.try_it?.length) {
      const steps = el('div', 'idn-section');
      steps.append(el('h3', '', 'อยากรู้ว่าใช่จริงไหม? ลองทำสิ่งเหล่านี้'));
      const ul = el('ul', 'idn-steps');
      result.try_it.forEach((text) => ul.append(el('li', '', text)));
      steps.append(ul);
      card.append(steps);
    }
    if (result.related?.length) {
      const rel = el('div', 'idn-section');
      rel.append(el('h3', '', 'อาชีพที่เกี่ยวข้อง — ลองเทียบดู'));
      const chips = el('div', 'idn-chips');
      result.related.forEach((r) => {
        const target = careerOf(r.id);
        if (target) chips.append(button(`${r.icon} ${r.name}`, 'idn-chip idn-chip-btn', () => startPlay(target)));
      });
      rel.append(chips);
      card.append(rel);
    }
    card.append(el('p', 'idn-confidence', result.confidence || ''), el('p', 'idn-disclaimer', result.disclaimer));
    const hint = saveHint(fresh);
    if (hint) card.append(hint);

    const actions = el('div', 'idn-actions');
    actions.append(
      button('ลองอาชีพอื่น', 'button primary', () => renderPick(true)),
      button('ดูสรุปรวม', 'button soft', renderSummary),
    );
    if (career) actions.append(button('ทำอาชีพนี้ใหม่', 'button outline', () => startPlay(career)));
    card.append(actions);
    stage(card);
  }

  // ---------- 4) แบบสำรวจภาพรวม ----------
  function startDiscover() {
    state.discover = { index: 0, answers: [] };
    renderDiscoverQuestion();
  }

  function renderDiscoverQuestion() {
    const { index, answers } = state.discover;
    const total = state.discoverQuestions.length;
    if (index >= total) { submitDiscover(); return; }
    const question = state.discoverQuestions[index];
    const card = el('div', 'panel idn-card');
    const top = el('div', 'idn-card-top');
    top.append(el('span', 'idn-badge tone-violet', '🧭 แบบสำรวจภาพรวม'), button('← ออก', 'idn-link', () => {
      if (!answers.length || window.confirm('ออกจากแบบสำรวจนี้? คำตอบที่ทำไว้จะหายไป')) { state.discover = null; renderPick(true); }
    }));
    card.append(top, progress(index, total, `ข้อที่ ${index + 1} จาก ${total}`));
    card.append(el('h2', 'idn-situation', question.situation));
    const choices = el('div', 'idn-choices');
    question.choices.forEach((text, choiceIndex) => {
      const choice = el('button', `idn-choice${answers[index] === choiceIndex ? ' selected' : ''}`);
      choice.type = 'button';
      choice.append(el('span', 'idn-choice-key', 'ABCD'[choiceIndex]), el('span', '', text));
      choice.addEventListener('click', () => { answers[index] = choiceIndex; state.discover.index += 1; renderDiscoverQuestion(); });
      choices.append(choice);
    });
    card.append(choices, el('p', 'idn-muted idn-hint', 'ไม่มีข้อถูกหรือผิด เลือกข้อที่ “เป็นเธอมากที่สุด” แม้ไม่ตรงเป๊ะก็ตาม'));
    const nav = el('div', 'idn-nav');
    if (index > 0) nav.append(button('← ข้อก่อนหน้า', 'button outline', () => { state.discover.index -= 1; renderDiscoverQuestion(); }));
    card.append(nav);
    stage(card);
  }

  async function submitDiscover() {
    if (state.busy) return;
    state.busy = true;
    const { answers } = state.discover;
    stage(el('div', 'panel idn-card idn-loading', 'กำลังวิเคราะห์สไตล์ของเธอ…'));
    try {
      const result = await computeAndStore('/api/identity/discover/results', '/api/identity/discover/evaluate', { answers });
      state.discover = null;
      renderDiscoverResult(result, true);
    } catch (error) {
      toast(error.message);
      state.discover.index = state.discoverQuestions.length - 1;
      renderDiscoverQuestion();
    } finally {
      state.busy = false;
    }
  }

  function rankRows(rows, { showTried }) {
    const list = el('div', 'idn-rank-list');
    rows.forEach((row, i) => {
      const item = el('button', 'idn-rank');
      item.type = 'button';
      const name = el('span', 'idn-rank-name', `${row.icon || ''} ${row.name}`);
      if (showTried) name.append(el('small', row.tried ? 'idn-tag done' : 'idn-tag', row.tried ? `ลองแล้ว · เหมาะ ${row.fit}%` : 'ประเมินจากโปรไฟล์'));
      else name.append(el('small', 'idn-tag', row.group_label));
      const track = el('div', 'idn-bar-track');
      const fill = el('i');
      fill.style.width = `${row.score}%`;
      track.append(fill);
      item.append(el('span', 'idn-rank-no', String(i + 1)), name, track, el('b', '', `${row.score}%`));
      item.title = row.matched?.length ? `เด่นตรงกับอาชีพนี้: ${row.matched.join(', ')}` : 'กดเพื่อดูรายละเอียด';
      item.addEventListener('click', () => {
        const prior = latestPerCareer().find((r) => r.career_id === row.career_id);
        if (prior) renderResult(prior, false);
        else { const target = careerOf(row.career_id); if (target) startPlay(target); }
      });
      list.append(item);
    });
    return list;
  }

  function renderDiscoverResult(result, fresh) {
    const card = el('div', 'panel idn-card idn-result');
    const top = el('div', 'idn-card-top');
    top.append(el('h2', '', '🧭 ผลแบบสำรวจภาพรวม'), button('← กลับไปเลือกอาชีพ', 'idn-link', () => renderPick(true)));
    card.append(top, archetypeBox(result.archetype));

    const traitBox = el('div', 'idn-section');
    traitBox.append(el('h3', '', 'โปรไฟล์สไตล์ 6 มิติ'));
    (result.traits || []).slice().sort((a, b) => b.score - a.score).forEach((t) => traitBox.append(bar(t.label, t.score, t.desc)));
    traitBox.append(el('small', 'idn-muted', 'คะแนนมาจากการเลือกแบบบังคับเลือก จึงบอก “ว่ามิติไหนเด่นกว่า” ได้ดีกว่าการบอกว่าเก่งเท่าไร'));
    card.append(traitBox);

    const careers = el('div', 'idn-section');
    careers.append(el('h3', '', 'อาชีพที่เข้ากับสไตล์ของเธอมากที่สุด'), rankRows(result.top_careers || [], { showTried: false }), el('small', 'idn-muted', FIT_NOTE));
    card.append(careers);

    const fac = el('div', 'idn-section');
    fac.append(el('h3', '', 'คณะ/สาขาที่น่าสำรวจ'), chipLinks(result.faculties || []), el('small', 'idn-muted', 'รวมจากอาชีพอันดับต้น ๆ — กดชื่อคณะเพื่อดูรอบรับสมัครจริงจาก myTCAS'));
    card.append(fac);

    card.append(listBox('มิติที่ยังเด่นน้อย (ลองฝึกได้)', result.low_traits, '', 'grow'));
    card.append(el('p', 'idn-confidence', result.confidence || ''), el('p', 'idn-disclaimer', result.disclaimer));
    const hint = saveHint(fresh);
    if (hint) card.append(hint);

    const actions = el('div', 'idn-actions');
    actions.append(button('เลือกอาชีพไปลองเล่น', 'button primary', () => renderPick(true)), button('ดูสรุปรวม', 'button soft', renderSummary), button('ทำแบบสำรวจใหม่', 'button outline', startDiscover));
    card.append(actions);
    stage(card);
  }

  // ---------- 5) สรุปรวม (คำนวณที่เซิร์ฟเวอร์จากคำตอบดิบ) ----------
  async function renderSummary() {
    const careers = latestPerCareer();
    const entries = careers
      .filter((r) => Array.isArray(r.answers) && Number.isInteger(r.enjoyment))
      .map((r) => ({ career_id: r.career_id, answers: r.answers, enjoyment: r.enjoyment }));
    const disc = latestDiscover();
    const discoverAnswers = disc && Array.isArray(disc.answers) ? disc.answers : null;
    const skipped = careers.length - entries.length;

    if (!entries.length && !discoverAnswers) {
      const card = el('div', 'panel idn-card idn-summary');
      card.append(el('p', 'acc-empty', skipped ? 'ผลเก่าที่บันทึกไว้ยังรวมแบบใหม่ไม่ได้ — ลองทำอาชีพหรือแบบสำรวจภาพรวมใหม่อีกครั้ง' : 'ยังไม่มีผล — ลองเริ่มจากแบบสำรวจภาพรวมหรือเลือกอาชีพสักอาชีพก่อนนะ'),
        button('เริ่มเลย', 'button primary', () => renderPick(true)));
      stage(card);
      return;
    }
    if (state.busy) return;
    state.busy = true;
    stage(el('div', 'panel idn-card idn-loading', 'กำลังรวมผลของเธอ…'));
    try {
      const data = await postJson('/api/identity/profile', { entries, discover: discoverAnswers }, false);
      renderProfile(data.profile, skipped, Boolean(discoverAnswers));
    } catch (error) {
      toast(error.message);
      renderPick(true);
    } finally {
      state.busy = false;
    }
  }

  function renderProfile(profile, skipped, hasDiscover) {
    const card = el('div', 'panel idn-card idn-summary');
    const top = el('div', 'idn-card-top');
    top.append(el('h2', '', 'สรุปรวมของเธอ'), button('← กลับไปเลือกอาชีพ', 'idn-link', () => renderPick(true)));
    card.append(top, archetypeBox(profile.archetype));
    card.append(el('p', `idn-conf idn-conf-${profile.confidence_level}`, `ความน่าเชื่อถือของภาพรวม: ${{ low: 'ยังน้อย', medium: 'พอเห็นแนวโน้ม', good: 'ค่อนข้างดี' }[profile.confidence_level]} — ${profile.confidence}`));
    if (skipped > 0) card.append(el('p', 'idn-muted', `มีผลเก่า ${skipped} รายการที่ยังนำมารวมไม่ได้ (บันทึกไว้ก่อนระบบอัปเดต) — ทำอาชีพนั้นใหม่เพื่อให้ถูกรวม`));

    const prof = el('div', 'idn-section');
    prof.append(el('h3', '', `ภาพรวมสไตล์ของเธอ (รวมจาก ${profile.sources.careers} อาชีพ${profile.sources.discover ? ' + แบบสำรวจภาพรวม' : ''})`));
    (profile.traits || []).slice().sort((a, b) => b.score - a.score).forEach((t) => prof.append(bar(t.label, t.score, t.desc)));
    card.append(prof);

    const rank = el('div', 'idn-section');
    rank.append(el('h3', '', 'อาชีพที่เข้ากับเธอมากที่สุด (จากทุกอาชีพในระบบ)'), rankRows(profile.ranking || [], { showTried: true }), el('small', 'idn-muted', FIT_NOTE));
    card.append(rank);

    if (profile.explore_next?.length) {
      const next = el('div', 'idn-section');
      next.append(el('h3', '', 'ลองอาชีพเหล่านี้ต่อ — น่าจะเข้ากับเธอแต่ยังไม่เคยลอง'));
      const grid = el('div', 'idn-explore');
      profile.explore_next.forEach((row) => {
        const target = careerOf(row.career_id);
        if (!target) return;
        const item = el('button', `idn-career tone-${target.tone}`);
        item.type = 'button';
        item.append(el('span', 'idn-career-icon', target.icon), el('b', '', target.name), el('small', '', row.matched?.length ? `ตรงกับสไตล์เด่นของเธอ: ${row.matched.join(', ')}` : target.tagline), el('em', 'idn-career-new', `ลองเล่น · เข้ากัน ${row.score}%`));
        item.addEventListener('click', () => startPlay(target));
        grid.append(item);
      });
      next.append(grid);
      card.append(next);
    }

    const fac = el('div', 'idn-section');
    fac.append(el('h3', '', 'คณะ/สาขาที่น่าสำรวจ'), chipLinks(profile.faculties || []), el('small', 'idn-muted', 'รวมจากอาชีพอันดับต้น ๆ — กดชื่อคณะเพื่อดูรอบรับสมัครจริงจาก myTCAS'));
    card.append(fac, listBox('มิติที่ยังเด่นน้อย (ลองฝึกได้)', profile.low_traits, '', 'grow'), el('p', 'idn-disclaimer', profile.disclaimer));

    const actions = el('div', 'idn-actions');
    actions.append(button('ลองอาชีพอื่น', 'button primary', () => renderPick(true)));
    if (!hasDiscover) actions.append(button('ทำแบบสำรวจภาพรวมเพื่อให้ภาพชัดขึ้น', 'button soft', startDiscover));
    card.append(actions);
    stage(card);
  }

  // ---------- เริ่มต้น ----------
  async function init() {
    try {
      const [careersRes, discoverRes] = await Promise.all([fetch('/api/identity/careers'), fetch('/api/identity/discover')]);
      if (!careersRes.ok) throw new Error();
      const data = await careersRes.json();
      state.careers = data.careers || [];
      state.groups = data.groups || [];
      state.discoverQuestions = discoverRes.ok ? ((await discoverRes.json()).questions || []) : [];
    } catch {
      root.replaceChildren(el('p', 'acc-empty', 'โหลดรายการอาชีพไม่สำเร็จ ลองรีเฟรชหน้าอีกครั้ง'));
      return;
    }
    await loadResults();
    // ถ้าผู้ใช้กำลังทำข้อสอบอยู่ อย่าดึงกลับหน้าเลือกอาชีพ
    if (!state.play && !state.discover) renderPick();
  }

  // session จาก Supabase อาจมาหลังหน้าโหลด — พอรู้ว่าล็อกอินแล้วให้ดึงผลที่บันทึกไว้ใน server
  document.addEventListener('account:ready', async () => {
    if (state.busy || state.loggedIn || !state.careers.length) return;
    await loadResults();
    if (!state.play && !state.discover) renderPick();
  });

  init();
})();
