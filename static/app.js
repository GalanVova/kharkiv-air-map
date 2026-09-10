const mapEl = document.getElementById('map');
if (!window.L) throw new Error('Leaflet is not available');

mapEl.innerHTML = '';
const map = L.map('map', {
  zoomControl: true,
  preferCanvas: true,
  attributionControl: true
}).setView([49.9935, 36.2304], 9);

const primaryTiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  crossOrigin: true,
  updateWhenIdle: true,
  keepBuffer: 2,
  attribution: '&copy; OpenStreetMap contributors'
});

let tileErrors = 0;
primaryTiles.on('tileerror', () => {
  tileErrors += 1;
  if (tileErrors === 4) {
    document.getElementById('last-update').textContent = 'ошибка загрузки подложки';
    document.getElementById('status-dot').className = 'status-dot err';
  }
});
primaryTiles.addTo(map);

setTimeout(() => map.invalidateSize(true), 150);
window.addEventListener('resize', () => map.invalidateSize(false));

const markerLayer = L.layerGroup().addTo(map);
const markerByEvent = new Map();
let latestEvents = [];

const iconFor = (kind) => {
  if (kind === 'FPV') return '⚡';
  if (kind === 'Молнія') return '✦';
  if (kind === 'Shahed' || kind === 'БПЛА') return '◆';
  if (kind === 'КАБ') return '⬣';
  if (kind === 'Балістика' || kind === 'Ракета') return '▲';
  if (kind === 'РСЗВ') return '✹';
  if (kind === 'Офіційна тривога') return '!';
  return '•';
};

function ageText(iso) {
  const sec = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec} сек`;
  return `${Math.floor(sec / 60)} мин`;
}

function esc(s='') {
  return String(s).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

function eventTitle(e) {
  if (e.direction_from && e.direction_to) return `${e.direction_from} → ${e.direction_to}`;
  if (e.direction_to) return `направление: ${e.direction_to}`;
  return e.location || 'Без точки на карте';
}

function popupHtml(e) {
  return `<div class="popup-title">${esc(e.kind)} · ${esc(eventTitle(e))}</div>
    <div class="popup-meta">${esc(e.source_name)} · ${ageText(e.published_at)}</div>
    <div class="popup-text">${esc(e.text)}</div>
    <a class="popup-link" href="${esc(e.url)}" target="_blank" rel="noopener">Открыть источник</a>`;
}

function renderMarkers(events) {
  markerLayer.clearLayers();
  markerByEvent.clear();
  events.filter(e => e.mapped && Number.isFinite(e.lat) && Number.isFinite(e.lon)).forEach(e => {
    const html = `<div class="threat-marker ${e.coarse ? 'coarse' : ''}" title="${esc(e.kind)}">${iconFor(e.kind)}</div>`;
    const marker = L.marker([e.lat, e.lon], {
      icon: L.divIcon({className:'marker-wrap', html, iconSize:[34,34], iconAnchor:[17,17]})
    }).bindPopup(popupHtml(e), {maxWidth: 330});
    marker.addTo(markerLayer);
    markerByEvent.set(e.id, marker);
  });
}

function renderFeed(events) {
  const feed = document.getElementById('feed');
  if (!events.length) {
    feed.innerHTML = '<div class="event"><div class="event-text">Свежих событий за заданный интервал нет.</div></div>';
    return;
  }
  feed.innerHTML = events.slice(0, 80).map(e => `
    <div class="event" data-id="${esc(e.id)}">
      <div class="event-head"><span class="event-kind">${esc(e.kind)}</span><span class="event-time">${ageText(e.published_at)}</span></div>
      <div class="event-location">${esc(eventTitle(e))}</div>
      <div class="event-text">${esc(e.text)}</div>
      <div class="event-source">${esc(e.source_name)}</div>
    </div>`).join('');

  feed.querySelectorAll('.event[data-id]').forEach(el => {
    el.addEventListener('click', () => {
      const marker = markerByEvent.get(el.dataset.id);
      if (marker) {
        map.setView(marker.getLatLng(), Math.max(map.getZoom(), 12));
        marker.openPopup();
      } else {
        const e = latestEvents.find(x => x.id === el.dataset.id);
        if (e?.url) window.open(e.url, '_blank', 'noopener');
      }
    });
  });
}

function renderSummary(events, ttl) {
  const mapped = events.filter(e => e.mapped).length;
  const kinds = {};
  events.forEach(e => kinds[e.kind] = (kinds[e.kind] || 0) + 1);
  const top = Object.entries(kinds).sort((a,b)=>b[1]-a[1]).slice(0,5)
    .map(([k,v]) => `${esc(k)}: ${v}`).join(' · ');
  document.getElementById('summary').innerHTML = `<strong>${events.length}</strong> свежих сообщений, <strong>${mapped}</strong> на карте.<br><span style="color:#9aa7bb">Окно: ${ttl} мин${top ? ' · ' + top : ''}</span>`;
}

async function loadStatus() {
  try {
    const r = await fetch('/api/status', {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const s = await r.json();
    const box = document.getElementById('sources');
    box.innerHTML = s.sources.map(src => {
      const state = s.source_status?.[src.id] || 'unknown';
      const bad = state.startsWith('error');
      return `<a class="source-chip ${bad ? 'bad' : ''}" href="${src.url}" target="_blank" rel="noopener" title="${esc(state)}">${esc(src.name)}</a>`;
    }).join('') + `<span class="source-chip ${s.alerts_in_ua_enabled ? '' : 'bad'}">alerts.in.ua: ${s.alerts_in_ua_enabled ? 'on' : 'token нужен'}</span>`;
    document.getElementById('status-dot').className = 'status-dot ok';
  } catch (_) {
    document.getElementById('status-dot').className = 'status-dot err';
  }
}

async function loadEvents() {
  try {
    const r = await fetch('/api/events', {cache:'no-store'});
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    latestEvents = data.events || [];
    renderMarkers(latestEvents);
    renderFeed(latestEvents);
    renderSummary(latestEvents, data.ttl_minutes);
    document.getElementById('last-update').textContent = `обновлено ${new Date().toLocaleTimeString()}`;
    document.getElementById('status-dot').className = 'status-dot ok';
  } catch (_) {
    document.getElementById('last-update').textContent = 'ошибка обновления';
    document.getElementById('status-dot').className = 'status-dot err';
  }
}

async function forceRefresh() {
  const btn = document.getElementById('refresh-btn');
  btn.disabled = true;
  btn.textContent = '…';
  try {
    await fetch('/api/refresh', {method:'POST'});
    await Promise.allSettled([loadEvents(), loadStatus()]);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Обновить';
  }
}

document.getElementById('refresh-btn').addEventListener('click', forceRefresh);
loadEvents();
setTimeout(loadStatus, 300);
setInterval(loadEvents, 20000);
setInterval(loadStatus, 60000);
