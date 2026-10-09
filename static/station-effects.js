/* Shared pointer feedback and workspace menu controls. */
(() => {
  const root = document.documentElement;
  const reduce = matchMedia('(prefers-reduced-motion:reduce)');
  const pulse = document.querySelector('.pulse');
  const menu = document.getElementById('workspace-menu');
  const toggle = document.getElementById('workspace-effects');
  let enabled = true, frame = 0, point = null;
  try { enabled = localStorage.getItem('station-effects') !== 'off'; } catch (e) {}
  toggle.checked = enabled;
  function hideGlow() {
    point = null;
    root.style.setProperty('--x', '-500px');
    root.style.setProperty('--y', '-500px');
    pulse.classList.remove('bloom');
  }
  toggle.addEventListener('change', () => {
    enabled = toggle.checked;
    try { localStorage.setItem('station-effects', enabled ? 'on' : 'off'); } catch (e) {}
    hideGlow();
  });
  window.addEventListener('pointermove', e => {
    if (!enabled || reduce.matches || e.pointerType === 'touch') return;
    point = {x:e.clientX+12, y:e.clientY+12};
    if (!frame) frame = requestAnimationFrame(() => {
      frame = 0;
      if (!point) return;
      root.style.setProperty('--x', point.x+'px');
      root.style.setProperty('--y', point.y+'px');
    });
  }, {passive:true});
  window.addEventListener('pointerdown', e => {
    if (!enabled || reduce.matches) return;
    root.style.setProperty('--tap-x', e.clientX+12+'px');
    root.style.setProperty('--tap-y', e.clientY+12+'px');
    pulse.classList.remove('bloom');
    void pulse.offsetWidth;
    pulse.classList.add('bloom');
  }, {passive:true});
  document.addEventListener('pointerleave', hideGlow);
  window.addEventListener('blur', hideGlow);
  reduce.addEventListener('change', hideGlow);
  document.addEventListener('click', e => { if (!menu.contains(e.target)) menu.open = false; });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && menu.open) { menu.open = false; menu.querySelector('summary').focus(); }
  });
  document.getElementById('workspace-theme').addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('station-theme', root.dataset.theme); } catch (e) {}
  });
  document.getElementById('workspace-logout').addEventListener('click', async e => {
    e.target.disabled = true;
    try {
      const r = await fetch('/logout', {method:'POST', headers:{'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}, signal:AbortSignal.timeout(7000)});
      if (!r.ok) throw Error('Sign-out failed. Try again.');
      location.href = '/login';
    } catch (error) {
      document.getElementById('feedback').textContent = error.message;
      e.target.disabled = false;
    }
  });
})();
