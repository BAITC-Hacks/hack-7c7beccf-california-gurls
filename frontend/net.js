// Tamyr — общий слой запросов: имя аналитика (для журнала), токен доступа (если включён на сервере).
const TAMYR = (() => {
  const get = (k, store = localStorage) => { try { return store.getItem(k) || ""; } catch (e) { return ""; } };
  const set = (k, v, store = localStorage) => { try { store.setItem(k, v); } catch (e) {} };
  let analyst = get("tamyr.analyst"), token = get("tamyr.token", sessionStorage);
  async function api(p, opt = {}) {
    const headers = { ...(opt.headers || {}) };
    if (analyst) headers["X-Analyst"] = encodeURIComponent(analyst);
    if (token) headers["X-Api-Token"] = token;
    const r = await fetch("/api/" + p, { ...opt, headers });
    if (r.status === 401 && !opt._retry) {        // сервер требует токен
      const t = await askToken();
      if (t) { token = t; set("tamyr.token", t, sessionStorage); return api(p, { ...opt, _retry: true }); }
    }
    if (!r.ok) {
      let msg = r.status; try { msg = (await r.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return r.json();
  }
  function askToken() {
    return new Promise(res => {
      let box = document.getElementById("token-box");
      if (!box) {
        box = document.createElement("div"); box.id = "token-box"; box.className = "token-box";
        box.innerHTML = `<form><b>Доступ к Tamyr</b><span class="note">Сервер защищён токеном (API_TOKEN). Введите его:</span>
          <input type="password" autocomplete="off"><button class="btn accent">Войти</button></form>`;
        document.body.append(box);
      }
      box.classList.remove("hidden");
      const f = box.querySelector("form"), i = box.querySelector("input");
      i.focus();
      f.onsubmit = e => { e.preventDefault(); box.classList.add("hidden"); res(i.value.trim()); };
    });
  }
  return { api, get analyst() { return analyst; }, setAnalyst(v) { analyst = v.trim().slice(0, 64); set("tamyr.analyst", analyst); } };
})();
