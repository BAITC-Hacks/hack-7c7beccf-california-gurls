
const ROLE_RU = { coordinator: "Координатор", consolidator: "Консолидатор", distributor: "Распределитель",
  transit: "Транзитный счёт", terminal: "Конечный получатель", boundary: "Граница выгрузки", peripheral: "Периферия" };
const ROLE_MEANING = {
  coordinator: "координирующий узел, кандидат в организаторы: собирает средства и распределяет их дальше",
  consolidator: "точка консолидации: аккумулирует средства от нескольких участников",
  distributor: "веерное распределение средств на много получателей",
  transit: "транзитный счёт: пропускает средства дальше, не удерживая",
  terminal: "конечный получатель: средства поступают и остаются",
  boundary: "узел на границе выгрузки: исходящие переводы не выгружались, роль не определена",
  peripheral: "признаков выраженной роли не выявлено" };
const money = x => x == null ? "—" : Math.round(x).toLocaleString("ru-RU") + " ₸";
const pct = x => x == null ? "—" : Math.round(x * 100) + "%";
const esc = s => String(s ?? "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const api = TAMYR.api;
const gid = new URLSearchParams(location.search).get("gid");

async function build() {
  const [n, clusters, gaps, top] = await Promise.all([api("node/" + gid + "?ctx=report"), api("clusters"), api("next_requests?n=50"), api("top?n=50")]);
  const cyc = n.cycles ? await api("cycles/" + gid) : { cycles: [], n_cycles: 0 };
  const sp = (n.split_out + n.split_in) ? await api("splitting?gid=" + gid) : { episodes: [] };
  const cl = clusters.find(c => c.cluster_id === n.cluster_id) || {};
  const rank = top.find(t => t.gid === gid);
  const myGaps = gaps.filter(g => g.gid === gid);
  document.title = `Справка ${gid}`;

  const caveats = [];
  if (n.is_seed) caveats.push("Клиент из исходного списка (seed): граф собран от него, поэтому входящие переводы в выгрузке неполны.");
  if (n.truncated) caveats.push("Узел на 4-м колене обхода: его исходящие переводы не выгружались, дальнейшее движение средств неизвестно.");
  if (!n.is_seed && n.out_sum > n.in_sum * 1.2) caveats.push(`Исходящие (${money(n.out_sum)}) превышают видимые входящие (${money(n.in_sum)}): у клиента есть источники средств вне выборки.`);
  caveats.push("В выгрузку не попали переводы менее 5 000 ₸ и межбанковские операции.");

  const signs = [];
  if (n.second_level) signs.push(`Сборщик второго уровня: средства поступают от ${n.hub_payers} узлов, которые сами имеют признаки сбора или распределения.`);
  if (n.seed_reach) signs.push(`Средства ${n.seed_reach} клиентов из исходного списка доходят до узла по цепочкам переводов.`);
  if (n.fast_share >= 0.5) signs.push(`Сквозной транзит: ${pct(n.fast_share)} поступлений уходит дальше в течение 2 дней.`);
  if (n.max_payers_same_day >= 3) signs.push(`Синхронные поступления: до ${n.max_payers_same_day} разных плательщиков в один день.`);
  if (n.split_out + n.split_in) signs.push(`Дробление: ${n.split_out + n.split_in} эпизодов (≥3 перевода одному получателю в один день), всего ${n.split_tx} переводов.`);
  if (n.anomaly) signs.push(`Аномальный профиль для своего колена: ${esc(n.anomaly_text)}.`);
  if (n.routes_mid) signs.push(`Посредник в ${n.routes_mid} повторяющихся маршрутах A→B→C (перевод дальше в течение 3 дней, ≥3 повторов).`);
  if (n.cycles) signs.push(`Возвратные потоки: ${n.cycles} цепочек, в которых средства возвращаются к отправителю.`);
  if (!signs.length) signs.push("Дополнительных поведенческих признаков не выявлено.");

  const rows = (list, dir) => list.slice(0, 15).map(f => `<tr><td class="mono">${f.gid}</td><td>${ROLE_RU[f.role]}${f.is_seed ? " · seed" : ""}</td>
      <td class="n">${f.n_tx}</td><td class="n">${money(f.sum_kzt)}</td></tr>`).join("") ||
      `<tr><td colspan="4">${dir === "in" ? "Входящих переводов в выгрузке нет" : "Исходящих переводов в выгрузке нет"}</td></tr>`;

  const actions = myGaps.map(g => `Запросить ${g.request}: ${g.reason}.`);
  if (n.role !== "peripheral") actions.push("Проверить документы-основания крупнейших переводов (назначение платежа, договоры).");
  if (n.incoming.length) actions.push(`Проверить крупнейших плательщиков: ${n.incoming.slice(0, 3).map(f => f.gid).join(", ")}.`);
  if (n.outgoing.length) actions.push(`Проверить крупнейших получателей: ${n.outgoing.slice(0, 3).map(f => f.gid).join(", ")}.`);

  document.getElementById("doc").innerHTML = `
  <div class="stamp"><span><b style="letter-spacing:.14em;color:#111">TAMYR</b> · Для служебного пользования</span><span>Сформировано: ${new Date().toLocaleString("ru-RU")}</span></div>
  <h1>Аналитическая справка по клиенту</h1>
  <div class="gid">gid ${gid}</div>
  <div class="disclaimer">Справка сформирована автоматически по структуре переводов (июль 2026, внутрибанковские переводы ≥5 000 ₸).
    Все выводы — <b>гипотезы для проверки</b>, а не утверждение о причастности клиента к противоправной деятельности.</div>

  <h2>1. Роль в сети</h2>
  <div class="role">${ROLE_RU[n.role]}${n.second_level ? " (сборщик второго уровня)" : ""}</div>
  <div>${ROLE_MEANING[n.role]}.</div>
  <p><b>Обоснование:</b> ${esc(n.evidence)}</p>
  <div class="kv">
    <div><small>Уверенность в роли</small><b>${n.role_score.toFixed(2)}</b></div>
    <div><small>Приоритет проверки</small><b>${n.priority_score.toFixed(2)}${rank ? ` · место ${rank.rank}` : ""}</b></div>
    <div><small>Колено от исходного списка</small><b>${n.depth}${n.is_seed ? " (seed)" : ""}</b></div>
  </div>
  <p><b>Устойчивость роли:</b> роль сохраняется в ${Math.round(n.role_stability * 100)}% вариантов порогов (±20%)${n.alt_role ? `; альтернативная трактовка — ${(ROLE_RU[n.alt_role] || n.alt_role).toLowerCase()}` : ""}.
    ${n.role_stability < 0.7 ? "<b>Роль пограничная — вывод требует особенно внимательной проверки.</b>" : ""}</p>
  ${n.mark ? `<p><b>Решение аналитика:</b> ${{confirmed: "гипотеза подтверждена", review: "на проверке", rejected: "гипотеза отклонена"}[n.mark.status]}${n.mark.comment ? ` — «${esc(n.mark.comment)}»` : ""} (${n.mark.updated_at.slice(0, 16)}).</p>` : ""}
  <p><b>Кластер ${n.cluster_id}</b> (${cl.n_nodes ?? "—"} клиентов, из них seed: ${cl.n_seed ?? "—"}): ${esc(cl.hypothesis)}</p>

  <h2>2. Финансовые показатели</h2>
  <div class="kv">
    <div><small>Входящие: плательщиков / сумма</small><b>${n.in_deg} / ${money(n.in_sum)}</b></div>
    <div><small>Исходящие: получателей / сумма</small><b>${n.out_deg} / ${money(n.out_sum)}</b></div>
    <div><small>Доля полученного, ушедшая дальше</small><b>${(n.is_seed || n.out_sum > n.in_sum * 1.2) ? "н/д (входящие неполны)" : pct(n.pass_ratio)}</b></div>
    <div><small>Ушло дальше за ≤2 дня</small><b>${pct(n.fast_share)}</b></div>
    <div><small>Активных дней в июле</small><b>${n.active_days}</b></div>
    <div><small>Доля переводов 5–10 тыс ₸</small><b>${pct(n.near_threshold_share)}</b></div>
  </div>

  <h2>3. Выявленные признаки</h2>
  <ul>${signs.map(s => `<li>${s}</li>`).join("")}</ul>

  <h2>4. Входящие переводы (крупнейшие ${Math.min(15, n.incoming.length)} из ${n.incoming.length})</h2>
  <table><tr><th>Плательщик (gid)</th><th>Роль</th><th class="n">Переводов</th><th class="n">Сумма</th></tr>${rows(n.incoming, "in")}</table>

  <h2>5. Исходящие переводы (крупнейшие ${Math.min(15, n.outgoing.length)} из ${n.outgoing.length})</h2>
  <table><tr><th>Получатель (gid)</th><th>Роль</th><th class="n">Переводов</th><th class="n">Сумма</th></tr>${rows(n.outgoing, "out")}</table>

  ${sp.episodes.length ? `<h2>6. Эпизоды дробления</h2>
  <table><tr><th>Дата</th><th>Отправитель</th><th>Получатель</th><th class="n">Переводов</th><th class="n">Сумма</th><th class="n">Мин–макс</th></tr>
  ${sp.episodes.map(e => `<tr><td>${e.day}</td><td class="mono">${e.src}</td><td class="mono">${e.dst}</td><td class="n">${e.n_tx}</td>
     <td class="n">${money(e.sum_kzt)}</td><td class="n">${money(e.min_kzt)} – ${money(e.max_kzt)}</td></tr>`).join("")}</table>` : ""}

  ${cyc.cycles.length ? `<h2>${sp.episodes.length ? 7 : 6}. Возвратные потоки</h2>
  <table><tr><th>Цепочка</th><th>Суммы по звеньям</th></tr>
  ${cyc.cycles.slice(0, 8).map(c => `<tr><td class="mono">${c.chain.join(" → ")}</td><td>${c.sums_kzt.map(money).join(" → ")}</td></tr>`).join("")}</table>` : ""}

  <h2>Хронология операций (${Math.min(40, n.transactions.length)} из ${n.transactions.length})</h2>
  <table><tr><th>Дата</th><th>Направление</th><th>Контрагент (gid)</th><th class="n">Сумма</th></tr>
  ${n.transactions.slice(0, 40).map(t => `<tr><td>${t.date}</td><td>${t.dst === gid ? "поступление" : "списание"}</td>
     <td class="mono">${t.dst === gid ? t.src : t.dst}</td><td class="n">${money(t.sum_kzt)}</td></tr>`).join("")}</table>

  <h2>Ограничения данных</h2>
  <ul>${caveats.map(c => `<li>${c}</li>`).join("")}</ul>

  <h2>Рекомендуемые действия</h2>
  <ul>${actions.map(a => `<li>${esc(a)}</li>`).join("")}</ul>

  <div id="ai-block"></div>

  <div class="sign">Отпечаток прогона SHA-256: <span id="fp">…</span> · Tamyr · роли определены по формальным правилам с порогами (см. README проекта) ·
    идентификаторы обезличены. Справка не является заключением о виновности.</div>`;
}

document.getElementById("btn-ai").onclick = async () => {
  const st = document.getElementById("status"); st.textContent = "Готовлю AI-справку…";
  try {
    const d = await api(`node/${gid}/card`, { method: "POST" });
    document.getElementById("ai-block").innerHTML = `<h2>Краткое резюме (сгенерировано AI по данным выше)</h2><div class="ai">${esc(d.card)}</div>`;
    st.textContent = "";
  } catch (e) { st.textContent = "⚠ " + e.message; }
};

gid ? build().then(fillFp).catch(e => document.getElementById("doc").textContent = "Ошибка: " + e.message)
    : document.getElementById("doc").textContent = "Не указан gid";

document.getElementById("btn-print").addEventListener("click", () => window.print());
function fillFp() {   // вызывается после отрисовки справки
  api("integrity").then(r => { const el = document.getElementById("fp"); if (el) el.textContent = (r.run_fingerprint || "").slice(0, 16) + (r.ok ? " (данные не изменялись)" : " (ВНИМАНИЕ: файлы изменены после расчёта)"); }).catch(() => {});
}
