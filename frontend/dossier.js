// Tamyr — досье клиента: инфографика на чистом SVG. gid — строки.
const ROLES = {
  coordinator: ["координатор", "#e66767"], distributor: ["распределитель", "#9085e9"], consolidator: ["консолидатор", "#d95926"],
  transit: ["транзит", "#3987e5"], terminal: ["конечный получатель", "#199e70"], boundary: ["граница выгрузки", "#6B7280"],
  peripheral: ["периферия", "#6B7280"],
};
const IN = "#2EBD85", OUT = "#F6465D", ACC = "#F0B429";
const PR_COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500"];   // 4 слота проверенной палитры
const gid = new URLSearchParams(location.search).get("gid");
const $ = s => document.querySelector(s);
const api = TAMYR.api;
document.getElementById("btn-print").addEventListener("click", () => window.print());
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const money = x => x >= 1e6 ? (x / 1e6).toFixed(1).replace(".", ",") + " млн ₸" : x >= 1e3 ? Math.round(x / 1e3) + " тыс ₸" : Math.round(x) + " ₸";
const short = g => "…" + g.slice(-9, -3);
const pill = (t, c) => `<span class="badge" style="color:${c};background:${c}1f;box-shadow:inset 0 0 0 1px ${c}55">${t}</span>`;
const rolePill = r => pill(ROLES[r][0], r === "peripheral" ? "#9AA3AF" : ROLES[r][1]);
const pct = x => Math.round(x * 100) + "%";

// ---------- подсказки ----------
const tip = $("#tip");
document.addEventListener("mousemove", e => {
  const t = e.target.closest("[data-tip]");
  if (!t) return tip.classList.add("hidden");
  tip.innerHTML = t.getAttribute("data-tip");
  tip.classList.remove("hidden");
  const x = Math.min(e.clientX + 14, innerWidth - 300);
  tip.style.left = x + "px"; tip.style.top = e.clientY + 14 + "px";
});

