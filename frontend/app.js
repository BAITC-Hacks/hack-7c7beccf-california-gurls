// Tamyr — фронтенд. gid везде СТРОКИ (значения ~1e17 не помещаются в Number).
// Цвета ролей проверены валидатором палитры на тёмном фоне (яркость, различимость при дальтонизме, контраст).
const ROLES = {
  coordinator:  { ru: "координатор",         color: "#e66767" },
  distributor:  { ru: "распределитель",      color: "#9085e9" },
  consolidator: { ru: "консолидатор",        color: "#d95926" },
  transit:      { ru: "транзит",             color: "#3987e5" },
  terminal:     { ru: "конечный получатель", color: "#199e70" },
  boundary:     { ru: "граница выгрузки",    color: "#6B7280" },
  peripheral:   { ru: "периферия",           color: "#3F4652" },
};
// 8 крупнейших кластеров — фиксированные цвета, остальные — нейтральный «прочие» (цвета не зацикливаем)
const PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const clusterColor = c => c >= 1 && c <= 8 ? PALETTE[c - 1] : "#4A5260";

const $ = s => document.querySelector(s);
const api = async (p, opt) => { const r = await fetch("/api/" + p, opt); if (!r.ok) throw new Error((await r.json()).detail || r.status); return r.json(); };
const money = x => x >= 1e6 ? (x / 1e6).toFixed(1).replace(".", ",") + " млн ₸" : x >= 1e3 ? Math.round(x / 1e3) + " тыс ₸" : Math.round(x) + " ₸";
const short = g => "…" + g.slice(-9, -3);
const pill = (text, c) => `<span class="badge" style="color:${c};background:${c}1f;box-shadow:inset 0 0 0 1px ${c}55">${text}</span>`;
const badge = role => pill(ROLES[role].ru, role === "peripheral" ? "#9AA3AF" : ROLES[role].color);
const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

let cy, FULL, CFG = null, MARKS = new Map(), TOP = [], state = { mode: "full", color: "role", hops: 1, selected: null, status: "all" };
const MARK = { confirmed: { ic: "OK", ru: "подтверждено" }, review: { ic: "ПРВ", ru: "на проверке" }, rejected: { ic: "ОТК", ru: "отклонено" } };
const ROLE_RU_ALT = r => ROLES[r] ? ROLES[r].ru : r;

// ---------- граф ----------
function nodeData(n) {
  return { id: n.gid, role: n.role, cluster: n.cluster_id, prio: n.priority_score, seed: n.is_seed,
           label: short(n.gid), size: 6 + 34 * Math.pow(n.priority_score, 2.2) };
}
function edgeData(e) {
  return { id: e.src + ">" + e.dst, source: e.src, target: e.dst, sum: e.sum_kzt,
           w: 0.4 + Math.min(6, Math.log10(Math.max(e.sum_kzt, 1e4)) - 3.5) };
}
function style() {
  const col = state.color === "role" ? ele => ROLES[ele.data("role")].color : ele => clusterColor(ele.data("cluster"));
  return [
    { selector: "node", style: { "background-color": col, width: "data(size)", height: "data(size)", "border-width": 0 } },
    { selector: "node[?seed]", style: { "border-width": 2, "border-color": "#EAECEF" } },
    { selector: "node[role='boundary']", style: { "border-width": 1, "border-style": "dashed", "border-color": "#848E9C" } },
    { selector: "edge", style: { width: "data(w)", "line-color": "#2B3139", "curve-style": "haystack", opacity: 0.7 } },
    { selector: ".ego edge, edge.ego", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": "#5E6673",
        "line-color": "#434A55", opacity: 0.95, "arrow-scale": 0.9 } },
    { selector: "node.labeled, .ego node", style: { label: "data(label)", "font-size": 9, color: "#B7BDC6",
        "text-valign": "bottom", "text-margin-y": 3, "font-family": "JetBrains Mono, SF Mono, Menlo, monospace" } },
    { selector: ".faded", style: { opacity: 0.07 } },
    { selector: "edge.hl", style: { opacity: 1, "line-color": "#F0B429", "target-arrow-color": "#F0B429", "curve-style": "bezier", "target-arrow-shape": "triangle", "z-index": 9 } },
    { selector: "node.hl", style: { opacity: 1, label: "data(label)", "font-size": 9, color: "#EAECEF", "z-index": 9 } },
    { selector: "node:selected, node.focus", style: { "border-width": 3, "border-color": "#F0B429", "z-index": 10 } },
    { selector: "node.changed", style: { "border-width": 3, "border-color": "#F0B429", "border-style": "solid" } },
  ];
}

async function initGraph() {
  FULL = await api("graph");
  cy = cytoscape({ container: $("#cy"), style: style(), minZoom: 0.05, maxZoom: 4, wheelSensitivity: 0.25,
    hideEdgesOnViewport: true, textureOnViewport: true, pixelRatio: 1 });
  drawFull();
  cy.on("tap", "node", e => select(e.target.id()));
  cy.on("tap", e => { if (e.target === cy) clearHL(); });
  const tip = $("#tip");
  cy.on("mouseover", "node", e => {
    const d = e.target.data();
    tip.innerHTML = `<span class="num">${d.id}</span><br>${ROLES[d.role].ru}${d.seed ? " · seed" : ""} · приоритет <b class="num">${d.prio.toFixed(2)}</b>`;
    tip.classList.remove("hidden");
  });
  cy.on("mousemove", e => { const o = e.originalEvent; if (o) { tip.style.left = o.clientX + 14 + "px"; tip.style.top = o.clientY + 12 + "px"; } });
  cy.on("mouseout", "node", () => tip.classList.add("hidden"));
}

