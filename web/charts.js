'use strict';
/* Inline-SVG charts, no library. Spec (dataviz method): 2px lines, ~10% area wash,
   1px solid recessive grid, >=8px markers with a 2px surface ring, a crosshair
   (pointer + arrow keys) on line charts, nearest-point hover (>=24px) on the
   scatter, text in ink tokens only, tooltip text via textContent. Colours come
   from CSS tokens (--chart validated per theme; see styles.css). */

const Charts = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  };
  const text = (parent, x, y, str, attrs = {}) => { const t = el('text', { x, y, ...attrs }, parent); t.textContent = str; return t; };
  const logScale = (d0, d1, r0, r1) => v => r0 + (Math.log(v) - Math.log(d0)) / (Math.log(d1) - Math.log(d0)) * (r1 - r0);
  const linScale = (d0, d1, r0, r1) => v => r0 + (v - d0) / (d1 - d0) * (r1 - r0);

  function frame(host, height) {
    host.querySelector('svg')?.remove();
    const w = Math.max(280, host.clientWidth);
    const svg = el('svg', { width: w, height, viewBox: `0 0 ${w} ${height}`, class: 'chart-svg' });
    host.prepend(svg);
    return { svg, w, h: height };
  }

  function tooltip(host) {
    let tip = host.querySelector('.chart-tip');
    if (!tip) { tip = document.createElement('div'); tip.className = 'chart-tip'; tip.hidden = true; host.appendChild(tip); }
    return {
      show(x, y, value, label) {
        tip.replaceChildren();
        const v = document.createElement('b'); v.textContent = value;
        const l = document.createElement('span'); l.textContent = label;
        tip.append(v, l);
        tip.hidden = false;
        const hw = host.clientWidth, tw = tip.offsetWidth;
        tip.style.left = Math.min(Math.max(0, x - tw / 2), hw - tw) + 'px';
        tip.style.top = Math.max(0, y - tip.offsetHeight - 14) + 'px';
      },
      hide() { tip.hidden = true; },
    };
  }

  /* Liquidity curve: % sellable vs days (log). opts: points [[d, share]], ceiling,
     milestones [{days, share, label}], marker {days}, fmtValue(d, share). */
  function curve(host, opts) {
    const { svg, w, h } = frame(host, opts.height || 300);
    const m = { l: 44, r: 16, t: 18, b: 34 };
    const x = logScale(1, 365, m.l, w - m.r), y = linScale(0, 1, h - m.b, m.t);
    const g = el('g', {}, svg);
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      el('line', { x1: m.l, x2: w - m.r, y1: y(v), y2: y(v), class: 'grid' }, g);
      text(g, m.l - 8, y(v) + 4, Math.round(v * 100) + '%', { class: 'tick', 'text-anchor': 'end' });
    }
    const narrow = w < 520;
    const xt = narrow ? [[1, '1d'], [7, '1w'], [30, '1m'], [90, '3m'], [365, '1y']]
      : [[1, '1 day'], [7, '1 week'], [30, '1 month'], [90, '3 months'], [365, '1 year']];
    for (const [d, lab] of xt) {
      el('line', { x1: x(d), x2: x(d), y1: m.t, y2: h - m.b, class: 'grid' }, g);
      text(g, x(d), h - m.b + 20, lab, { class: 'tick', 'text-anchor': d === 1 ? 'start' : d === 365 ? 'end' : 'middle' });
    }
    if (opts.ceiling != null && opts.ceiling < 0.995) {
      el('line', { x1: m.l, x2: w - m.r, y1: y(opts.ceiling), y2: y(opts.ceiling), class: 'ceiling' }, g);
      text(g, w - m.r, y(opts.ceiling) - 7, opts.ceilingLabel, { class: 'note', 'text-anchor': 'end' });
    }
    const pts = opts.points;
    const line = pts.map(([d, s], i) => `${i ? 'L' : 'M'}${x(d).toFixed(1)},${y(s).toFixed(1)}`).join('');
    el('path', { d: `${line}L${x(365)},${y(0)}L${x(1)},${y(0)}Z`, class: 'area' }, g);
    const path = el('path', { d: line, class: 'line' }, g);
    const len = path.getTotalLength?.() || 0;
    if (len && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
      path.style.strokeDasharray = len; path.style.strokeDashoffset = len;
      requestAnimationFrame(() => { path.style.transition = 'stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)'; path.style.strokeDashoffset = 0; });
    }
    for (const ms of opts.milestones || []) {
      if (ms.days == null || ms.days > 365) continue;
      const cx = x(Math.max(1, ms.days)), cy = y(ms.share);
      el('circle', { cx, cy, r: 5, class: 'dot' }, g);
      text(g, cx + 9, cy + 14, ms.label, { class: 'label' });
    }
    // current horizon marker
    const mk = el('g', { class: 'marker' }, g);
    const mLine = el('line', { y1: m.t, y2: h - m.b, class: 'marker-line' }, mk);
    const mDot = el('circle', { r: 5, class: 'dot' }, mk);
    const shareAt = d => { // exact on the sampled points; linear in log-days between them
      if (d <= pts[0][0]) return pts[0][1];
      for (let i = 1; i < pts.length; i++) if (d <= pts[i][0]) {
        const [d0, s0] = pts[i - 1], [d1, s1] = pts[i];
        const k = (Math.log(d) - Math.log(d0)) / (Math.log(d1) - Math.log(d0));
        return s0 + (s1 - s0) * k;
      }
      return pts[pts.length - 1][1];
    };
    const place = d => { const px = x(d); mLine.setAttribute('x1', px); mLine.setAttribute('x2', px); mDot.setAttribute('cx', px); mDot.setAttribute('cy', y(opts.exactAt?.(d) ?? shareAt(d))); };
    if (opts.marker) place(opts.marker);
    // crosshair + keyboard
    const tip = tooltip(host);
    const cross = el('line', { y1: m.t, y2: h - m.b, class: 'cross', visibility: 'hidden' }, g);
    const cDot = el('circle', { r: 5, class: 'dot', visibility: 'hidden' }, g);
    const hit = el('rect', { x: m.l, y: m.t, width: w - m.l - m.r, height: h - m.t - m.b, fill: 'transparent' }, svg);
    let kd = opts.marker || 7;
    const showAt = d => {
      d = Math.min(365, Math.max(1, d));
      const s = opts.exactAt?.(d) ?? shareAt(d), px = x(d), py = y(s);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cDot.setAttribute('cx', px); cDot.setAttribute('cy', py);
      cross.setAttribute('visibility', 'visible'); cDot.setAttribute('visibility', 'visible');
      const [value, label] = opts.fmtValue(d, s);
      tip.show(px, py, value, label);
    };
    const hide = () => { cross.setAttribute('visibility', 'hidden'); cDot.setAttribute('visibility', 'hidden'); tip.hide(); };
    const inv = px => Math.exp(Math.log(1) + (px - m.l) / (w - m.r - m.l) * (Math.log(365) - Math.log(1)));
    hit.addEventListener('pointermove', ev => { const r = svg.getBoundingClientRect(); showAt(Math.round(inv(ev.clientX - r.left))); });
    hit.addEventListener('pointerleave', hide);
    svg.setAttribute('tabindex', '0');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', opts.aria);
    svg.addEventListener('keydown', ev => {
      const steps = [1, 2, 3, 5, 7, 10, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365];
      let i = steps.findIndex(s => s >= kd);
      if (ev.key === 'ArrowRight') i = Math.min(steps.length - 1, i + 1);
      else if (ev.key === 'ArrowLeft') i = Math.max(0, i - 1);
      else if (ev.key === 'Escape') { hide(); return; }
      else return;
      ev.preventDefault(); kd = steps[i]; showAt(kd);
    });
    svg.addEventListener('blur', hide);
    return { setMarker: d => { place(d); } };
  }

  /* Scatter: x = reported $ (log), y = sellable share, r ∝ sqrt(visits).
     points [{id, x, y, visits, label, flag}], onPick(id), fmt(p) -> [value, label]. */
  function scatter(host, opts) {
    const { svg, w, h } = frame(host, opts.height || 360);
    const m = { l: 44, r: 20, t: 18, b: 38 };
    const xs = opts.points.map(p => p.x);
    const lo = Math.pow(10, Math.floor(Math.log10(Math.min(...xs)))), hi = Math.pow(10, Math.ceil(Math.log10(Math.max(...xs))));
    const x = logScale(lo, hi, m.l, w - m.r), y = linScale(0, 1, h - m.b, m.t);
    const vmax = Math.max(1, ...opts.points.map(p => p.visits || 0));
    const r = v => v ? 4 + 16 * Math.sqrt(v / vmax) : 4;
    const g = el('g', {}, svg);
    for (const v of [0, 0.25, 0.5, 0.75, 1]) {
      el('line', { x1: m.l, x2: w - m.r, y1: y(v), y2: y(v), class: 'grid' }, g);
      text(g, m.l - 8, y(v) + 4, Math.round(v * 100) + '%', { class: 'tick', 'text-anchor': 'end' });
    }
    for (let v = lo; v <= hi; v *= 10) {
      el('line', { x1: x(v), x2: x(v), y1: m.t, y2: h - m.b, class: 'grid' }, g);
      text(g, x(v), h - m.b + 20, opts.fmtAxis(v), { class: 'tick', 'text-anchor': v === lo ? 'start' : v >= hi ? 'end' : 'middle' });
    }
    const placed = opts.points.map(p => ({ ...p, cx: x(p.x), cy: y(p.y), r: r(p.visits) }));
    // Largest first so small bubbles stay on top and hoverable.
    [...placed].sort((a, b) => b.r - a.r).forEach((p, i) => {
      const c = el('circle', { cx: p.cx, cy: p.cy, r: p.r, class: 'bubble' + (p.flag ? ' flag' : '') }, g);
      c.style.animationDelay = Math.min(i, 40) * 18 + 'ms';
    });
    const labels = [];
    for (const p of placed.filter(q => q.label)) {
      const right = p.cx < w - 120;
      const t = text(g, right ? p.cx + p.r + 6 : p.cx - p.r - 6, p.cy + 4, p.label, { class: 'label', 'text-anchor': right ? 'start' : 'end' });
      const bb = t.getBBox();
      if (labels.some(o => !(bb.x + bb.width < o.x || o.x + o.width < bb.x || bb.y + bb.height < o.y || o.y + o.height < bb.y))) t.remove();
      else labels.push(bb);
    }
    const tip = tooltip(host);
    const ring = el('circle', { class: 'hover-ring', r: 0, visibility: 'hidden' }, g);
    const nearest = (px, py) => {
      let best = null, bd = Infinity;
      for (const p of placed) { const d = Math.hypot(p.cx - px, p.cy - py) - p.r; if (d < bd) { bd = d; best = p; } }
      return bd <= 24 ? best : null;
    };
    let cur = null;
    const show = p => {
      cur = p;
      if (!p) { ring.setAttribute('visibility', 'hidden'); tip.hide(); svg.style.cursor = ''; return; }
      ring.setAttribute('cx', p.cx); ring.setAttribute('cy', p.cy); ring.setAttribute('r', p.r + 4); ring.setAttribute('visibility', 'visible');
      const [value, label] = opts.fmt(p);
      tip.show(p.cx, p.cy - p.r, value, label);
      svg.style.cursor = 'pointer';
    };
    svg.addEventListener('pointermove', ev => { const b = svg.getBoundingClientRect(); show(nearest(ev.clientX - b.left, ev.clientY - b.top)); });
    svg.addEventListener('pointerleave', () => show(null));
    svg.addEventListener('click', () => { if (cur) opts.onPick(cur.id); });
    // keyboard: arrows walk points left to right
    const order = [...placed].sort((a, b) => a.cx - b.cx);
    let ki = -1;
    svg.setAttribute('tabindex', '0'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', opts.aria);
    svg.addEventListener('keydown', ev => {
      if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
        ev.preventDefault(); ki = (ki + (ev.key === 'ArrowRight' ? 1 : -1) + order.length) % order.length; show(order[ki]);
      } else if (ev.key === 'Enter' && cur) opts.onPick(cur.id);
      else if (ev.key === 'Escape') show(null);
    });
    svg.addEventListener('blur', () => show(null));
  }

  /* Sparkline over time: points [{t: Date, v: share}]. */
  function spark(host, opts) {
    const { svg, w, h } = frame(host, opts.height || 120);
    const m = { l: 44, r: 12, t: 12, b: 26 };
    const t0 = opts.points[0].t, t1 = opts.points[opts.points.length - 1].t;
    const x = linScale(+t0, +t1, m.l, w - m.r), y = linScale(0, 1, h - m.b, m.t);
    const g = el('g', {}, svg);
    for (const v of [0, 0.5, 1]) {
      el('line', { x1: m.l, x2: w - m.r, y1: y(v), y2: y(v), class: 'grid' }, g);
      text(g, m.l - 8, y(v) + 4, Math.round(v * 100) + '%', { class: 'tick', 'text-anchor': 'end' });
    }
    text(g, m.l, h - 6, opts.fmtT(t0), { class: 'tick' });
    text(g, w - m.r, h - 6, opts.fmtT(t1), { class: 'tick', 'text-anchor': 'end' });
    const d = opts.points.map((p, i) => `${i ? 'L' : 'M'}${x(+p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
    el('path', { d, class: 'line' }, g);
    const last = opts.points[opts.points.length - 1];
    el('circle', { cx: x(+last.t), cy: y(last.v), r: 4, class: 'dot' }, g);
    const tip = tooltip(host);
    const cross = el('line', { y1: m.t, y2: h - m.b, class: 'cross', visibility: 'hidden' }, g);
    const showI = i => {
      const p = opts.points[i], px = x(+p.t);
      cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
      const [value, label] = opts.fmt(p); tip.show(px, y(p.v), value, label);
    };
    const hideT = () => { cross.setAttribute('visibility', 'hidden'); tip.hide(); };
    svg.addEventListener('pointermove', ev => {
      const b = svg.getBoundingClientRect(), px = ev.clientX - b.left;
      let bi = 0, bd = Infinity; opts.points.forEach((p, i) => { const dd = Math.abs(x(+p.t) - px); if (dd < bd) { bd = dd; bi = i; } });
      showI(bi);
    });
    svg.addEventListener('pointerleave', hideT);
    let ki = opts.points.length - 1;
    svg.setAttribute('tabindex', '0'); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', opts.aria);
    svg.addEventListener('keydown', ev => {
      if (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft') return;
      ev.preventDefault(); ki = Math.min(opts.points.length - 1, Math.max(0, ki + (ev.key === 'ArrowRight' ? 1 : -1))); showI(ki);
    });
    svg.addEventListener('blur', hideT);
  }

  // Redraw on container resize.
  function responsive(host, draw) {
    let last = host.clientWidth;
    draw();
    if (!('ResizeObserver' in window)) return;
    new ResizeObserver(() => { if (Math.abs(host.clientWidth - last) > 4) { last = host.clientWidth; draw(); } }).observe(host);
  }

  return { curve, scatter, spark, responsive };
})();