async function main() {
  const [n, top, clusters, gaps, routes, split] = await Promise.all([
    api("node/" + gid + "?ctx=dossier"), api("top?n=50"), api("clusters"), api("next_requests?n=50"),
    api("routes?gid=" + gid + "&n=50"), api("splitting?gid=" + gid)]);
  let cfg = null; try { cfg = await api("config"); } catch (e) {}
  let integ = null; try { integ = await api("integrity"); } catch (e) {}
  const cyc = n.cycles ? await api("cycles/" + gid) : { cycles: [], n_cycles: 0 };
  const rank = top.find(t => t.gid === gid);
  const cl = clusters.find(c => c.cluster_id === n.cluster_id) || {};
  const incomplete = n.is_seed || (n.in_sum > 0 && n.out_sum > n.in_sum * 1.2);
  document.title = `Досье ${short(gid)} — Tamyr`;
  $("#to-report").href = "report.html?gid=" + gid;
  $("#to-card").href = "/#c=" + gid;
  document.querySelector(".brand").href = "/#c=" + gid;

  // контрагенты: объединяем входящие и исходящие
  const cp = new Map();
  n.incoming.forEach(f => cp.set(f.gid, { gid: f.gid, role: f.role, seed: f.is_seed, in: f.sum_kzt, out: 0, nin: f.n_tx, nout: 0 }));
  n.outgoing.forEach(f => { const c = cp.get(f.gid) || { gid: f.gid, role: f.role, seed: f.is_seed, in: 0, out: 0, nin: 0, nout: 0 }; c.out = f.sum_kzt; c.nout = f.n_tx; cp.set(f.gid, c); });
  const cps = [...cp.values()].sort((a, b) => (b.in + b.out) - (a.in + a.out));

  $("#root").innerHTML = `
  <section class="hero">
    <div>
      <div class="kicker">Досье клиента · кластер ${n.cluster_id} · колено ${n.depth}${n.is_seed ? " · из исходного списка (seed)" : ""}</div>
      <h1>${gid}</h1>
      <div class="tags">${rolePill(n.role)}
        ${n.second_level ? pill("сборщик 2-го уровня", ACC) : ""}
        ${n.anomaly ? pill("аномалия для колена", "#FF9F6B") : ""}
        ${n.mark ? pill({ confirmed: "подтверждено аналитиком", review: "на проверке", rejected: "отклонено аналитиком" }[n.mark.status], n.mark.status === "confirmed" ? IN : n.mark.status === "review" ? ACC : "#9AA3AF") : ""}</div>
      <div class="evid">${esc(n.evidence)}</div>
    </div>
    <div class="prio"><div class="big">${n.priority_score.toFixed(2)}</div>
      <small>приоритет проверки${rank ? ` · место <b class="mono" style="color:var(--ink)">${rank.rank}</b> из 2 248` : ""}</small></div>
  </section>

  <section class="kpis">
    ${kpi("Поступило", money(n.in_sum), `${n.in_deg} плательщ.`, IN)}
    ${kpi("Отправлено", money(n.out_sum), `${n.out_deg} получат.`, OUT)}
    ${kpi("Доля, ушедшая дальше", incomplete ? "н/д" : pct(n.pass_ratio ?? 0), incomplete ? "вход виден не полностью" : "out / in")}
    ${kpi("Ушло дальше за ≤2 дня", pct(n.fast_share), "сквозной транзит")}
    ${kpi("Деньги seed доходят", n.seed_reach, "из 81 клиента списка")}
    ${kpi("Устойчивость роли", pct(n.role_stability), n.alt_role ? "иначе: " + ROLES[n.alt_role][0] : "при порогах ±20%",
          n.role_stability >= .9 ? IN : n.role_stability >= .7 ? ACC : OUT)}
  </section>

  <div class="grid">
    <div class="box c12"><h2>Движение денег</h2>
      <div class="sub">Кто платит клиенту и кому уходят деньги. Толщина ленты — сумма, цвет — роль контрагента. Показаны 8 крупнейших с каждой стороны.</div>
      ${flowChart(n, cps)}</div>

    <div class="box c7"><h2>Контрагенты</h2>
      <div class="sub">Крупнейшие по обороту: слева — сколько получено от контрагента, справа — сколько ему отправлено</div>
      <div class="lg"><span><i style="background:${IN}"></i>получено</span><span><i style="background:${OUT}"></i>отправлено</span></div>
      ${butterfly(cps.slice(0, 12))}</div>

    <div class="box c5"><h2>Из чего сложился приоритет</h2>
      <div class="sub">Взвешенная сумма четырёх интерпретируемых компонент (веса — в config.yaml)</div>
      ${priorityBar(n, cfg)}
      <h2 style="margin-top:18px">Устойчивость роли</h2>
      <div class="sub">В скольких из 60 вариантов порогов (каждый ±20%) роль остаётся той же</div>
      ${gauge(n)}</div>

    <div class="box c8"><h2>Поступления и списания по дням</h2>
      <div class="sub">Июль 2026 · вверх — поступления, вниз — списания</div>
      <div class="lg"><span><i style="background:${IN}"></i>поступления</span><span><i style="background:${OUT}"></i>списания</span></div>
      ${daily(n)}</div>

    <div class="box c4"><h2>Календарь активности</h2>
      <div class="sub">Число операций в день</div>
      ${calendar(n)}</div>

    <div class="box c6"><h2>Сальдо нарастающим итогом</h2>
      <div class="sub">Поступления минус списания с 1 июля${incomplete ? " · вход виден не полностью — сальдо занижено" : ""}</div>
      ${cumulative(n)}</div>

    <div class="box c6"><h2>Размеры переводов</h2>
      <div class="sub">Сколько операций в каждом диапазоне сумм · нижняя граница выгрузки — 5 000 ₸</div>
      <div class="lg"><span><i style="background:${IN}"></i>поступления</span><span><i style="background:${OUT}"></i>списания</span></div>
      ${histogram(n)}</div>

    <div class="box c12"><h2>Выявленные признаки</h2>
      <div class="sub">Каждый признак — формальное правило; подсвечены сработавшие</div>
      ${signals(n, routes, split, cyc)}</div>

    <div class="box c6"><h2>Положение в цепочке</h2>
      <div class="sub">Колено — сколько переводов отделяет клиента от исходного списка</div>
      <div class="ladder">${["seed", "1-е", "2-е", "3-е", "4-е"].map((t, i) => `<div class="st ${i === n.depth ? "me" : ""}">${t}</div>`).join("")}</div>
      <p style="color:var(--ink-2);margin:12px 0 4px"><b>Кластер ${n.cluster_id}</b> · ${cl.n_nodes ?? "—"} клиентов, из них seed ${cl.n_seed ?? "—"}, внутренний оборот ${money(cl.sum_kzt_internal || 0)}</p>
      <p class="note" style="margin:0">${esc(cl.hypothesis)}</p></div>

    <div class="box c6"><h2>Рекомендуемые действия</h2>
      <div class="sub">Следующие шаги для аналитика</div>
      <ul class="recs">${recs(n, gaps, cps).map(r => `<li>${r}</li>`).join("")}</ul></div>
  </div>
  <div class="disc">${integ ? `Отпечаток прогона SHA-256: <span class="mono">${integ.run_fingerprint.slice(0, 16)}</span> ·
    ${integ.ok ? `данные, конфиг и код не изменялись после расчёта (${integ.files_checked} файлов)` : "<b style='color:var(--out)'>внимание: файлы изменены после расчёта</b>"} ·
    сформировал: ${esc(TAMYR.analyst || "аноним")}<br>` : ""}Досье сформировано автоматически инструментом Tamyr по обезличенной выгрузке внутрибанковских переводов ≥5 000 ₸ за июль 2026.
    Роли определены формальными правилами (см. README). Все выводы — гипотезы для проверки, а не утверждение о причастности клиента к противоправной деятельности.</div>`;
}

