// Граф денег — фронтенд. gid везде СТРОКИ (значения ~1e17 не помещаются в Number).
const ROLES = {
  coordinator:  { ru: "координатор",        color: "#d7263d" },
  consolidator: { ru: "консолидатор",       color: "#f46036" },
  distributor:  { ru: "распределитель",     color: "#8e44ad" },
  transit:      { ru: "транзит",            color: "#2e86de" },
  terminal:     { ru: "конечный получатель", color: "#1b998b" },
  boundary:     { ru: "граница выгрузки",   color: "#a0a6b1" },
  peripheral:   { ru: "периферия",          color: "#cfd3da" },
};
const PALETTE = ["#2f5bea","#e4572e","#17bebb","#ffc914","#76b041","#9d4edd","#ff70a6","#3a86ff",
                 "#fb5607","#8338ec","#06d6a0","#ef476f","#118ab2","#b5838d","#6d597a","#e09f3e"];
const clusterColor = c => c === 0 ? "#888" : PALETTE[(c - 1) % PALETTE.length];

const $ = s => document.querySelector(s);
const api = async (p, opt) => { const r = await fetch("/api/" + p, opt); if (!r.ok) throw new Error((await r.json()).detail || r.status); return r.json(); };
const money = x => x >= 1e6 ? (x / 1e6).toFixed(1).replace(".", ",") + " млн ₸" : x >= 1e3 ? Math.round(x / 1e3) + " тыс ₸" : Math.round(x) + " ₸";
const short = g => "…" + g.slice(-9, -3);
const badge = (role) => `<span class="badge" style="background:${ROLES[role].color}">${ROLES[role].ru}</span>`;
const esc = s => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

let cy, FULL, state = { mode: "full", color: "role", hops: 1, selected: null };

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
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  return [
    { selector: "node", style: { "background-color": col, width: "data(size)", height: "data(size)", "border-width": 0 } },
    { selector: "node[?seed]", style: { "border-width": 2, "border-color": dark ? "#fff" : "#111" } },
    { selector: "node[role='boundary']", style: { "border-width": 1, "border-style": "dashed", "border-color": "#777" } },
    { selector: "edge", style: { width: "data(w)", "line-color": dark ? "#3a4254" : "#c9ced8", "curve-style": "haystack", opacity: 0.55 } },
    { selector: ".ego edge, edge.ego", style: { "curve-style": "bezier", "target-arrow-shape": "triangle", "target-arrow-color": dark ? "#8b93a7" : "#8a91a0",
        "line-color": dark ? "#5a6378" : "#aab1bf", opacity: 0.9, "arrow-scale": 0.9 } },
    { selector: "node.labeled, .ego node", style: { label: "data(label)", "font-size": 9, color: dark ? "#cfd4de" : "#333",
        "text-valign": "bottom", "text-margin-y": 3, "font-family": "monospace" } },
    { selector: ".faded", style: { opacity: 0.08 } },
    { selector: "edge.hl", style: { opacity: 1, "line-color": "#2f5bea", "target-arrow-color": "#2f5bea", "curve-style": "bezier", "target-arrow-shape": "triangle", "z-index": 9 } },
    { selector: "node.hl", style: { opacity: 1, label: "data(label)", "font-size": 9, color: dark ? "#fff" : "#111", "z-index": 9 } },
    { selector: "node:selected, node.focus", style: { "border-width": 4, "border-color": "#2f5bea", "z-index": 10 } },
  ];
}

async function initGraph() {
  FULL = await api("graph");
  cy = cytoscape({ container: $("#cy"), style: style(), minZoom: 0.05, maxZoom: 4, wheelSensitivity: 0.25,
    hideEdgesOnViewport: true, textureOnViewport: true, pixelRatio: 1 });
  drawFull();
  cy.on("tap", "node", e => select(e.target.id()));
  cy.on("tap", e => { if (e.target === cy) clearHL(); });
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
}