function drawFull() {
  state.mode = "full"; setSeg("#mode", "full");
  cy.elements().remove();
  cy.add(FULL.nodes.map(n => ({ group: "nodes", data: nodeData(n), position: { x: n.x, y: n.y } })));
  cy.add(FULL.edges.map(e => ({ group: "edges", data: edgeData(e) })));
  cy.nodes().filter(n => n.data("prio") > 0.85).addClass("labeled");
  cy.layout({ name: "preset", fit: true, padding: 20 }).run();
  $("#graph-hint").textContent = `${FULL.nodes.length} узлов · ${FULL.edges.length} связей · размер = приоритет, рамка = seed`;
  if (state.selected) highlight(state.selected, false);
  if (LAB_ROLES) paintLab();
}

async function drawEgo(gid) {
  state.mode = "ego"; setSeg("#mode", "ego");
  if (state.hops === 2) return drawChain(gid);
  const sub = await api(`ego/${gid}?hops=1`);
  cy.elements().remove();
  cy.add(sub.nodes.map(n => ({ group: "nodes", data: nodeData(n) })));
  cy.add(sub.edges.map(e => ({ group: "edges", data: edgeData(e), classes: "ego" })));
  cy.nodes().addClass("labeled");
  cy.$id(gid).addClass("focus");
  flowLayout(gid);
  $("#graph-hint").textContent = `Окрестность ${short(gid)}: ${sub.nodes.length} узлов · стрелки = направление денег`;
}

// «Цепочка денег» на 2 шага: плательщики 2-го и 1-го уровня → узел → получатели 1-го и 2-го уровня.
// Берём только направленные пути (откуда пришли деньги и куда ушли), в каждой колонке — топ по приоритету.
async function drawChain(gid, perCol = 25) {
  const [up, down] = await Promise.all([api(`ego/${gid}?hops=2&direction=in`), api(`ego/${gid}?hops=2&direction=out`)]);
  const nodes = new Map([...up.nodes, ...down.nodes].map(n => [n.gid, n]));
  const edges = new Map([...up.edges, ...down.edges].map(e => [e.src + ">" + e.dst, e]));
  // уровни: BFS против направления (плательщики) и по направлению (получатели)
  const level = new Map([[gid, 0]]);
  const bfs = (sign, key, next) => {
    let frontier = [gid];
    for (let d = 1; d <= 2; d++) {
      const nxt = [];
      for (const e of edges.values()) if (frontier.includes(e[key]) && !level.has(e[next])) { level.set(e[next], sign * d); nxt.push(e[next]); }
      frontier = nxt;
    }
  };
  bfs(-1, "dst", "src"); bfs(1, "src", "dst");
  const cols = new Map();
  for (const [id, lv] of level) if (nodes.has(id)) (cols.get(lv) || cols.set(lv, []).get(lv)).push(nodes.get(id));
  let hidden = 0;
  const shown = new Set();
  for (const [lv, list] of cols) {
    list.sort((a, b) => b.priority_score - a.priority_score);
    hidden += Math.max(0, list.length - perCol);
    list.slice(0, perCol).forEach(n => shown.add(n.gid));
  }
  cy.elements().remove();
  cy.add([...shown].map(id => ({ group: "nodes", data: nodeData(nodes.get(id)) })));
  cy.add([...edges.values()].filter(e => shown.has(e.src) && shown.has(e.dst))
          .map(e => ({ group: "edges", data: edgeData(e), classes: "ego" })));
  cy.nodes().addClass("labeled");
  cy.$id(gid).addClass("focus");
  for (const [lv, list] of cols) {
    const vis = list.filter(n => shown.has(n.gid));
    vis.forEach((n, i) => cy.$id(n.gid).position({ x: lv * 340, y: (i - (vis.length - 1) / 2) * 32 }));
  }
  cy.fit(cy.elements(), 40);
  const cnt = lv => (cols.get(lv) || []).length;
  $("#graph-hint").textContent = `Цепочка денег ${short(gid)} · плательщики: 2-й ур. ${cnt(-2)}, 1-й ур. ${cnt(-1)} · получатели: 1-й ур. ${cnt(1)}, 2-й ур. ${cnt(2)}`
    + (hidden ? ` · показаны топ-${perCol} в колонке, скрыто ${hidden}` : "");
}

// «Схема потока»: плательщики слева → узел → получатели справа; двусторонние связи сверху
function flowLayout(gid) {
  const c = cy.$id(gid);
  const ins = new Set(c.incomers("node").map(n => n.id())), outs = new Set(c.outgoers("node").map(n => n.id()));
  const both = [...ins].filter(x => outs.has(x));
  const left = [...ins].filter(x => !outs.has(x)), right = [...outs].filter(x => !ins.has(x));
  const bySum = (ids, dir) => ids.sort((a, b) => {
    const s = id => (dir === "in" ? cy.$id(id + ">" + gid) : cy.$id(gid + ">" + id)).data("sum") || 0;
    return s(b) - s(a);
  });
  const column = (ids, x0, sign) => {
    const perCol = 22, gap = 34;
    ids.forEach((id, i) => {
      const col = Math.floor(i / perCol), row = i % perCol, n = Math.min(perCol, ids.length - col * perCol);
      cy.$id(id).position({ x: x0 + sign * col * 160, y: (row - (n - 1) / 2) * gap });
    });
  };
  c.position({ x: 0, y: 0 });
  column(bySum(left, "in"), -380, -1);
  column(bySum(right, "out"), 380, 1);
  both.forEach((id, i) => cy.$id(id).position({ x: (i - (both.length - 1) / 2) * 90, y: -420 }));
  cy.fit(cy.elements(), 40);
}

