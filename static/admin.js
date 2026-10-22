// หน้า /admin — ระบบหลังบ้าน: ผู้ใช้/สิทธิ์, กระทู้ชุมชน, มหาวิทยาลัย+เกณฑ์รับ, Ticket
// ใช้ตัวช่วยกลางจาก app.js: $, $$, el, authFetch, toast, startGoogleLogin
(() => {
  const state = {
    tab: 'overview',
    users: [],
    posts: [],
    tags: [],
    institutions: [],
    admissions: [],
    edit: null,       // { title, subtitle, fields, save, onDelete }
    allowed: false,   // ผ่านการตรวจสิทธิ์แอดมินแล้วหรือยัง
    searchTimers: {},
  };

  const ROLE_LABELS = { student: 'นักเรียน', parents: 'ผู้ปกครอง', teacher: 'คุณครู', admin: 'แอดมิน' };
  const TONES = ['purple', 'blue', 'pink', 'teal', 'gold', 'rose', 'violet', 'indigo', 'green'];

  const formatTime = (value) => {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('th-TH', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' });
  };

  function emptyRow(message) {
    const tr = el('tr');
    const td = el('td', 'acc-empty', message);
    td.colSpan = 6;
    tr.append(td);
    return tr;
  }

  function setStatus(selector, message, kind) {
    const node = $(selector);
    if (!node) return;
    node.textContent = message || '';
    node.className = `news-status${kind ? ` ${kind}` : ''}`;
    node.hidden = !message;
  }

  // ---------- แท็บ ----------
  function showTab(name) {
    state.tab = name;
    $$('[data-admin-tab]').forEach((button) => button.classList.toggle('active', button.dataset.adminTab === name));
    $$('[data-admin-pane]').forEach((pane) => { pane.hidden = pane.dataset.adminPane !== name; });
    history.replaceState(null, '', `#${name}`);
    if (!state.allowed) return;  // ยังไม่ผ่านการตรวจสิทธิ์ — ยังโหลดข้อมูลไม่ได้
    if (name === 'users') loadUsers();
    if (name === 'posts') loadPosts();
    if (name === 'institutes') loadInstitutions();
    if (name === 'tickets') loadAdminTickets(state.adminTicketStatus || '');
    if (name === 'audit') loadAudit();
  }

  // ---------- ภาพรวม ----------
  async function loadStats() {
    try {
      const data = await authFetch('/api/admin/stats');
      const set = (key, value) => { const node = $(`[data-admin-stat="${key}"]`); if (node) node.textContent = value; };
      set('users', Number(data.users || 0).toLocaleString('th-TH'));
      set('posts', Number(data.posts || 0).toLocaleString('th-TH'));
      set('views', data.views === null || data.views === undefined ? '—' : Number(data.views).toLocaleString('th-TH'));
      set('online', data.online === null || data.online === undefined ? '—' : Number(data.online).toLocaleString('th-TH'));
      set('tickets_open', Number(data.tickets?.open || 0).toLocaleString('th-TH'));

      const roles = data.users_by_role || {};
      renderBreakdown('#admin-role-breakdown', Object.entries(roles).map(([key, count]) => ({
        label: ROLE_LABELS[key] || key, value: count, total: data.users || 0,
      })));

      const tickets = data.tickets || {};
      const statusLabels = { open: 'รอแอดมินตอบ', answered: 'ตอบแล้ว', closed: 'ปิดแล้ว' };
      const total = Object.values(tickets).reduce((sum, value) => sum + (value || 0), 0);
      renderBreakdown('#admin-ticket-breakdown', Object.entries(tickets).map(([key, count]) => ({
        label: statusLabels[key] || key, value: count, total,
      })));
    } catch (error) {
      console.warn('โหลดสถิติไม่สำเร็จ', error);
    }
  }

  function renderBreakdown(selector, rows) {
    const box = $(selector);
    if (!box) return;
    if (!rows.length) { box.replaceChildren(el('p', 'acc-empty', 'ยังไม่มีข้อมูล')); return; }
    box.replaceChildren(...rows.map((row) => {
      const item = el('div', 'role-row');
      const head = el('div', 'role-head');
      head.append(el('span', '', row.label), el('b', '', String(row.value)));
      const bar = el('div', 'role-bar');
      const fill = el('i');
      fill.style.width = row.total ? `${Math.round((row.value / row.total) * 100)}%` : '0%';
      bar.append(fill);
      item.append(head, bar);
      return item;
    }));
  }

  // ---------- ผู้ใช้ & สิทธิ์ ----------
  async function loadUsers(query = '') {
    const body = $('#admin-users-body');
    if (!body) return;
    try {
      const data = await authFetch(`/api/admin/users?limit=200${query ? `&q=${encodeURIComponent(query)}` : ''}`);
      state.users = data.items || [];
      if (!state.users.length) {
        body.replaceChildren(emptyRow('ไม่พบผู้ใช้'));
        setStatus('#admin-users-status', '');
        return;
      }
      body.replaceChildren(...state.users.map(buildUserRow));
      setStatus('#admin-users-status', '');
    } catch (error) {
      setStatus('#admin-users-status', error.message, 'err');
    }
  }

  function buildUserRow(user) {
    const tr = el('tr');
    const who = el('td');
    const name = el('b', '', user.name);
    const email = el('small', '', user.email);
    who.append(name, email);
    if (user.school || user.grade_level) {
      who.append(el('small', '', [user.school, user.grade_level].filter(Boolean).join(' · ')));
    }

    const roleCell = el('td');
    const roleSelect = el('select', 'admin-role-select');
    Object.entries(ROLE_LABELS).forEach(([value, label]) => {
      const option = el('option', '', label);
      option.value = value;
      if (value === user.role) option.selected = true;
      roleSelect.append(option);
    });
    roleSelect.addEventListener('change', async () => {
      try {
        await authFetch(`/api/admin/users/${encodeURIComponent(user.open_id)}/role`, {
          method: 'POST', body: JSON.stringify({ role: roleSelect.value }),
        });
        toast(`เปลี่ยนบทบาทเป็น ${ROLE_LABELS[roleSelect.value]} แล้ว`);
        loadUsers();
      } catch (error) { toast(error.message); roleSelect.value = user.role; }
    });
    roleCell.append(roleSelect);

    const permCell = el('td');
    const adminBtn = el('button', `acc-mini${user.is_admin ? ' on' : ''}`, user.is_admin ? '★ แอดมิน' : '☆ แอดมิน');
    adminBtn.type = 'button';
    adminBtn.title = 'แต่งตั้ง/ถอดสิทธิ์แอดมิน';
    adminBtn.addEventListener('click', async () => {
      try {
        await authFetch(`/api/admin/users/${encodeURIComponent(user.open_id)}/admin`, {
          method: 'POST', body: JSON.stringify({ is_admin: !user.is_admin }),
        });
        toast(user.is_admin ? 'ถอดสิทธิ์แอดมินแล้ว' : 'แต่งตั้งเป็นแอดมินแล้ว');
        loadUsers();
      } catch (error) { toast(error.message); }
    });
    permCell.append(adminBtn);
    if (user.is_disabled) permCell.append(el('span', 'acc-badge off', 'ระงับ'));

    const activity = el('td');
    activity.append(el('small', '', `${user.posts} กระทู้ · ${user.tickets} Ticket`));

    const seen = el('td', '', '');
    seen.append(el('small', '', formatTime(user.last_signed_in)));

    const actions = el('td');
    const rename = el('button', 'acc-mini', 'ตั้งชื่อ');
    rename.type = 'button';
    rename.addEventListener('click', () => openEdit({
      title: 'ตั้งชื่อที่แสดง',
      subtitle: user.email,
      fields: [{ key: 'display_name', label: 'ชื่อที่แสดง', value: user.name }],
      save: async (values) => {
        await authFetch(`/api/admin/users/${encodeURIComponent(user.open_id)}/display-name`, {
          method: 'POST', body: JSON.stringify(values),
        });
        toast('ตั้งชื่อแล้ว');
        loadUsers();
      },
    }));
    const disable = el('button', `acc-mini${user.is_disabled ? ' on' : ' danger'}`, user.is_disabled ? 'ปลดระงับ' : 'ระงับ');
    disable.type = 'button';
    disable.addEventListener('click', async () => {
      try {
        await authFetch(`/api/admin/users/${encodeURIComponent(user.open_id)}/disabled`, {
          method: 'POST', body: JSON.stringify({ is_disabled: !user.is_disabled }),
        });
        toast(user.is_disabled ? 'ปลดระงับบัญชีแล้ว' : 'ระงับบัญชีแล้ว');
        loadUsers();
      } catch (error) { toast(error.message); }
    });
    actions.append(rename, disable);

    tr.append(who, roleCell, permCell, activity, seen, actions);
    return tr;
  }

  // ---------- กระทู้ชุมชน ----------
  async function loadPosts(query = '') {
    const list = $('#admin-posts-list');
    if (!list) return;
    try {
      const data = await authFetch(`/api/admin/posts?limit=200${query ? `&q=${encodeURIComponent(query)}` : ''}`);
      state.posts = data.items || [];
      if (!state.posts.length) {
        list.replaceChildren(el('li', 'acc-empty', 'ไม่พบกระทู้'));
        setStatus('#admin-posts-status', '');
        return;
      }
      list.replaceChildren(...state.posts.map(buildPostItem));
      setStatus('#admin-posts-status', '');
    } catch (error) {
      setStatus('#admin-posts-status', error.message, 'err');
    }
  }

  function buildPostItem(post) {
    const li = el('li', 'admin-post-item');
    const head = el('div', 'admin-post-head');
    head.append(el('b', '', post.title || '(ไม่มีหัวข้อ)'), el('small', '', `${post.author_name || 'ผู้ใช้'} · ${formatTime(post.created_at)}`));
    const actions = el('div', 'admin-post-actions');
    const comments = el('button', 'acc-mini', `ความคิดเห็น ${post.comments || 0}`);
    comments.type = 'button';
    comments.addEventListener('click', () => openComments(post));
    const remove = el('button', 'acc-mini danger', 'ลบกระทู้');
    remove.type = 'button';
    remove.addEventListener('click', async () => {
      if (!window.confirm(`ลบกระทู้ "${post.title}" ใช่หรือไม่? ลบแล้วกู้คืนไม่ได้`)) return;
      try {
        await authFetch(`/api/admin/posts/${post.id}`, { method: 'DELETE' });
        toast('ลบกระทู้แล้ว');
        loadPosts();
        loadStats();
      } catch (error) { toast(error.message); }
    });
    actions.append(comments, remove);
    head.append(actions);
    li.append(head);
    if (post.body) li.append(el('p', 'admin-post-body', post.body));
    const tags = el('div', 'thread-tags');
    (post.tags || []).forEach((name) => {
      const chip = el('span', 'tag-choice', `#${name}`);
      chip.classList.add(toneFor(name));
      tags.append(chip);
    });
    if ((post.tags || []).length) li.append(tags);
    return li;
  }

  async function openComments(post) {
    try {
      const data = await authFetch(`/api/admin/posts/${post.id}/comments`);
      const items = data.items || [];
      openEdit({
        title: 'ความคิดเห็น',
        subtitle: post.title,
        body: items.length
          ? items.map((item) => ({
            title: `${item.author_name || 'ผู้ใช้'} · ${formatTime(item.created_at)}`,
            text: item.body,
            onDelete: async () => {
              if (!window.confirm('ลบความคิดเห็นนี้?')) return;
              await authFetch(`/api/admin/comments/${item.id}`, { method: 'DELETE' });
              toast('ลบความคิดเห็นแล้ว');
              openComments(post);
              loadPosts();
            },
          }))
          : [{ title: '', text: 'ยังไม่มีความคิดเห็น' }],
        fields: [],
        save: null,
      });
    } catch (error) { toast(error.message); }
  }

  async function createTag() {
    const input = $('#admin-tag-new');
    if (!input) return;
    const name = input.value.trim().replace(/^#/, '');
    if (!name) { toast('กรุณากรอกชื่อ tag'); return; }
    try {
      await authFetch('/api/admin/tags', { method: 'POST', body: JSON.stringify({ name, color: 'purple' }) });
      input.value = '';
      await loadTags();
      toast(`เพิ่ม tag #${name} แล้ว`);
    } catch (error) { toast(error.message); }
  }

  async function loadTags() {
    const box = $('#admin-tag-list');
    if (!box) return;
    try {
      const data = await authFetch('/api/admin/tags');
      state.tags = data.items || [];
      if (!state.tags.length) { box.replaceChildren(el('p', 'acc-empty', 'ยังไม่มี tag')); return; }
      box.replaceChildren(...state.tags.map((tag) => {
        const row = el('div', 'tag-manage-row');
        const chip = el('span', 'tag-choice', `#${tag.name}`);
        chip.classList.add(toneFor(tag.name));
        const count = el('small', '', `${tag.posts || 0} กระทู้`);
        const colorSelect = el('select', 'admin-color-select');
        TONES.forEach((tone) => {
          const option = el('option', '', tone);
          option.value = tone;
          if (tone === tag.color) option.selected = true;
          colorSelect.append(option);
        });
        colorSelect.addEventListener('change', async () => {
          try {
            await authFetch('/api/admin/tags', { method: 'POST', body: JSON.stringify({ name: tag.name, color: colorSelect.value }) });
            toast('เปลี่ยนสี tag แล้ว');
            loadTags();
          } catch (error) { toast(error.message); }
        });
        const remove = el('button', 'acc-mini danger', 'ลบ');
        remove.type = 'button';
        remove.addEventListener('click', async () => {
          if (!window.confirm(`ลบ tag #${tag.name} ? จะถูกถอดออกจากทุกกระทู้ที่ใช้`)) return;
          try {
            await authFetch(`/api/admin/tags/${encodeURIComponent(tag.name)}`, { method: 'DELETE' });
            toast('ลบ tag แล้ว');
            loadTags();
            loadPosts();
          } catch (error) { toast(error.message); }
        });
        row.append(chip, count, colorSelect, remove);
        return row;
      }));
    } catch (error) {
      box.replaceChildren(el('p', 'acc-empty', error.message));
    }
  }

  const toneFor = (name) => {
    const found = state.tags.find((tag) => tag.name === name);
    if (found?.color) return found.color;
    let hash = 0;
    for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) % 997;
    return TONES[hash % TONES.length];
  };

  // ---------- มหาวิทยาลัย + เกณฑ์รับ ----------
  async function loadInstitutions(query = '') {
    const body = $('#admin-inst-body');
    if (!body) return;
    try {
      const data = await authFetch(`/api/admin/institutions?limit=300${query ? `&q=${encodeURIComponent(query)}` : ''}`);
      state.institutions = data.items || [];
      if (!state.institutions.length) {
        body.replaceChildren(emptyRow('ไม่พบมหาวิทยาลัย'));
        setStatus('#admin-inst-status', '');
        return;
      }
      body.replaceChildren(...state.institutions.map((item) => {
        const tr = el('tr');
        const nameCell = el('td');
        nameCell.append(el('b', '', item.name || '(ไม่มีชื่อ)'));
        if (item.short_name) nameCell.append(el('small', '', item.short_name));
        const cityCell = el('td', '', item.city || '—');
        const statusCell = el('td');
        statusCell.append(el('span', `acc-badge${item.is_published === false ? ' off' : ''}`, item.is_published === false ? 'ซ่อน' : 'แสดง'));
        const actions = el('td');
        const edit = el('button', 'acc-mini', 'แก้ไข');
        edit.type = 'button';
        edit.addEventListener('click', () => openInstitutionForm(item));
        const remove = el('button', 'acc-mini danger', 'ลบ');
        remove.type = 'button';
        remove.addEventListener('click', async () => {
          if (!window.confirm(`ลบ "${item.name}" ใช่หรือไม่?`)) return;
          try {
            await authFetch(`/api/admin/institutions/${item.id}`, { method: 'DELETE' });
            toast('ลบมหาวิทยาลัยแล้ว');
            loadInstitutions();
          } catch (error) { toast(error.message); }
        });
        actions.append(edit, remove);
        tr.append(nameCell, cityCell, statusCell, actions);
        return tr;
      }));
      setStatus('#admin-inst-status', '');
    } catch (error) {
      setStatus('#admin-inst-status', error.message, 'err');
    }
  }

  function openInstitutionForm(item = null) {
    const isNew = !item;
    openEdit({
      title: isNew ? 'เพิ่มมหาวิทยาลัย' : 'แก้ไขมหาวิทยาลัย',
      subtitle: isNew ? 'เพิ่มสถาบันใหม่เข้าสู่รายชื่อ' : item.name,
      fields: [
        { key: 'name', label: 'ชื่อมหาวิทยาลัย', value: item?.name || '', required: true },
        { key: 'short_name', label: 'ชื่อย่อ', value: item?.short_name || '' },
        { key: 'city', label: 'จังหวัด/เมือง (myTCAS ไม่มีข้อมูลนี้ — เติมเองได้)', value: item?.city || '' },
        { key: 'logo_url', label: 'URL โลโก้', value: item?.logoUrl || '' },
        { key: 'website_url', label: 'URL เว็บไซต์ทางการ', value: item?.website_url || '' },
        { key: 'is_published', label: 'แสดงในหน้าเว็บ', type: 'checkbox', value: item?.is_published !== false },
      ],
      save: async (values) => {
        if (isNew) await authFetch('/api/admin/institutions', { method: 'POST', body: JSON.stringify(values) });
        else await authFetch(`/api/admin/institutions/${item.id}`, { method: 'PUT', body: JSON.stringify(values) });
        toast(isNew ? 'เพิ่มมหาวิทยาลัยแล้ว' : 'บันทึกแล้ว');
        loadInstitutions();
      },
    });
  }

  async function loadAdmissions() {
    const body = $('#admin-adm-body');
    if (!body) return;
    try {
      const data = await authFetch('/api/admin/admissions?limit=200');
      state.admissions = data.items || [];
      if (!state.admissions.length) {
        body.replaceChildren(emptyRow('ยังไม่มีรายการรับสมัคร'));
        setStatus('#admin-adm-status', '');
        return;
      }
      body.replaceChildren(...state.admissions.map((item) => {
        const tr = el('tr');
        const inst = el('td');
        inst.append(el('b', '', item.institution || '—'));
        if (item.source_url) {
          const link = el('a', 'admin-source-link', 'แหล่งอ้างอิง');
          link.href = item.source_url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          inst.append(link);
        }
        const faculty = el('td', '', item.faculty || '—');
        if (item.program) faculty.append(el('small', '', item.program));
        const round = el('td', '', item.round || '—');
        const deadline = el('td', '', item.deadline || '—');
        const status = el('td');
        status.append(el('span', `acc-badge${item.is_published === false ? ' off' : ''}`, item.is_published === false ? 'ซ่อน' : 'แสดง'));
        const actions = el('td');
        const edit = el('button', 'acc-mini', 'แก้ไข');
        edit.type = 'button';
        edit.addEventListener('click', () => openAdmissionForm(item));
        const remove = el('button', 'acc-mini danger', 'ลบ');
        remove.type = 'button';
        remove.addEventListener('click', async () => {
          if (!window.confirm(`ลบรายการ "${item.institution} — ${item.faculty}" ใช่หรือไม่?`)) return;
          try {
            await authFetch(`/api/admin/admissions/${item.id}`, { method: 'DELETE' });
            toast('ลบรายการแล้ว');
            loadAdmissions();
          } catch (error) { toast(error.message); }
        });
        actions.append(edit, remove);
        tr.append(inst, faculty, round, deadline, status, actions);
        return tr;
      }));
      setStatus('#admin-adm-status', '');
    } catch (error) {
      setStatus('#admin-adm-status', error.message, 'err');
    }
  }

  function openAdmissionForm(item = null) {
    const isNew = !item;
    openEdit({
      title: isNew ? 'เพิ่มเกณฑ์รับ' : 'แก้ไขเกณฑ์รับ',
      subtitle: isNew ? 'ข้อมูลที่แสดงในหน้า "ค้นหาโควตา / TCAS"' : item.institution,
      fields: [
        { key: 'institution', label: 'มหาวิทยาลัย', value: item?.institution || '', required: true },
        { key: 'faculty', label: 'คณะ/สาขา', value: item?.faculty || '', required: true },
        { key: 'program', label: 'หลักสูตร (ถ้ามี)', value: item?.program || '' },
        { key: 'round', label: 'รอบการรับ', value: item?.round || '', required: true, placeholder: 'เช่น รอบ 1 Portfolio' },
        { key: 'criteria', label: 'เกณฑ์การรับ', type: 'textarea', value: item?.criteria || '' },
        { key: 'source_url', label: 'ลิงก์ประกาศ/แหล่งอ้างอิง', value: item?.source_url || '', placeholder: 'https://www.mytcas.com/...' },
        { key: 'source_label', label: 'ชื่อแหล่งอ้างอิง', value: item?.source_label || '' },
        { key: 'deadline', label: 'กำหนดปิดรับ (YYYY-MM-DD)', value: item?.deadline || '' },
        { key: 'is_published', label: 'แสดงในหน้าเว็บ', type: 'checkbox', value: item?.is_published !== false },
      ],
      save: async (values) => {
        if (isNew) await authFetch('/api/admin/admissions', { method: 'POST', body: JSON.stringify(values) });
        else await authFetch(`/api/admin/admissions/${item.id}`, { method: 'PUT', body: JSON.stringify(values) });
        toast(isNew ? 'เพิ่มรายการแล้ว' : 'บันทึกแล้ว');
        loadAdmissions();
      },
    });
  }

  // ---------- บันทึกการทำงาน ----------
  async function loadAudit() {
    const list = $('#admin-audit-list');
    if (!list) return;
    try {
      const data = await authFetch('/api/admin/audit?limit=100');
      const items = data.items || [];
      if (!items.length) { list.replaceChildren(el('li', 'acc-empty', 'ยังไม่มีบันทึก')); return; }
      list.replaceChildren(...items.map((item) => {
        const li = el('li', 'audit-row');
        const head = el('div', 'audit-head');
        head.append(el('b', '', item.action), el('small', '', `${item.actor_name || 'แอดมิน'} · ${formatTime(item.created_at)}`));
        li.append(head);
        if (item.detail) li.append(el('p', 'audit-detail', item.detail));
        return li;
      }));
      setStatus('#admin-audit-status', '');
    } catch (error) {
      setStatus('#admin-audit-status', error.message, 'err');
    }
  }

  // ---------- กล่องโต้ตอบแก้ไข ----------
  function openEdit(config) {
    state.edit = config;
    $('#admin-edit-title').textContent = config.title;
    $('#admin-edit-subtitle').textContent = config.subtitle || '';
    const form = $('#admin-edit-form');
    form.replaceChildren();

    (config.body || []).forEach((item) => {
      const block = el('div', 'admin-edit-block');
      block.append(el('b', '', item.title));
      block.append(el('p', '', item.text));
      if (item.onDelete) {
        const remove = el('button', 'acc-mini danger', 'ลบรายการนี้');
        remove.type = 'button';
        remove.addEventListener('click', () => item.onDelete());
        block.append(remove);
      }
      form.append(block);
    });

    (config.fields || []).forEach((field) => {
      const wrapper = el('div', 'field');
      wrapper.append(el('label', '', field.label));
      let input;
      if (field.type === 'select') {
        input = el('select');
        const blank = el('option', '', '— ไม่ระบุ —');
        blank.value = '';
        input.append(blank);
        (field.options || []).forEach((option) => {
          const node = el('option', '', option);
          node.value = option;
          if (option === field.value) node.selected = true;
          input.append(node);
        });
      } else if (field.type === 'textarea') {
        input = el('textarea');
        input.rows = 3;
        input.value = field.value || '';
      } else if (field.type === 'checkbox') {
        input = el('input');
        input.type = 'checkbox';
        input.checked = field.value !== false;
        const label = el('label', 'admin-checkbox');
        label.append(input, el('span', '', field.label));
        wrapper.replaceChildren(label);
        wrapper.dataset.key = field.key;
        wrapper.dataset.type = 'checkbox';
        form.append(wrapper);
        return;
      } else {
        input = el('input');
        input.value = field.value || '';
        if (field.placeholder) input.placeholder = field.placeholder;
      }
      input.dataset.key = field.key;
      wrapper.append(input);
      form.append(wrapper);
    });

    const save = $('#admin-edit-save');
    save.hidden = !config.save;
    save.onclick = async () => {
      if (!config.save) return;
      const values = {};
      $$('#admin-edit-form [data-key]').forEach((node) => {
        const key = node.dataset.key;
        if (node.dataset.type === 'checkbox') values[key] = node.checked;
        else values[key] = node.value.trim();
      });
      const required = (config.fields || []).filter((field) => field.required);
      const missing = required.find((field) => !values[field.key]);
      if (missing) {
        $('#admin-edit-status').textContent = `กรุณากรอก "${missing.label}"`;
        return;
      }
      save.disabled = true;
      $('#admin-edit-status').textContent = 'กำลังบันทึก…';
      try {
        await config.save(values);
        closeEdit();
      } catch (error) {
        $('#admin-edit-status').textContent = error.message;
      }
      save.disabled = false;
    };

    $('#admin-edit-status').textContent = '';
    $('#admin-edit-modal').classList.add('open');
  }

  function closeEdit() {
    $('#admin-edit-modal').classList.remove('open');
    state.edit = null;
  }

  // ---------- คิว Ticket (อยู่ใน community.js) ----------
  // ฟังก์ชันจัดการคิว Ticket อยู่ใน static/community.js เพื่อให้ใช้โค้ดร่วมกันกับหน้า /community

  // ---------- เริ่มต้น ----------
  function init() {
    if (document.body.dataset.page !== 'admin') return;

    $$('[data-admin-tab]').forEach((button) => button.addEventListener('click', () => showTab(button.dataset.adminTab)));
    $$('[data-admin-goto]').forEach((button) => button.addEventListener('click', () => showTab(button.dataset.adminGoto)));
    $$('[data-subtab]').forEach((button) => button.addEventListener('click', () => {
      $$('[data-subtab]').forEach((item) => item.classList.toggle('active', item === button));
      $$('[data-subpane]').forEach((pane) => { pane.hidden = pane.dataset.subpane !== button.dataset.subtab; });
      if (button.dataset.subtab === 'admissions') loadAdmissions();
    }));

    $('#admin-inst-add')?.addEventListener('click', () => openInstitutionForm(null));
    $('#admin-adm-add')?.addEventListener('click', () => openAdmissionForm(null));
    $('#admin-audit-refresh')?.addEventListener('click', loadAudit);
    $('#admin-tag-create')?.addEventListener('click', createTag);
    $('#admin-tag-new')?.addEventListener('keydown', (event) => { if (event.key === 'Enter') { event.preventDefault(); createTag(); } });

    $$('[data-close-admin-edit]').forEach((button) => button.addEventListener('click', closeEdit));
    $('#admin-edit-modal')?.addEventListener('click', (event) => { if (event.target.id === 'admin-edit-modal') closeEdit(); });
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeEdit(); });

    const debounce = (key, fn) => (event) => {
      window.clearTimeout(state.searchTimers[key]);
      const value = event.target.value.trim();
      state.searchTimers[key] = window.setTimeout(() => fn(value), 300);
    };
    $('#admin-user-search')?.addEventListener('input', debounce('users', loadUsers));
    $('#admin-post-search')?.addEventListener('input', debounce('posts', loadPosts));
    $('#admin-inst-search')?.addEventListener('input', debounce('inst', loadInstitutions));

    const hash = window.location.hash.replace('#', '');
    if (['overview', 'users', 'posts', 'institutes', 'tickets', 'audit'].includes(hash)) showTab(hash);

    // ปุ่มเข้าสู่ระบบบนประตูสิทธิ์
    $('#admin-gate-login')?.addEventListener('click', startGoogleLogin);

    // รอให้ตรวจสิทธิ์ผ่านก่อนจึงโหลดข้อมูล (ถ้าผู้ใช้ล็อกอินอยู่แล้ว ให้ตรวจสิทธิ์เลย)
    if (window.myAccount) checkAccess();
    else {
      // session อาจยังกำลัง restore — ลองอีกครั้งเมื่อพร้อม
      window.setTimeout(() => { if (!state.allowed) checkAccess(); }, 2500);
    }
  }

  // ---------- ประตูสิทธิ์ ----------
  function showGate(title, copy, showLogin) {
    $('#admin-page').hidden = true;
    $('#admin-gate').hidden = false;
    $('#admin-gate-title').textContent = title;
    $('#admin-gate-copy').textContent = copy;
    $('#admin-gate-login').hidden = !showLogin;
  }

  function grantAccess() {
    state.allowed = true;
    $('#admin-gate').hidden = true;
    $('#admin-page').hidden = false;
    addSidebarLink();
    loadStats();
    loadTags();
    window.setInterval(loadStats, 30000);
  }

  // แสดงลิงก์ "หลังบ้าน" ใน sidebar เฉพาะตอนที่เป็นแอดมิน
  function addSidebarLink() {
    if ($('#admin-nav-link')) return;
    const nav = $('.main-nav');
    if (!nav) return;
    const link = el('a', 'nav-item', '✦ หลังบ้าน');
    link.id = 'admin-nav-link';
    link.href = '/admin';
    link.innerHTML = '<span class="nav-icon">✦</span><span>หลังบ้าน</span>';
    nav.append(link);
  }

  async function checkAccess() {
    try {
      // ต้องแนบ Bearer token — API ฝั่งแอดมินตรวจสิทธิ์จาก token
      await authFetch('/api/admin/stats');
      grantAccess();
      return;
    } catch (error) {
      const message = error.message || '';
      if (message.includes('ยังไม่ได้เข้าสู่ระบบ') || message.includes('กรุณาเข้าสู่ระบบ')) {
        showGate('เข้าสู่ระบบก่อน', 'กรุณาเข้าสู่ระบบด้วยบัญชีที่มีสิทธิ์แอดมิน', true);
        return;
      }
      if (message.includes('แอดมิน')) {
        showGate('ไม่มีสิทธิ์เข้าหลังบ้าน', 'บัญชีนี้ไม่ได้รับสิทธิ์แอดมิน — ถ้าคิดว่าควรมีสิทธิ์ แจ้งทีมผู้ดูแลระบบได้', false);
        return;
      }
      showGate('ยังตรวจสอบสิทธิ์ไม่ได้', message || 'ระบบฐานข้อมูลอาจมีปัญหา — ลองรีเฟรชอีกครั้ง', false);
    }
  }

  document.addEventListener('account:ready', () => { checkAccess(); });
  // ถ้าโหลดข้อมูลบัญชีไม่สำเร็จ (ช้า/500) แต่ session ยังอยู่ — ลองตรวจสิทธิ์แอดมินโดยตรง
  document.addEventListener('account:error', () => { checkAccess(); });
  document.addEventListener('account:guest', (event) => {
    if (event.detail?.reason === 'not_configured') showGate('ระบบหลังบ้านยังไม่พร้อม', 'ยังไม่ได้ตั้งค่า Supabase จึงยังจัดการข้อมูลไม่ได้', false);
    else showGate('เข้าสู่ระบบก่อน', 'กรุณาเข้าสู่ระบบด้วยบัญชีที่มีสิทธิ์แอดมิน', true);
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
