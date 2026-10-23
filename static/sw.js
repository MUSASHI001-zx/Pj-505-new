/* TCAS Buddy Web Push service worker */
self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch { data = { body: event.data?.text() || '' }; }
  const title = data.title || 'TCAS Buddy · มีอัปเดตใหม่';
  const options = {
    body: data.body || 'มีรายการที่คุณติดตามอัปเดตแล้ว',
    icon: '/static/assets/tcas-logo.png',
    badge: '/static/assets/tcas-logo.png',
    data: { url: data.url || '/' },
    tag: data.dedupe_key || `${data.entity_type || 'update'}-${data.entity_id || Date.now()}`,
    renotify: false
  };
  event.waitUntil(self.registration.showNotification(title, options));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const raw = event.notification.data?.url || '/';
  let target = '/';
  try { const parsed = new URL(raw, self.location.origin); if (parsed.origin === self.location.origin) target = parsed.href; } catch {}
  event.waitUntil((async () => {
    const clientsList = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of clientsList) {
      if (new URL(client.url).origin === self.location.origin) { await client.focus(); if ('navigate' in client) await client.navigate(target); return; }
    }
    await self.clients.openWindow(target);
  })());
});