function highlight(gid, center = true) {
  const n = cy.$id(gid);
  if (!n.length) return;
  cy.elements().removeClass("hl faded focus");
  const hood = n.closedNeighborhood();
  cy.elements().not(hood).addClass("faded");
  hood.addClass("hl"); n.addClass("focus");
  if (center) cy.animate({ center: { eles: n }, zoom: Math.max(cy.zoom(), 1.2) }, { duration: 400 });
}
function clearHL() { cy.elements().removeClass("hl faded focus"); }

async function select(gid) {
  state.selected = gid;
  if (state.mode === "flows") { $("#sankey").classList.add("hidden"); drawFull(); }
  document.querySelectorAll(".item").forEach(el => el.classList.toggle("sel", el.dataset.gid === gid));
  if (state.mode === "ego") await drawEgo(gid); else highlight(gid);
  renderCard(gid);
}

// ---------- карточка узла ----------
async function renderCard(gid) {
  const n = await api("node/" + gid);
  const caveats = [];
  if (n.is_seed) caveats.push("seed: входящие переводы в выгрузке занижены");
  if (n.truncated) caveats.push("4-е колено: исходящие переводы не выгружались");
  else if (n.out_sum > n.in_sum * 1.2 && n.in_sum > 0) caveats.push("отдаёт больше, чем видно на входе — есть источники вне выборки");
  const incomplete = n.is_seed || (n.in_sum > 0 && n.out_sum > n.in_sum * 1.2);
  const pr = n.pass_ratio == null ? "—" : incomplete ? "н/д · вход неполон" : Math.round(n.pass_ratio * 100) + "%";
  const flows = (list, dir) => list.slice(0, 12).map(f => `
    <div class="flow" data-gid="${f.gid}"><span class="dir ${dir === "←" ? "in" : "out"}">${dir}</span>${badge(f.role)}<span class="gid">${short(f.gid)}</span>
    ${f.is_seed ? '<span class="badge seed">seed</span>' : ""}<span class="amt">${money(f.sum_kzt)}${f.n_tx > 1 ? " ×" + f.n_tx : ""}</span></div>`).join("")
    + (list.length > 12 ? `<small style="color:var(--muted)">… ещё ${list.length - 12}</small>` : "");
  // дневная активность: вход (зелёный) / выход (красный)
  const days = Array.from({ length: 31 }, () => ({ i: 0, o: 0 }));
  n.transactions.forEach(t => { const d = +t.date.slice(8, 10) - 1; if (t.dst === gid) days[d].i += t.sum_kzt; else days[d].o += t.sum_kzt; });
  const mx = Math.max(1, ...days.map(d => Math.max(d.i, d.o)));
  const bars = days.map(d => `<div style="height:${100 * d.i / mx}%;background:#1b998b" title="вход ${money(d.i)}"></div><div style="height:${100 * d.o / mx}%;background:#d7263d" title="выход ${money(d.o)}"></div>`).join("");

  $("#card").innerHTML = `<div class="card">
    <h2>${gid}</h2>
    <div class="tags">${badge(n.role)} ${n.is_seed ? '<span class="badge seed">seed</span>' : ""}
      ${pill("кластер " + n.cluster_id, "#9AA3AF")} ${pill("колено " + n.depth, "#9AA3AF")}
      ${n.second_level ? pill("сборщик 2-го уровня", "#F0B429") : ""}
      ${n.cycles ? pill("циклов " + n.cycles, "#E8A13A") : ""}
      ${n.split_out + n.split_in ? pill("дробление " + (n.split_out + n.split_in), "#E8A13A") : ""}
      ${n.anomaly ? pill("аномалия для колена", "#FF9F6B") : ""}
      ${n.routes_mid ? pill("маршрутов A→B→C " + n.routes_mid, "#9AA3AF") : ""}
      ${n.burst ? pill("всплеск активности", "#E8A13A") : ""}</div>
    <div class="evidence">${esc(n.evidence)}</div>
    ${caveats.map(c => `<div class="caveat">! ${c}</div>`).join("")}
    <div class="stab">Устойчивость роли: <b style="color:${n.role_stability >= .9 ? "var(--in)" : n.role_stability >= .7 ? "var(--warn)" : "var(--out)"}">${Math.round(n.role_stability * 100)}%</b>
      вариантов порогов ±20%${n.alt_role ? ` · иначе — ${ROLE_RU_ALT(n.alt_role)}` : ""}</div>
    ${n.anomaly ? `<div class="caveat anom">Аномалия: ${esc(n.anomaly_text)}</div>` : ""}
    <h3 style="margin-top:4px">Из чего сложился приоритет ${n.priority_score.toFixed(2)}</h3>
    <div class="decomp" id="decomp"></div>
    <div class="metrics">
      <div><small>Приоритет</small><b>${n.priority_score.toFixed(2)}</b></div>
      <div><small>Уверенность в роли</small><b>${n.role_score.toFixed(2)}</b></div>
      <div><small>Вход: плательщиков / сумма</small><b>${n.in_deg} / ${money(n.in_sum)}</b></div>
      <div><small>Выход: получателей / сумма</small><b>${n.out_deg} / ${money(n.out_sum)}</b></div>
      <div><small>Коэф. пропуска</small><b>${pr}</b></div>
      <div><small>Ушло дальше за ≤2 дня</small><b>${Math.round(n.fast_share * 100)}%</b></div>
      <div><small>Seed выше по цепочке</small><b>${n.seed_reach}</b></div>
      <div><small>Макс. плательщиков в день</small><b>${n.max_payers_same_day}</b></div>
      <div><small>Платят узлы-хабы</small><b>${n.hub_payers}</b></div>
      <div><small>Возвратные цепочки / встречные</small><b>${n.cycles} / ${n.reciprocal}</b></div>
      <div><small>Эпизоды дробления (отпр. / получ.)</small><b>${n.split_out} / ${n.split_in}</b></div>
      <div><small>Доля переводов 5–10 тыс ₸</small><b>${Math.round(n.near_threshold_share * 100)}%</b></div>
      <div><small>Пиковый день · доля оборота</small><b>${n.burst_day ? n.burst_day.slice(8) + ".07 · " + Math.round(n.burst_share * 100) + "%" : "—"}</b></div>
      <div><small>Активных дней</small><b>${n.active_days}</b></div>
    </div>
    <div class="actions">
      <button class="btn" id="btn-ego">Окрестность</button>
      <button class="btn ghost" id="btn-ai">AI-справка</button>
      <button class="btn ghost" id="btn-pdf">Справка PDF</button>
      <button class="btn accent" id="btn-dossier">Досье</button>
    </div>
    <div class="markbox" id="markbox"></div>
    <div id="ai-card"></div>
    <h3>Активность по дням (июль) — вход / выход</h3><div class="bars">${bars}</div>
    <div id="cycles"></div>
    <div id="splits"></div>
    <div id="routes"></div>
    <h3>Входящие (${n.incoming.length})</h3><div class="flows">${flows(n.incoming, "←") || "<small>нет в выгрузке</small>"}</div>
    <h3>Исходящие (${n.outgoing.length})</h3><div class="flows">${flows(n.outgoing, "→") || "<small>нет в выгрузке</small>"}</div>
  </div>`;
  $("#card").querySelectorAll(".flow").forEach(el => el.onclick = () => select(el.dataset.gid));
  $("#btn-ego").onclick = () => { state.mode = "ego"; drawEgo(gid); };
  $("#btn-pdf").onclick = () => window.open("report.html?gid=" + gid, "_blank");
  $("#btn-dossier").onclick = () => window.open("dossier.html?gid=" + gid, "_blank");
  renderDecomp(n);
  renderMarkBox(gid, n.mark);
  {  // маршруты: узел может быть в начале, середине или конце цепочки
    const r = await api("routes?gid=" + gid + "&n=8");
    if (r.routes.length) {
      $("#routes").innerHTML = `<h3>Повторяющиеся маршруты A→B→C (${r.routes.length}${r.routes.length === 8 ? "+" : ""})</h3>` +
        r.routes.map(x => `<div class="cyc">${[x.a, x.b, x.c].map(g => g === gid ? "<b>●</b>" : `<a data-gid="${g}">${short(g)}</a>`).join(" → ")}
          · <b>${x.repeats} раз</b> <span style="color:var(--muted)">${x.first_day.slice(5)}…${x.last_day.slice(5)}, ${money(x.sum_ab)} → ${money(x.sum_bc)}</span></div>`).join("");
      bindLinks($("#routes"));
    }
  }
  if (n.split_out + n.split_in) {
    const sp = await api("splitting?gid=" + gid);
    $("#splits").innerHTML = `<h3>Дробление (${sp.n_episodes})</h3>` + sp.episodes.slice(0, 6).map(e =>
      `<div class="cyc">${e.day} · ${e.src === gid ? "→ " + `<a data-gid="${e.dst}">${short(e.dst)}</a>` : `<a data-gid="${e.src}">${short(e.src)}</a>` + " →"}
       <b>${e.n_tx} перев.</b> на ${money(e.sum_kzt)} <span style="color:var(--muted)">(${money(e.min_kzt)}–${money(e.max_kzt)})</span></div>`).join("");
    bindLinks($("#splits"));
  }
  if (n.cycles) {
    const c = await api("cycles/" + gid);
    $("#cycles").innerHTML = `<h3>Возвратные потоки (${c.n_cycles})</h3>` + c.cycles.slice(0, 5).map(x =>
      `<div class="cyc">${x.chain.map(g => g === gid ? "<b>●</b>" : `<a data-gid="${g}">${short(g)}</a>`).join(" → ")}
       <br><span style="color:var(--muted)">${x.sums_kzt.map(money).join(" → ")}</span></div>`).join("");
    bindLinks($("#cycles"));
  }
  $("#btn-ai").onclick = async () => {
    const b = $("#btn-ai"); b.disabled = true; $("#ai-card").innerHTML = '<div class="ai">Готовлю справку…</div>';
    try { const r = await api(`node/${gid}/card`, { method: "POST" }); $("#ai-card").innerHTML = `<div class="ai">${linkify(r.card)}</div>`; }
    catch (e) { $("#ai-card").innerHTML = `<div class="ai">Ошибка: ${esc(e.message)}</div>`; }
    b.disabled = false; bindLinks($("#ai-card"));
  };
}

