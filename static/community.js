// หน้า /community — ระบบกระทู้ชุมชน (โพสต์/โพล + tag แบบ Discord) + Ticket แชทส่วนตัวกับแอดมิน
// ใช้ตัวช่วยกลางจาก app.js: $, $$, el, authFetch, toast
(() => {
  const state = {
    tags: [],
    selectedTags: new Set(),
    options: [],
    activeTag: '',
    query: '',
    posts: [],
    imageFile: null,
    ticketId: null,
    ticketStatus: '',
    adminTicketId: null,
    adminTicketStatus: '',
    pollTimer: null,
  };

  const TONE_CLASSES = ['purple', 'blue', 'pink', 'teal', 'gold', 'rose', 'violet', 'indigo', 'green'];
  const STATUS_LABELS = { open: 'รอแอดมินตอบ', answered: 'ตอบแล้ว', closed: 'ปิดแล้ว' };
  const NO_ADMIN_REPLY = 'ยังไม่มีแอดมินอยู่ในขณะนี้';

  const toneFor = (name) => {
    const found = state.tags.find((tag) => tag.name === name);
    if (found?.color) return found.color;
    let hash = 0;
    for (const char of name) hash = (hash * 31 + char.charCodeAt(0)) % 997;
    return TONE_CLASSES[hash % TONE_CLASSES.length];
  };

  const formatTime = (value) => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('th-TH', { day: 'numeric', month: 'short', year: '2-digit', hour: '2-digit', minute: '2-digit' });
  };

  function setStatus(selector, message, kind) {
    const node = $(selector);
    if (!node) return;
    node.textContent = message || '';
    node.className = `acc-status${kind ? ` ${kind}` : ''}`;
  }

  // ---------- แท็บ ----------
  function showTab(name) {
    const previous = $$('[data-community-pane]').find((pane) => !pane.hidden)?.dataset.communityPane;
    $$('[data-community-tab]').forEach((button) => button.classList.toggle('active', button.dataset.communityTab === name));
    $$('[data-community-pane]').forEach((pane) => { pane.hidden = pane.dataset.communityPane !== name; });
    // ออกจากแท็บ AI → ล้างข้อมูลการคุยทิ้ง (ไม่เก็บไว้เลย)
    if (previous === 'advisor' && name !== 'advisor') {
      document.dispatchEvent(new CustomEvent('advisor:clear'));
    }
    if (name === 'ticket') { loadTickets(); pollTickets(); }
    else stopPolling();
  }

  function stopPolling() {
    if (state.pollTimer) { window.clearInterval(state.pollTimer); state.pollTimer = null; }
  }

  // ---------- tag ----------
  function renderTagSelector() {
    const box = $('#tag-selector');
    if (!box) return;
    box.replaceChildren(...state.tags.map((tag) => {
      const chip = el('button', 'tag-choice', `#${tag.name}`);
      chip.type = 'button';
      chip.classList.add(toneFor(tag.name));
      chip.setAttribute('aria-pressed', String(state.selectedTags.has(tag.name)));
      chip.addEventListener('click', () => {
        if (state.selectedTags.has(tag.name)) state.selectedTags.delete(tag.name);
        else {
          if (state.selectedTags.size >= 5) { toast('เลือกได้สูงสุด 5 tag'); return; }
          state.selectedTags.add(tag.name);
        }
        renderTagSelector();
      });
      return chip;
    }));
  }


  function renderTagFilter() {
    const row = $('#tag-filter-row');
    if (!row) return;
    const buttons = [el('button', `filter${state.activeTag ? '' : ' active'}`, 'ทั้งหมด')];
    buttons[0].dataset.tagFilter = '';
    buttons[0].addEventListener('click', () => { state.activeTag = ''; renderTagFilter(); loadPosts(); });
    state.tags.forEach((tag) => {
      const button = el('button', `filter${state.activeTag === tag.name ? ' active' : ''}`, `#${tag.name}`);
      button.dataset.tagFilter = tag.name;
      button.addEventListener('click', () => { state.activeTag = tag.name; renderTagFilter(); loadPosts(); });
      buttons.push(button);
    });
    row.replaceChildren(...buttons);
  }

  async function loadTags() {
    try {
      const response = await fetch('/api/community/tags');
      const data = await response.json();
      state.tags = data.items || [];
    } catch {
      state.tags = [];
    }
    renderTagSelector();
    renderTagFilter();
  }

  // ---------- ตัวเลือกโพล ----------
  function renderOptions() {
    const box = $('#compose-option-list');
    if (!box) return;
    box.replaceChildren(...state.options.map((label, index) => {
      const row = el('div', 'option-row');
      const input = el('input');
      input.value = label;
      input.maxLength = 120;
      input.placeholder = `ตัวเลือกที่ ${index + 1}`;
      input.addEventListener('input', () => { state.options[index] = input.value; });
      const remove = el('button', 'option-remove', '×');
      remove.type = 'button';
      remove.setAttribute('aria-label', 'ลบตัวเลือกนี้');
      remove.addEventListener('click', () => { state.options.splice(index, 1); renderOptions(); });
      row.append(input, remove);
      return row;
    }));
  }

  function addOption() {
    if (state.options.length >= 8) { toast('เพิ่มได้สูงสุด 8 ตัวเลือก'); return; }
    state.options.push('');
    renderOptions();
    const inputs = $$('#compose-option-list input');
    inputs[inputs.length - 1]?.focus();
  }

  // ---------- รีเฟรชผลโหวตในกล่องโพล (ไม่โหลดทั้งหน้าใหม่) ----------
  function repaintPoll(post, poll) {
    const total = post.total_votes || 0;
    const rows = poll.querySelectorAll('.poll-option');
    const topVotes = Math.max(0, ...post.options.map((option) => option.votes || 0));
    post.options.forEach((option, index) => {
      const row = rows[index];
      if (!row) return;
      const votes = option.votes || 0;
      const percent = total ? Math.round((votes / total) * 100) : 0;
      const isPicked = post.my_vote === option.id;
      const isLeading = total > 0 && votes === topVotes && votes > 0;
      row.classList.toggle('picked', isPicked);
      row.classList.toggle('leading', isLeading);
      row.setAttribute('aria-pressed', String(isPicked));
      const bar = row.querySelector('.poll-bar');
      if (bar) bar.style.width = `${percent}%`;
      const count = row.querySelector('.poll-count');
      if (count) count.textContent = `${votes} (${percent}%)`;
      const crown = row.querySelector('.poll-crown');
      if (crown) crown.textContent = isLeading ? '👑' : '';
    });
    const totalLine = poll.querySelector('.poll-total');
    if (totalLine) {
      totalLine.textContent = post.my_vote != null
        ? `โหวตแล้ว ${total} คน · คุณเลือกแล้ว — กดซ้ำเพื่อเปลี่ยนคำตอบ`
        : `โหวตแล้ว ${total} คน · โหวตได้คนละหนึ่งเสียง`;
    }
  }

  // ---------- รูปภาพประกอบกระทู้ ----------
  function previewSelectedImage() {
    const file = state.imageFile;
    const preview = $('#compose-image-preview');
    const thumb = $('#compose-image-thumb');
    const clear = $('#compose-image-clear');
    if (!file || !preview || !thumb) { if (preview) preview.hidden = true; if (clear) clear.hidden = true; return; }
    // ปลด URL เดิมก่อนสร้างใหม่ — ไม่ให้รั่ว memory ตอนเลือกรูปหลายครั้ง
    if (thumb.src?.startsWith('blob:')) URL.revokeObjectURL(thumb.src);
    thumb.src = URL.createObjectURL(file);
    preview.hidden = false;
    if (clear) clear.hidden = false;
  }

  function clearSelectedImage() {
    const input = $('#compose-image');
    const thumb = $('#compose-image-thumb');
    if (thumb?.src?.startsWith('blob:')) URL.revokeObjectURL(thumb.src);
    if (input) input.value = '';
    state.imageFile = null;
    const preview = $('#compose-image-preview');
    if (preview) preview.hidden = true;
    const clear = $('#compose-image-clear');
    if (clear) clear.hidden = true;
  }

  async function uploadSelectedImage() {
    const file = state.imageFile;
    if (!file) return '';
    if (file.size > 5 * 1024 * 1024) {
      setStatus('#compose-status', 'รูปใหญ่เกิน 5 MB — ลองย่อขนาดก่อนนะ', 'err');
      return null;
    }
    const form = new FormData();
    form.append('file', file);
    const token = await accessToken();
    if (!token) throw new Error('ยังไม่ได้เข้าสู่ระบบ');
    const response = await fetch('/api/community/uploads', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'อัปโหลดรูปไม่สำเร็จ');
    return data.url || '';
  }

  // ---------- กระทู้ ----------
  function buildPost(post) {
    const card = el('article', 'thread-card');

    const head = el('div', 'thread-head');
    const avatar = el('div', 'thread-avatar');
    if (post.author_avatar) {
      const img = el('img');
      img.src = post.author_avatar;
      img.alt = '';
      img.loading = 'lazy';
      avatar.append(img);
    } else {
      avatar.textContent = (post.author_name || 'ผู้ใช้').trim().charAt(0).toUpperCase();
    }
    const meta = el('div', 'thread-meta');
    meta.append(el('b', '', post.author_name || 'ผู้ใช้'), el('small', '', formatTime(post.created_at)));
    head.append(avatar, meta);

    const tags = el('div', 'thread-tags');
    (post.tags || []).forEach((name) => {
      const chip = el('span', 'tag-choice', `#${name}`);
      chip.classList.add(toneFor(name));
      tags.append(chip);
    });

    const title = el('h3', 'thread-title', post.title);
    const body = post.body ? el('p', 'thread-body', post.body) : null;

    // รูปภาพประกอบกระทู้
    let image = null;
    if (post.image_url) {
      image = el('div', 'thread-image');
      const img = el('img');
      img.src = post.image_url;
      img.alt = post.title ? `รูปประกอบกระทู้: ${post.title}` : 'รูปประกอบกระทู้';
      img.loading = 'lazy';
      img.addEventListener('error', () => image.remove());
      image.append(img);
    }

    const actions = el('div', 'thread-actions');
    const like = el('button', 'thread-action');
    like.type = 'button';
    like.classList.toggle('on', !!post.liked);
    like.setAttribute('aria-pressed', String(!!post.liked));
    like.setAttribute('aria-label', post.liked ? 'เอากดไลก์ออก' : 'กดไลก์กระทู้นี้');
    like.innerHTML = `<span aria-hidden="true">${post.liked ? '♥' : '♡'}</span> ${post.likes || 0}`;
    like.addEventListener('click', async () => {
      like.disabled = true;
      try {
        const data = await authFetch(`/api/community/posts/${post.id}/like`, { method: 'POST' });
        post.liked = data.liked;
        post.likes = typeof data.likes === 'number' ? data.likes : Math.max(0, (post.likes || 0) + (data.liked ? 1 : -1));
        like.classList.toggle('on', post.liked);
        like.setAttribute('aria-pressed', String(post.liked));
        like.setAttribute('aria-label', post.liked ? 'เอากดไลก์ออก' : 'กดไลก์กระทู้นี้');
        like.innerHTML = `<span aria-hidden="true">${post.liked ? '♥' : '♡'}</span> ${post.likes}`;
      } catch (error) { toast(error.message); }
      like.disabled = false;
    });
    const commentBtn = el('button', 'thread-action');
    commentBtn.type = 'button';
    commentBtn.setAttribute('aria-label', 'ดูความคิดเห็น');
    commentBtn.innerHTML = `<span aria-hidden="true">💬</span> ${post.comments_count || 0}`;
    actions.append(like, commentBtn);

    card.append(head, tags, title);
    if (body) card.append(body);
    if (image) card.append(image);

    // ตัวเลือกโพล + ผลโหวต
    if ((post.options || []).length) {
      const poll = el('div', 'poll-box');
      const total = post.total_votes || 0;
      const picked = post.my_vote != null;
      post.options.forEach((option) => {
        const votes = option.votes || 0;
        const percent = total ? Math.round((votes / total) * 100) : 0;
        const isPicked = post.my_vote === option.id;
        const row = el('button', `poll-option${isPicked ? ' picked' : ''}`);
        row.type = 'button';
        row.setAttribute('aria-pressed', String(isPicked));
        const bar = el('span', 'poll-bar');
        bar.style.width = `${percent}%`;
        const label = el('span', 'poll-label', option.label);
        const count = el('span', 'poll-count', `${votes} (${percent}%)`);
        const crown = el('span', 'poll-crown');
        row.append(bar, label, count, crown);
        row.addEventListener('click', async () => {
          if (row.disabled) return;
          // ยกเลิกก่อนเพื่อกันกดรัว ๆ ส่งคำขอซ้ำ
          poll.querySelectorAll('.poll-option').forEach((node) => { node.disabled = true; });
          try {
            const data = await authFetch(`/api/community/posts/${post.id}/vote`, {
              method: 'POST',
              body: JSON.stringify({ option_id: option.id }),
            });
            // อัปเดตผลโหวตในที่โดยไม่ต้องโหลดทั้งหน้าใหม่
            post.my_vote = data.my_vote ?? null;
            post.total_votes = data.total_votes ?? post.total_votes;
            (data.options || []).forEach((updated) => {
              const target = post.options.find((item) => item.id === updated.id);
              if (target) target.votes = updated.votes;
            });
            repaintPoll(post, poll);
            // ดูผลจริงจาก response (ไม่ใช่ค่าเก่าที่ปิดไว้ตอน render)
            toast(data.my_vote == null ? 'ยกเลิกการโหวตแล้ว' : 'บันทึกการโหวตแล้ว');
          } catch (error) { toast(error.message); }
          poll.querySelectorAll('.poll-option').forEach((node) => { node.disabled = false; });
        });
        poll.append(row);
      });
      const totalLine = el('div', 'poll-total');
      totalLine.textContent = picked
        ? `โหวตแล้ว ${total} คน · คุณเลือกแล้ว — กดซ้ำเพื่อเปลี่ยนคำตอบ`
        : `โหวตแล้ว ${total} คน · โหวตได้คนละหนึ่งเสียง`;
      poll.append(totalLine);
      card.append(poll);
      // ไฮไลต์ตัวเลือกที่มีโหวตสูงสุด
      repaintPoll(post, poll);
    }

    card.append(actions);

    // ความคิดเห็น
    const comments = el('div', 'thread-comments');
    comments.hidden = true;
    const commentList = el('div', 'comment-list');
    comments.append(commentList);

    const form = el('form', 'comment-form');
    const input = el('input');
    input.placeholder = 'เขียนความคิดเห็น...';
    input.maxLength = 2000;
    const submit = el('button', 'acc-mini', 'ส่ง');
    submit.type = 'submit';
    form.append(input, submit);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const body = input.value.trim();
      if (!body) return;
      submit.disabled = true;
      try {
        await authFetch(`/api/community/posts/${post.id}/comments`, { method: 'POST', body: JSON.stringify({ body }) });
        input.value = '';
        await loadComments(post.id, commentList, comments);
      } catch (error) { toast(error.message); }
      submit.disabled = false;
    });
    comments.append(form);

    commentBtn.addEventListener('click', async () => {
      comments.hidden = !comments.hidden;
      if (!comments.hidden && !commentList.childElementCount) await loadComments(post.id, commentList, comments);
    });

    card.append(comments);
    return card;
  }

  async function loadComments(postId, list, container) {
    try {
      const response = await fetch(`/api/community/posts/${postId}`);
      const data = await response.json();
      const items = data.comments || [];
      if (!items.length) {
        list.replaceChildren(el('p', 'acc-empty', 'ยังไม่มีความคิดเห็น เป็นคนแรกที่ตอบเลย!'));
        return;
      }
      list.replaceChildren(...items.map((comment) => {
        const row = el('div', 'comment-row');
        const avatar = el('div', 'comment-avatar');
        if (comment.author_avatar) {
          const img = el('img');
          img.src = comment.author_avatar;
          img.alt = '';
          img.loading = 'lazy';
          img.addEventListener('error', () => {
            img.remove();
            avatar.textContent = (comment.author_name || 'ผู้ใช้').trim().charAt(0).toUpperCase();
          });
          avatar.append(img);
        } else {
          avatar.textContent = (comment.author_name || 'ผู้ใช้').trim().charAt(0).toUpperCase();
        }
        const body = el('div', 'comment-body');
        body.append(el('b', '', comment.author_name || 'ผู้ใช้'), el('small', '', formatTime(comment.created_at)), el('p', '', comment.body));
        row.append(avatar, body);
        return row;
      }));
    } catch (error) {
      list.replaceChildren(el('p', 'acc-empty', error.message));
    }
  }

  async function loadPosts() {
    const list = $('#thread-list');
    if (!list) return;
    const status = $('#thread-status');
    const params = new URLSearchParams();
    if (state.activeTag) params.set('tag', state.activeTag);
    if (state.query) params.set('q', state.query);
    try {
      const response = await fetch(`/api/community/posts?${params.toString()}`);
      const data = await response.json();
      if (!data.configured) {
        list.replaceChildren(el('p', 'acc-empty', data.error || 'ยังไม่ได้เชื่อมต่อฐานข้อมูล — รัน supabase/migrations/007_community.sql เพื่อเปิดใช้ระบบกระทู้'));
        if (status) { status.hidden = false; status.textContent = 'ระบบกระทู้ยังไม่พร้อมใช้งาน — รัน migration 007 ใน Supabase SQL Editor แล้วรีเฟรชหน้านี้'; }
        return;
      }
      state.posts = data.items || [];
      if (!state.posts.length) {
        list.replaceChildren(el('p', 'acc-empty', state.query || state.activeTag ? 'ไม่พบกระทู้ที่ตรงกับเงื่อนไข' : 'ยังไม่มีกระทู้ — เป็นคนแรกที่ถามชุมชนเลย!'));
      } else {
        list.replaceChildren(...state.posts.map(buildPost));
      }
      if (status) status.hidden = true;
    } catch (error) {
      list.replaceChildren(el('p', 'acc-empty', `โหลดกระทู้ไม่สำเร็จ: ${error.message}`));
    }
  }

  async function submitPost() {
    const title = $('#compose-title').value.trim();
    const body = $('#compose-body').value.trim();
    if (!title) { setStatus('#compose-status', 'กรุณาเขียนหัวข้อคำถาม', 'err'); return; }
    const button = $('#submit-post');
    button.disabled = true;
    setStatus('#compose-status', 'กำลังโพสต์…');
    try {
      // อัปโหลดรูปก่อน (ถ้ามี) — ถ้าอัปโหลดไม่สำเร็จยังโพสต์กระทู้ได้ แต่จะไม่มีรูป
      let imageUrl = '';
      if (state.imageFile) {
        setStatus('#compose-status', 'กำลังอัปโหลดรูป…');
        const uploaded = await uploadSelectedImage();
        if (uploaded === null) { button.disabled = false; return; }
        imageUrl = uploaded;
      }
      await authFetch('/api/community/posts', {
        method: 'POST',
        body: JSON.stringify({
          title,
          body,
          tags: [...state.selectedTags],
          options: state.options.map((label) => label.trim()).filter(Boolean),
          image_url: imageUrl,
        }),
      });
      $('#compose-title').value = '';
      $('#compose-body').value = '';
      state.options = [];
      state.selectedTags.clear();
      clearSelectedImage();
      renderOptions();
      renderTagSelector();
      setStatus('#compose-status', 'โพสต์เรียบร้อยแล้ว', 'ok');
      await loadPosts();
      toast('โพสต์กระทู้ของคุณแล้ว');
    } catch (error) { setStatus('#compose-status', error.message, 'err'); }
    button.disabled = false;
  }

  // ---------- Ticket ----------
  function buildTicketItem(item, isAdmin) {
    const activeId = isAdmin ? state.adminTicketId : state.ticketId;
    const status = item.status || 'open';
    const li = el('li', `ticket-item ticket-item--${status}${Number(item.id) === Number(activeId) ? ' active' : ''}`);
    li.dataset.ticketId = item.id;

    // แถบสีสถานะด้านซ้าย
    li.append(el('span', 'ticket-item-bar'));

    const body = el('div', 'ticket-item-body');
    const title = el('div', 'ticket-item-title');
    title.append(el('b', '', item.subject));
    title.append(el('span', `ticket-status-pill ${status}`, STATUS_LABELS[status] || status));
    body.append(title);

    const meta = el('div', 'ticket-item-meta');
    meta.append(el('span', 'ticket-item-cat', item.category || 'ทั่วไป'));
    meta.append(el('small', '', formatTime(item.updated_at)));
    if (item.message_count) {
      const count = el('span', 'ticket-item-count', `${item.message_count} ข้อความ`);
      meta.append(count);
    }
    body.append(meta);

    if (!isAdmin && item.last_message) {
      body.append(el('p', 'ticket-item-preview', item.last_message));
    }
    li.append(body);
    return li;
  }

  async function loadTickets() {
    const list = $('#ticket-list');
    if (!list) return;
    try {
      const data = await authFetch('/api/tickets');
      setAdminPresence(data.admin_online);
      const items = data.items || [];
      if (!items.length) {
        list.replaceChildren(el('li', 'acc-empty', 'ยังไม่มี Ticket — กด + ใหม่เพื่อเริ่มปรึกษาแอดมิน'));
        setEmptyChat('ยังไม่มี Ticket — กด + ใหม่เพื่อเริ่มปรึกษาแอดมิน');
        return;
      }
      list.replaceChildren(...items.map((item) => buildTicketItem(item, false)));
      if (!state.ticketId && items.length) {
        const first = items[0];
        state.ticketId = first.id;
        state.ticketStatus = first.status;
        openTicket(first.id);
      }
    } catch (error) {
      list.replaceChildren(el('li', 'acc-empty', error.message));
    }
  }

  function setAdminPresence(online) {
    const node = $('#admin-presence');
    if (!node) return;
    node.classList.toggle('on', !!online);
    node.querySelector('span').textContent = online ? 'แอดมินออนไลน์อยู่ — พิมพ์ได้เลย' : NO_ADMIN_REPLY;
  }

  function buildMessage(message) {
    const row = el('div', `chat-msg ${message.sender_type}`);
    const bubble = el('div', 'chat-bubble');
    const head = el('div', 'chat-msg-head');
    head.append(el('b', '', message.sender_name || (message.sender_type === 'admin' ? 'แอดมิน' : 'ผู้ใช้')), el('small', '', formatTime(message.created_at)));
    bubble.append(head, el('p', '', message.body));
    row.append(bubble);
    return row;
  }

  function renderChat(messages) {
    const box = $('#chat-messages');
    box.replaceChildren(...(messages || []).map(buildMessage));
    box.scrollTop = box.scrollHeight;
  }

  async function openTicket(ticketId) {
    state.ticketId = ticketId;
    $$('#ticket-list .ticket-item').forEach((node) => node.classList.toggle('active', Number(node.dataset.ticketId) === Number(ticketId)));
    try {
      const data = await authFetch(`/api/tickets/${ticketId}`);
      $('#ticket-chat-empty').hidden = true;
      $('#ticket-chat-body').hidden = false;
      $('#chat-subject').textContent = data.ticket.subject || '';
      state.ticketStatus = data.ticket.status;
      $('#chat-status').textContent = `${data.ticket.category || 'ทั่วไป'} · ${formatTime(data.ticket.updated_at)}`;
      const pill = $('#chat-status-pill');
      pill.textContent = STATUS_LABELS[data.ticket.status] || data.ticket.status;
      pill.classList.toggle('off', data.ticket.status === 'closed');
      $('#close-ticket').hidden = data.ticket.status === 'closed';
      setAdminPresence(data.admin_online);
      renderChat(data.messages);
    } catch (error) { toast(error.message); }
  }

  const TICKET_CATEGORIES = ['ทั่วไป', 'ปัญหาการใช้งาน', 'บัญชีและข้อมูลส่วนตัว', 'เกี่ยวกับคณะ/การสมัคร', 'ข้อเสนอแนะ'];

  function openNewTicketModal() {
    const modal = $('#new-ticket-modal');
    if (!modal) return;
    const subject = $('#new-ticket-subject');
    const body = $('#new-ticket-body');
    const category = $('#new-ticket-category');
    const status = $('#new-ticket-status');
    if (subject) subject.value = '';
    if (body) body.value = '';
    if (status) status.textContent = '';
    if (category) {
      category.replaceChildren(...TICKET_CATEGORIES.map((name) => {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        return option;
      }));
    }
    modal.classList.add('open');
    subject?.focus();
  }

  function closeNewTicketModal() {
    $('#new-ticket-modal')?.classList.remove('open');
  }

  async function submitNewTicket() {
    const subject = ($('#new-ticket-subject')?.value || '').trim();
    const body = ($('#new-ticket-body')?.value || '').trim();
    const category = ($('#new-ticket-category')?.value || 'ทั่วไป').trim();
    const status = $('#new-ticket-status');
    if (!subject) {
      if (status) status.textContent = 'กรุณาใส่หัวข้อ';
      return;
    }
    if (!body) {
      if (status) status.textContent = 'กรุณาเขียนรายละเอียด';
      return;
    }
    if (status) status.textContent = 'กำลังส่ง...';
    try {
      const data = await authFetch('/api/tickets', {
        method: 'POST',
        body: JSON.stringify({ subject, body, category }),
      });
      state.ticketId = data.ticket.id;
      closeNewTicketModal();
      await loadTickets();
      await openTicket(data.ticket.id);
      toast(data.admin_online ? 'ส่งข้อความแล้ว แอดมินจะตอบกลับ' : NO_ADMIN_REPLY);
    } catch (error) {
      if (status) status.textContent = error.message;
    }
  }

  async function sendChatMessage(event) {
    event.preventDefault();
    const input = $('#chat-input');
    const body = input.value.trim();
    if (!body || !state.ticketId) return;
    input.value = '';
    try {
      const data = await authFetch(`/api/tickets/${state.ticketId}/messages`, { method: 'POST', body: JSON.stringify({ body }) });
      const current = await authFetch(`/api/tickets/${state.ticketId}`);
      renderChat(current.messages);
      if (data.admin_online === false) toast(NO_ADMIN_REPLY);
    } catch (error) {
      toast(error.message);
      input.value = body;
    }
  }

  async function closeTicket() {
    if (!state.ticketId) return;
    if (!window.confirm('ปิด Ticket นี้?\n\nข้อความทั้งหมดจะถูกลบออกจากระบบถาวร ถ้าต้องการปรึกษาต่อให้เปิด Ticket ใหม่')) return;
    try {
      await authFetch(`/api/tickets/${state.ticketId}/close`, { method: 'POST' });
      // ตั๋วถูกลบไปแล้ว — เคลียร์หน้าจอแชทและเลือกตั๋วถัดไป
      state.ticketId = null;
      resetChat();
      await loadTickets();
      toast('ปิด Ticket แล้ว — ข้อความถูกลบออกจากระบบ');
    } catch (error) { toast(error.message); }
  }

  // ล้างหน้าจอแชทกลับไปเป็นสถานะว่าง
  function resetChat() {
    const empty = $('#ticket-chat-empty');
    const body = $('#ticket-chat-body');
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    const messages = $('#chat-messages');
    if (messages) messages.replaceChildren();
    const input = $('#chat-input');
    if (input) input.value = '';
    setEmptyChat('เลือก Ticket จากรายการด้านซ้ายเพื่อดูข้อความและพิมพ์ตอบ');
  }

  // เปลี่ยนข้อความในช่องว่างฝั่งขวา ให้ตรงกับสถานะปัจจุบัน
  function setEmptyChat(message) {
    const empty = $('#ticket-chat-empty');
    if (!empty) return;
    empty.replaceChildren(el('p', '', message));
  }

  function pollTickets() {
    stopPolling();
    state.pollTimer = window.setInterval(() => {
      if ($('[data-community-pane="ticket"]')?.hidden) return;
      loadTickets();
    }, 15000);
  }

  // ---------- ผู้ดูแลระบบ (หน้า /admin) ----------
  async function loadAdminTickets(status) {
    const list = $('#admin-ticket-list');
    if (!list) return;
    try {
      const params = status ? `?status=${status}` : '';
      const data = await authFetch(`/api/admin/tickets${params}`);
      const items = data.items || [];
      if (!items.length) {
        list.replaceChildren(el('li', 'acc-empty', 'ไม่มี Ticket ในคิวนี้'));
        return;
      }
      list.replaceChildren(...items.map((item) => {
        const li = buildTicketItem(item, true);
        li.classList.toggle('active', Number(item.id) === Number(state.adminTicketId));
        li.addEventListener('click', () => openAdminTicket(item.id));
        return li;
      }));
    } catch (error) {
      list.replaceChildren(el('li', 'acc-empty', error.message));
    }
  }

  async function openAdminTicket(ticketId) {
    state.adminTicketId = ticketId;
    $$('#admin-ticket-list .ticket-item').forEach((node) => node.classList.toggle('active', Number(node.dataset.ticketId) === Number(ticketId)));
    try {
      const data = await authFetch(`/api/admin/tickets/${ticketId}`);
      $('#admin-ticket-empty').hidden = true;
      $('#admin-ticket-body').hidden = false;
      $('#admin-ticket-subject').textContent = data.ticket.subject || '';
      $('#admin-ticket-user').textContent = `${data.user?.name || 'ผู้ใช้'} · ${data.user?.email || ''}`;
      state.adminTicketStatus = data.ticket.status;
      const pill = $('#admin-ticket-pill');
      pill.textContent = STATUS_LABELS[data.ticket.status] || data.ticket.status;
      pill.classList.toggle('off', data.ticket.status === 'closed');
      const box = $('#admin-ticket-messages');
      box.replaceChildren(...(data.messages || []).map(buildMessage));
      box.scrollTop = box.scrollHeight;
    } catch (error) { toast(error.message); }
  }

  async function setAdminTicketStatus(status) {
    if (!state.adminTicketId) return;
    if (status === 'closed') {
      if (!window.confirm('ปิด Ticket นี้?\n\nข้อความทั้งหมดจะถูกลบออกจากระบบถาวร')) return;
    }
    try {
      await authFetch(`/api/admin/tickets/${state.adminTicketId}/status`, { method: 'POST', body: JSON.stringify({ status }) });
      if (status === 'closed') {
        // ตั๋วถูกลบไปแล้ว — เคลียร์หน้าจอแชทฝั่งแอดมิน
        state.adminTicketId = null;
        const empty = $('#admin-ticket-empty');
        const body = $('#admin-ticket-body');
        if (empty) empty.hidden = false;
        if (body) body.hidden = true;
        const messages = $('#admin-ticket-messages');
        if (messages) messages.replaceChildren();
        await loadAdminTickets(state.adminTicketStatus);
        toast('ปิด Ticket แล้ว — ข้อความถูกลบออกจากระบบ');
        return;
      }
      await loadAdminTickets(state.adminTicketStatus);
      await openAdminTicket(state.adminTicketId);
      toast('อัปเดตสถานะแล้ว');
    } catch (error) { toast(error.message); }
  }

  async function replyAdmin(event) {
    event.preventDefault();
    const input = $('#admin-ticket-input');
    const body = input.value.trim();
    if (!body || !state.adminTicketId) return;
    input.value = '';
    try {
      await authFetch(`/api/admin/tickets/${state.adminTicketId}/reply`, { method: 'POST', body: JSON.stringify({ body }) });
      await openAdminTicket(state.adminTicketId);
      await loadAdminTickets(state.adminTicketStatus);
    } catch (error) {
      toast(error.message);
      input.value = body;
    }
  }

  async function loadAdminStats() {
    try {
      const data = await authFetch('/api/admin/stats');
      const set = (key, value) => { const node = $(`[data-admin-stat="${key}"]`); if (node) node.textContent = value; };
      set('users', Number(data.users || 0).toLocaleString('th-TH'));
      set('posts', Number(data.posts || 0).toLocaleString('th-TH'));
      set('tickets_open', Number(data.tickets?.open || 0).toLocaleString('th-TH'));
    } catch { /* สิทธิ์ไม่ถึง = ไม่แสดงตัวเลข */ }
  }

  // สถานะออนไลน์ของแอดมิน: heartbeat ส่งจาก app.js (ทุกหน้า) แล้วแจ้งเหตุการณ์มาที่นี่
  function showAdminOnline() {
    const node = $('#admin-online');
    if (node) { node.innerHTML = '<i></i> Admin online'; node.classList.add('on'); }
  }

  document.addEventListener('admin:online', showAdminOnline);

  // ---------- ตรวจว่าตารางพร้อมใช้งานหรือยัง ----------
  async function checkSetup() {
    try {
      const response = await fetch('/api/setup/status');
      const data = await response.json();
      if (data.ready) return true;
      showSetupNotice(data);
      return false;
    } catch { return true; }  // ตรวจไม่ได้ — ไม่ขวางการใช้งาน
  }

  function showSetupNotice(data) {
    const migrations = data.migrations_to_run || [];
    const box = el('div', 'setup-notice');
    box.append(el('b', '', 'ระบบกระทู้และ Ticket ยังไม่พร้อมใช้งาน'));
    const copy = el('p', '', data.missing_tables
      ? `ยังไม่ได้สร้างตาราง: ${Object.keys(data.missing_tables).join(', ')}`
      : (data.message || 'ยังไม่ได้รัน migration'));
    box.append(copy);
    if (migrations.length) {
      const hint = el('p', 'setup-hint', 'วิธีแก้: รันไฟล์ migration ใน Supabase → SQL Editor (รันซ้ำได้ ไม่พัง)');
      box.append(hint);
      const code = el('code', 'setup-code');
      code.textContent = `python scripts/run_migrations.py ${migrations.map((m) => m.split('_')[0]).join(' ')}`;
      box.append(code);
      const alt = el('p', 'setup-hint', 'หรือคัดลอก SQL จากไฟล์ supabase/migrations/007_009_all.sql ไปวางใน SQL Editor แล้วกด Run');
      box.append(alt);
    }
    const target = document.querySelector('[data-community-pane="threads"]');
    if (target && !target.querySelector('.setup-notice')) target.prepend(box);
  }

  // ---------- เริ่มต้น ----------
  function init() {
    const isCommunity = document.body.dataset.page === 'community';
    const isAdmin = document.body.dataset.page === 'admin';
    if (!isCommunity && !isAdmin) return;

    $$('[data-community-tab]').forEach((button) => button.addEventListener('click', () => showTab(button.dataset.communityTab)));

    if (isCommunity) {
      $('#add-option')?.addEventListener('click', addOption);
      $('#submit-post')?.addEventListener('click', submitPost);
      $('#compose-image')?.addEventListener('change', (event) => {
        const file = event.target.files?.[0];
        state.imageFile = file || null;
        state.imageUrl = '';
        previewSelectedImage();
        if (file) setStatus('#compose-status', '');
      });
      $('#compose-image-clear')?.addEventListener('click', clearSelectedImage);
      $('#new-ticket')?.addEventListener('click', openNewTicketModal);
      $('#new-ticket-close')?.addEventListener('click', closeNewTicketModal);
      $('#new-ticket-cancel')?.addEventListener('click', closeNewTicketModal);
      $('#new-ticket-submit')?.addEventListener('click', submitNewTicket);
      $('#new-ticket-modal')?.addEventListener('click', (event) => { if (event.target.id === 'new-ticket-modal') closeNewTicketModal(); });
      $('#close-ticket')?.addEventListener('click', closeTicket);
      $('#chat-form')?.addEventListener('submit', sendChatMessage);
      $('#ticket-list')?.addEventListener('click', (event) => {
        const item = event.target.closest('.ticket-item');
        if (item) openTicket(Number(item.dataset.ticketId));
      });
      let searchTimer = null;
      $('#thread-search')?.addEventListener('input', (event) => {
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => { state.query = event.target.value.trim(); loadPosts(); }, 300);
      });
      loadTags();
      checkSetup().then((ready) => { if (ready) loadPosts(); });
    }

    if (isAdmin) {
      $$('[data-ticket-status]').forEach((button) => button.addEventListener('click', () => {
        $$('[data-ticket-status]').forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        state.adminTicketStatus = button.dataset.ticketStatus;
        loadAdminTickets(state.adminTicketStatus);
      }));
      $('#admin-ticket-form')?.addEventListener('submit', replyAdmin);
      $('#admin-ticket-answer')?.addEventListener('click', () => setAdminTicketStatus('answered'));
      $('#admin-ticket-close')?.addEventListener('click', () => setAdminTicketStatus('closed'));
      loadAdminTickets('');
      loadAdminStats();
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
