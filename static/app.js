const qs = (id) => document.getElementById(id);
const refreshButton = qs('refresh-button');
const toast = qs('toast');
let previousProcessed = null;
let reloadTimer = null;

function won(value) {
  if (value === null || value === undefined) return '가격문의';
  return Number(value).toLocaleString('ko-KR') + '원';
}
function showToast(message) {
  if (!toast) return;
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), 2200);
}
function setText(id, value) { const el = qs(id); if (el) el.textContent = value; }

async function updateStatus() {
  try {
    const r = await fetch('/api/status', {cache:'no-store'});
    if (!r.ok) return;
    const data = await r.json();
    setText('top-status', data.running ? '수집 중…' : (data.last_status || '대기'));
    const dot = qs('live-dot'); if (dot) dot.classList.toggle('running', !!data.running);
    setText('stat-active', data.active_count ?? 0);
    setText('stat-soldout', data.soldout_count ?? 0);
    setText('stat-ended', data.ended_count ?? 0);
    setText('stat-avg', won(data.avg_price));
    setText('stat-changes', data.changes_24h ?? 0);
    setText('stat-result', data.running ? '진행 중' : (data.last_status === 'success' ? '완료' : data.last_status || '대기'));
    setText('stat-result-sub', `신규 ${data.new_count || 0} · 변경 ${data.updated_count || 0}`);

    const wrap = qs('progress-wrap');
    if (wrap) wrap.classList.toggle('hidden', !data.running);
    if (data.running) {
      setText('progress-text', `${data.processed || 0} / ${data.queued || 0} · ${data.progress_pct || 0}%`);
      setText('current-product', data.current_product || '수집 중…');
      const bar = qs('progress-bar'); if (bar) bar.style.width = `${data.progress_pct || 0}%`;
      if (previousProcessed !== null && data.processed > previousProcessed) {
        clearTimeout(reloadTimer);
        reloadTimer = setTimeout(() => {
          if (document.visibilityState === 'visible') location.reload();
        }, 5000);
      }
      previousProcessed = data.processed || 0;
    } else if (previousProcessed !== null) {
      previousProcessed = null;
      if (data.last_status === 'success') {
        showToast('상품 수집이 완료되었습니다.');
        setTimeout(() => location.reload(), 700);
      }
    }
  } catch (_) {}
}

if (refreshButton) {
  refreshButton.addEventListener('click', async () => {
    refreshButton.disabled = true;
    refreshButton.textContent = '시작 중…';
    try {
      const r = await fetch('/api/refresh', {method:'POST'});
      if (r.ok) showToast('새 수집을 시작했습니다.');
      else showToast('이미 수집이 진행 중입니다.');
    } catch (_) {
      showToast('수집 시작 요청에 실패했습니다.');
    } finally {
      setTimeout(() => { refreshButton.disabled = false; refreshButton.textContent = '수집 시작'; }, 1800);
      updateStatus();
    }
  });
}

setInterval(updateStatus, 1500);
updateStatus();