// разложение priority_score на вклады компонент (веса — из config.yaml)
function renderDecomp(n) {
  if (!CFG) return;
  const w = CFG.priority.weights, rw = CFG.priority.role_weight[n.role];
  const mult = n.is_seed ? CFG.priority.seed_multiplier : 1;
  const parts = [
    ["Роль × уверенность", w.role * n.c_role, "#d7263d", `вес роли ${rw} × уверенность ${n.role_score.toFixed(2)}`],
    ["Объём денег", w.money * n.c_money, "#2f5bea", `оборот больше, чем у ${Math.round(n.c_money * 100)}% узлов`],
    ["Охват seed", w.seed_exposure * n.c_seed, "#8e44ad", `до узла доходят деньги ${n.seed_reach} seed`],
    ["Центральность", w.centrality * n.c_central, "#1b998b", `центральнее ${Math.round(n.c_central * 100)}% узлов`],
  ];
  const max = w.role + w.money + w.seed_exposure + w.centrality;
  $("#decomp").innerHTML = parts.map(([t, v, c, tip]) => `<div class="r" title="${tip}"><span>${t}</span>
      <div class="t"><i style="width:${100 * v / Math.max(w.role, w.money, w.seed_exposure, w.centrality)}%;background:${c}"></i></div>
      <span class="v">${(v * mult).toFixed(2)}</span></div>`).join("")
    + (n.is_seed ? `<small style="color:var(--muted)">× ${mult} — seed уже известен, приоритет понижен</small>` : "")
    + `<small style="color:var(--muted)">сумма вкладов нормируется в 0–1 по всей сети</small>`;
}

