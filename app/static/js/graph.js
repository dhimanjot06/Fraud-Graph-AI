/* Minimal force-directed network renderer, no dependencies.
 * Consumes {nodes:[{id, role, level, ring?}], edges:[{source, target, count, total, ring?}]}
 * and draws an SVG into the given container.
 */
(function () {
  const LEVEL_COLOR = { high: 'var(--signal)', medium: 'var(--amber)', low: 'var(--ink-45)' };
  const ROLE_SHAPE = { collector: 6.5, hub: 6.5, bridge: 6, beneficiary: 5.5 };

  function layout(nodes, edges, width, height, iterations) {
    const pos = new Map();
    const n = nodes.length;
    nodes.forEach((node, i) => {
      const angle = (2 * Math.PI * i) / n;
      pos.set(node.id, { x: width / 2 + Math.cos(angle) * (Math.min(width, height) * 0.32),
                         y: height / 2 + Math.sin(angle) * (Math.min(width, height) * 0.32) });
    });
    const k = Math.sqrt((width * height) / Math.max(n, 1)) * 0.9;
    const idx = new Map(nodes.map((n, i) => [n.id, i]));

    for (let it = 0; it < iterations; it++) {
      const disp = nodes.map(() => ({ x: 0, y: 0 }));
      for (let i = 0; i < n; i++) {
        for (let j = i + 1; j < n; j++) {
          const a = pos.get(nodes[i].id), b = pos.get(nodes[j].id);
          let dx = a.x - b.x, dy = a.y - b.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const force = (k * k) / dist;
          dx = (dx / dist) * force; dy = (dy / dist) * force;
          disp[i].x += dx; disp[i].y += dy; disp[j].x -= dx; disp[j].y -= dy;
        }
      }
      edges.forEach(e => {
        const i = idx.get(e.source), j = idx.get(e.target);
        if (i === undefined || j === undefined || i === j) return;
        const a = pos.get(nodes[i].id), b = pos.get(nodes[j].id);
        let dx = a.x - b.x, dy = a.y - b.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const force = (dist * dist) / k;
        dx = (dx / dist) * force; dy = (dy / dist) * force;
        disp[i].x -= dx; disp[i].y -= dy; disp[j].x += dx; disp[j].y += dy;
      });
      const temp = Math.max(width, height) * (1 - it / iterations) * 0.06;
      nodes.forEach((node, i) => {
        const d = disp[i];
        const dist = Math.sqrt(d.x * d.x + d.y * d.y) || 0.01;
        const cap = Math.min(dist, temp);
        const p = pos.get(node.id);
        p.x = Math.min(width - 40, Math.max(40, p.x + (d.x / dist) * cap));
        p.y = Math.min(height - 40, Math.max(40, p.y + (d.y / dist) * cap));
      });
    }
    return pos;
  }

  function svgEl(tag, attrs) {
    const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  }

  window.renderFraudGraph = function (container, data, opts) {
    opts = opts || {};
    container.innerHTML = '';
    if (!data.nodes.length) {
      container.innerHTML = '<div class="graph-empty">No accounts to display.</div>';
      return;
    }
    const width = container.clientWidth || 800;
    const height = opts.height || Math.max(360, Math.min(640, data.nodes.length * 14));
    const pos = layout(data.nodes, data.edges, width, height, Math.min(220, 60 + data.nodes.length * 2));

    const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img',
      'aria-label': 'Network graph of accounts and transfers between them' });

    const idxOf = new Map(data.nodes.map(n => [n.id, n]));
    const maxCount = Math.max(1, ...data.edges.map(e => e.count || 1));

    data.edges.forEach(e => {
      const a = pos.get(e.source), b = pos.get(e.target);
      if (!a || !b) return;
      const isLoop = e.source === e.target;
      const w = 1 + 2.2 * ((e.count || 1) / maxCount);
      let d;
      const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
      const dx = b.x - a.x, dy = b.y - a.y;
      const curve = 0.18;
      d = `M ${a.x} ${a.y} Q ${mx - dy * curve} ${my + dx * curve} ${b.x} ${b.y}`;
      const path = svgEl('path', { d, fill: 'none', stroke: 'var(--ink-15)', 'stroke-width': w });
      path.classList.add('graph-edge');
      svg.appendChild(path);
      const marker = svgEl('circle', { cx: b.x - dx * 0.13, cy: b.y - dy * 0.13, r: 2.2, fill: 'var(--ink-45)' });
      svg.appendChild(marker);
    });

    data.nodes.forEach(node => {
      const p = pos.get(node.id);
      const g = svgEl('g', { transform: `translate(${p.x},${p.y})`, tabindex: '0' });
      const r = ROLE_SHAPE[node.role] || 5;
      const color = LEVEL_COLOR[node.level] || 'var(--ink-70)';
      const circle = svgEl('circle', { r, fill: 'var(--panel)', stroke: color, 'stroke-width': 1.8 });
      g.appendChild(circle);
      const label = svgEl('text', { y: r + 12, 'text-anchor': 'middle', 'font-size': '9', fill: 'var(--ink-70)' });
      label.textContent = node.id;
      g.appendChild(label);
      const title = svgEl('title', {});
      title.textContent = `${node.id} — ${node.role || 'member'}${node.risk != null ? ' — risk ' + Math.round(node.risk) + '/100' : ''}`;
      g.appendChild(title);
      svg.appendChild(g);
    });

    container.appendChild(svg);
  };
})();