async function drawEgo(gid) {
  state.mode = "ego"; setSeg("#mode", "ego");
  const sub = await api(`ego/${gid}?hops=${state.hops}`);
  cy.elements().remove();
  cy.add(sub.nodes.map(n => ({ group: "nodes", data: nodeData(n) })));
  cy.add(sub.edges.map(e => ({ group: "edges", data: edgeData(e), classes: "ego" })));
  cy.nodes().addClass("labeled");
  cy.$id(gid).addClass("focus");
  if (state.hops === 1) flowLayout(gid);
  else cy.layout({ name: "concentric", concentric: n => n.id() === gid ? 10 : (n.degree() > 3 ? 5 : 1),
                   levelWidth: () => 3, minNodeSpacing: 18, animate: false }).run();
  cy.edges().addClass("ego");
  $("#graph-hint").textContent = `Окрестность ${short(gid)}: ${sub.nodes.length} узлов, ${state.hops} шаг(а) · стрелки = направление денег`;
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
  const pr = n.pass_ratio == null ? "—" : Math.round(n.pass_ratio * 100) + "%";
  const flows = (list, dir) => list.slice(0, 12).map(f => `
    <div class="flow" data-gid="${f.gid}"><span>${dir}</span>${badge(f.role)}<span class="gid">${short(f.gid)}</span>
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
      <span class="badge" style="background:${clusterColor(n.cluster_id)}">кластер ${n.cluster_id}</span>
      <span class="badge" style="background:#555">колено ${n.depth}</span></div>
    <div class="evidence">${esc(n.evidence)}</div>
    ${caveats.map(c => `<div class="caveat">⚠ ${c}</div>`).join("")}
    <div class="metrics">
      <div><small>Приоритет</small><b>${n.priority_score.toFixed(2)}</b></div>
      <div><small>Уверенность в роли</small><b>${n.role_score.toFixed(2)}</b></div>
      <div><small>Вход: плательщиков / сумма</small><b>${n.in_deg} / ${money(n.in_sum)}</b></div>
      <div><small>Выход: получателей / сумма</small><b>${n.out_deg} / ${money(n.out_sum)}</b></div>
      <div><small>Коэф. пропуска</small><b>${pr}</b></div>
      <div><small>Ушло дальше за ≤2 дня</small><b>${Math.round(n.fast_share * 100)}%</b></div>
      <div><small>Seed выше по цепочке</small><b>${n.seed_reach}</b></div>
      <div><small>Макс. плательщиков в день</small><b>${n.max_payers_same_day}</b></div>
    </div>
    <div style="display:flex;gap:6px">
      <button class="btn" id="btn-ego">Окрестность</button>
      <button class="btn ghost" id="btn-ai">AI-справка</button>
    </div>
    <div id="ai-card"></div>
    <h3>Активность по дням (июль) — вход / выход</h3><div class="bars">${bars}</div>
    <h3>Входящие (${n.incoming.length})</h3><div class="flows">${flows(n.incoming, "←") || "<small>нет в выгрузке</small>"}</div>
    <h3>Исходящие (${n.outgoing.length})</h3><div class="flows">${flows(n.outgoing, "→") || "<small>нет в выгрузке</small>"}</div>
  </div>`;
  $("#card").querySelectorAll(".flow").forEach(el => el.onclick = () => select(el.dataset.gid));
  $("#btn-ego").onclick = () => { state.mode = "ego"; drawEgo(gid); };
  $("#btn-ai").onclick = async () => {
    const b = $("#btn-ai"); b.disabled = true; $("#ai-card").innerHTML = '<div class="ai">Готовлю справку…</div>';
    try { const r = await api(`node/${gid}/card`, { method: "POST" }); $("#ai-card").innerHTML = `<div class="ai">${linkify(r.card)}</div>`; }
    catch (e) { $("#ai-card").innerHTML = `<div class="ai">⚠ ${esc(e.message)}</div>`; }
    b.disabled = false; bindLinks($("#ai-card"));
  };
}

// ---------- левые панели ----------
async function renderTop() {
  const top = await api("top?n=50");
  const hide = $("#hide-seed").checked;
  $("#top-list").innerHTML = top.filter(t => !(hide && t.is_seed)).map(t => `
    <li class="item" data-gid="${t.gid}"><div class="row"><span class="rank">${t.rank}</span>${badge(t.role)}
      <span class="gid">${short(t.gid)}</span>${t.is_seed ? '<span class="badge seed">seed</span>' : ""}
      <span class="score">${t.priority_score.toFixed(2)}</span></div>
      <div class="why">${esc(t.why)}</div></li>`).join("");
  $("#top-list").querySelectorAll(".item").forEach(el => el.onclick = () => select(el.dataset.gid));
}

async function renderClusters() {
  const cl = await api("clusters");
  $("#cluster-list").innerHTML = cl.map(c => `
    <div class="item" data-c="${c.cluster_id}"><div class="row">
      <span class="badge" style="background:${clusterColor(c.cluster_id)}">#${c.cluster_id}</span>
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
  } catch (err) { pending.textContent = "⚠ " + err.message; history.pop(); }
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
    box.innerHTML = res.length ? res.map(r => `<div data-gid="${r.gid}"><span class="gid" style="font-family:var(--mono)">${r.gid}</span>${badge(r.role)}</div>`).join("")
                               : "<div>ничего не найдено</div>";
    box.classList.remove("hidden");
    box.querySelectorAll("[data-gid]").forEach(el => el.onclick = () => { box.classList.add("hidden"); $("#search").value = el.dataset.gid; select(el.dataset.gid); });
  }, 200);
};
$("#search").onkeydown = e => { if (e.key === "Enter") { const f = $("#search-results [data-gid]"); if (f) f.click(); } };

// ---------- прочее ----------
function setSeg(sel, val) { document.querySelectorAll(sel + " button").forEach(b => b.classList.toggle("active", Object.values(b.dataset)[0] === val)); }
document.querySelectorAll(".tabs button").forEach(b => b.onclick = () => {
  document.querySelectorAll(".tabs button, .tab").forEach(x => x.classList.remove("active"));
  b.classList.add("active"); $("#tab-" + b.dataset.tab).classList.add("active");
});
document.querySelectorAll("#mode button").forEach(b => b.onclick = () => {
  if (b.dataset.mode === "full") drawFull();
  else if (state.selected) drawEgo(state.selected);
  else $("#graph-hint").textContent = "Сначала выберите узел";
});
document.querySelectorAll("#color-by button").forEach(b => b.onclick = () => { state.color = b.dataset.c; setSeg("#color-by", b.dataset.c); cy.style(style()); renderLegend(); });
document.querySelectorAll("#hops button").forEach(b => b.onclick = () => { state.hops = +b.dataset.h; setSeg("#hops", b.dataset.h); if (state.mode === "ego" && state.selected) drawEgo(state.selected); });
$("#hide-seed").onchange = renderTop;

$("#btn-resilience").onclick = async () => {
  const r = await api("resilience?top_n=10");
  $("#resilience").innerHTML = `<div class="res">Если заблокировать топ-10 (без seed):<br>
    компонент связности: <b>${r.before.components} → ${r.after.components}</b><br>
    крупнейшая компонента: <b>${r.before.largest_component} → ${r.after.largest_component}</b><br>
    узлов, достижимых от seed: <b>${r.before.nodes_reachable_from_seed} → ${r.after.nodes_reachable_from_seed}</b> (−${Math.round(r.reach_cut_share * 100)}%)<br>
    оборот в сети: −${Math.round(r.flow_cut_share * 100)}%</div>`;
};

function renderLegend() {
  $("#legend").innerHTML = state.color === "role"
    ? Object.entries(ROLES).map(([k, v]) => `<span><i style="background:${v.color}"></i>${v.ru}</span>`).join("") + '<span><i style="border:2px solid currentColor"></i>seed</span>'
    : "<span>Цвет = кластер (Louvain)</span>";
}

async function renderStats() {
  const s = await api("stats");
  $("#stats").innerHTML = `<span><b>${s.nodes}</b> узлов</span><span><b>${s.seeds}</b> seed</span>
    <span><b>${s.edges}</b> связей</span><span><b>${money(s.turnover)}</b> оборот</span><span><b>${s.clusters}</b> кластеров</span>`;
}

renderStats(); renderTop(); renderClusters(); renderLegend(); initGraph();