// отметки аналитика: подтвердить / на проверке / отклонить + комментарий
function renderMarkBox(gid, mark) {
  const st = mark ? mark.status : null;
  $("#markbox").innerHTML = `<div class="row"><span class="lbl">Решение аналитика</span>
      ${Object.entries(MARK).map(([k, v]) => `<button data-s="${k}" class="${k} ${st === k ? "on" : ""}">${v.ru}</button>`).join("")}
      ${st ? '<button data-s="clear">снять</button>' : ""}</div>
    <input id="mark-comment" placeholder="комментарий (основание решения)" value="${esc(mark?.comment || "")}">
    ${mark ? `<small style="color:var(--muted)">обновлено ${mark.updated_at.slice(0, 16)}</small>` : ""}`;
  $("#markbox").querySelectorAll("button").forEach(b => b.onclick = async () => {
    const r = await api("marks/" + gid, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: b.dataset.s, comment: $("#mark-comment").value }) });
    await loadMarks();                 // перечитываем с ролью и приоритетом для вкладок статусов
    renderMarkBox(gid, r.mark); renderTop();
  });
}

async function loadMarks() { MARKS = new Map((await api("marks")).map(m => [m.gid, m])); }

// ---------- левые панели ----------
async function renderTop() {
  if (!TOP.length) TOP = await api("top?n=50");
  const hide = $("#hide-seed").checked, st = state.status;
  const cnt = k => [...MARKS.values()].filter(m => m.status === k).length;
  const counts = { all: TOP.length, none: TOP.filter(t => !MARKS.has(t.gid)).length,
                   review: cnt("review"), confirmed: cnt("confirmed"), rejected: cnt("rejected") };
  document.querySelectorAll("#status-tabs button").forEach(b => {
    b.classList.toggle("active", b.dataset.st === st); b.querySelector("span").textContent = counts[b.dataset.st];
  });
  $("#marks-summary").textContent = st === "all" || st === "none" ? `топ-${TOP.length} по приоритету` : "все клиенты с этим статусом";
  const rankOf = new Map(TOP.map(t => [t.gid, t.rank]));
  let rows;
  if (st === "all" || st === "none") {
    rows = TOP.filter(t => st === "all" || !MARKS.has(t.gid)).map(t => ({ ...t, text: t.why }));
  } else {   // статусные вкладки показывают всех отмеченных клиентов, даже вне топ-50
    rows = [...MARKS.values()].filter(m => m.status === st)
      .map(m => ({ gid: m.gid, role: m.role || "peripheral", priority_score: m.priority_score ?? 0, rank: rankOf.get(m.gid) || "—",
                   is_seed: false, text: (m.comment ? "Комментарий: " + m.comment : "Без комментария") + " · " + (m.updated_at || "").slice(0, 16) }))
      .sort((a, b) => b.priority_score - a.priority_score);
  }
  rows = rows.filter(t => !(hide && t.is_seed));
  $("#top-list").innerHTML = rows.length ? rows.map(t => `
    <li class="item" data-gid="${t.gid}"><div class="row"><span class="rank">${t.rank}</span>${badge(t.role)}
      <span class="gid">${short(t.gid)}</span>${t.is_seed ? '<span class="badge seed">seed</span>' : ""}
      ${MARKS.has(t.gid) ? `<span class="mk ${MARKS.get(t.gid).status}" title="${MARK[MARKS.get(t.gid).status].ru}">${MARK[MARKS.get(t.gid).status].ic}</span>` : ""}
      <span class="pbar"><i style="width:${t.priority_score * 100}%"></i></span><span class="score">${(+t.priority_score).toFixed(2)}</span></div>
      <div class="why">${esc(t.text)}</div></li>`).join("")
    : `<li class="empty-list">${st === "none" ? "Все клиенты из топ-листа уже проверены" : "Пока нет клиентов с этим статусом. Отметьте клиента в его карточке."}</li>`;
  $("#top-list").querySelectorAll(".item").forEach(el => el.onclick = () => select(el.dataset.gid));
  document.querySelectorAll(".item").forEach(el => el.classList.toggle("sel", el.dataset.gid === state.selected));
}
document.querySelectorAll("#status-tabs button").forEach(b => b.onclick = () => { state.status = b.dataset.st; renderTop(); });

async function renderGaps() {
  const g = await api("next_requests?n=40");
  $("#gaps-list").innerHTML = g.map(r => `
    <div class="item" data-gid="${r.gid}"><div class="row"><span class="req">${esc(r.request)}</span>
      <span class="score">${r.score.toFixed(2)}</span></div>
      <div class="row"><span class="gid">${short(r.gid)}</span><span style="color:var(--muted)">кластер ${r.cluster_id}</span></div>
      <div class="why">${esc(r.reason)}</div></div>`).join("");
  $("#gaps-list").querySelectorAll(".item").forEach(el => el.onclick = () => select(el.dataset.gid));
}

async function renderClusters() {
  const cl = await api("clusters");
  $("#cluster-list").innerHTML = cl.map(c => `
    <div class="item" data-c="${c.cluster_id}"><div class="row">
      ${pill("#" + c.cluster_id, c.cluster_id >= 1 && c.cluster_id <= 8 ? clusterColor(c.cluster_id) : "#9AA3AF")}
      <span>${c.n_nodes} узл. · ${c.n_seed} seed</span><span class="score">${money(c.sum_kzt_internal)}</span></div>
      <div class="why">${esc(c.hypothesis)}</div></div>`).join("");
  $("#cluster-list").querySelectorAll(".item").forEach(el => el.onclick = () => focusCluster(+el.dataset.c));
}