function kpi(label, value, sub, color) {
  return `<div class="kpi"><small>${label}</small><b style="${color ? "color:" + color : ""}">${value}</b><i>${sub}</i></div>`;
}

// ---------- 1. диаграмма потоков: плательщики → клиент → получатели ----------
// Толщина лент — в едином масштабе; блоки на краях раздвигаются минимум на 30 px, чтобы подписи не слипались.
function flowChart(n, cps) {
  const W = 1180, top = 20, bw = 10, K = 8, MIN = 30, base = 300;
  const side = (list, key) => {
    const s = list.filter(c => c[key] > 0).sort((a, b) => b[key] - a[key]);
    const main = s.slice(0, K), rest = s.slice(K);
    if (rest.length) main.push({ gid: "rest", role: "peripheral", [key]: rest.reduce((a, c) => a + c[key], 0), restN: rest.length });
    return main;
  };
  const L = side(cps, "in"), R = side(cps, "out");
  const totIn = L.reduce((a, c) => a + c.in, 0), totOut = R.reduce((a, c) => a + c.out, 0);
  if (!totIn && !totOut) return '<div class="note">Переводов ≥5 000 ₸ в выгрузке нет</div>';
  const k = base / Math.max(totIn, totOut);
  const place = (list, key) => { let y = 0; return list.map(c => { const h = Math.max(2, c[key] * k), o = { c, y, h }; y += Math.max(h + 6, MIN); return o; }); };
  const PL = place(L, "in"), PR = place(R, "out");
  const hL = PL.length ? PL[PL.length - 1].y + PL[PL.length - 1].h : 0, hR = PR.length ? PR[PR.length - 1].y + PR[PR.length - 1].h : 0;
  const cH = Math.max(totIn, totOut) * k, H = Math.max(hL, hR, cH) + top * 2 + 20;
  const midY = (H - 20) / 2, xL = 210, xC = W / 2 - 8, xR = W - 220;
  const offL = midY - hL / 2, offR = midY - hR / 2, cY = midY - cH / 2;
  let svg = "", cin = midY - totIn * k / 2, cout = midY - totOut * k / 2;
  PL.forEach(({ c, y, h }) => {
    const col = c.gid === "rest" ? "#6B7280" : ROLES[c.role][1], yy = offL + y;
    const t = c.gid === "rest" ? `Прочие плательщики (${c.restN}): ${money(c.in)}` : `${c.gid}<br>${ROLES[c.role][0]}${c.seed ? " · seed" : ""}<br>→ клиенту ${money(c.in)}, ${c.nin} оп.`;
    svg += band(xL + bw, yy, xC, cin, h, col, t) + `<rect x="${xL}" y="${yy}" width="${bw}" height="${h}" rx="2" fill="${col}"/>`;
    svg += label(xL - 8, yy + h / 2, c.gid === "rest" ? `прочие · ${c.restN}` : short(c.gid), money(c.in), "end", c);
    cin += c.in * k;
  });
  PR.forEach(({ c, y, h }) => {
    const col = c.gid === "rest" ? "#6B7280" : ROLES[c.role][1], yy = offR + y;
    const t = c.gid === "rest" ? `Прочие получатели (${c.restN}): ${money(c.out)}` : `${c.gid}<br>${ROLES[c.role][0]}${c.seed ? " · seed" : ""}<br>от клиента ${money(c.out)}, ${c.nout} оп.`;
    svg += band(xC + 16, cout, xR, yy, h, col, t) + `<rect x="${xR}" y="${yy}" width="${bw}" height="${h}" rx="2" fill="${col}"/>`;
    svg += label(xR + bw + 8, yy + h / 2, c.gid === "rest" ? `прочие · ${c.restN}` : short(c.gid), money(c.out), "start", c);
    cout += c.out * k;
  });
  svg += `<rect x="${xC}" y="${cY}" width="16" height="${Math.max(cH, 4)}" rx="3" fill="${ACC}" data-tip="Клиент ${gid}<br>поступило ${money(n.in_sum)} · отправлено ${money(n.out_sum)}"/>`;
  svg += `<text x="${xC + 8}" y="${cY - 8}" text-anchor="middle" class="val" style="fill:${ACC}">${short(gid)}</text>`;
  svg += `<text x="${xL}" y="${H - 4}" class="mut">ПЛАТЕЛЬЩИКИ · ${money(n.in_sum)}</text><text x="${xR + bw}" y="${H - 4}" text-anchor="end" class="mut">ПОЛУЧАТЕЛИ · ${money(n.out_sum)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${svg}</svg>`;
}
function band(x1, y1, x2, y2, h, col, t) {
  const m = (x1 + x2) / 2;
  return `<path d="M${x1},${y1} C${m},${y1} ${m},${y2} ${x2},${y2} L${x2},${y2 + h} C${m},${y2 + h} ${m},${y1 + h} ${x1},${y1 + h} Z" fill="${col}" opacity=".32" data-tip="${esc(t)}"/>`;
}
function label(x, y, name, val, anchor, c) {
  const link = c.gid !== "rest" ? `<a href="dossier.html?gid=${c.gid}">` : "";
  return `${link}<text x="${x}" y="${y - 1}" text-anchor="${anchor}" class="val">${name}</text>${link ? "</a>" : ""}
    <text x="${x}" y="${y + 12}" text-anchor="${anchor}" class="mut">${val}${c.gid !== "rest" ? " · " + ROLES[c.role][0] : ""}</text>`;
}

