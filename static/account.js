// หน้า /account — ใช้ตัวช่วยกลางจาก app.js: $, $$, el, authFetch, applyAvatar, toast, startGoogleLogin, signOut
(() => {
  const ROLE_LABELS = { student: 'นักเรียน', parents: 'ผู้ปกครอง', teacher: 'คุณครู' };
  const NOTIFY_ITEMS = [
    { key: 'news', title: 'ข่าวใหม่', desc: 'เมื่อมีข่าวในหมวดที่คุณติดตาม' },
    { key: 'deadlines', title: 'กำหนดการสำคัญ', desc: 'เตือนก่อนถึงวันสมัครหรือวันสำคัญของ TCAS' },
    { key: 'community', title: 'ชุมชนและโพล', desc: 'เมื่อมีคนตอบหรือโหวตโพลของคุณ' },
    { key: 'ticket', title: 'ข้อความจากแอดมิน', desc: 'เมื่อแอดมินตอบ Ticket ที่คุณเปิดไว้' },
  ];
  const SECTIONS = ['profile', 'faculties', 'notifications', 'invites', 'help'];
  const INVITE_STATUS = { active: 'ใช้งานได้', revoked: 'ยกเลิกแล้ว', expired: 'หมดอายุ', full: 'ใช้ครบแล้ว' };

  const page = $('#account-page');
  const state = { options: null, profile: null, faculties: new Set(), avatarChoice: null, invitesLoaded: false };
  const isMobile = () => window.matchMedia('(max-width: 760px)').matches;

  // ---------- สถานะหน้า ----------
  function showGate(title, copy, showLogin) {
    $('#account-layout').hidden = true;
    $('#account-gate').hidden = false;
    $('#account-gate-title').textContent = title;
    $('#account-gate-copy').textContent = copy;
    $('#account-gate-login').hidden = !showLogin;
  }

  function setStatus(id, message, kind) {
    const node = $(id);
    if (!node) return;
    node.textContent = message || '';
    node.className = `acc-status${kind ? ` ${kind}` : ''}`;
  }

  async function withBusy(button, task) {
    button.disabled = true;
    try { return await task(); } finally { button.disabled = false; }
  }

  // ---------- เมนู / แผงย่อย ----------
  function openSection(name, { push = true } = {}) {
    $$('.acc-panel').forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
    $$('.acc-row').forEach((row) => row.classList.toggle('active', row.dataset.section === name));
    page.dataset.view = 'section';
    if (push && window.location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
    if (name === 'invites' && !state.invitesLoaded) loadInvites();
    if (isMobile()) window.scrollTo({ top: 0 });
  }

  function backToMenu() {
    page.dataset.view = 'menu';
    history.replaceState(null, '', window.location.pathname);
    if (!isMobile()) openSection('profile', { push: false });
  }

  function applyResponsiveView() {
    if (!state.profile) return;
    if (!isMobile()) {
      const current = $$('.acc-panel').find((panel) => !panel.hidden);
      openSection(current ? current.dataset.panel : 'profile', { push: false });
    } else if (!$$('.acc-panel').some((panel) => !panel.hidden)) page.dataset.view = 'menu';
  }

  // ---------- แสดงข้อมูลโปรไฟล์ ----------
  function renderHeader(profile) {
    const name = profile.display_name || 'ผู้ใช้';
    $('#acc-name').textContent = name;
    const classInfo = [profile.grade_level, profile.classroom].filter(Boolean).join(' ');
    $('#acc-sub').textContent = [classInfo, profile.school].filter(Boolean).join(' · ') || profile.email;
    $('#acc-role').textContent = ROLE_LABELS[profile.role] || '';
    const img = $('#acc-avatar-img');
    const letter = $('#acc-avatar-letter');
    if (profile.avatar_url) { img.src = profile.avatar_url; img.hidden = false; letter.hidden = true; }
    else { img.hidden = true; img.removeAttribute('src'); letter.hidden = false; letter.textContent = name.trim().charAt(0).toUpperCase(); }
  }

  function fillForm(profile) {
    $('#f-name').value = profile.has_custom_name ? profile.display_name : '';
    $('#f-name').placeholder = profile.has_custom_name ? '' : profile.display_name;
    $('#f-email').value = profile.email || '';
    $('#f-school').value = profile.school || '';
    $('#f-grade').value = profile.grade_level || '';
    $('#f-class').value = profile.classroom || '';
  }

  function renderProfile(profile) {
    state.profile = profile;
    window.myAccount = profile;
    renderHeader(profile);
    applyAvatar(profile);
    fillForm(profile);
    state.faculties = new Set(profile.interested_faculties || []);
    renderFaculties();
    renderNotifications(profile.notify_prefs);
  }

  async function saveProfilePatch(patch) {
    const data = await authFetch('/api/account', { method: 'PUT', body: JSON.stringify(patch) });
    renderProfile(data.profile);
    return data.profile;
  }

  // ---------- ข้อมูลส่วนตัว ----------
  function buildGradeOptions() {
    const select = $('#f-grade');
    state.options.grade_levels.forEach((level) => { const option = el('option', '', level); option.value = level; select.append(option); });
  }

  async function saveProfile() {
    const button = $('#save-profile');
    setStatus('#status-profile', 'กำลังบันทึก…');
    try {
      await withBusy(button, () => saveProfilePatch({
        display_name: $('#f-name').value,
        school: $('#f-school').value,
        grade_level: $('#f-grade').value || null,
        classroom: $('#f-class').value,
      }));
      setStatus('#status-profile', 'บันทึกข้อมูลแล้ว', 'ok');
    } catch (error) { setStatus('#status-profile', error.message, 'err'); }
  }

  // ---------- คณะที่สนใจ ----------
  function updateFacultyCount() {
    const max = state.options.max_faculties;
    $('#fac-count').textContent = `${state.faculties.size}/${max}`;
    $$('#fac-chips .acc-chip').forEach((chip) => {
      const on = state.faculties.has(chip.dataset.value);
      chip.setAttribute('aria-pressed', String(on));
      chip.disabled = !on && state.faculties.size >= max;
    });
  }

  function renderFaculties() {
    const box = $('#fac-chips');
    if (!state.options) return;
    $('#fac-max').textContent = state.options.max_faculties;
    if (!box.children.length) {
      state.options.faculties.forEach((name) => {
        const chip = el('button', 'acc-chip', name);
        chip.type = 'button';
        chip.dataset.value = name;
        chip.addEventListener('click', () => {
          if (state.faculties.has(name)) state.faculties.delete(name); else state.faculties.add(name);
          updateFacultyCount();
          setStatus('#status-faculties', '');
        });
        box.append(chip);
      });
    }
    updateFacultyCount();
  }

  async function saveFaculties() {
    setStatus('#status-faculties', 'กำลังบันทึก…');
    try {
      await withBusy($('#save-faculties'), () => saveProfilePatch({ interested_faculties: [...state.faculties] }));
      setStatus('#status-faculties', 'บันทึกคณะที่สนใจแล้ว', 'ok');
    } catch (error) { setStatus('#status-faculties', error.message, 'err'); }
  }

  // ---------- การแจ้งเตือน (บันทึกทันทีเมื่อสลับ) ----------
  function renderNotifications(prefs) {
    const list = $('#notify-list');
    list.replaceChildren(...NOTIFY_ITEMS.map((item) => {
      const row = el('label', 'acc-toggle');
      const copy = el('div', 'acc-toggle-copy');
      copy.append(el('b', '', item.title), el('small', '', item.desc));
      const wrap = el('span', 'acc-switch');
      const input = el('input');
      input.type = 'checkbox';
      input.checked = prefs[item.key] !== false;
      input.setAttribute('role', 'switch');
      input.addEventListener('change', async () => {
        const wanted = input.checked;
        input.disabled = true;
        setStatus('#status-notifications', 'กำลังบันทึก…');
        try {
          await saveProfilePatch({ notify_prefs: { [item.key]: wanted } });
          setStatus('#status-notifications', 'บันทึกแล้ว', 'ok');
        } catch (error) {
          input.checked = !wanted;
          setStatus('#status-notifications', error.message, 'err');
        }
        input.disabled = false;
      });
      wrap.append(input, el('span'));
      row.append(copy, wrap);
      return row;
    }));
  }

  // ---------- ลิงก์คำเชิญ ----------
  const inviteUrl = (code) => `${window.location.origin}/invite/${code}`;

  function inviteMeta(item) {
    const parts = [`ใช้แล้ว ${item.uses}${item.max_uses ? `/${item.max_uses}` : ''} คน`];
    parts.push(item.expires_at ? `หมดอายุ ${new Date(item.expires_at).toLocaleDateString('th-TH', { day: 'numeric', month: 'short', year: 'numeric' })}` : 'ไม่หมดอายุ');
    return parts.join(' · ');
  }

  function buildInvite(item) {
    const active = item.status === 'active';
    const li = el('li', `acc-invite${active ? '' : ' off'}`);
    const title = el('div', 'acc-invite-title');
    title.append(el('span', '', item.label || 'ลิงก์คำเชิญ'), el('span', `acc-badge${active ? '' : ' off'}`, INVITE_STATUS[item.status] || item.status));
    const actions = el('div', 'acc-invite-actions');
    if (active) {
      const copy = el('button', 'acc-mini', 'คัดลอก');
      copy.type = 'button';
      copy.addEventListener('click', () => copyText(inviteUrl(item.code)));
      const revoke = el('button', 'acc-mini danger', 'ยกเลิก');
      revoke.type = 'button';
      revoke.addEventListener('click', () => revokeInvite(item.code, revoke));
      actions.append(copy, revoke);
    }
    li.append(title, actions, el('div', 'acc-invite-meta', inviteMeta(item)));
    if (active) li.append(el('div', 'acc-invite-url', inviteUrl(item.code)));
    return li;
  }

  function renderInvites(items) {
    const list = $('#invite-list');
    if (!items.length) { list.replaceChildren(el('li', 'acc-empty', 'ยังไม่มีลิงก์คำเชิญ กดสร้างลิงก์เพื่อเริ่มชวนเพื่อน')); return; }
    list.replaceChildren(...items.map(buildInvite));
  }

  async function loadInvites() {
    setStatus('#status-invites', 'กำลังโหลดลิงก์…');
    try {
      const data = await authFetch('/api/account/invites');
      state.invitesLoaded = true;
      state.invites = data.items;
      renderInvites(data.items);
      setStatus('#status-invites', '');
    } catch (error) { setStatus('#status-invites', error.message, 'err'); }
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); toast('คัดลอกลิงก์แล้ว'); }
    catch {
      const area = el('textarea'); area.value = text; document.body.append(area); area.select();
      try { document.execCommand('copy'); toast('คัดลอกลิงก์แล้ว'); } catch { toast('คัดลอกไม่สำเร็จ ลองเลือกข้อความแล้วคัดลอกเอง'); }
      area.remove();
    }
  }

  async function createInvite() {
    setStatus('#status-invites', 'กำลังสร้างลิงก์…');
    const max = $('#inv-max').value;
    const exp = $('#inv-exp').value;
    try {
      const data = await withBusy($('#create-invite'), () => authFetch('/api/account/invites', {
        method: 'POST',
        body: JSON.stringify({ label: $('#inv-label').value || null, max_uses: max ? Number(max) : null, expires_in_days: exp ? Number(exp) : null }),
      }));
      $('#inv-label').value = '';
      state.invites = [data.invite, ...(state.invites || [])];
      renderInvites(state.invites);
      setStatus('#status-invites', 'สร้างลิงก์แล้ว', 'ok');
      copyText(inviteUrl(data.invite.code));
    } catch (error) { setStatus('#status-invites', error.message, 'err'); }
  }

  async function revokeInvite(code, button) {
    if (!window.confirm('ยกเลิกลิงก์นี้? คนที่ได้รับลิงก์จะใช้ไม่ได้อีก')) return;
    try {
      await withBusy(button, () => authFetch(`/api/account/invites/${encodeURIComponent(code)}`, { method: 'DELETE' }));
      await loadInvites();
      toast('ยกเลิกลิงก์แล้ว');
    } catch (error) { setStatus('#status-invites', error.message, 'err'); }
  }

  // ---------- เลือกรูปโปรไฟล์ ----------
  function openAvatarPicker() {
    state.avatarChoice = state.profile?.avatar_key || null;
    const grid = $('#avatar-grid');
    grid.replaceChildren(...state.options.avatars.map((item, index) => {
      const button = el('button', 'avatar-option');
      button.type = 'button';
      button.setAttribute('role', 'radio');
      button.setAttribute('aria-label', `รูปโปรไฟล์ ${index + 1}`);
      button.setAttribute('aria-checked', String(item.key === state.avatarChoice));
      const img = el('img'); img.src = item.url; img.alt = ''; img.loading = 'lazy';
      button.append(img);
      button.addEventListener('click', () => {
        state.avatarChoice = item.key;
        $$('.avatar-option', grid).forEach((node) => node.setAttribute('aria-checked', String(node === button)));
      });
      return button;
    }));
    setStatus('#avatar-status', '');
    $('#avatar-status').textContent = state.options.avatars.length ? '' : 'ยังไม่มีรูปให้เลือก เพิ่มไฟล์ในโฟลเดอร์ static/assets/avatars';
    $('#avatar-modal').classList.add('open');
  }

  const closeAvatarPicker = () => $('#avatar-modal').classList.remove('open');

  async function saveAvatar(key) {
    const status = $('#avatar-status');
    status.textContent = 'กำลังบันทึก…';
    try {
      await saveProfilePatch({ avatar_key: key });
      closeAvatarPicker();
      toast('เปลี่ยนรูปโปรไฟล์แล้ว');
    } catch (error) { status.textContent = error.message; }
  }

  // ---------- เริ่มต้น ----------
  async function loadOptions() {
    if (state.options) return;
    const response = await fetch('/api/account/options');
    state.options = await response.json();
    buildGradeOptions();
    const hotline = state.options.hotline;
    if (hotline) { $('#help-hotline').href = hotline.tel; $('#help-hotline-num').textContent = hotline.phone; }
  }

  async function onReady(event) {
    try { await loadOptions(); } catch { showGate('โหลดตัวเลือกไม่สำเร็จ', 'ลองรีเฟรชหน้านี้อีกครั้ง', false); return; }
    renderProfile(event.detail);
    $('#account-gate').hidden = true;
    $('#account-layout').hidden = false;
    const wanted = window.location.hash.replace('#', '');
    if (SECTIONS.includes(wanted)) openSection(wanted, { push: false });
    else if (!isMobile()) openSection('profile', { push: false });
    else page.dataset.view = 'menu';
  }

  document.addEventListener('account:ready', onReady);
  document.addEventListener('account:guest', (event) => {
    if (event.detail?.reason === 'not_configured') showGate('ระบบบัญชียังไม่พร้อม', 'ยังไม่ได้ตั้งค่า Supabase จึงยังจัดการบัญชีไม่ได้', false);
    else showGate('เข้าสู่ระบบเพื่อจัดการบัญชี', 'เลือกรูปโปรไฟล์ แก้ข้อมูล ตั้งค่าการแจ้งเตือน และสร้างลิงก์คำเชิญได้หลังเข้าสู่ระบบ', true);
  });
  document.addEventListener('account:error', (event) => showGate('โหลดข้อมูลบัญชีไม่สำเร็จ', event.detail?.message || 'ลองรีเฟรชหน้านี้อีกครั้ง', false));

  $('#account-gate-login')?.addEventListener('click', startGoogleLogin);
  $$('.acc-row, .acc-name-edit').forEach((node) => node.addEventListener('click', () => openSection(node.dataset.section)));
  $('#acc-back')?.addEventListener('click', backToMenu);
  $('#acc-logout')?.addEventListener('click', signOut);
  $('#acc-avatar-btn')?.addEventListener('click', openAvatarPicker);
  $('#save-profile')?.addEventListener('click', saveProfile);
  $('#save-faculties')?.addEventListener('click', saveFaculties);
  $('#create-invite')?.addEventListener('click', createInvite);
  $('#avatar-save')?.addEventListener('click', () => { if (state.avatarChoice) saveAvatar(state.avatarChoice); else $('#avatar-status').textContent = 'แตะเลือกรูปก่อนนะ'; });
  $('#avatar-clear')?.addEventListener('click', () => saveAvatar(null));
  $$('[data-close-avatar]').forEach((button) => button.addEventListener('click', closeAvatarPicker));
  $('#avatar-modal')?.addEventListener('click', (event) => { if (event.target.id === 'avatar-modal') closeAvatarPicker(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeAvatarPicker(); });
  window.matchMedia('(max-width: 760px)').addEventListener('change', applyResponsiveView);
  window.addEventListener('hashchange', () => {
    if (!state.profile) return;
    const name = window.location.hash.replace('#', '');
    if (SECTIONS.includes(name)) openSection(name, { push: false });
    else if (!name) backToMenu();
  });
})();