function focusCluster(c) {
  if (state.mode !== "full") drawFull();
  state.color = "cluster"; setSeg("#color-by", "cluster"); cy.style(style());
  const nodes = cy.nodes().filter(n => n.data("cluster") === c);
  cy.elements().removeClass("hl faded focus");
  cy.elements().not(nodes.union(nodes.edgesWith(nodes))).addClass("faded");
  cy.animate({ fit: { eles: nodes, padding: 60 } }, { duration: 400 });
}

// ---------- ассистент ----------
const history = [];
function linkify(text) {
  return esc(text).replace(/\b(1\d{17})\b/g, '<a data-gid="$1">$1</a>');
}
function bindLinks(root) { root.querySelectorAll("a[data-gid]").forEach(a => a.onclick = () => select(a.dataset.gid)); }

$("#chat-form").onsubmit = async e => {
  e.preventDefault();
  const q = $("#chat-input").value.trim(); if (!q) return;
  $("#chat-input").value = "";
  const log = $("#chat-log");
  log.insertAdjacentHTML("beforeend", `<div class="msg user">${esc(q)}</div>`);
  const pending = document.createElement("div"); pending.className = "msg bot"; pending.textContent = "Анализирую граф…"; log.append(pending);
  log.scrollTop = log.scrollHeight;
  history.push({ role: "user", content: q });
  try {
    const r = await api("assistant", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ messages: history }) });
    history.push({ role: "assistant", content: r.answer });
    pending.innerHTML = linkify(r.answer) + (r.trace.length ? `<div class="trace">инструменты: ${r.trace.map(t => t.tool).join(" → ")}</div>` : "");
    bindLinks(pending);
  } catch (err) { pending.textContent = "Ошибка: " + err.message; history.pop(); }
  log.scrollTop = log.scrollHeight;
};

// ---------- поиск ----------
let st;
$("#search").oninput = e => {
  clearTimeout(st);
  const q = e.target.value.replace(/\D/g, "");
  if (q.length < 3) return $("#search-results").classList.add("hidden");
  st = setTimeout(async () => {
    const res = await api("search?q=" + q);
    const box = $("#search-results");
    box.innerHTML = res.length ? res.map(r => `<div data-gid="${r.gid}"><span class="gid">${r.gid}</span>${badge(r.role)}</div>`).join("")
                               : "<div>ничего не найдено</div>";
    box.classList.remove("hidden");
    box.querySelectorAll("[data-gid]").forEach(el => el.onclick = () => { box.classList.add("hidden"); $("#search").value = el.dataset.gid; select(el.dataset.gid); });
  }, 200);
};
$("#search").onkeydown = e => { if (e.key === "Enter") { const f = $("#search-results [data-gid]"); if (f) f.click(); } };

// ---------- прочее ----------
document.addEventListener("keydown", e => { if (e.key === "/" && document.activeElement.tagName !== "INPUT") { e.preventDefault(); $("#search").focus(); } });
function setSeg(sel, val) { document.querySelectorAll(sel + " button").forEach(b => b.classList.toggle("active", Object.values(b.dataset)[0] === val)); }
document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tabs button, .tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); $("#tab-" + b.dataset.tab).classList.add("active");
});
document.querySelectorAll("#mode button").forEach(b => b.onclick = () => {
  if (b.dataset.mode !== "flows") $("#sankey").classList.add("hidden");
  if (b.dataset.mode === "flows") return drawSankey();
  if (b.dataset.mode === "full") drawFull();
  else if (state.selected) drawEgo(state.selected);
  else $("#graph-hint").textContent = "Сначала выберите узел";
});
document.querySelectorAll("#color-by button").forEach(b => b.onclick = () => { state.color = b.dataset.c; setSeg("#color-by", b.dataset.c); cy.style(style()); renderLegend(); });
document.querySelectorAll("#hops button").forEach(b => b.onclick = () => {
  state.hops = +b.dataset.h; setSeg("#hops", b.dataset.h);
  if (state.selected) drawEgo(state.selected);           // сразу показываем окрестность выбранного узла
  else $("#graph-hint").textContent = "Сначала выберите узел — затем покажу его окрестность";
});
$("#hide-seed").onchange = renderTop;


$("#btn-resilience").onclick = async () => {
  const r = await api("resilience?top_n=10");
  $("#resilience").innerHTML = `<div class="res">Если заблокировать топ-10 (без seed) — гипотетически:<br>
    компонент связности: <b>${r.before.components} → ${r.after.components}</b><br>
    крупнейшая компонента: <b>${r.before.largest_component} → ${r.after.largest_component}</b><br>
    узлов, достижимых от seed: <b>${r.before.nodes_reachable_from_seed} → ${r.after.nodes_reachable_from_seed}</b> (−${Math.round(r.reach_cut_share * 100)}%)<br>
    оборот в сети: −${Math.round(r.flow_cut_share * 100)}%<br>
    <span class="note">Число компонент включает 19 seed без переводов (16 связных + 19 изолированных = 35).</span></div>`;
};

function renderLegend() {
  $("#legend").innerHTML = state.color === "role"
    ? Object.entries(ROLES).map(([k, v]) => `<span><i style="background:${v.color}"></i>${v.ru}</span>`).join("") + '<span><i style="box-shadow:inset 0 0 0 2px #EAECEF"></i>seed</span>'
    : PALETTE.map((c, i) => `<span><i style="background:${c}"></i>кластер ${i + 1}</span>`).join("") + '<span><i style="background:#4A5260"></i>прочие</span>';
}