// ---------- 2. «бабочка» контрагентов ----------
function butterfly(list) {
  if (!list.length) return '<div class="note">Контрагентов в выгрузке нет</div>';
  const W = 660, row = 26, H = list.length * row + 6, mid = W / 2, lw = 104, span = mid - lw / 2 - 64;
  const mx = Math.max(...list.flatMap(c => [c.in, c.out]), 1);
  let svg = "";
  list.forEach((c, i) => {
    const y = i * row + 4, wi = span * c.in / mx, wo = span * c.out / mx;
    svg += `<g data-tip="${esc(`${c.gid}<br>${ROLES[c.role][0]}${c.seed ? " · seed" : ""}<br>получено ${money(c.in)} (${c.nin} оп.) · отправлено ${money(c.out)} (${c.nout} оп.)`)}">
      <rect x="0" y="${y - 2}" width="${W}" height="${row - 2}" fill="transparent"/>
      ${c.in ? `<rect x="${mid - lw / 2 - wi}" y="${y + 3}" width="${wi}" height="14" rx="3" fill="${IN}"/>
        <text x="${mid - lw / 2 - wi - 6}" y="${y + 14}" text-anchor="end" class="val">${money(c.in)}</text>` : ""}
      ${c.out ? `<rect x="${mid + lw / 2}" y="${y + 3}" width="${wo}" height="14" rx="3" fill="${OUT}"/>
        <text x="${mid + lw / 2 + wo + 6}" y="${y + 14}" class="val">${money(c.out)}</text>` : ""}
      <a href="dossier.html?gid=${c.gid}"><text x="${mid}" y="${y + 14}" text-anchor="middle" class="val">${short(c.gid)}</text></a>
      <rect x="${mid - lw / 2 + 2}" y="${y + 18}" width="${lw - 4}" height="2" fill="${ROLES[c.role][1]}" opacity=".8"/></g>`;
  });
  svg += `<line x1="${mid - lw / 2}" x2="${mid - lw / 2}" y1="0" y2="${H}" class="axis"/><line x1="${mid + lw / 2}" x2="${mid + lw / 2}" y1="0" y2="${H}" class="axis"/>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${svg}</svg><div class="note">Полоска под gid — цвет роли контрагента. Клик по gid открывает его досье.</div>`;
}