async function renderStats() {
  const s = await api("stats");
  const r = s.roles, t = (l, v, extra = "", cls = "") => `<div class="t"><small>${l}</small><b class="${cls}">${v}</b>${extra}</div>`;
  $("#stats").innerHTML = t("Оборот сети", money(s.turnover), "", "acc") + t("Клиентов", s.nodes.toLocaleString("ru-RU"), `<i>seed ${s.seeds}</i>`)
    + t("Переводов (агр.)", s.edges.toLocaleString("ru-RU")) + t("Кластеров", s.clusters)
    + t("Координаторы", r.coordinator || 0) + t("Распределители", r.distributor || 0) + t("Консолидаторы", r.consolidator || 0)
    + t("Транзит", r.transit || 0) + t("Конечные", r.terminal || 0) + t("Граница выгрузки", r.boundary || 0);
  try { const st = await api("storage"); $("#storage").innerHTML = `<span class="dot"></span>${st.backend === "postgres" ? "PostgreSQL" : "локальный режим"}`; } catch (e) {}
}

// ---------- проигрыватель июля ----------
let TL = null, plTimer = null;
async function openPlayer() {
  $("#sankey").classList.add("hidden");
  if (state.mode !== "full") drawFull();
  if (!TL) {
    const tx = await api("timeline");
    TL = Array.from({ length: 31 }, () => []);
    tx.forEach(t => TL[+t.date.slice(8, 10) - 1].push(t));
  }
  $("#player").classList.remove("hidden");
  showDay(+$("#pl-day").value);
}
function showDay(d) {
  $("#pl-day").value = d;
  $("#pl-label").textContent = `${d} июля`;
  const cum = $("#pl-cum").checked;
  const days = cum ? TL.slice(0, d) : [TL[d - 1]];
  const txs = days.flat();
  const agg = new Map();
  txs.forEach(t => { const k = t.src + ">" + t.dst; agg.set(k, (agg.get(k) || 0) + t.sum_kzt); });
  cy.batch(() => {
    cy.elements().removeClass("hl focus").addClass("faded");
    agg.forEach((sum, id) => {
      const e = cy.$id(id);
      if (!e.length) return;
      e.removeClass("faded").addClass("hl");
      e.source().removeClass("faded").addClass("hl");
      e.target().removeClass("faded").addClass("hl");
    });
  });
  const total = txs.reduce((a, t) => a + t.sum_kzt, 0);
  $("#pl-stats").textContent = `${txs.length} перев. · ${money(total)}${cum ? " с 1 июля" : " за день"}`;
}
function stopPlay() { clearInterval(plTimer); plTimer = null; $("#pl-toggle").textContent = "Играть"; }
$("#btn-play").onclick = openPlayer;
$("#pl-day").oninput = e => showDay(+e.target.value);
$("#pl-cum").onchange = () => showDay(+$("#pl-day").value);
$("#pl-toggle").onclick = () => {
  if (plTimer) return stopPlay();
  $("#pl-toggle").textContent = "Пауза";
  if (+$("#pl-day").value >= 31) showDay(1);
  plTimer = setInterval(() => { const d = +$("#pl-day").value; d >= 31 ? stopPlay() : showDay(d + 1); }, 700);
};
$("#pl-close").onclick = () => { stopPlay(); $("#player").classList.add("hidden"); clearHL(); };

// ---------- санкей: потоки денег по коленам и ролям ----------
async function drawSankey() {
  stopPlay(); $("#player").classList.add("hidden");
  setSeg("#mode", "flows"); state.mode = "flows";
  const { flows } = await api("flows");
  const order = Object.keys(ROLES);
  const fwd = flows.filter(f => f.d2 === f.d1 + 1);
  const other = flows.filter(f => f.d2 !== f.d1 + 1).reduce((a, f) => a + f.sum_kzt, 0);
  const box = $("#sankey"); box.classList.remove("hidden");
  const W = Math.max(box.clientWidth, 700), H = Math.max(box.clientHeight - 40, 420), bw = 16, pad = 8, top = 34;
  const blocks = new Map();
  const blk = (d, r) => { const k = d + "|" + r; if (!blocks.has(k)) blocks.set(k, { d, r, in: 0, out: 0 }); return blocks.get(k); };
  fwd.forEach(f => { blk(f.d1, f.r1).out += f.sum_kzt; blk(f.d2, f.r2).in += f.sum_kzt; });
  const cols = [0, 1, 2, 3, 4].map(d => [...blocks.values()].filter(b => b.d === d)
    .sort((a, b) => order.indexOf(a.r) - order.indexOf(b.r)));
  const val = b => Math.max(b.in, b.out);
  const scale = Math.min(...cols.filter(c => c.length).map(c => (H - top - pad * (c.length - 1)) / c.reduce((a, b) => a + val(b), 0)));
  cols.forEach((c, d) => { let y = top; c.forEach(b => { b.x = 70 + d * (W - 260) / 4; b.y = y; b.h = Math.max(2, val(b) * scale); b.oi = 0; b.oo = 0; y += b.h + pad; }); });
  let svg = "";
  fwd.sort((a, b) => order.indexOf(a.r2) - order.indexOf(b.r2)).forEach(f => {
    const s = blocks.get(f.d1 + "|" + f.r1), t = blocks.get(f.d2 + "|" + f.r2), h = f.sum_kzt * scale;
    const y1 = s.y + s.oo, y2 = t.y + t.oi; s.oo += h; t.oi += h;
    const x1 = s.x + bw, x2 = t.x, mx = (x1 + x2) / 2;
    svg += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2} L${x2},${y2 + h} C${mx},${y2 + h} ${mx},${y1 + h} ${x1},${y1 + h} Z"
      fill="${ROLES[f.r1].color}" opacity=".38"><title>${ROLES[f.r1].ru} (${f.d1}) → ${ROLES[f.r2].ru} (${f.d2}): ${money(f.sum_kzt)}, ${f.n_edges} связей</title></path>`;
  });
  blocks.forEach(b => {
    svg += `<rect x="${b.x}" y="${b.y}" width="${bw}" height="${b.h}" rx="3" fill="${ROLES[b.r].color}"><title>${ROLES[b.r].ru}, колено ${b.d}: вход ${money(b.in)}, выход ${money(b.out)}</title></rect>`;
    if (b.h > 11) svg += `<text x="${b.x + bw + 5}" y="${b.y + Math.min(b.h / 2, 14) + 4}">${ROLES[b.r].ru} · ${money(val(b))}</text>`;
  });
  ["seed (0)", "1-е колено", "2-е колено", "3-е колено", "4-е колено"].forEach((t, d) =>
    svg += `<text x="${70 + d * (W - 260) / 4}" y="20" font-weight="600">${t}</text>`);
  svg += `<text class="muted" x="70" y="${H + 28}">Показаны переводы на следующее колено. Переводы внутри колена и «назад»: ${money(other)}. Толщина ленты = сумма, цвет = роль отправителя.</text>`;
  box.innerHTML = `<svg width="${W}" height="${H + 40}">${svg}</svg>`;
  $("#graph-hint").textContent = "Потоки денег: куда уходят средства 81 seed по коленам и ролям";
}

// ---------- лаборатория порогов ----------
let KNOBS = null, labTimer = null, LAB_ROLES = null;
async function openLab() {
  $("#lab").classList.remove("hidden");
  if (!KNOBS) KNOBS = await api("whatif");
  $("#lab-knobs").innerHTML = KNOBS.map((k, i) => `<div class="knob">
      <label>${k.label}<b id="kv${i}">${fmtKnob(k, k.value)}</b></label>
      <input type="range" data-i="${i}" min="${k.min}" max="${k.max}" step="${k.step}" value="${k.value}"></div>`).join("");
  $("#lab-knobs").querySelectorAll("input").forEach(el => el.oninput = () => {
    const k = KNOBS[+el.dataset.i], v = +el.value;
    const b = $("#kv" + el.dataset.i); b.textContent = fmtKnob(k, v); b.classList.toggle("chg", v !== k.value);
    clearTimeout(labTimer); labTimer = setTimeout(runLab, 120);
  });
  runLab();
}
const fmtKnob = (k, v) => k.key.includes("sum") ? money(v) : k.key.includes("ratio") ? Math.round(v * 100) + "%" : v;
async function runLab() {
  const overrides = {};
  $("#lab-knobs").querySelectorAll("input").forEach(el => {
    const k = KNOBS[+el.dataset.i]; if (+el.value !== k.value) overrides[k.section + "." + k.key] = +el.value;
  });
  const r = await api("whatif", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ overrides }) });
  LAB_ROLES = r.roles;
  const mx = Math.max(...r.counts.filter(c => c.role !== "peripheral" && c.role !== "boundary").flatMap(c => [c.base, c.new]), 1);
  const rows = r.counts.filter(c => c.role !== "peripheral" && c.role !== "boundary").map(c => {
    const d = c.new - c.base;
    return `<div class="cmp"><span>${ROLES[c.role].ru}</span><span class="tr">
      <i class="b" style="width:${100 * c.base / mx}%"></i><i class="n" style="width:${100 * c.new / mx}%;background:${ROLES[c.role].color}"></i></span>
      <span class="v">${c.new}${d ? ` <span class="${d > 0 ? "up" : "dn"}">${d > 0 ? "+" : ""}${d}</span>` : ""}</span></div>`;
  }).join("");
  $("#lab-result").innerHTML = `<h3 style="margin:0 0 8px">Роли: было (серым) → стало</h3>${rows}
    <h3 style="margin:14px 0 6px">Сменили роль: <span class="num" style="color:var(--ink)">${r.changed}</span> узлов</h3>
    ${r.transitions.slice(0, 8).map(t => `<div class="trans">${ROLES[t.from].ru} → ${ROLES[t.to].ru}<b>${t.n}</b></div>`).join("")
      || '<div class="note">Роли совпадают с базовыми — правила пайплайна и лаборатории одинаковы.</div>'}
    ${r.top_changed.length ? `<h3 style="margin:14px 0 6px">Самые приоритетные из изменившихся</h3>` + r.top_changed.slice(0, 8).map(t =>
      `<div class="trans" data-gid="${t.gid}"><span class="num">${short(t.gid)}</span> ${ROLES[t.old].ru} → ${ROLES[t.new].ru}<b>${t.priority_score.toFixed(2)}</b></div>`).join("") : ""}`;
  $("#lab-result").querySelectorAll(".trans[data-gid]").forEach(el => el.onclick = () => select(el.dataset.gid));
  paintLab();
}
function paintLab() {  // перекрашиваем граф по новым ролям, изменившиеся — с янтарной обводкой
  if (!cy || state.mode === "flows") return;
  cy.batch(() => cy.nodes().forEach(n => {
    if (!n.scratch("_base")) n.scratch("_base", n.data("role"));
    const nr = LAB_ROLES && LAB_ROLES[n.id()];
    n.data("role", nr || n.scratch("_base"));
    n.toggleClass("changed", !!nr);
  }));
}
function closeLab() {
  $("#lab").classList.add("hidden"); LAB_ROLES = null; paintLab();
}
$("#btn-lab").onclick = () => $("#lab").classList.contains("hidden") ? openLab() : closeLab();
$("#lab-close").onclick = closeLab;
$("#lab-reset").onclick = () => { KNOBS && openLab(); };

(async () => {
  try { CFG = await api("config"); } catch (e) { /* без конфига просто не рисуем разложение */ }
  await loadMarks();
  renderStats(); renderTop(); renderClusters(); renderGaps(); renderLegend(); initGraph();
})();