// ---------- 3. разложение приоритета ----------
function priorityBar(n, cfg) {
  if (!cfg) return '<div class="note">Конфигурация недоступна</div>';
  const w = cfg.priority.weights, mult = n.is_seed ? cfg.priority.seed_multiplier : 1;
  const parts = [["Роль × уверенность", w.role * n.c_role], ["Объём денег", w.money * n.c_money],
                 ["Охват seed", w.seed_exposure * n.c_seed], ["Центральность", w.centrality * n.c_central]];
  const tot = parts.reduce((a, p) => a + p[1], 0) || 1, W = 440;
  let x = 0, svg = "";
  parts.forEach(([t, v], i) => {
    const wd = W * v / 1.0;
    if (wd > 0.5) svg += `<rect x="${x}" y="0" width="${Math.max(wd - 2, 1)}" height="18" rx="3" fill="${PR_COLORS[i]}" data-tip="${t}: ${(v * mult).toFixed(3)}"/>`;
    x += wd;
  });
  svg += `<rect x="0" y="0" width="${W}" height="18" rx="3" fill="none" stroke="var(--line-2)"/>`;
  return `<svg viewBox="0 0 ${W} 20" width="100%">${svg}</svg>
    <div class="lg" style="margin-top:8px">${parts.map(([t, v], i) => `<span><i style="background:${PR_COLORS[i]}"></i>${t} <b class="mono">${(v * mult).toFixed(2)}</b></span>`).join("")}</div>
    <div class="note">Сумма вкладов ${(tot * mult).toFixed(2)} из 1,00 возможных${n.is_seed ? ` · ×${mult} для seed` : ""}; итог нормируется по всей сети → ${n.priority_score.toFixed(2)}</div>`;
}

// ---------- 4. полукольцо устойчивости ----------
function gauge(n) {
  const v = n.role_stability, col = v >= .9 ? IN : v >= .7 ? ACC : OUT, status = v >= .9 ? "устойчивая" : v >= .7 ? "умеренная" : "пограничная";
  const R = 62, cx = 80, cy = 74, a = Math.PI * (1 - v);
  const x = cx + R * Math.cos(a), y = cy - R * Math.sin(a);
  return `<div style="display:flex;align-items:center;gap:16px"><svg viewBox="0 0 160 86" width="170">
      <path d="M${cx - R},${cy} A${R},${R} 0 0 1 ${cx + R},${cy}" fill="none" stroke="var(--panel-3)" stroke-width="12" stroke-linecap="round"/>
      <path d="M${cx - R},${cy} A${R},${R} 0 0 1 ${x},${y}" fill="none" stroke="${col}" stroke-width="12" stroke-linecap="round"/>
      <text x="${cx}" y="${cy - 8}" text-anchor="middle" class="val" style="font-size:20px;font-weight:700">${pct(v)}</text></svg>
    <div><b style="color:${col}">${status}</b><div class="note">${n.alt_role ? `в остальных вариантах чаще всего — ${ROLES[n.alt_role][0]}` : "роль не меняется ни в одном варианте"}</div></div></div>`;
}

// ---------- 5. поступления / списания по дням ----------
function perDay(n) {
  const d = Array.from({ length: 31 }, (_, i) => ({ day: i + 1, i: 0, o: 0, ni: 0, no: 0 }));
  n.transactions.forEach(t => { const k = +t.date.slice(8, 10) - 1; if (t.dst === gid) { d[k].i += t.sum_kzt; d[k].ni++; } else { d[k].o += t.sum_kzt; d[k].no++; } });
  return d;
}
function daily(n) {
  const d = perDay(n), W = 760, H = 220, mid = H / 2, x0 = 58, bw = (W - x0) / 31;
  const mx = Math.max(...d.flatMap(x => [x.i, x.o]), 1), k = (mid - 14) / mx;
  let svg = `<line x1="${x0}" x2="${W}" y1="${mid}" y2="${mid}" class="axis"/>`;
  [mx, mx / 2].forEach(v => {
    svg += `<line x1="${x0}" x2="${W}" y1="${mid - v * k}" y2="${mid - v * k}" class="gl"/><line x1="${x0}" x2="${W}" y1="${mid + v * k}" y2="${mid + v * k}" class="gl"/>
      <text x="${x0 - 4}" y="${mid - v * k + 4}" text-anchor="end" class="mut">${money(v).replace(" ₸", "")}</text>`;
  });
  d.forEach((x, i) => {
    const bx = x0 + i * bw + 2, w = bw - 4;
    svg += `<g data-tip="${x.day} июля<br>поступления ${money(x.i)} (${x.ni} оп.)<br>списания ${money(x.o)} (${x.no} оп.)">
      <rect x="${bx - 1}" y="4" width="${w + 2}" height="${H - 20}" fill="transparent"/>
      ${x.i ? `<rect x="${bx}" y="${mid - x.i * k}" width="${w}" height="${x.i * k}" rx="2" fill="${IN}"/>` : ""}
      ${x.o ? `<rect x="${bx}" y="${mid}" width="${w}" height="${x.o * k}" rx="2" fill="${OUT}"/>` : ""}</g>`;
    if ((i + 1) % 5 === 1) svg += `<text x="${bx + w / 2}" y="${H - 2}" text-anchor="middle" class="mut">${i + 1}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${svg}</svg>`;
}

// ---------- 6. календарь ----------
function calendar(n) {
  const d = perDay(n), cell = 30, gap = 4, first = (new Date(2026, 6, 1).getDay() + 6) % 7;   // пн = 0
  const mx = Math.max(...d.map(x => x.ni + x.no), 1);
  const days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"];
  let svg = days.map((t, i) => `<text x="${i * (cell + gap) + cell / 2 + 26}" y="12" text-anchor="middle" class="mut">${t}</text>`).join("");
  d.forEach((x, i) => {
    const pos = first + i, col = pos % 7, row = Math.floor(pos / 7), cnt = x.ni + x.no;
    const op = cnt ? 0.25 + 0.75 * cnt / mx : 0;
    svg += `<g data-tip="${x.day} июля: ${cnt} операций<br>поступления ${money(x.i)} · списания ${money(x.o)}">
      <rect x="${col * (cell + gap) + 26}" y="${row * (cell + gap) + 20}" width="${cell}" height="${cell}" rx="4" fill="${cnt ? ACC : "var(--panel-3)"}" fill-opacity="${cnt ? op : 1}"/>
      <text x="${col * (cell + gap) + 26 + cell / 2}" y="${row * (cell + gap) + 20 + cell / 2 + 4}" text-anchor="middle" class="mut" style="fill:${op > .6 ? "#111" : "var(--muted)"}">${x.day}</text></g>`;
  });
  const rows = Math.ceil((first + 31) / 7);
  const active = d.filter(x => x.ni + x.no).length;
  return `<svg viewBox="0 0 ${7 * (cell + gap) + 30} ${rows * (cell + gap) + 24}" width="100%" style="max-width:300px">${svg}</svg>
    <div class="note">Активных дней: <b class="mono" style="color:var(--ink)">${active}</b> из 31 · максимум ${mx} операций в день</div>`;
}

// ---------- 7. сальдо ----------
function cumulative(n) {
  const d = perDay(n), W = 560, H = 190, x0 = 44, y0 = 12;
  let acc = 0; const pts = d.map(x => (acc += x.i - x.o));
  const mn = Math.min(0, ...pts), mx = Math.max(0, ...pts), rng = mx - mn || 1;
  const X = i => x0 + i * (W - x0 - 8) / 30, Y = v => y0 + (H - 34) * (mx - v) / rng;
  const line = pts.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  let svg = `<line x1="${x0}" x2="${W}" y1="${Y(0)}" y2="${Y(0)}" class="axis"/>
    <text x="${x0 - 4}" y="${Y(mx) + 4}" text-anchor="end" class="mut">${money(mx).replace(" ₸", "")}</text>
    <text x="${x0 - 4}" y="${Y(mn) + 4}" text-anchor="end" class="mut">${mn < 0 ? "−" + money(-mn).replace(" ₸", "") : "0"}</text>
    <path d="${line} L${X(30)},${Y(0)} L${X(0)},${Y(0)} Z" fill="${ACC}" opacity=".08"/>
    <path d="${line}" fill="none" stroke="${ACC}" stroke-width="2"/>`;
  pts.forEach((v, i) => {
    svg += `<g data-tip="${i + 1} июля: сальдо ${v < 0 ? "−" : ""}${money(Math.abs(v))}"><rect x="${X(i) - 8}" y="0" width="16" height="${H - 20}" fill="transparent"/>
      ${i === 30 || i % 5 === 0 ? `<circle cx="${X(i)}" cy="${Y(v)}" r="3" fill="${ACC}" stroke="var(--panel)" stroke-width="2"/>` : ""}</g>`;
    if (i % 5 === 0) svg += `<text x="${X(i)}" y="${H - 4}" text-anchor="middle" class="mut">${i + 1}</text>`;
  });
  const last = pts[30];
  svg += `<text x="${X(30)}" y="${Y(last) - 8}" text-anchor="end" class="val">${last < 0 ? "−" : ""}${money(Math.abs(last))}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${svg}</svg>`;
}

// ---------- 8. гистограмма сумм ----------
function histogram(n) {
  const edges = [5e3, 1e4, 2.5e4, 5e4, 1e5, 2.5e5, 5e5, 1e6, Infinity];
  const names = ["5–10 тыс", "10–25 тыс", "25–50 тыс", "50–100 тыс", "100–250 тыс", "250–500 тыс", "0,5–1 млн", "> 1 млн"];
  const bi = names.map(() => ({ i: 0, o: 0 }));
  n.transactions.forEach(t => { const k = edges.findIndex((e, j) => t.sum_kzt >= e && t.sum_kzt < edges[j + 1]); if (k >= 0) bi[k][t.dst === gid ? "i" : "o"]++; });
  const W = 560, H = 190, x0 = 28, gw = (W - x0) / names.length, mx = Math.max(...bi.flatMap(b => [b.i, b.o]), 1), k = (H - 40) / mx;
  let svg = `<line x1="${x0}" x2="${W}" y1="${H - 26}" y2="${H - 26}" class="axis"/>`;
  bi.forEach((b, i) => {
    const gx = x0 + i * gw, w = (gw - 12) / 2;
    svg += `<g data-tip="${names[i]} ₸<br>поступлений: ${b.i} · списаний: ${b.o}"><rect x="${gx}" y="0" width="${gw}" height="${H - 20}" fill="transparent"/>
      ${b.i ? `<rect x="${gx + 4}" y="${H - 26 - b.i * k}" width="${w}" height="${b.i * k}" rx="2" fill="${IN}"/><text x="${gx + 4 + w / 2}" y="${H - 30 - b.i * k}" text-anchor="middle" class="val">${b.i}</text>` : ""}
      ${b.o ? `<rect x="${gx + 6 + w}" y="${H - 26 - b.o * k}" width="${w}" height="${b.o * k}" rx="2" fill="${OUT}"/><text x="${gx + 6 + w + w / 2}" y="${H - 30 - b.o * k}" text-anchor="middle" class="val">${b.o}</text>` : ""}</g>
      <text x="${gx + gw / 2}" y="${H - 8}" text-anchor="middle" class="mut">${names[i]}</text>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">${svg}</svg>`;
}

// ---------- 9. признаки ----------
function signals(n, routes, split, cyc) {
  const s = [
    ["Сборщик 2-го уровня", n.second_level, n.second_level ? `${n.hub_payers} хабов` : `${n.hub_payers} хабов`, "платят ≥6 узлов-хабов, деньги ≥5 seed"],
    ["Сквозной транзит", n.fast_share >= .5, pct(n.fast_share), "доля поступлений, ушедших дальше за ≤2 дня"],
    ["Всплеск активности", !!n.burst, n.burst_day ? `${Math.round(n.burst_share * 100)}% за день` : "нет", n.burst ? `пиковый день ${n.burst_day}: ≥60% оборота месяца` : "оборот распределён по дням"],
    ["Синхронные поступления", n.max_payers_same_day >= 3, `${n.max_payers_same_day} плательщ.`, "максимум разных плательщиков в один день"],
    ["Дробление сумм", n.split_out + n.split_in > 0, `${n.split_out + n.split_in} эпиз.`, "≥3 перевода одному получателю в день"],
    ["Возвратные потоки", n.cycles > 0, `${n.cycles} цепоч.`, "деньги возвращаются к отправителю (≤4 шага)"],
    ["Маршруты A→B→C", routes.routes.length > 0, `${routes.routes.length} маршр.`, "устойчивые цепочки, ≥3 повтора"],
    ["Аномалия для колена", !!n.anomaly, n.anomaly ? `z = ${(+n.anomaly_score).toFixed(1)}` : "нет", n.anomaly ? esc(n.anomaly_text) : "суммы в пределах нормы колена"],
    ["Неполные данные", n.is_seed || n.truncated || (n.in_sum > 0 && n.out_sum > n.in_sum * 1.2), n.truncated ? "4-е колено" : n.is_seed ? "seed" : n.out_sum > n.in_sum * 1.2 ? "вход < выход" : "нет",
      "есть ограничения выгрузки — учесть при выводах"],
  ];
  return `<div class="signals">${s.map(([t, on, v, d]) => `<div class="sig ${on ? "on" : ""}" data-tip="${esc(d)}">
      <div class="h">${t}<em>${on ? "ДА" : "НЕТ"}</em></div><b>${v}</b><small>${d}</small></div>`).join("")}</div>`;
}

// ---------- 10. рекомендации ----------
function recs(n, gaps, cps) {
  const out = gaps.filter(g => g.gid === gid).map(g => `Запросить ${esc(g.request)}: ${esc(g.reason)}.`);
  if (n.role !== "peripheral") out.push("Проверить назначение платежей и документы-основания крупнейших операций.");
  const payers = cps.filter(c => c.in).slice(0, 3), recv = cps.filter(c => c.out).slice(0, 3);
  if (payers.length) out.push(`Проверить крупнейших плательщиков: ${payers.map(c => `<a href="dossier.html?gid=${c.gid}" class="mono">${short(c.gid)}</a>`).join(", ")}.`);
  if (recv.length) out.push(`Проверить крупнейших получателей: ${recv.map(c => `<a href="dossier.html?gid=${c.gid}" class="mono">${short(c.gid)}</a>`).join(", ")}.`);
  if (n.role_stability < .7) out.push("Роль пограничная — подтвердить дополнительными данными перед включением в запрос.");
  if (n.split_out + n.split_in) out.push("Сопоставить эпизоды дробления с лимитами и порогами обязательного контроля.");
  return out;
}

gid ? main().catch(e => { $("#root").innerHTML = `<div class="note">Ошибка: ${esc(e.message)}</div>`; }) : ($("#root").innerHTML = '<div class="note">Не указан gid</div>');
