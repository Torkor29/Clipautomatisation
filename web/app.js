"use strict";
/* ClipAuto — interface web (vanilla JS, pas de build). */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s) => { s = Math.max(0, s || 0); return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`; };
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const deep = (o) => JSON.parse(JSON.stringify(o));

/* Le front peut être servi par le VPS (même adresse) OU par Vercel : dans ce cas
   window.CLIPAUTO_API (web/config.js) = adresse https du VPS. Connexion par mot de passe (jeton). */
const API = (window.CLIPAUTO_API || "").replace(/\/+$/, "");
(() => { // #k=… dans l'adresse = connexion directe, puis on nettoie l'adresse
  const m = location.hash.match(/[#&]k=([^&]+)/);
  if (m) { try { localStorage.setItem("clipauto_token", decodeURIComponent(m[1])); } catch { } history.replaceState(null, "", location.pathname + "#/clips"); }
})();
let TOKEN = (() => { try { return localStorage.getItem("clipauto_token") || ""; } catch { return ""; } })();
let MB = TOKEN ? `${API}/t/${encodeURIComponent(TOKEN)}` : API; // base des médias (img / video ne peuvent pas envoyer d'en-tête)
async function api(path, opts = {}) {
  const o = { ...opts, headers: { ...(opts.headers || {}) } };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers["Content-Type"] = "application/json"; delete o.json; }
  if (TOKEN) o.headers.Authorization = `Bearer ${TOKEN}`;
  let r;
  try { r = await fetch(API + path, o); } catch (e) { throw new Error(API ? `Serveur injoignable (${API})` : "Serveur injoignable"); }
  if (r.status === 401) { showLogin(); throw new Error("Connexion requise"); }
  if (!r.ok) {
    let m = ""; try { m = (await r.json()).detail || ""; } catch { }
    if (!m) m = r.status >= 500 ? `le serveur a planté (${r.status}) sur ${path.split("?")[0]} — redémarrage en cours ? réessaie dans 30 s` : `erreur ${r.status} sur ${path.split("?")[0]}`;
    throw new Error(m);
  }
  return r.status === 204 ? null : r.json();
}
function showLogin() {
  // Page de connexion simple : champ TEXTE masqué par CSS (évite les soucis du gestionnaire de mots
  // de passe d'iOS sur type=password), aucun flou / animation autour du champ.
  if ($("#login")) return;
  try { localStorage.removeItem("clipauto_token"); } catch { }
  document.body.classList.add("is-login");
  const m = h(`<form class="login" id="login" autocomplete="off" novalidate>
    <div class="login-hero">
      <div class="login-mark">${ic("play")}</div>
      <h1>ClipAuto</h1>
      <p>Les meilleurs moments de tes lives, détectés, montés et sous-titrés automatiquement.</p>
      <ul>
        <li>${ic("radio")} Surveille Twitch, Kick et YouTube</li>
        <li>${ic("sparkles")} Détecte les moments forts grâce au chat</li>
        <li>${ic("scissors")} Clips 9:16 sous-titrés, prêts à publier</li>
      </ul>
    </div>
    <div class="login-box">
      <label class="f" for="lpw"><b>Mot de passe</b></label>
      <input type="text" class="pw masked" id="lpw" name="clipauto-code" inputmode="text" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" enterkeyhint="go" placeholder="••••••••">
      <label class="inline lshow"><input type="checkbox" id="lsh"> Afficher</label>
      <button class="btn pri" type="submit">Se connecter ${ic("chevron-right")}</button>
      <p class="lerr" id="lerr" hidden></p>
      <p class="lhint">Astuce : ouvre <code>${esc(location.origin)}/#k=TONMOTDEPASSE</code> pour te connecter sans rien taper.</p>
    </div></form>`);
  document.body.append(m);
  const pw = $("#lpw", m);
  $("#lsh", m).onchange = (e) => pw.classList.toggle("masked", !e.target.checked);
  m.onsubmit = async (e) => {
    e.preventDefault();
    const val = pw.value.trim(), err = $("#lerr", m);
    if (!val) { err.hidden = false; err.textContent = "Tape ton mot de passe."; return; }
    const r = await fetch(API + "/api/meta", { headers: { Authorization: `Bearer ${val}` } }).catch(() => null);
    if (r && r.ok) { try { localStorage.setItem("clipauto_token", val); } catch { } location.replace(location.pathname + "#/clips"); location.reload(); }
    else { err.hidden = false; err.textContent = r ? `Mot de passe incorrect (${val.length} caractères envoyés).` : "Serveur injoignable."; }
  };
}
function toast(msg, ms = 2600) {
  const d = h(`<div>${esc(msg)}</div>`); $("#toast").append(d); setTimeout(() => d.remove(), ms);
}
let META = null, timers = [];
window.addEventListener("error", (e) => toast(`Erreur : ${e.message}`, 6000));
window.addEventListener("unhandledrejection", (e) => toast(`Erreur : ${e.reason?.message || e.reason}`, 6000));
function every(fn, ms) { fn(); timers.push(setInterval(fn, ms)); }
function clearTimers() { timers.forEach(clearInterval); timers = []; }

/* ===================================================================== router */
const routes = { clips: viewClips, streamers: viewStreamers, import: viewImport, settings: viewSettings, edit: viewEditor };
async function route() {
  clearTimers();
  if (window._edCleanup) { window._edCleanup(); window._edCleanup = null; }
  const [name, arg] = (location.hash.replace(/^#\//, "") || "clips").split("/");
  $$("nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === name || (name === "edit" && a.dataset.r === "clips")));
  const v = $("#view"); v.innerHTML = "";
  if (!META) { try { META = await api("/api/meta"); } catch (e) { v.append(h(`<div class="empty">${esc(e.message)}</div>`)); return; } }
  try { await (routes[name] || viewClips)(v, arg); } catch (e) { v.append(h(`<div class="empty">Erreur : ${esc(e.message)}</div>`)); }
}
window.addEventListener("hashchange", route);

async function refreshIntegrations() {
  try {
    const s = await api("/api/state");
    const i = s.integrations, live = s.streamers.filter((x) => x.live).length;
    $("#integrations").innerHTML = `
      <div><span class="dot ${live ? "live" : ""}"></span>${live} live / ${s.streamers.length} suivis</div>
      <div><span class="dot ${i.twitch ? "on" : ""}"></span>Twitch API</div>
      <div><span class="dot ${i.discord ? "on" : ""}"></span>Discord</div>
      <div><span class="dot ${i.postforme ? "on" : ""}"></span>Post for Me</div>`;
  } catch { }
}

/* ===================================================================== CLIPS */
async function viewClips(v) {
  let filter = sessionStorage.getItem("cf") || "";
  v.append(h(`<div class="row"><div><h1>Clips</h1><p class="sub">Moments forts détectés automatiquement sur les lives et les imports.</p></div>
    <div class="spacer"></div><button class="btn" id="selm">${ic("square-check")} Faire un résumé</button><a class="btn pri" href="#/import">${ic("upload")} Importer</a></div>`));
  const picked = []; let selMode = false;
  const bar = h(`<div class="selbar" hidden><b id="selc"></b><span style="color:var(--mute);font-size:13px">L'ordre de sélection = l'ordre dans le résumé</span><div class="spacer"></div>
    <button class="btn sm" id="selx">Annuler</button><button class="btn pri" id="selgo">${ic("clapperboard")} Créer le résumé</button></div>`);
  $("#selm").onclick = () => { selMode = !selMode; picked.length = 0; sig = ""; load(); };
  const stats = h(`<div class="stats"></div>`); v.append(stats);
  const tabs = h(`<div class="tabs"></div>`); v.append(tabs);
  const grid = h(`<div class="clips"></div>`); v.append(grid);
  const T = [["", "Tous"], ["pending", "À valider"], ["approved", "Approuvés"], ["published", "Publiés"], ["rejected", "Rejetés"]];
  let sig = "";
  async function load() {
    const [clips, st] = await Promise.all([api("/api/clips" + (filter ? `?status=${filter}` : "")), api("/api/state")]);
    const live = st.streamers.filter((x) => x.live);
    stats.innerHTML = `
      <a class="stat" href="#/streamers"><span>${ic("radio")} En live</span><b>${live.length}<small>/${st.streamers.length}</small></b><em>${live.length ? esc(live.map((x) => x.channel).join(", ")) : "aucun streamer en live"}</em></a>
      <button class="stat" data-f="pending"><span>${ic("square-check")} À valider</span><b>${st.counts.pending || 0}</b><em>clips en attente</em></button>
      <button class="stat" data-f="approved"><span>${ic("check")} Approuvés</span><b>${st.counts.approved || 0}</b><em>prêts à publier</em></button>
      <button class="stat" data-f="published"><span>${ic("send")} Publiés</span><b>${st.counts.published || 0}</b><em>sur tes réseaux</em></button>`;
    $$("[data-f]", stats).forEach((b) => b.onclick = () => { filter = b.dataset.f; sessionStorage.setItem("cf", filter); sig = ""; load(); });
    tabs.innerHTML = T.map(([k, l]) => `<button data-k="${k}" class="${k === filter ? "on" : ""}">${l}${k && st.counts[k] ? ` · ${st.counts[k]}` : ""}</button>`).join("");
    $$("button", tabs).forEach((b) => b.onclick = () => { filter = b.dataset.k; sessionStorage.setItem("cf", filter); sig = ""; load(); });
    const nsig = JSON.stringify(clips.map((c) => [c.id, c.status, c.render_status, c.title]));
    if (nsig === sig) return; sig = nsig;
    grid.innerHTML = "";
    if (!clips.length) { grid.append(h(`<div class="empty" style="grid-column:1/-1">Aucun clip pour l'instant.<br>Ajoute des streamers ou importe une VOD.</div>`)); return; }
    for (const c of clips) {
      const card = clipCard(c, load);
      if (selMode) {
        const n = picked.indexOf(c.id);
        card.classList.toggle("picked", n >= 0);
        const pk = h(`<div class="pick">${n >= 0 ? n + 1 : ""}</div>`); $(".thumb", card).append(pk);
        $(".thumb", card).onclick = (e) => { e.stopPropagation(); const k = picked.indexOf(c.id); k >= 0 ? picked.splice(k, 1) : picked.push(c.id); sig = ""; load(); };
        $(".thumb", card).onmouseenter = null;
      }
      grid.append(card);
    }
    bar.hidden = !selMode; $("#selc").textContent = `${picked.length} clip${picked.length > 1 ? "s" : ""} sélectionné${picked.length > 1 ? "s" : ""}`;
    $("#selm").innerHTML = selMode ? `${ic("x")} Annuler` : `${ic("square-check")} Faire un résumé`;
  }
  v.append(bar);
  $("#selx").onclick = () => { selMode = false; picked.length = 0; sig = ""; load(); };
  $("#selgo").onclick = () => { if (picked.length < 2) return toast("Sélectionne au moins 2 clips"); compilationModal({ clip_ids: [...picked] }, () => { selMode = false; picked.length = 0; sig = ""; load(); }); };
  every(load, 5000);
}

function clipCard(c, reload) {
  const sc = c.detail?.viral ?? Math.round(100 * (1 - Math.exp(-Math.max(c.score, 0) / 2)));
  const why = clipWhy(c);
  const cls = sc >= 70 ? "hi" : sc >= 40 ? "mid" : "lo";
  const rendering = ["rendering", "queued"].includes(c.render_status);
  const el = h(`<div class="clipc">
    <div class="thumb">
      ${c.thumb ? `<img loading="lazy" src="${MB}/media/${c.id}/thumb?v=${c.render_status}">` : ""}
      <div class="score ${cls}">${sc}<small>VIRAL</small></div>
      <div class="dur">${fmt(c.duration)}</div>
      ${rendering ? `<div class="rstat">${ic("loader")} rendu en cours…</div>` : ""}
      ${c.render_status === "error" ? `<div class="rstat">${ic("triangle-alert")} échec du rendu</div>` : ""}
    </div>
    <div class="meta">
      <div class="t">${esc(c.title || "Sans titre")}</div>
      ${why ? `<div class="reason-line" title="${esc(why)}">${ic("search")} ${esc(why)}</div>` : ""}
      ${c.status === "rejected" && c.error ? `<div class="reason-line" style="color:var(--warn)">${esc(c.error)}</div>` : ""}
      <div class="row" style="gap:6px"><span class="pill">${esc(c.streamer || "—")}</span><span class="pill ${c.status}">${statusLabel(c.status)}</span>${c.origin === "compilation" ? `<span class="pill" style="color:var(--acc2)">résumé</span>` : ""}</div>
      <div class="acts">
        <a class="btn sm" href="#/edit/${c.id}" title="Éditer">${ic("scissors")}</a>
        <button class="btn sm ok" data-a="approve" title="Approuver">${ic("check")}</button>
        <button class="btn sm bad" data-a="reject" title="Rejeter">${ic("x")}</button>
        ${c.path ? `<a class="btn sm" href="${MB}/media/${c.id}/final?dl=1" title="Télécharger">${ic("download")}</a>` : ""}
      </div>
    </div></div>`);
  const th = $(".thumb", el);
  th.onclick = () => location.hash = `#/edit/${c.id}`;
  if (c.path && !rendering) {
    let vid;
    th.onmouseenter = () => { vid = h(`<video muted loop playsinline src="${MB}/media/${c.id}/final"></video>`); vid.style.position = "absolute"; vid.style.inset = 0; th.append(vid); vid.play().catch(() => { }); };
    th.onmouseleave = () => vid && vid.remove();
  }
  $$("[data-a]", el).forEach((b) => b.onclick = async () => { await api(`/api/clips/${c.id}/${b.dataset.a}`, { method: "POST" }); toast(b.dataset.a === "approve" ? "Clip approuvé" : "Clip rejeté"); reload(); });
  return el;
}
function clipWhy(c) { // « pourquoi ce clip » en une phrase
  const d = c.detail || {};
  const sig = (d.signals || []).filter((x) => x.strong).slice(0, 2).map((x) => `${x.label.split(" (")[0]} ×${x.ratio ?? "+" + x.z}`);
  if (c.origin === "import" && !sig.length && d.z?.audio) sig.push(`pic de son (+${d.z.audio}σ)`);
  if (c.origin === "compilation") return `résumé de ${(d.compilation || []).length} moments`;
  const txt = (d.analysis?.reasons || []).slice(0, 1);
  return [...sig, ...txt].join(" · ");
}
async function compilationModal(opts, done) {
  const S = await api("/api/settings"), C = S.compilation;
  let ids = opts.clip_ids || [];
  const all = await api("/api/clips");
  const byId = Object.fromEntries(all.map((c) => [c.id, c]));
  const m = h(`<div class="modal"><div class="card">
    <h2>${ic("clapperboard")} ${opts.streamer ? `Résumé du live de ${esc(opts.streamer)}` : "Créer un résumé"}</h2>
    ${opts.streamer ? `<div class="grid2" style="gap:10px">
        <label class="f"><b>Quels clips ?</b><select id="mpk"><option value="recent">Les derniers faits</option><option value="best">Les meilleurs scores</option></select></label>
        <label class="f"><b>Sur les dernières</b><div class="inline"><input type="number" id="mh" value="${C.hours}" min="1"> h</div></label>
        <label class="f"><b>Nombre de moments</b><input type="number" id="mn" value="${C.clips}" min="2" max="20"></label></div>
        <button class="btn sm" id="mprev" style="margin-bottom:12px">${ic("search")} Prévisualiser la sélection</button>` : ""}
    <div class="ord" id="mord"></div>
    <label class="f"><b>Titre (affiché en accroche)</b><input type="text" id="mt" value="${esc(opts.streamer ? `Le best-of de ${opts.streamer} 🔥` : "Best-of du live 🔥")}"></label>
    <div class="grid2" style="gap:10px">
      <label class="f"><b>Transition</b><select id="mtr">${Object.entries(META.transitions).map(([k, l]) => `<option value="${k}" ${k === C.transition ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f"><b>Durée de transition (s)</b><input type="number" step="0.1" id="mtd" value="${C.transition_duration}"></label>
      <label class="f"><b>Max par moment (s)</b><input type="number" id="mme" value="${C.max_each}"><small>Garde la fin (la chute) de chaque moment</small></label>
      <label class="f"><b>Effet sur chaque moment</b><select id="mef">${Object.entries(META.effects).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
    </div>
    <label class="inline f"><input type="checkbox" id="mit" checked> <b>Afficher le titre au début</b></label>
    <div class="row"><div class="spacer"></div><button class="btn" id="mx">Annuler</button><button class="btn pri" id="mgo">${ic("sparkles")} Générer</button></div>
  </div></div>`);
  document.body.append(m);
  const drawOrd = () => {
    $("#mord", m).innerHTML = ids.length ? "" : `<div style="color:var(--mute)">Aucun clip.</div>`;
    ids.forEach((id, i) => {
      const c = byId[id] || {};
      const why = clipWhy(c);
      const row = h(`<div><b>${i + 1}</b>${c.thumb ? `<img src="${MB}/media/${id}/thumb">` : ""}<span class="ordt"><b>${esc(c.title || "#" + id)}</b> · ${fmt(c.duration)} · ${c.detail?.viral != null ? `score ${c.detail.viral}/100` : ""}
        <small>${new Date(c.created * 1000).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })} — ${esc(why || "pas de détail (clip ancien)")}</small></span>
        <button class="btn sm" data-u ${i ? "" : "disabled"}>${ic("arrow-up")}</button><button class="btn sm" data-d ${i < ids.length - 1 ? "" : "disabled"}>${ic("arrow-down")}</button><button class="btn sm bad" data-r>${ic("x")}</button></div>`);
      $("[data-u]", row).onclick = () => { [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]]; drawOrd(); };
      $("[data-d]", row).onclick = () => { [ids[i + 1], ids[i]] = [ids[i], ids[i + 1]]; drawOrd(); };
      $("[data-r]", row).onclick = () => { ids.splice(i, 1); drawOrd(); };
      $("#mord", m).append(row);
    });
  };
  const preview = () => {
    const since = Date.now() / 1000 - Number($("#mh", m).value) * 3600;
    const cand = all.filter((c) => c.streamer === opts.streamer && c.created >= since && c.status !== "rejected" && c.origin !== "compilation");
    const vir = (c) => c.detail?.viral ?? c.score;
    const pick = $("#mpk", m).value === "best" ? cand.sort((a, b) => vir(b) - vir(a)) : cand.sort((a, b) => b.created - a.created);
    ids = pick.slice(0, Number($("#mn", m).value)).sort((a, b) => a.created - b.created).map((c) => c.id);
    drawOrd();
  };
  if (opts.streamer) { $("#mprev", m).onclick = preview; $("#mpk", m).onchange = preview; $("#mh", m).onchange = preview; $("#mn", m).onchange = preview; preview(); } else drawOrd();
  $("#mx", m).onclick = () => m.remove();
  m.onclick = (e) => { if (e.target === m) m.remove(); };
  $("#mgo", m).onclick = async () => {
    if (ids.length < 2) return toast("Il faut au moins 2 moments");
    try {
      await api("/api/compilations", { method: "POST", json: { clip_ids: ids, title: $("#mt", m).value, transition: $("#mtr", m).value,
        duration: Number($("#mtd", m).value), max_each: Number($("#mme", m).value), effect: $("#mef", m).value, intro_text: $("#mit", m).checked } });
      toast("Résumé en cours de création… (onglet Importer pour suivre)", 4000); m.remove(); done && done();
    } catch (e) { toast(e.message); }
  };
}
const statusLabel = (s) => ({ pending: "À valider", approved: "Approuvé", published: "Publié", rejected: "Rejeté", error: "Erreur" }[s] || s);

/* ===================================================================== STREAMERS */
async function viewStreamers(v) {
  v.append(h(`<div><h1>Streamers</h1><p class="sub">Chaînes surveillées. Dès qu'une passe en live : enregistrement, lecture du chat et détection des moments forts.</p></div>`));
  const add = h(`<div class="card" style="margin-bottom:20px"><div class="row">
      <select id="pf" style="width:130px"><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="youtube">YouTube</option></select>
      <input id="ch" type="text" placeholder="Nom de la chaîne ou lien (ex. mehdoche, https://kick.com/xqc, @Chaine)" style="flex:1;min-width:200px">
      <button class="btn pri" id="addb">+ Ajouter</button></div></div>`);
  v.append(add);
  const list = h(`<div class="str"></div>`); v.append(list);
  $("#addb").onclick = async () => {
    const channel = $("#ch").value.trim(); if (!channel) return;
    let platform = $("#pf").value;
    if (/kick\.com/.test(channel)) platform = "kick"; else if (/twitch\.tv/.test(channel)) platform = "twitch"; else if (/youtube\.com|^@/.test(channel)) platform = "youtube";
    try { await api("/api/streamers", { method: "POST", json: { platform, channel } }); $("#ch").value = ""; toast("Streamer ajouté — vérifié au prochain passage (≤ 2 min)"); render(true); } catch (e) { toast(e.message); }
  };
  $("#ch").onkeydown = (e) => e.key === "Enter" && $("#addb").click();
  const open = new Set();
  async function render(force) {
    const st = await api("/api/state");
    if (!st.streamers.length) { list.innerHTML = `<div class="empty">Aucun streamer suivi. Ajoute une chaîne ci-dessus.</div>`; return; }
    if (!force && $$("input:focus,textarea:focus", list).length) return; // ne pas écraser une saisie
    list.innerHTML = "";
    for (const s of st.streamers) list.append(streamerCard(s, open, render));
  }
  every(render, 4000);
}

function streamerCard(s, open, rerender) {
  const ss = s.session;
  const el = h(`<div class="card">
    <div class="strc">
      <div class="avatar ${s.platform}">${esc(s.channel[0]?.toUpperCase() || "?")}</div>
      <div>
        <div class="row" style="gap:8px"><b style="font-size:16px">${esc(s.channel)}</b><span class="pill">${s.platform}</span>
          ${s.live ? `<span class="pill" style="color:var(--live)"><span class="dot live"></span>EN LIVE</span>` : `<span class="pill">hors ligne</span>`}
          ${!s.enabled ? `<span class="pill">en pause</span>` : ""}
          ${Object.keys(s.overrides || {}).length ? `<span class="pill" style="color:var(--acc)">réglages perso</span>` : ""}</div>
        ${ss ? `<div style="color:var(--mute);font-size:13px;margin-top:4px">${esc(ss.title || "")} · ${ic("eye")} ${ss.viewers ?? "?"} · ${ic("message-square")} ${ss.chat_msgs} msgs · depuis ${fmt((Date.now() / 1000 - ss.since))}</div>` : ""}
      </div>
      <div class="row" style="gap:6px">
        <label class="inline" title="Surveiller"><input type="checkbox" ${s.enabled ? "checked" : ""} data-x="en"> actif</label>
        <button class="btn sm" data-x="sum" title="Résumé des meilleurs moments">${ic("clapperboard")} Résumé</button>
        <button class="btn sm" data-x="cfg">${ic("settings")}</button>
        <button class="btn sm bad" data-x="del">${ic("trash-2")}</button>
      </div>
    </div>
    ${ss ? sparkline(ss) : ""}
    <div class="ovr" ${open.has(s.id) ? "" : "hidden"}></div>
  </div>`);
  $('[data-x="en"]', el).onchange = async (e) => { await api(`/api/streamers/${s.id}`, { method: "PATCH", json: { enabled: e.target.checked } }); rerender(true); };
  $('[data-x="del"]', el).onclick = async () => { if (!confirm(`Ne plus suivre ${s.channel} ?`)) return; await api(`/api/streamers/${s.id}`, { method: "DELETE" }); rerender(true); };
  $('[data-x="sum"]', el).onclick = () => compilationModal({ streamer: s.channel });
  $('[data-x="cfg"]', el).onclick = () => { open.has(s.id) ? open.delete(s.id) : open.add(s.id); rerender(true); };
  if (open.has(s.id)) {
    const o = s.overrides || {}, d = o.detect || {};
    const box = $(".ovr", el);
    box.innerHTML = `<h3>Réglages propres à ${esc(s.channel)} (vides = réglages globaux)</h3>
      <div class="grid2">
        <label class="f"><b>Seuil de déclenchement</b><input type="number" step="0.1" data-k="threshold" value="${d.threshold ?? ""}"><small>Plus bas = plus de clips</small></label>
        <label class="f"><b>Délai du chat (s)</b><input type="number" data-k="chat_delay_seconds" value="${d.chat_delay_seconds ?? ""}"><small>Retard moyen entre l'action et la réaction du chat</small></label>
        <label class="f"><b>Mots-clés en plus</b><input type="text" data-k="keywords" value="${esc((d.keywords || []).join(", "))}"><small>Ex. noms de persos, « clip », expressions de la commu</small></label>
        <label class="f"><b>Max clips / heure</b><input type="number" data-k="max_clips_per_hour" value="${d.max_clips_per_hour ?? ""}"></label>
      </div>
      <div class="row"><button class="btn pri sm" data-x="save">Enregistrer</button><button class="btn sm" data-x="clr">Revenir aux réglages globaux</button></div>`;
    $('[data-x="save"]', box).onclick = async () => {
      const det = {};
      $$("[data-k]", box).forEach((i) => {
        const k = i.dataset.k, val = i.value.trim(); if (val === "") return;
        det[k] = k === "keywords" ? val.split(",").map((x) => x.trim()).filter(Boolean) : Number(val);
      });
      await api(`/api/streamers/${s.id}`, { method: "PATCH", json: { overrides: Object.keys(det).length ? { detect: det } : {} } });
      toast("Réglages enregistrés (appliqués à chaud)"); rerender(true);
    };
    $('[data-x="clr"]', box).onclick = async () => { await api(`/api/streamers/${s.id}`, { method: "PATCH", json: { overrides: {} } }); rerender(true); };
  }
  return el;
}

function sparkline(ss) {
  const pts = ss.timeline; if (pts.length < 2) return `<div style="color:var(--mute);font-size:12px;margin-top:10px">Calibrage du stream en cours…</div>`;
  const W = 600, H = 56, max = Math.max(ss.threshold * 1.6, ...pts.map((p) => p[1]));
  const x = (i) => (i / (pts.length - 1)) * W, y = (v) => H - (v / max) * (H - 4) - 2;
  const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("");
  const z = ss.last_z || {};
  const names = { chat_rate: "chat", unique_chatters: "viewers actifs", laugh_emotes: "rires", hype_emotes: "hype", keywords: "mots-clés", audio: "audio" };
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="g" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".5"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></linearGradient></defs>
    <path d="${d}L${W},${H}L0,${H}Z" fill="url(#g)"/><path d="${d}" fill="none" stroke="#a78bfa" stroke-width="2" vector-effect="non-scaling-stroke"/>
    <line x1="0" x2="${W}" y1="${y(ss.threshold)}" y2="${y(ss.threshold)}" stroke="#f59e0b" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/></svg>
    <div class="zs">${Object.entries(z).map(([k, v]) => `<span class="${v > 1.5 ? "up" : ""}">${names[k] || k} ${v > 0 ? "+" : ""}${v}</span>`).join("")}
    <span>— seuil ${ss.threshold}</span></div>`;
}

/* ===================================================================== IMPORT */
async function viewImport(v) {
  v.append(h(`<div><h1>Importer</h1><p class="sub">Une VOD Twitch / Kick / YouTube (lien) ou un fichier : l'outil trouve les meilleurs moments et crée les clips.</p></div>`));
  const f = h(`<div class="card grid2" style="margin-bottom:20px">
    <div>
      <label class="f"><b>Lien de la vidéo</b><input type="url" id="iu" placeholder="https://www.twitch.tv/videos/… · https://youtu.be/… · https://kick.com/…/videos/…"></label>
      <div class="drop" id="dz">…ou dépose un fichier vidéo ici (cliquer pour choisir)<input type="file" id="if" accept="video/*" hidden></div>
    </div>
    <div>
      <label class="f"><b>Nom du streamer</b><input type="text" id="is" placeholder="optionnel"></label>
      <div class="grid2" style="gap:10px">
        <label class="f"><b>Nombre de clips</b><input type="number" id="in" value="5" min="1" max="30"></label>
        <label class="f"><b>Durée (s)</b><div class="inline"><input type="number" id="imin" placeholder="min"><input type="number" id="imax" placeholder="max"></div></label>
      </div>
      <button class="btn pri" id="ig" style="width:100%;justify-content:center">${ic("sparkles")} Trouver les moments forts</button>
      <p style="color:var(--mute);font-size:12px">Astuce : ajoute des mots-clés dans Réglages → Détection pour repérer aussi ce qui est <i>dit</i> (plus lent : transcription complète).</p>
    </div></div>`);
  v.append(f);
  let file = null;
  const dz = $("#dz", f), fi = $("#if", f);
  dz.onclick = () => fi.click();
  fi.onchange = () => { file = fi.files[0]; if (file) dz.innerHTML = `${ic("folder")} ${esc(file.name)}`; };
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("on"); };
  dz.ondragleave = () => dz.classList.remove("on");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("on"); file = e.dataTransfer.files[0]; dz.innerHTML = `${ic("folder")} ${esc(file.name)}`; };
  $("#ig", f).onclick = async () => {
    const fd = new FormData();
    const url = $("#iu", f).value.trim();
    if (!url && !file) return toast("Colle un lien ou choisis un fichier");
    if (url) fd.append("url", url); if (file) fd.append("file", file);
    fd.append("streamer", $("#is", f).value); fd.append("max_clips", $("#in", f).value || 5);
    if ($("#imin", f).value) fd.append("min_seconds", $("#imin", f).value);
    if ($("#imax", f).value) fd.append("max_seconds", $("#imax", f).value);
    $("#ig", f).disabled = true;
    try { await api("/api/import", { method: "POST", body: fd }); toast("Import lancé"); } catch (e) { toast(e.message); }
    $("#ig", f).disabled = false; file = null; $("#iu", f).value = "";
  };
  const jobs = h(`<div class="card"><h2>Imports &amp; résumés en cours</h2><div id="jl"></div></div>`); v.append(jobs);
  every(async () => {
    const js = await api("/api/jobs");
    $("#jl", jobs).innerHTML = js.length ? js.map((j) => `<div class="job"><div class="row"><b style="overflow:hidden;text-overflow:ellipsis;max-width:70%">${esc(j.label)}</b><div class="spacer"></div>
      <span class="pill ${j.status === "error" ? "error" : j.status === "done" ? "published" : "pending"}">${j.status === "running" ? "en cours" : j.status === "done" ? "terminé" : "erreur"}</span></div>
      <div class="bar"><div style="width:${Math.round((j.progress || 0) * 100)}%"></div></div><small style="color:var(--mute)">${esc(j.message || "")}${j.status === "running" ? ` · ${fmt(Date.now() / 1000 - j.created)} écoulées` : ""}</small></div>`).join("")
      : `<div style="color:var(--mute)">Aucun import.</div>`;
  }, 3000);
}

/* ===================================================================== SETTINGS */
async function viewSettings(v) {
  const S = await api("/api/settings");
  v.append(h(`<div class="row"><div><h1>Réglages</h1><p class="sub">Appliqués à chaud aux lives en cours. Chaque streamer peut avoir ses propres réglages (page Streamers → ${ic("settings")}).</p></div>
    <div class="spacer"></div><button class="btn pri" id="sv">${ic("save")} Enregistrer</button></div>`));
  const d = S.detect, c = S.clip, p = S.publish;
  const names = { chat_rate: "Activité du chat", unique_chatters: "Viewers qui écrivent", laugh_emotes: "Rires (KEKW, 😂, mdr…)", hype_emotes: "Hype (Pog, W, …)", keywords: "Vos mots-clés", audio: "Pics de volume" };
  const g = h(`<div class="grid2">
   <div class="card"><h2>${ic("crosshair")} Détection des moments forts</h2>
     <label class="f"><b>Sensibilité — seuil : <span id="thv">${d.threshold}</span></b><input type="range" min="0.5" max="5" step="0.1" data-p="detect.threshold" value="${d.threshold}" oninput="thv.textContent=this.value"><small>À gauche = plus de clips (plus de déchets) · à droite = seulement les gros moments</small></label>
     <label class="f"><b>Signaux qui doivent monter ensemble</b><select data-p="detect.min_signals" data-n>${[1, 2, 3, 4].map((n) => `<option ${n == d.min_signals ? "selected" : ""}>${n}</option>`).join("")}</select><small>2 recommandé : un spammeur seul ne déclenche rien</small></label>
     <h3>Poids de chaque signal</h3>
     <div class="weights">${Object.keys(names).map((k) => `<span>${names[k]}</span><input type="range" min="0" max="3" step="0.1" data-p="detect.weights.${k}" value="${d.weights[k] ?? 0}" oninput="this.nextElementSibling.textContent=this.value"><b>${d.weights[k] ?? 0}</b>`).join("")}</div>
     <h3>Timing</h3>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Temps de réaction du chat (s)</b><input type="number" data-p="detect.chat_delay_seconds" data-n value="${d.chat_delay_seconds}"><small>Le chat réagit ~5-10 s après l'action</small></label>
      <label class="f"><b>Pause entre 2 clips (s)</b><input type="number" data-p="detect.cooldown_seconds" data-n value="${d.cooldown_seconds}"></label>
      <label class="f"><b>Calibrage au début (s)</b><input type="number" data-p="detect.warmup_seconds" data-n value="${d.warmup_seconds}"></label>
      <label class="f"><b>Max clips / heure</b><input type="number" data-p="detect.max_clips_per_hour" data-n value="${d.max_clips_per_hour}"></label>
     </div>
   </div>
   <div class="card"><h2>${ic("type")} Mots &amp; emotes</h2>
     <label class="f"><b>Mots-clés perso</b><textarea data-p="detect.keywords" data-l placeholder="clip, braquage, la police, nom d'un perso…">${esc(d.keywords.join(", "))}</textarea><small>Dans le chat (live) et dans ce qui est dit (imports). Terminer par * = préfixe (ex. brakage*)</small></label>
     <label class="f"><b>Rires</b><textarea data-p="detect.laugh_words" data-l>${esc(d.laugh_words.join(", "))}</textarea></label>
     <label class="f"><b>Hype</b><textarea data-p="detect.hype_words" data-l>${esc(d.hype_words.join(", "))}</textarea></label>
   </div>
   <div class="card"><h2>${ic("scissors")} Clips</h2>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Durée min (s)</b><input type="number" data-p="clip.min_seconds" data-n value="${c.min_seconds}"></label>
      <label class="f"><b>Durée max (s)</b><input type="number" data-p="clip.max_seconds" data-n value="${c.max_seconds}"></label>
      <label class="f"><b>Avant le pic (s)</b><input type="number" data-p="clip.pre_roll" data-n value="${c.pre_roll}"><small>La montée en tension</small></label>
      <label class="f"><b>Après le pic (s)</b><input type="number" data-p="clip.post_roll" data-n value="${c.post_roll}"><small>La réaction</small></label>
     </div>
     <label class="f"><b>Score viral minimum : <span id="mvv">${c.min_viral}</span>/100</b><input type="range" min="0" max="90" step="5" data-p="clip.min_viral" value="${c.min_viral}" oninput="mvv.textContent=this.value"><small>En dessous, le clip est écarté automatiquement (visible dans « Rejetés » avec la raison). Monte-le si tu as trop de clips.</small></label>
     <label class="inline f"><input type="checkbox" data-p="clip.streamer_only" ${c.streamer_only !== false ? "checked" : ""}><b>Sous-titrer uniquement le streamer</b></label>
     <small style="color:var(--mute);display:block;margin:-8px 0 14px 27px">Les phrases dans une autre langue que celle des sous-titres (voix des PNJ du jeu, vidéo regardée en live…) sont masquées. Réactivables une par une dans la transcription. (Utilise au minimum la précision « Équilibrée ».)</small>
     <label class="inline f"><input type="checkbox" data-p="clip.snap_to_sentences" ${c.snap_to_sentences ? "checked" : ""}><b>Couper entre deux phrases (jamais au milieu d'un mot)</b></label>
     <label class="inline f"><input type="checkbox" data-p="clip.auto_render" ${c.auto_render ? "checked" : ""}><b>Rendu final automatique</b></label>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Langue des sous-titres</b><select data-p="clip.language">${[["fr", "Français"], ["en", "Anglais"], ["es", "Espagnol"], ["", "Auto"]].map(([k, l]) => `<option value="${k}" ${k === (c.language || "") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f"><b>Précision transcription</b><select data-p="clip.whisper_model">${[["base", "Rapide"], ["small", "Équilibrée"], ["medium", "Précise (lent)"], ["large-v3", "Max (GPU)"]].map(([k, l]) => `<option value="${k}" ${k === c.whisper_model ? "selected" : ""}>${l}</option>`).join("")}</select></label>
     </div>
   </div>
   <div class="card"><h2>${ic("palette")} Style par défaut des nouveaux clips</h2><div id="stylebox"></div></div>
   <div class="card"><h2>${ic("bot")} Juge IA (optionnel, payant)</h2>
     <p style="color:var(--mute);margin-top:0">Sans IA, l'outil analyse déjà gratuitement le chat, le son et ce qui est dit. L'IA ajoute un avis + un titre accrocheur. <b>Désactivée par défaut.</b></p>
     <label class="inline f"><input type="checkbox" data-p="ai.enabled" ${S.ai.enabled ? "checked" : ""}><b>Activer le juge IA</b></label>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Fournisseur</b><select data-p="ai.provider"><option value="gemini" ${S.ai.provider === "gemini" ? "selected" : ""}>Gemini (clé GEMINI_API_KEY)</option><option value="ollama" ${S.ai.provider === "ollama" ? "selected" : ""}>Ollama (gratuit, sur ton serveur)</option></select></label>
      <label class="f"><b>Modèle</b><input type="text" data-p="ai.model" value="${esc(S.ai.model)}"></label>
      <label class="f"><b>Plafond d'appels / jour</b><input type="number" data-p="ai.max_calls_per_day" data-n value="${S.ai.max_calls_per_day}"><small>1 appel par clip</small></label>
      <label class="f"><b>Utilisé aujourd'hui</b><input type="text" disabled value="${(S.ai_usage?.day === new Date().toISOString().slice(0, 10) ? S.ai_usage.calls : 0)} appel(s)"></label>
     </div>
     <label class="inline f"><input type="checkbox" data-p="ai.use_title" ${S.ai.use_title ? "checked" : ""}><b>Utiliser le titre proposé par l'IA</b></label>
     <small style="color:var(--mute)">Coût estimé avec gemini-2.5-flash-lite : ~0,0002 $ par clip (≈ 1 000 tokens) → 30 clips/jour ≈ 0,20 $/mois. Le plafond bloque tout dépassement.</small>
   </div>
   <div class="card"><h2>${ic("clapperboard")} Résumés de live</h2>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Transition par défaut</b><select data-p="compilation.transition">${Object.entries(META.transitions).map(([k, l]) => `<option value="${k}" ${k === S.compilation.transition ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f"><b>Durée transition (s)</b><input type="number" step="0.1" data-p="compilation.transition_duration" data-n value="${S.compilation.transition_duration}"></label>
      <label class="f"><b>Nombre de moments</b><input type="number" data-p="compilation.clips" data-n value="${S.compilation.clips}"></label>
      <label class="f"><b>Max par moment (s)</b><input type="number" data-p="compilation.max_each" data-n value="${S.compilation.max_each}"></label>
      <label class="f"><b>Fenêtre (heures)</b><input type="number" data-p="compilation.hours" data-n value="${S.compilation.hours}"></label>
     </div>
   </div>
   <div class="card"><h2>${ic("send")} Publication (Post for Me)</h2>
     <label class="inline f"><input type="checkbox" data-p="publish.auto_publish" ${p.auto_publish ? "checked" : ""}><b>Publier automatiquement quand j'approuve</b></label>
     <label class="f"><b>Comptes sociaux (IDs Post for Me)</b><input type="text" data-p="publish.social_accounts" data-l value="${esc(p.social_accounts.join(", "))}" placeholder="spc_xxx, spc_yyy"></label>
     <label class="f"><b>Légende</b><input type="text" data-p="publish.caption_template" value="${esc(p.caption_template)}"><small>Variables : {title} {streamer} {platform}</small></label>
   </div>
   <div class="card"><h2>${ic("radio")} Surveillance</h2>
     <label class="f"><b>Vérifier les lives toutes les (s)</b><input type="number" data-p="poll_seconds" data-n value="${S.poll_seconds}"></label>
     <label class="f"><b>Qualité d'enregistrement</b><input type="text" data-p="record.quality" value="${esc(S.record.quality)}"><small>Ordre de préférence Streamlink</small></label>
     <label class="f"><b>Mémoire du live (min)</b><input type="number" data-p="record.buffer_minutes" data-n value="${S.record.buffer_minutes}"></label>
   </div>
  </div>`);
  v.append(g);
  const style = deep(S.style), layout = deep(S.layout), hook = deep(S.hook);
  styleControls($("#stylebox", g), style, layout, hook, () => { });
  $("#sv").onclick = async () => {
    const out = {};
    $$("[data-p]", g).forEach((i) => {
      let val = i.type === "checkbox" ? i.checked : i.value;
      if (i.hasAttribute("data-l")) val = val.split(",").map((x) => x.trim()).filter(Boolean);
      else if (i.hasAttribute("data-n") || i.type === "range") val = Number(val);
      const ks = i.dataset.p.split("."); let o = out;
      ks.slice(0, -1).forEach((k) => o = o[k] ??= {}); o[ks.at(-1)] = val;
    });
    out.style = style; out.layout = { ...S.layout, mode: layout.mode }; out.hook = hook;
    await api("/api/settings", { method: "PUT", json: out }); toast("Réglages enregistrés");
  };
}

/* ---------- contrôles de style partagés (réglages + éditeur) */
function styleControls(box, st, layout, hook, onChange) {
  const ch = () => onChange();
  box.innerHTML = `
    <div class="presets">${Object.entries(META.presets).map(([k, p]) => { const q = { ...META.caption_base, ...p }; return `<button data-pr="${k}" title="${esc(p.label)}" class="${st.preset === k ? "on" : ""}"
      style="font-family:'${q.font}';color:${q.highlight_mode === "box" ? q.highlight_text : q.highlight};${q.highlight_mode === "box" ? `background:${q.highlight};` : ""}${q.box ? `background:${q.box_color};` : ""}${q.glow ? `text-shadow:0 0 8px ${q.glow_color};` : ""}text-transform:${q.uppercase ? "uppercase" : "none"}">${esc(p.label)}</button>`; }).join("")}</div>
    <h3>Animation</h3>
    <div class="grid2" style="gap:10px">
      <label class="f"><b>Mot prononcé</b><select data-s="word_anim">${Object.entries(META.word_anims).map(([k, l]) => `<option value="${k}" ${k === st.word_anim ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f"><b>Apparition des mots</b><select data-s="reveal"><option value="all" ${st.reveal !== "progressive" ? "selected" : ""}>Toute la ligne</option><option value="progressive" ${st.reveal === "progressive" ? "selected" : ""}>Au fur et à mesure</option></select></label>
      <label class="f"><b>Entrée de ligne</b><select data-s="line_in">${Object.entries(META.line_anims).map(([k, l]) => `<option value="${k}" ${k === st.line_in ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f"><b>Sortie de ligne</b><select data-s="line_out"><option value="none" ${st.line_out !== "fade" ? "selected" : ""}>Aucune</option><option value="fade" ${st.line_out === "fade" ? "selected" : ""}>Fondu</option></select></label>
      <label class="f"><b>Mot actif</b><select data-s="highlight_mode"><option value="color" ${st.highlight_mode !== "box" ? "selected" : ""}>Couleur</option><option value="box" ${st.highlight_mode === "box" ? "selected" : ""}>Dans une boîte</option></select></label>
      <label class="f"><b>Bruitage</b><div class="inline"><select data-s="sfx">${Object.entries(META.sfx).map(([k, l]) => `<option value="${k}" ${k === (st.sfx || "none") ? "selected" : ""}>${l}</option>`).join("")}</select>
        <select data-s="sfx_on"><option value="line" ${st.sfx_on === "line" ? "selected" : ""}>chaque ligne</option><option value="emphasis" ${st.sfx_on === "emphasis" ? "selected" : ""}>mots forts</option><option value="word" ${st.sfx_on === "word" ? "selected" : ""}>chaque mot</option></select>
        <button class="btn sm" data-sfxplay title="Écouter">${ic("volume-2")}</button></div></label>
    </div>
    <div class="row" style="margin-bottom:12px">
      <label class="inline"><input type="checkbox" data-s="glow" ${st.glow ? "checked" : ""}> Halo lumineux</label><input type="color" data-s="glow_color" value="${st.glow_color || "#FF8800"}">
      <label class="inline">Texte du mot encadré <input type="color" data-s="highlight_text" value="${st.highlight_text || "#000000"}"></label>
      <label class="inline">Mots pas encore dits <input type="color" data-s="pending_color" value="${st.pending_color || st.color}"></label>
    </div>
    <div class="grid2" style="gap:10px">
      <label class="f"><b>Police</b><select data-s="font">${META.fonts.map((f) => `<option ${f === st.font ? "selected" : ""} style="font-family:'${f}'">${f}</option>`).join("")}</select></label>
      <label class="f"><b>Taille <span>${st.size}</span></b><input type="range" min="40" max="180" data-s="size" data-n value="${st.size}"></label>
      <label class="f"><b>Position verticale <span>${st.position}%</span></b><input type="range" min="10" max="90" data-s="position" data-n value="${st.position}"></label>
      <label class="f"><b>Mots par ligne <span>${st.words_per_line}</span></b><input type="range" min="1" max="7" data-s="words_per_line" data-n value="${st.words_per_line}"></label>
      <label class="f"><b>Contour <span>${st.outline}</span></b><input type="range" min="0" max="14" data-s="outline" data-n value="${st.outline}"></label>
      <label class="f"><b>Ombre <span>${st.shadow}</span></b><input type="range" min="0" max="10" data-s="shadow" data-n value="${st.shadow}"></label>
    </div>
    <div class="row" style="margin-bottom:12px">
      <label class="inline">Texte <input type="color" data-s="color" value="${st.color}"></label>
      <label class="inline">Mot actif <input type="color" data-s="highlight" value="${st.highlight}"></label>
      <label class="inline">Contour <input type="color" data-s="outline_color" value="${st.outline_color}"></label>
    </div>
    <div class="row" style="margin-bottom:14px">
      <label class="inline"><input type="checkbox" data-s="uppercase" ${st.uppercase ? "checked" : ""}> MAJUSCULES</label>
      <label class="inline"><input type="checkbox" data-s="clean_punct" ${st.clean_punct !== false ? "checked" : ""}> Sans ponctuation</label>
      <label class="inline"><input type="checkbox" data-s="remove_fillers" ${st.remove_fillers !== false ? "checked" : ""}> Retirer « euh, bah »</label>
    </div>
    <div class="row" style="margin-bottom:12px">
      <label class="inline"><input type="checkbox" data-s="emphasis" ${st.emphasis !== false ? "checked" : ""}> Mots forts en couleur</label>
      <input type="color" data-s="emphasis_color" value="${st.emphasis_color || "#FF4D4D"}">
      <label class="inline"><input type="checkbox" data-s="box" ${st.box ? "checked" : ""}> Fond en boîte</label>
      <input type="color" data-s="box_color" value="${st.box_color || "#000000"}">
      <label class="inline">opacité <input type="number" min="0" max="100" style="width:64px" data-s="box_opacity" data-n value="${st.box_opacity ?? 70}"></label>
    </div>
    <div class="row" style="margin-bottom:14px">
      <label class="inline"><input type="checkbox" data-s="auto_position" ${st.auto_position !== false ? "checked" : ""}> Position auto (sur la jonction cam / jeu en format 50/50)</label>
    </div>
    <h3>Format</h3>
    <div class="layouts">${layoutBtns(layout.mode)}</div>
    <h3>Titre d'accroche (hook)</h3>
    <div class="row"><label class="inline"><input type="checkbox" data-hk="enabled" ${hook.enabled ? "checked" : ""}> Afficher</label>
      <label class="inline">pendant <input type="number" step="0.5" style="width:70px" data-hk="seconds" value="${hook.seconds}"> s</label>
      <label class="inline">Texte <input type="color" data-hk="color" value="${hook.color}"></label>
      <label class="inline">Fond <input type="color" data-hk="bg" value="${hook.bg}"></label></div>`;
  $$("[data-pr]", box).forEach((b) => b.onclick = () => {
    const keep = { position: st.position, auto_position: st.auto_position, clean_punct: st.clean_punct, remove_fillers: st.remove_fillers };
    for (const k of Object.keys(st)) delete st[k];
    Object.assign(st, META.caption_base, META.presets[b.dataset.pr], keep, { preset: b.dataset.pr }); delete st.label;
    styleControls(box, st, layout, hook, onChange); ch();
  });
  const sp = $("[data-sfxplay]", box); if (sp) sp.onclick = (e) => { e.preventDefault(); if (st.sfx && st.sfx !== "none") new Audio(`${MB}/sfx/${st.sfx}.mp3`).play(); };
  $$("[data-s]", box).forEach((i) => i.oninput = () => {
    st[i.dataset.s] = i.type === "checkbox" ? i.checked : i.hasAttribute("data-n") ? Number(i.value) : i.value;
    const lab = i.previousElementSibling?.querySelector?.("span"); if (lab) lab.textContent = i.value + (i.dataset.s === "position" ? "%" : "");
    st.preset = "custom"; ch();
  });
  $$("[data-hk]", box).forEach((i) => i.oninput = () => { hook[i.dataset.hk] = i.type === "checkbox" ? i.checked : i.type === "number" ? Number(i.value) : i.value; ch(); });
  $$("[data-lm]", box).forEach((b) => b.onclick = () => { layout.mode = b.dataset.lm; $$("[data-lm]", box).forEach((x) => x.classList.toggle("on", x === b)); ch(); });
}
function layoutBtns(mode) {
  const L = {
    blur: ["Fond flou", `<rect x="1" y="1" width="26" height="44" rx="3" fill="#555"/><rect x="1" y="16" width="26" height="14" fill="#a78bfa"/>`],
    fill: ["Plein écran", `<rect x="1" y="1" width="26" height="44" rx="3" fill="#a78bfa"/>`],
    split: ["Cam + jeu", `<rect x="1" y="1" width="26" height="21" rx="3" fill="#f472b6"/><rect x="1" y="24" width="26" height="21" rx="3" fill="#38bdf8"/>`],
    pip: ["Cam incrustée", `<rect x="1" y="1" width="26" height="44" rx="3" fill="#38bdf8"/><rect x="4" y="6" width="11" height="8" rx="2" fill="#f472b6" stroke="#fff"/>`],
    fit: ["Bandes noires", `<rect x="1" y="1" width="26" height="44" rx="3" fill="#111"/><rect x="1" y="16" width="26" height="14" fill="#a78bfa"/>`],
  };
  return Object.entries(L).map(([k, [n, svg]]) => `<button data-lm="${k}" class="${mode === k ? "on" : ""}"><svg viewBox="0 0 28 46">${svg}</svg>${n}</button>`).join("");
}

/* ===================================================================== EDITOR */
const EMOTION = new Set(["putain","wesh","frère","frérot","gros","zebi","sah","dingue","dinguerie","incroyable","jamais","mdr","ptdr","oh","ah","non","attends","attend","quoi","comment","sérieux","sérieusement","fou","folie","malade","choqué","choquant","ouf","énorme","abusé","abuse","trop","nul","merde","bordel","honte","pitié","aïe","chaud","grave","omg","wtf","arrête","arrêtez","regarde","regardez","vas-y","allez","bravo","gagné","perdu","mort","tué","police","flic","braquage","argent","million","bro","dude","insane","crazy","what","wait","no","yes","god","fuck","shit","damn","holy","never","dead","won","lost","money","cops","run"]);
const FILLERS = new Set(["euh", "heu", "hum", "bah", "ben", "hein", "um", "uh", "erm"]);
const baseWord = (w) => w.toLowerCase().replace(/[^\p{L}\p{N}'’-]/gu, "");
function prepareWords(words, st, keywords) { // identique à captions.prepare_words (Python)
  const kws = (keywords || []).map((k) => k.toLowerCase().replace(/\*$/, "")).filter(Boolean);
  const out = [];
  for (const w of words) {
    if (w.skip) continue; // voix du jeu / autre langue : jamais en sous-titre
    const raw = (w.w || "").trim(), b = baseWord(raw);
    if (st.remove_fillers !== false && FILLERS.has(b)) continue;
    const txt = st.clean_punct !== false ? raw.replace(/[.,;:…«»"“”()]+/g, "") : raw;
    if (!txt.trim()) continue;
    const emph = st.emphasis !== false && !!b && (EMOTION.has(b) || kws.some((k) => b.startsWith(k)) || /\d/.test(b));
    out.push({ ...w, w: txt, p: ".?!,;:".includes(raw.slice(-1)) ? raw.slice(-1) : "", x: emph, src: w });
  }
  return out;
}
const captionY = (st, L) => (st.auto_position !== false && L && L.mode === "split") ? L.split_ratio * 100 : st.position;
function groupWords(words, perLine, maxChars) { // identique à captions.group_words (Python)
  const lines = []; let cur = [];
  for (const w of words) {
    if (!(w.w || "").trim()) continue;
    if (cur.length) {
      const gap = w.s - cur.at(-1).e;
      const chars = cur.reduce((a, x) => a + x.w.trim().length + 1, 0) + w.w.trim().length;
      const lp = cur.at(-1).p ?? cur.at(-1).w.trim().slice(-1);
      if (cur.length >= perLine || gap > 0.6 || chars > maxChars || (lp && ".?!,".includes(lp))) { lines.push(cur); cur = []; }
    }
    cur.push(w);
  }
  if (cur.length) lines.push(cur);
  return lines;
}
function cropRect(r, iw, ih, aspect) { // identique à clipper._crop
  const pw = r.w * iw, ph = r.h * ih; let nw, nh;
  if (pw / ph > aspect) { nw = ph * aspect; nh = ph; } else { nw = pw; nh = pw / aspect; }
  const cx = r.x * iw + pw / 2, cy = r.y * ih + ph / 2;
  return { x: clamp(cx - nw / 2, 0, iw - nw), y: clamp(cy - nh / 2, 0, ih - nh), w: nw, h: nh };
}

async function viewEditor(v, id) {
  const clip = await api(`/api/clips/${id}`);
  let words = deep(clip.words || []);
  const E = clip.edit && clip.edit.trim ? deep(clip.edit) : { trim: [0, clip.duration || 30], style: {}, layout: { mode: "blur" }, hook: {}, title: clip.title || "" };
  const S = await api("/api/settings");
  E.style = { ...S.style, ...E.style }; E.layout = { ...S.layout, ...E.layout }; E.hook = { ...S.hook, ...E.hook };
  E.speed = E.speed || 1;
  if (!E.segments || !E.segments.length) E.segments = [{ s: E.trim[0], e: E.trim[1], effect: "none", transition: { type: "fade", duration: 0.4 } }];
  let curSeg = 0;
  /* ---- montage : segments -> temps de la vidéo finale (même calcul que clipper.timeline) */
  const segSpeed = (g) => E.speed * (g.effect === "slowmo" ? 0.75 : g.effect === "fast" ? 1.25 : 1);
  function tline() {
    let t = 0; return E.segments.map((g, i) => {
      const d = (g.e - g.s) / segSpeed(g), tr = g.transition || {};
      const td = i === 0 || (tr.type || "cut") === "cut" ? 0 : Math.min(tr.duration ?? 0.4, d / 2);
      const st = t - td; t = st + d; return { ...g, os: st, od: d, td };
    });
  }
  const outDur = () => { const T = tline(); return T.length ? T.at(-1).os + T.at(-1).od : 0; };
  const segAt = (t) => E.segments.findIndex((g) => t >= g.s - 0.02 && t < g.e);
  const outTime = (t) => { const T = tline(), i = segAt(t); return i < 0 ? 0 : T[i].os + (t - T[i].s) / segSpeed(T[i]); };
  let reordered = E.segments.some((g, i) => i && g.s < E.segments[i - 1].s);
  const syncTrim = () => { if (!reordered) E.segments.sort((a, b) => a.s - b.s); E.trim = [Math.min(...E.segments.map((g) => g.s)), Math.max(...E.segments.map((g) => g.e))]; };
  let dirty = false, shift = 0;
  let tlTimer = null, tlBusy = false;
  const mark = () => {
    dirty = true; $("#dirty").hidden = false; draw();
    if (!tlBusy && typeof renderTL === "function") { clearTimeout(tlTimer); tlTimer = setTimeout(() => { if (!tlBusy) renderTL(); }, 250); }
  };

  v.append(h(`<div class="row" style="margin-bottom:16px">
    <a class="btn sm" href="#/clips">${ic("chevron-left")} Clips</a>
    <input type="text" id="ttl" value="${esc(E.title)}" placeholder="Titre d'accroche du clip" style="flex:1;min-width:200px;font-weight:600;font-size:16px">
    <span class="pill ${clip.status}">${statusLabel(clip.status)}</span></div>`));
  const ed = h(`<div class="ed">
    <div class="stage">
      <div class="phone" id="ph"></div>
      <div class="controls">
        <button class="btn sm" id="pp">${ic("play")}</button><button class="btn sm" id="rw">${ic("skip-back")} début</button>
        <select id="spd" style="width:auto;padding:5px 8px">${[0.9, 1, 1.1, 1.2, 1.25].map((s) => `<option ${s == E.speed ? "selected" : ""}>${s}</option>`).join("")}</select>
        <span class="time" id="tm"></span></div>
      <button class="btn" id="trb" style="width:100%;max-width:380px;justify-content:center">${ic("file-text")} Afficher la transcription</button>
      <div id="trp" class="trp" hidden></div>
      <div class="savebar">
        <button class="btn" id="save">${ic("save")} Enregistrer</button>
        <button class="btn pri" id="rend">${ic("clapperboard")} Rendu final</button>
        <span id="dirty" class="pill pending" hidden>modifs non enregistrées</span>
      </div>
      <div class="savebar" id="outbar"></div>
    </div>
    <div class="panel">
      <div class="ptabs">${["Montage", "Sous-titres", "Style", "Cadrage", "Calques", "Pourquoi ?", "Publier"].map((t, i) => `<button data-t="${i}" class="${i ? "" : "on"}">${t}</button>`).join("")}</div>
      <div class="pbody" id="pb"></div>
    </div></div>`);
  v.append(ed);
  $("#ttl").oninput = (e) => { E.title = e.target.value; mark(); };
  const tsug = h(`<div class="tsug"><span>${ic("lightbulb")} Idées de titre :</span></div>`);
  $("#ttl").closest(".row").after(tsug);
  const showTitles = (list) => {
    $$("button", tsug).forEach((b) => b.parentNode.removeChild(b));
    for (const t of list) { const b = h(`<button class="chip">${esc(t)}</button>`); b.onclick = () => { E.title = t; $("#ttl").value = t; mark(); }; tsug.append(b); }
    const r = h(`<button class="chip" title="Recalculer">${ic("dices")}</button>`); r.onclick = async () => showTitles(await api(`/api/clips/${clip.id}/titles`)); tsug.append(r);
    const n = h(`<button class="chip" title="Pas de titre">${ic("x")} aucun</button>`); n.onclick = () => { E.title = ""; $("#ttl").value = ""; mark(); }; tsug.append(n);
  };
  showTitles(clip.detail?.title_options || []);
  if (!clip.detail?.title_options) api(`/api/clips/${clip.id}/titles`).then(showTitles).catch(() => { });

  /* ---- lecteurs vidéo (un maître avec le son + des copies muettes pour les calques) */
  const src = `${MB}/media/${clip.id}/source`;
  const master = h(`<video preload="auto" playsinline webkit-playsinline src="${src}"></video>`);
  master.style.display = "none"; ed.append(master);
  let iw = 1920, ih = 1080, dur = 1;
  const ph = $("#ph"), copies = [];
  const mk = () => { const x = h(`<video muted playsinline webkit-playsinline preload="auto" src="${src}#t=${(E.trim?.[0] || 0).toFixed(2)}"></video>`); x.muted = true; copies.push(x); try { x.load(); } catch { } return x; };
  const capEl = h(`<div class="capw"></div>`), hookEl = h(`<div class="hookl"></div>`);

  function buildStage() {
    ph.innerHTML = ""; copies.length = 0;
    const W = ph.clientWidth, H = ph.clientHeight, L = E.layout;
    const place = (vid, box, bw, bh, r) => {
      const s = bw / r.w;
      Object.assign(vid.style, { width: `${iw * s}px`, height: `${ih * s}px`, left: `${-r.x * s}px`, top: `${-r.y * s}px` });
      box.append(vid);
    };
    const box = (top, hh) => { const b = h(`<div class="box"></div>`); Object.assign(b.style, { top: `${top}px`, height: `${hh}px` }); ph.append(b); return b; };
    if (L.mode === "split") {
      const th = Math.round(H * L.split_ratio), bh = H - th;
      if (L.cam_position === "bottom") {
        place(mk(), box(0, th), W, th, cropRect(L.gameplay, iw, ih, W / th));
        place(mk(), box(th, bh), W, bh, cropRect(L.facecam, iw, ih, W / bh));
      } else {
        place(mk(), box(0, th), W, th, cropRect(L.facecam, iw, ih, W / th));
        place(mk(), box(th, bh), W, bh, cropRect(L.gameplay, iw, ih, W / bh));
      }
    } else if (L.mode === "pip") {
      place(mk(), box(0, H), W, H, cropRect(L.gameplay, iw, ih, W / H));
      const fc = L.facecam, cw = W * (L.pip_size || .42), chh = Math.min(cw * (fc.h * ih) / (fc.w * iw), H / 2);
      const k = W / 1080, m = 40 * k, c = L.pip_corner || "tl";
      const b = h(`<div class="box" style="border:${6 * k}px solid #fff;border-radius:${10 * k}px;box-sizing:content-box"></div>`);
      Object.assign(b.style, { width: `${cw}px`, height: `${chh}px`, left: c[1] === "l" ? `${m}px` : `${W - cw - m - 12 * k}px`,
        top: c[0] === "t" ? `${220 * k}px` : `${H - chh - (m + 200 * k) - 12 * k}px` });
      ph.append(b); place(mk(), b, cw, chh, cropRect(fc, iw, ih, cw / chh));
    } else if (L.mode === "fill") {
      const nw = ih * 9 / 16; const x = clamp((L.focus?.x ?? .5) * iw - nw / 2, 0, iw - nw);
      place(mk(), box(0, H), W, H, { x, y: 0, w: nw, h: ih });
    } else {
      const b = box(0, H);
      if (L.mode === "blur") { const bg = mk(); bg.classList.add("bgv"); const s = Math.max(W / iw, H / ih); Object.assign(bg.style, { width: `${iw * s}px`, height: `${ih * s}px`, left: `${(W - iw * s) / 2}px`, top: `${(H - ih * s) / 2}px` }); b.append(bg); }
      const fg = mk(); const fw = W * (L.mode === "blur" ? (L.zoom || 1) : 1), fh = fw * ih / iw;
      Object.assign(fg.style, { width: `${fw}px`, height: `${fh}px`, left: `${(W - fw) / 2}px`, top: `${(H - fh) / 2}px` }); b.append(fg);
    }
    ph.append(fx, ovlEl, capEl, hookEl); capEl.style.zIndex = hookEl.style.zIndex = 3; ovlEl.style.zIndex = 4; capKey = "";
    ovlNodes.forEach((n) => n.el.remove()); ovlNodes.clear();
    copies.forEach((c) => { c.currentTime = master.currentTime; });
    draw();
  }

  /* ---- sous-titres & hook (même logique que le rendu ASS) */
  let lines = [];
  const mctx = document.createElement("canvas").getContext("2d");
  let capKey = "", capWords = [], capLineIdx = -1;
  function capLayout(line, st, k) { // identique à captions.layout_line (Python)
    const ratio = META.font_ratio[st.font] || 0.64, px = st.size * ratio;
    mctx.font = `${px}px '${st.font}'`;
    const texts = line.map((w) => st.uppercase ? w.w.toUpperCase() : w.w);
    const widths = texts.map((t) => mctx.measureText(t).width);
    const space = mctx.measureText(" ").width + px * (st.highlight_mode === "box" ? 0.32 : 0.2);
    const rows = []; let cur = [], cw = 0;
    widths.forEach((wd, i) => { const add = cur.length ? cw + space + wd : wd; if (cur.length && add > 1080 * 0.86) { rows.push(cur); cur = [i]; cw = wd; } else { cur.push(i); cw = add; } });
    if (cur.length) rows.push(cur);
    const rowH = px * 1.25, yc = 1920 * captionY(st, E.layout) / 100, y0 = yc - (rows.length - 1) * rowH / 2;
    const out = [];
    rows.forEach((idx, r) => {
      const total = idx.reduce((a, i) => a + widths[i], 0) + space * (idx.length - 1); let x = 540 - total / 2;
      for (const i of idx) { out[i] = { text: texts[i], x: (x + widths[i] / 2) * k, y: (y0 + r * rowH) * k, w: widths[i] * k, row: r }; x += widths[i] + space; }
    });
    return { pos: out, px: px * k, rows: rows.length };
  }
  function drawCaptions(t, k) {
    const st = { ...META.caption_base, ...E.style };
    if (E.captions === false) { capEl.innerHTML = ""; capLineIdx = -1; return; }
    lines = groupWords(prepareWords(words.filter((w) => E.segments.some((g) => w.s >= g.s - 0.01 && w.s < g.e)), st, S.detect.keywords), st.words_per_line, st.max_chars || 18);
    let li = -1;
    for (let i = 0; i < lines.length; i++) {
      const L = lines[i], nx = lines[i + 1], end = Math.min(L.at(-1).e + 0.25, nx ? nx[0].s : 1e9);
      if (t >= L[0].s && t < end) { li = i; break; }
    }
    const key = JSON.stringify([st, li, k, E.layout.mode, E.layout.split_ratio]);
    if (li < 0) { capEl.innerHTML = ""; capLineIdx = -1; capKey = ""; return; }
    const L = lines[li];
    if (key !== capKey) { // (re)construction de la ligne
      capKey = key;
      const { pos, px } = capLayout(L, st, k);
      capEl.innerHTML = ""; capWords = [];
      Object.assign(capEl.style, { position: "absolute", inset: 0, transform: "none", left: 0, right: 0, top: 0, fontFamily: `'${st.font}'`, fontSize: `${px}px`, lineHeight: 1 });
      if (st.box) {
        const a = Math.round((st.box_opacity ?? 70) * 2.55).toString(16).padStart(2, "0");
        [...new Set(pos.map((p) => p.row))].forEach((r) => {
          const ps = pos.filter((p) => p.row === r), pad = st.size * 0.14 * 1.6 * k;
          const x0 = Math.min(...ps.map((p) => p.x - p.w / 2)) - pad, x1 = Math.max(...ps.map((p) => p.x + p.w / 2)) + pad, hh = px * 0.62;
          capEl.append(h(`<div style="position:absolute;left:${x0}px;top:${ps[0].y - hh}px;width:${x1 - x0}px;height:${hh * 2}px;border-radius:${st.size * 0.25 * k}px;background:${st.box_color}${a}"></div>`));
        });
      }
      pos.forEach((p, i) => {
        const el = h(`<span class="cw">${esc(p.text)}</span>`);
        Object.assign(el.style, { left: `${p.x}px`, top: `${p.y}px`,
          WebkitTextStroke: st.outline ? `${st.outline * 2 * k}px ${st.outline_color}` : "0",
          textShadow: [st.shadow ? `${st.shadow * k}px ${st.shadow * k}px ${2 * k}px #000000aa` : "", st.glow ? `0 0 ${10 * k}px ${st.glow_color}, 0 0 ${22 * k}px ${st.glow_color}` : ""].filter(Boolean).join(",") || "none",
          padding: st.highlight_mode === "box" ? `0 ${st.size * 0.14 * 1.2 * k}px` : "0", borderRadius: `${st.size * 0.2 * k}px` });
        capEl.append(el); capWords.push({ el, w: L[i], state: "" });
      });
      if (li !== capLineIdx && st.reveal !== "progressive") {
        const anim = { fade: [{ opacity: 0 }, { opacity: 1 }], slide_up: [{ transform: `translateY(${50 * k}px)`, opacity: 0 }, { transform: "none", opacity: 1 }],
          slide_left: [{ transform: `translateX(${90 * k}px)`, opacity: 0 }, { transform: "none", opacity: 1 }], zoom: [{ transform: "scale(.7)", opacity: .3 }, { transform: "none", opacity: 1 }] }[st.line_in];
        if (anim) capEl.animate(anim, { duration: 200, easing: "ease-out" });
      }
      capLineIdx = li;
    }
    const wa = st.word_anim;
    capWords.forEach((cw, i) => {
      const nxt = i + 1 < L.length ? L[i + 1].s : 1e9;
      const state = t < cw.w.s ? "pend" : t < nxt ? "act" : "done";
      if (state === cw.state) return;
      cw.state = state; const el = cw.el;
      el.style.visibility = state === "pend" && st.reveal === "progressive" ? "hidden" : "visible";
      el.style.background = state === "act" && st.highlight_mode === "box" ? st.highlight : "transparent";
      el.style.color = state === "act" ? (st.highlight_mode === "box" ? st.highlight_text : st.highlight)
        : cw.w.x ? st.emphasis_color : state === "pend" ? (st.pending_color || st.color) : st.color;
      if (state === "act") {
        const kf = { pop: [{ transform: "translate(-50%,-50%) scale(1)" }, { transform: "translate(-50%,-50%) scale(1.16)", offset: .45 }, { transform: "translate(-50%,-50%) scale(1.08)" }],
          zoom: [{ transform: "translate(-50%,-50%) scale(.45)" }, { transform: "translate(-50%,-50%) scale(1.15)", offset: .58 }, { transform: "translate(-50%,-50%) scale(1.04)" }],
          bounce: [{ transform: "translate(-50%,-30%) scale(1)" }, { transform: "translate(-50%,-50%) scale(1.12)", offset: .5 }, { transform: "translate(-50%,-50%) scale(1.04)" }] }[wa];
        if (kf) el.animate(kf, { duration: wa === "zoom" ? 190 : 170, fill: "forwards", easing: "ease-out" });
      } else { el.getAnimations().forEach((x) => x.cancel()); }
    });
  }
  function draw() {
    const st = E.style, k = ph.clientWidth / 1080, t = master.currentTime - shift;
    drawCaptions(t, k);
    drawOverlays(k); tlPlayhead();
    const hk = E.hook, showH = hk.enabled && E.title && segAt(master.currentTime) >= 0 && outTime(master.currentTime) < hk.seconds;
    Object.assign(hookEl.style, { top: `${170 * k}px`, fontFamily: `'${st.font}'`, fontSize: `${(hk.size || 72) * k}px`, color: hk.color });
    hookEl.innerHTML = showH ? `<span style="background:${hk.bg}">${esc(E.title.replace(/\s+([!?:;»])/g, "\u00a0$1"))}</span>` : "";
    $("#tm").textContent = `${fmt(outTime(master.currentTime))} / ${fmt(outDur())}`;
    $$(".words .w").forEach((el) => { const w = words[el.dataset.i]; el.classList.toggle("cur", !!w && t >= w.s && t < w.e); });
    const tlph = $(".tl .ph"); if (tlph) tlph.style.left = `${(master.currentTime / dur) * 100}%`;
  }
  let raf;
  const loop = () => {
    if (!master.paused) {
      const t = master.currentTime, g = E.segments[curSeg];
      if (!g || t >= g.e - 0.03 || t < g.s - 0.5) {
        const nx = g && t >= g.e - 0.03 ? curSeg + 1 : E.segments.findIndex((x) => t < x.e);
        if (nx < 0 || nx >= E.segments.length) { master.pause(); curSeg = 0; seek(E.segments[0].s); }
        else { curSeg = nx; const n = E.segments[nx]; if (Math.abs(t - n.s) > 0.05) seek(n.s); flashTransition(n.transition, nx); }
      }
      const cg = E.segments[curSeg]; if (cg) { const r = segSpeed(cg); if (Math.abs(master.playbackRate - r) > 1e-3) master.playbackRate = r; }
    }
    applyEffect();
    for (const c of copies) { if (Math.abs(c.currentTime - master.currentTime) > 0.12) c.currentTime = master.currentTime; if (master.paused !== c.paused) master.paused ? c.pause() : c.play().catch(() => { }); }
    const ppi = master.paused ? "play" : "pause"; if ($("#pp").dataset.i !== ppi) { $("#pp").dataset.i = ppi; $("#pp").innerHTML = ic(ppi); }
    draw(); raf = requestAnimationFrame(loop);
  };
  const seek = (t) => { master.currentTime = clamp(t, 0, dur); copies.forEach((c) => c.currentTime = master.currentTime); };
  $("#pp").onclick = () => {
    if (master.paused) { curSeg = segAt(master.currentTime); if (curSeg < 0) { curSeg = Math.max(E.segments.findIndex((g) => master.currentTime < g.s), 0); seek(E.segments[curSeg].s); } master.play(); }
    else master.pause();
  };
  $("#rw").onclick = () => { curSeg = 0; seek(E.segments[0].s); };
  const fx = h(`<div style="position:absolute;inset:0;pointer-events:none;opacity:0;z-index:2"></div>`);
  function flashTransition(tr, i) { // aperçu simplifié (le rendu final utilise les vraies transitions ffmpeg)
    const type = tr?.type || "cut"; if (!i || type === "cut") return;
    const d = (tr.duration ?? 0.4) * 1000;
    fx.style.background = type === "fadewhite" ? "#fff" : "#000";
    fx.animate([{ opacity: type.startsWith("fade") || type === "dissolve" ? 0.9 : 0.5 }, { opacity: 0 }], { duration: d });
    if (/slide|wipe|smooth/.test(type)) { const dir = /left/.test(type) ? "100%,0" : /right/.test(type) ? "-100%,0" : /up/.test(type) ? "0,100%" : "0,-100%"; $$(".box", ph).forEach((b) => b.animate([{ transform: `translate(${dir})` }, { transform: "none" }], { duration: d, easing: "ease-out" })); }
    if (["zoomin", "circleopen", "radial"].includes(type)) $$(".box", ph).forEach((b) => b.animate([{ transform: "scale(1.4)", opacity: .3 }, { transform: "none", opacity: 1 }], { duration: d }));
  }
  function applyEffect() {
    const g = E.segments[segAt(master.currentTime)], ef = g?.effect || "none";
    let tf = "none"; const p = g ? clamp((master.currentTime - g.s) / (g.e - g.s), 0, 1) : 0;
    if (ef === "punch") tf = "scale(1.18)"; else if (ef === "zoomin") tf = `scale(${1 + 0.15 * p})`; else if (ef === "zoomout") tf = `scale(${1.15 - 0.15 * p})`;
    $$(".box", ph).forEach((b) => { if (!b.getAnimations().length) b.style.transform = tf; b.style.filter = ef === "bw" ? "grayscale(1)" : ""; });
  }
  $("#spd").onchange = (e) => { E.speed = Number(e.target.value); master.playbackRate = E.speed; mark(); };
  const ro = new ResizeObserver(() => buildStage()); ro.observe(ph);
  window._edCleanup = () => { cancelAnimationFrame(raf); ro.disconnect(); master.pause(); window.onbeforeunload = null; };
  window.onbeforeunload = () => dirty ? "" : undefined;
  /* =================================================================== TIMELINE MULTI-PISTES
     Calques (textes, emojis, images, vidéos, sons) posés sur le temps de la vidéo FINALE. */
  E.overlays = E.overlays || [];
  let selId = null, tlZoom = 1;
  const OCOL = { text: "#a855f7", emoji: "#f59e0b", image: "#22c55e", video: "#3b82f6", audio: "#ef4444" };
  const OICO = { text: ic("type"), emoji: ic("smile"), image: ic("image"), video: ic("film"), audio: ic("music") };
  const uid = () => Math.random().toString(36).slice(2, 9);
  const srcOf = (T) => { // temps final → temps source (inverse de outTime)
    const TL = tline(); let g = TL[0];
    for (const x of TL) if (T >= x.os) g = x;
    return g ? g.s + clamp(T - g.os, 0, g.od) * segSpeed(g) : 0;
  };
  const seekOut = (T) => { const s0 = srcOf(clamp(T, 0, outDur() - 0.01)); curSeg = Math.max(segAt(s0), 0); seek(s0); };
  const selItem = () => E.overlays.find((o) => o.id === selId);
  const ovlLabel = (o) => o.type === "text" ? (o.text || "Texte") : o.type === "emoji" ? o.emoji : (o.src || "").replace(/^(asset|sfx):/, "");

  function addOverlay(o) {
    const T = outTime(master.currentTime), D = outDur();
    const dur = o.dur || 3; delete o.dur;
    const used = new Set(E.overlays.filter((x) => x.start < T + dur && x.end > T).map((x) => x.track));
    let track = 0; while (used.has(track)) track++;
    const it = { id: uid(), track, start: +Math.min(T, Math.max(D - 0.5, 0)).toFixed(2), anim_in: "pop", anim_out: "fade", ...o };
    it.end = +Math.min(it.start + dur, D).toFixed(2);
    E.overlays.push(it); selId = it.id; mark(); renderTL(); showTab(4);
  }

  /* ---------- aperçu des calques sur le téléphone */
  const ovlEl = h(`<div class="ovl"></div>`);
  const ovlNodes = new Map();
  function ovlNode(o, k) {
    let n = ovlNodes.get(o.id);
    const { x, y, w, size, opacity, rotation, start, end, track, ...rest } = o; // ceux-là sont appliqués à chaque image
    const sig = JSON.stringify([rest, k]);
    if (n && n.sig === sig) return n;
    if (n) n.el.remove();
    let el;
    if (o.type === "text") {
      const ratio = META.font_ratio[o.font] || .64, px = 80 * ratio * k;
      el = h(`<div class="ot"><span>${esc(o.uppercase ? (o.text || "").toUpperCase() : o.text || "").replace(/\n/g, "<br>")}</span></div>`);
      Object.assign($("span", el).style, { fontFamily: `'${o.font || "Montserrat Black"}'`, fontSize: `${px}px`, color: o.color || "#fff",
        WebkitTextStroke: o.outline ? `${o.outline * 2 * k}px ${o.outline_color || "#000"}` : "0", textShadow: o.shadow ? `${o.shadow * k}px ${o.shadow * k}px ${2 * k}px #000a` : "none",
        background: o.bg ? o.bg + Math.round((o.bg_opacity ?? 100) * 2.55).toString(16).padStart(2, "0") : "transparent", padding: o.bg ? `${px * .3}px ${px * .35}px` : "0", borderRadius: `${px * .3}px` });
    } else if (o.type === "video") {
      el = h(`<div class="om"><video playsinline preload="auto" src="${MB}/assets/${encodeURIComponent(o.src.slice(6))}"></video></div>`);
      $("video", el).muted = !!o.muted; $("video", el).volume = clamp((o.volume ?? 100) / 100, 0, 1);
    } else if (o.type === "audio") {
      el = h(`<div class="oa" hidden><audio preload="auto" src="${o.src.startsWith("sfx:") ? `${MB}/sfx/${o.src.slice(4)}.mp3` : `${MB}/assets/${encodeURIComponent(o.src.slice(6))}`}"></audio></div>`);
      $("audio", el).volume = clamp((o.volume ?? 100) / 100, 0, 1);
    } else {
      const url = o.type === "emoji" ? `${MB}/api/emoji?c=${encodeURIComponent(o.emoji || "😂")}` : `${MB}/assets/${encodeURIComponent(o.src.slice(6))}`;
      el = h(`<div class="om"><img draggable="false" src="${url}"></div>`);
    }
    if (o.type !== "audio") {
      el.append(h(`<div class="rz" title="Redimensionner"></div>`));
      bindDrag(el, o);
    }
    n = { el, sig, active: false }; ovlNodes.set(o.id, n); ovlEl.append(el);
    return n;
  }
  function bindDrag(el, o) {
    el.onpointerdown = (e) => {
      e.preventDefault(); e.stopPropagation(); selId = o.id; renderTL(); if (curTab !== 4) showTab(4); else renderProps();
      const r = ph.getBoundingClientRect(), resize = e.target.classList.contains("rz"), x0 = e.clientX, y0 = e.clientY;
      const st = { x: o.x ?? .5, y: o.y ?? .5, w: o.w ?? .4, size: o.size || 80 };
      el.setPointerCapture(e.pointerId); tlBusy = true;
      el.onpointermove = (ev) => {
        const dx = (ev.clientX - x0) / r.width, dy = (ev.clientY - y0) / r.height;
        if (resize) { if (o.type === "text") o.size = Math.round(clamp(st.size * (1 + dx * 2.5), 20, 260)); else o.w = +clamp(st.w + dx * 2, .05, 1.2).toFixed(3); }
        else { o.x = +clamp(st.x + dx, 0, 1).toFixed(3); o.y = +clamp(st.y + dy, 0, 1).toFixed(3); }
        mark();
      };
      el.onpointerup = () => { el.onpointermove = null; tlBusy = false; renderProps(); };
    };
  }
  const ANIM = {
    pop: [{ transform: "translate(-50%,-50%) scale(.4)", opacity: 0 }, { transform: "translate(-50%,-50%) scale(1.12)", opacity: 1, offset: .6 }, { transform: "translate(-50%,-50%) scale(1)" }],
    fade: [{ opacity: 0 }, { opacity: 1 }],
    slide_up: [{ transform: "translate(-50%,0%)", opacity: 0 }, { transform: "translate(-50%,-50%)", opacity: 1 }],
    slide_left: [{ transform: "translate(40%,-50%)", opacity: 0 }, { transform: "translate(-50%,-50%)", opacity: 1 }],
    typewriter: [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }],
  };
  function drawOverlays(k) {
    const T = segAt(master.currentTime) >= 0 ? outTime(master.currentTime) : -1, playing = !master.paused;
    const ids = new Set(E.overlays.map((o) => o.id));
    for (const [id, n] of ovlNodes) if (!ids.has(id)) { n.el.remove(); ovlNodes.delete(id); }
    for (const o of E.overlays) {
      const n = ovlNode(o, k), on = T >= o.start && T < o.end;
      if (o.type !== "audio") { // position / taille appliquées à chaque image (glisser fluide)
        const es = n.el.style;
        es.left = `${(o.x ?? .5) * 100}%`; es.top = `${(o.y ?? .5) * 100}%`; es.opacity = (o.opacity ?? 100) / 100;
        es.zIndex = o.type === "text" ? 20 + (o.track || 0) : 10 + (o.track || 0);
        if (!n.el.getAnimations().length) es.transform = `translate(-50%,-50%) rotate(${o.rotation || 0}deg)`;
        if (o.type === "text") { const sp = n.el.firstElementChild, f = (o.size || 80) / 80; sp.style.fontSize = `${(META.font_ratio[o.font] || .64) * (o.size || 80) * k}px`; sp.style.padding = o.bg ? `${.3 * f * 80 * (META.font_ratio[o.font] || .64) * k}px ${.35 * f * 80 * (META.font_ratio[o.font] || .64) * k}px` : "0"; }
        else es.width = `${(o.w ?? .4) * 100}%`;
      }
      n.el.classList.toggle("sel", o.id === selId);
      if (o.type !== "audio") n.el.style.display = on ? "" : "none";
      if (on && !n.active && o.anim_in && ANIM[o.anim_in]) n.el.animate(ANIM[o.anim_in], { duration: o.anim_in === "typewriter" ? Math.min(1200, (o.end - o.start) * 400) : 260, easing: "ease-out" });
      n.active = on;
      const m = $("video,audio", n.el);
      if (m) {
        if (on) {
          const want = (o.trim_in || 0) + (T - o.start);
          if (Math.abs(m.currentTime - want) > 0.3) m.currentTime = want;
          if (playing && m.paused) m.play().catch(() => { }); else if (!playing && !m.paused) m.pause();
        } else if (!m.paused) m.pause();
      }
    }
  }

  /* ---------- la timeline */
  const tlx = h(`<div class="tlx card">
    <div class="row tlbar">
      <b>${ic("film")} Timeline</b>
      <button class="btn sm" data-add="text">${ic("plus")} Texte</button>
      <button class="btn sm" data-add="emoji">${ic("plus")} Emoji</button>
      <button class="btn sm" data-add="media">${ic("plus")} Image / vidéo / son</button>
      <button class="btn sm" data-x="autosfx" title="Place des bruitages sur les transitions, les apparitions et le moment fort">${ic("sparkles")} Bruitages auto</button>
      <div class="spacer"></div>
      <button class="btn sm" data-x="dup" title="Dupliquer">${ic("copy")}</button>
      <button class="btn sm bad" data-x="del" title="Supprimer">${ic("trash-2")}</button>
      <label class="inline" style="font-size:12px;color:var(--mute)">zoom <input type="range" min="1" max="6" step="0.5" value="1" data-x="zoom" style="width:90px"></label>
    </div>
    <div class="tlscroll"><div class="tlin"><div class="ruler"></div><div class="rows"></div><div class="tph"></div></div></div>
    <small style="color:var(--mute)">Glisse un calque pour le déplacer (aussi entre les pistes), tire ses bords pour changer sa durée. Sur l'aperçu : déplace-le, coin = taille.</small>
  </div>`);
  v.append(tlx);
  $$("[data-add]", tlx).forEach((b) => b.onclick = () => {
    const t = b.dataset.add;
    if (t === "text") addOverlay({ type: "text", text: "TON TEXTE", x: .5, y: .2, size: 90, font: "Montserrat Black", color: "#FFFFFF", outline: 6, outline_color: "#000000", shadow: 2, uppercase: true });
    else if (t === "emoji") emojiPicker((em) => addOverlay({ type: "emoji", emoji: em, x: .5, y: .35, w: .22, dur: 2 }));
    else mediaLibrary((a) => addOverlay(a));
  });
  $('[data-x="del"]', tlx).onclick = () => { if (!selId) return toast("Sélectionne un calque"); E.overlays = E.overlays.filter((o) => o.id !== selId); selId = null; mark(); renderTL(); if (curTab === 4) showTab(4); };
  $('[data-x="dup"]', tlx).onclick = () => { const o = selItem(); if (!o) return toast("Sélectionne un calque"); const c = { ...deep(o), id: uid(), track: Math.max(...E.overlays.map((x) => x.track)) + 1 }; E.overlays.push(c); selId = c.id; mark(); renderTL(); };
  $('[data-x="autosfx"]', tlx).onclick = () => {
    const before = E.overlays.length;
    E.overlays = E.overlays.filter((o) => !o.auto); // on remplace les bruitages auto précédents
    const removed = before - E.overlays.length, D = outDur(), cues = [];
    const TL = tline();
    // 1) transitions entre passages : whoosh centré sur la transition
    TL.forEach((g, i) => { if (i && (g.transition?.type || "cut") !== "cut") cues.push([Math.max(g.os - 0.15, 0), "whoosh", 60, "transition"]); });
    // 2) apparition des calques visuels : pop (texte/emoji) ou swoosh (glissé)
    for (const o of E.overlays) if (["text", "emoji", "image", "video"].includes(o.type) && o.anim_in && o.anim_in !== "none")
      cues.push([o.start, /slide/.test(o.anim_in) ? "swoosh" : o.anim_in === "typewriter" ? "click" : "pop", 55, "apparition"]);
    // 3) le moment fort détecté (pic du chat / du son) : impact
    const pk = clip.detail?.peak_src;
    if (pk != null && segAt(pk) >= 0) cues.push([Math.max(outTime(pk) - 0.05, 0), "hit-strong", 45, "moment fort"]);
    // 4) titre d'accroche au début
    if (E.title && E.hook?.enabled) cues.push([0, "swoosh", 45, "titre"]);
    cues.sort((a, b) => a[0] - b[0]);
    let last = -9, n = 0;
    for (const [t, sfx, vol] of cues) {
      if (t - last < 0.4 || t >= D) continue; last = t; n++;
      const used = new Set(E.overlays.filter((x) => x.start < t + 1.2 && x.end > t).map((x) => x.track)); let track = 0; while (used.has(track)) track++;
      E.overlays.push({ id: uid(), type: "audio", src: `sfx:${sfx}`, track, start: +t.toFixed(2), end: +Math.min(t + 1.2, D).toFixed(2), volume: vol, auto: true });
    }
    mark(); renderTL();
    toast(n ? `${ic("sparkles")} ${n} bruitage${n > 1 ? "s" : ""} placé${n > 1 ? "s" : ""} (transitions, apparitions, moment fort)${removed ? " — anciens remplacés" : ""}` : "Rien à sonoriser : ajoute des transitions ou des calques");
  };
  $('[data-x="zoom"]', tlx).oninput = (e) => { tlZoom = Number(e.target.value); renderTL(); };

  function renderTL() {
    const D = Math.max(outDur(), 0.1), inn = $(".tlin", tlx), rows = $(".rows", tlx), ruler = $(".ruler", tlx);
    inn.style.width = `${tlZoom * 100}%`;
    const step = D * (1 / tlZoom) > 40 ? 5 : D / tlZoom > 15 ? 2 : 1;
    ruler.innerHTML = ""; for (let s = 0; s <= D; s += step) ruler.append(h(`<span style="left:${(s / D) * 100}%">${fmt(s)}</span>`));
    rows.innerHTML = "";
    const row = (label, cls = "") => { const r = h(`<div class="trow ${cls}"><div class="tlab">${label}</div><div class="tlane"></div></div>`); rows.append(r); return $(".tlane", r); };
    // piste vidéo principale (passages)
    const vl = row("Vidéo", "main");
    tline().forEach((g, i) => vl.append(h(`<div class="tblk vid" style="left:${(g.os / D) * 100}%;width:${(g.od / D) * 100}%">#${i + 1}${g.td ? ` <i>⇄</i>` : ""}</div>`)));
    // sous-titres
    const cl = row("Sous-titres", "subs");
    const st = { ...META.caption_base, ...E.style };
    if (E.captions !== false) for (const L of groupWords(prepareWords(words.filter((w) => E.segments.some((g) => w.s >= g.s - 0.01 && w.s < g.e)), st, S.detect.keywords), st.words_per_line, st.max_chars || 18)) {
      const a = outTime(L[0].s), b = outTime(L.at(-1).e);
      if (b > a) cl.append(h(`<div class="tblk sub" style="left:${(a / D) * 100}%;width:${((b - a) / D) * 100}%" title="${esc(L.map((w) => w.w).join(" "))}"></div>`));
    }
    // pistes des calques
    const nT = Math.max(0, ...E.overlays.map((o) => o.track + 1)) + 1;
    const lanes = [];
    for (let t = nT - 1; t >= 0; t--) lanes[t] = row(`Piste ${t + 1}`, "olane");
    for (const o of E.overlays) {
      const b = h(`<div class="tblk ov ${o.id === selId ? "sel" : ""}" style="left:${(o.start / D) * 100}%;width:${((o.end - o.start) / D) * 100}%;background:${OCOL[o.type]}">
        <div class="eh l"></div><span>${OICO[o.type]} ${esc(ovlLabel(o))}</span><div class="eh r"></div></div>`);
      lanes[o.track].append(b);
      b.onpointerdown = (e) => {
        e.preventDefault(); selId = o.id; showTab(4);
        $$(".tblk.ov", tlx).forEach((x) => x.classList.remove("sel")); b.classList.add("sel");
        const lane = b.parentElement, W0 = lane.clientWidth, x0 = e.clientX, y0 = e.clientY, s0 = o.start, e0 = o.end, t0 = o.track;
        const mode = e.target.classList.contains("l") ? "l" : e.target.classList.contains("r") ? "r" : "m";
        const rowH = lane.parentElement.offsetHeight, snapPts = [0, D, outTime(master.currentTime), ...E.overlays.filter((x) => x !== o).flatMap((x) => [x.start, x.end])];
        const snap = (t) => { for (const p of snapPts) if (Math.abs(p - t) < 0.12 * D / 30 + 0.05) return p; return t; };
        b.setPointerCapture(e.pointerId); tlBusy = true;
        b.onpointermove = (ev) => {
          const dt = ((ev.clientX - x0) / W0) * D;
          if (mode === "l") o.start = +clamp(snap(s0 + dt), 0, o.end - 0.2).toFixed(2);
          else if (mode === "r") o.end = +clamp(snap(e0 + dt), o.start + 0.2, D).toFixed(2);
          else {
            const len = e0 - s0; let ns = clamp(snap(s0 + dt), 0, D - len); if (snap(ns + len) !== ns + len) ns = snap(ns + len) - len;
            o.start = +clamp(ns, 0, D - len).toFixed(2); o.end = +(o.start + len).toFixed(2);
            o.track = Math.max(0, t0 - Math.round((ev.clientY - y0) / rowH));
          }
          b.style.left = `${(o.start / D) * 100}%`; b.style.width = `${((o.end - o.start) / D) * 100}%`;
          mark();
        };
        b.onpointerup = () => { b.onpointermove = null; tlBusy = false; renderTL(); renderProps(); };
      };
    }
    // clic dans la timeline = se déplacer
    rows.onpointerdown = (e) => { if (e.target.closest(".tblk.ov")) return; const r = $(".tlane", rows).getBoundingClientRect(); seekOut(((e.clientX - r.left) / r.width) * D); };
    ruler.onpointerdown = rows.onpointerdown;
  }
  function tlPlayhead() {
    const ph2 = $(".tph", tlx), lane = $(".tlane", tlx); if (!ph2 || !lane) return;
    const D = Math.max(outDur(), 0.1), T = outTime(master.currentTime);
    ph2.style.left = `${lane.offsetLeft + (T / D) * lane.clientWidth}px`;
  }

  /* ---------- sélecteur d'emoji & médiathèque */
  function emojiPicker(cb) {
    const L = "😂🤣😭💀😱😳🤯😡🥶🔥💯👀🙏👏💪🤡🫡😎🥵😤🤔🙄😈👑💸💰🚨⚠️❌✅⭐🎯🎮🏆💥⚡🍿🚗🚓🔫💣🧠❤️💔👍👎🤝🫠😮‍💨";
    const m = h(`<div class="modal"><div class="card"><h2>Choisis un emoji</h2><div class="emos">${[...new Intl.Segmenter().segment(L)].map((x) => `<button>${x.segment}</button>`).join("")}</div>
      <label class="f" style="margin-top:12px"><b>…ou colle n'importe quel emoji</b><div class="inline"><input type="text" id="emi" placeholder="🙂"><button class="btn pri" id="emok">Ajouter</button></div></label></div></div>`);
    document.body.append(m);
    m.onclick = (e) => { if (e.target === m) m.remove(); };
    $$(".emos button", m).forEach((b) => b.onclick = () => { m.remove(); cb(b.textContent); });
    $("#emok", m).onclick = () => { const v2 = $("#emi", m).value.trim(); if (v2) { m.remove(); cb(v2); } };
  }
  async function mediaLibrary(cb) {
    const m = h(`<div class="modal"><div class="card" style="width:min(720px,100%)"><div class="row"><h2 style="margin:0">Médiathèque</h2><div class="spacer"></div><button class="btn sm" id="mlx">${ic("x")}</button></div>
      <div class="drop" id="mld" style="margin:14px 0">${ic("upload")} Dépose une image, une vidéo ou un son (logo, B-roll, musique…) ou clique<input type="file" hidden multiple accept="image/*,video/*,audio/*"></div>
      <h3>Tes médias</h3><div class="mlib" id="mll"></div>
      <h3>Bruitages intégrés</h3><div class="mlib" id="mls"></div>
      <h3>${ic("search")} Sons libres de droits (Openverse · Freesound…)</h3>
      <div class="row"><input type="text" id="osq" placeholder="whoosh, punch, rire, applause, epic music…" style="flex:1;min-width:180px">
        <select id="osk" style="width:auto"><option value="sfx">Bruitages</option><option value="music">Musiques</option></select><button class="btn pri" id="osg">Chercher</button></div>
      <small style="color:var(--mute)">Uniquement CC0 (libre) et CC BY (créditer l'auteur — noté dans la médiathèque). Astuce : cherche en anglais.</small>
      <div id="osr" class="osr"></div></div></div>`);
    document.body.append(m);
    const close = () => m.remove();
    $("#mlx", m).onclick = close; m.onclick = (e) => { if (e.target === m) close(); };
    const add = (a) => {
      close();
      if (a.kind === "image") cb({ type: "image", src: `asset:${a.name}`, x: .5, y: .3, w: .4, dur: 3 });
      else if (a.kind === "video") cb({ type: "video", src: `asset:${a.name}`, x: .5, y: .35, w: .7, trim_in: 0, volume: 80, dur: Math.min(a.duration || 5, 8) });
      else {
        const music = a.music || (!a.sfx && (a.duration || 0) > 12);
        cb({ type: "audio", src: a.sfx ? `sfx:${a.name}` : `asset:${a.name}`, volume: music ? 30 : 80, duck: music, fade_in: music ? 0.5 : 0, fade_out: music ? 1 : 0,
          dur: music ? outDur() : Math.min(a.duration || 1.5, 4) });
      }
    };
    async function load() {
      const list = await api("/api/assets"), box = $("#mll", m);
      box.innerHTML = list.length ? "" : `<div style="color:var(--mute)">Aucun média pour l'instant.</div>`;
      for (const a of list) {
        const prev = a.kind === "image" ? `<img src="${MB}/assets/${encodeURIComponent(a.name)}">` : a.kind === "video" ? `<video muted src="${MB}/assets/${encodeURIComponent(a.name)}#t=1"></video>` : `<div class="mi">${ic("music")}</div>`;
        const it = h(`<div class="mitem">${prev}<span>${esc(a.name)}</span><small>${a.kind}${a.duration ? ` · ${fmt(a.duration)}` : ""}</small><button class="btn sm bad" title="Supprimer">${ic("trash-2")}</button></div>`);
        it.onclick = (e) => { if (e.target.closest("button")) return; add(a); };
        $("button", it).onclick = async () => { if (confirm(`Supprimer ${a.name} ?`)) { await api(`/api/assets/${encodeURIComponent(a.name)}`, { method: "DELETE" }); load(); } };
        box.append(it);
      }
    }
    for (const [k, l] of Object.entries(META.sfx)) if (k !== "none") {
      const it = h(`<div class="mitem"><div class="mi">${ic("volume-2")}</div><span>${l}</span><button class="btn sm" title="Écouter">${ic("play")}</button></div>`);
      it.onclick = (e) => { if (e.target.closest("button")) { new Audio(`${MB}/sfx/${k}.mp3`).play(); return; } add({ kind: "audio", name: k, sfx: true }); };
      $("#mls", m).append(it);
    }
    let player = null;
    const osearch = async () => {
      const q = $("#osq", m).value.trim(); if (!q) return;
      const box = $("#osr", m); box.innerHTML = `<div style="color:var(--mute);padding:10px">Recherche…</div>`;
      try {
        const res = await api(`/api/sounds/search?q=${encodeURIComponent(q)}&kind=${$("#osk", m).value}`);
        box.innerHTML = res.length ? "" : `<div style="color:var(--mute);padding:10px">Aucun son trouvé (essaie en anglais).</div>`;
        for (const r of res) {
          const it = h(`<div class="osi"><button class="btn sm" data-p>${ic("play")}</button><div><b>${esc(r.title)}</b><small>${fmt(r.duration)} · ${r.license.toUpperCase()} · ${esc(r.creator)} · ${esc(r.source || "")}</small></div><button class="btn sm pri" data-a>${ic("plus")} Ajouter</button></div>`);
          $("[data-p]", it).onclick = () => { if (player) player.pause(); player = new Audio(r.url); player.play(); };
          $("[data-a]", it).onclick = async (e) => {
            e.target.disabled = true; e.target.textContent = "";
            try { const a = await api("/api/sounds/import", { method: "POST", json: r }); if (player) player.pause(); add({ kind: "audio", name: a.name, duration: r.duration, music: $("#osk", m).value === "music" }); }
            catch (er) { toast(er.message); e.target.disabled = false; e.target.textContent = "Ajouter"; }
          };
          box.append(it);
        }
      } catch (er) { box.innerHTML = `<div style="color:var(--bad);padding:10px">${esc(er.message)}</div>`; }
    };
    $("#osg", m).onclick = osearch; $("#osq", m).onkeydown = (e) => e.key === "Enter" && osearch();
    const dz = $("#mld", m), fi = $("input", dz);
    const up = async (files) => { for (const f of files) { const fd = new FormData(); fd.append("file", f); try { await api("/api/assets", { method: "POST", body: fd }); } catch (e) { toast(e.message); } } load(); };
    dz.onclick = () => fi.click(); fi.onchange = () => up(fi.files);
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("on"); }; dz.ondragleave = () => dz.classList.remove("on");
    dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("on"); up(e.dataTransfer.files); };
    load();
  }

  /* ---------- onglet « Calques » : propriétés du calque sélectionné */
  let curTab = 0;
  function tabLayers() { renderProps(); }
  function renderProps() {
    if (curTab !== 4) return;
    pb.innerHTML = "";
    const o = selItem();
    if (!o) {
      pb.append(h(`<div><p style="color:var(--mute);margin-top:0">Ajoute des textes, emojis, images (logo, sticker), vidéos (B-roll, réaction) et sons (musique, bruitages) avec la barre de la timeline sous l'éditeur, puis clique un calque pour le régler.</p>
        <div class="ovlist">${E.overlays.map((x) => `<button class="btn sm" data-id="${x.id}" style="border-left:4px solid ${OCOL[x.type]}">${OICO[x.type]} ${esc(ovlLabel(x)).slice(0, 30)} · ${fmt(x.start)}→${fmt(x.end)}</button>`).join("") || `<i style="color:var(--mute)">Aucun calque.</i>`}</div></div>`));
      $$("[data-id]", pb).forEach((b) => b.onclick = () => { selId = b.dataset.id; renderTL(); renderProps(); });
      return;
    }
    const f = (lab, html) => `<label class="f"><b>${lab}</b>${html}</label>`;
    const num = (k, v, step = 0.1, min = 0, max = 9999) => `<input type="number" data-o="${k}" data-n step="${step}" min="${min}" max="${max}" value="${v ?? ""}">`;
    const rng = (k, v, min, max, step) => `<input type="range" data-o="${k}" data-n min="${min}" max="${max}" step="${step}" value="${v}">`;
    const anims = (k, v) => `<select data-o="${k}">${Object.entries(k === "anim_out" ? { none: "Aucune", fade: "Fondu" } : META.ovl_anims).filter(([a]) => o.type === "text" || a !== "typewriter").map(([a, l]) => `<option value="${a}" ${a === v ? "selected" : ""}>${l}</option>`).join("")}</select>`;
    let html = `<div class="row" style="margin-bottom:12px"><b style="font-size:15px">${OICO[o.type]} ${esc(ovlLabel(o)).slice(0, 40)}</b><div class="spacer"></div><button class="btn sm" data-b="seek">${ic("play")} Aller</button><button class="btn sm" data-b="here">⇤ Commencer ici</button><button class="btn sm" data-b="none">${ic("x")}</button></div>
      <div class="grid2" style="gap:10px">${f("Début (s)", num("start", o.start))}${f("Fin (s)", num("end", o.end))}</div>`;
    if (o.type === "text") html += `${f("Texte", `<textarea data-o="text">${esc(o.text)}</textarea>`)}
      <div class="grid2" style="gap:10px">${f("Police", `<select data-o="font">${META.fonts.map((x) => `<option ${x === o.font ? "selected" : ""}>${x}</option>`).join("")}</select>`)}${f(`Taille ${o.size}`, rng("size", o.size, 20, 260, 1))}
      ${f("Entrée", anims("anim_in", o.anim_in))}${f("Sortie", anims("anim_out", o.anim_out))}${f(`Contour ${o.outline ?? 0}`, rng("outline", o.outline ?? 0, 0, 14, 1))}${f(`Rotation ${o.rotation || 0}°`, rng("rotation", o.rotation || 0, -30, 30, 1))}</div>
      <div class="row" style="margin-bottom:12px"><label class="inline">Texte <input type="color" data-o="color" value="${o.color || "#ffffff"}"></label><label class="inline">Contour <input type="color" data-o="outline_color" value="${o.outline_color || "#000000"}"></label>
      <label class="inline"><input type="checkbox" data-o="has_bg" ${o.bg ? "checked" : ""}> Fond</label><input type="color" data-o="bg" value="${o.bg || "#E11D48"}"><label class="inline"><input type="checkbox" data-o="uppercase" ${o.uppercase ? "checked" : ""}> MAJ</label></div>
      <small style="color:var(--mute)">Astuce : les emojis dans un texte sortent en noir et blanc au rendu ; utilise plutôt « ${ic("plus")} Emoji ».</small>`;
    if (o.type === "emoji") html += `${f("Emoji", `<input type="text" data-o="emoji" value="${esc(o.emoji)}">`)}`;
    if (["emoji", "image", "video"].includes(o.type)) html += `<div class="grid2" style="gap:10px">${f(`Taille ${Math.round((o.w ?? .4) * 100)}%`, rng("w", o.w ?? .4, .05, 1.2, .01))}${f(`Opacité ${o.opacity ?? 100}%`, rng("opacity", o.opacity ?? 100, 10, 100, 1))}
      ${f("Entrée", anims("anim_in", o.anim_in))}${f("Sortie", anims("anim_out", o.anim_out))}${f(`Rotation ${o.rotation || 0}°`, rng("rotation", o.rotation || 0, -45, 45, 1))}</div>`;
    if (["video", "audio"].includes(o.type)) html += `<div class="grid2" style="gap:10px">${f("Démarrer le média à (s)", num("trim_in", o.trim_in || 0))}${f(`Volume ${o.volume ?? 100}%`, rng("volume", o.volume ?? 100, 0, 200, 1))}</div>`;
    if (o.type === "video") html += `<label class="inline f"><input type="checkbox" data-o="muted" ${o.muted ? "checked" : ""}><b>Couper le son de cette vidéo</b></label>`;
    if (o.type === "audio") html += `<div class="grid2" style="gap:10px">${f("Fondu d'entrée (s)", num("fade_in", o.fade_in || 0))}${f("Fondu de sortie (s)", num("fade_out", o.fade_out || 0))}</div>
      <label class="inline f"><input type="checkbox" data-o="duck" ${o.duck ? "checked" : ""}><b>Baisser automatiquement quand le streamer parle (ducking)</b></label>`;
    html += `<div class="row" style="margin-top:8px"><button class="btn sm" data-b="dup">${ic("copy")} Dupliquer</button><button class="btn sm bad" data-b="del">${ic("trash-2")} Supprimer</button></div>`;
    pb.append(h(`<div>${html}</div>`));
    $$("[data-o]", pb).forEach((i) => i.oninput = () => {
      const k = i.dataset.o;
      let val = i.type === "checkbox" ? i.checked : i.hasAttribute("data-n") ? Number(i.value) : i.value;
      if (k === "has_bg") { o.bg = val ? $('[data-o="bg"]', pb).value : ""; }
      else if (k === "bg") { if ($('[data-o="has_bg"]', pb).checked) o.bg = val; }
      else o[k] = val;
      if (k === "start") o.start = clamp(o.start, 0, o.end - 0.2);
      if (k === "end") o.end = clamp(o.end, o.start + 0.2, outDur());
      const lab = i.closest("label")?.querySelector("b");
      if (lab && i.type === "range") lab.textContent = lab.textContent.replace(/-?[\d.]+(%|°)?$/, k === "w" ? `${Math.round(val * 100)}%` : `${val}${k === "opacity" || k === "volume" ? "%" : k === "rotation" ? "°" : ""}`);
      mark(); if (["start", "end", "text", "emoji"].includes(k)) renderTL();
    });
    $('[data-b="seek"]', pb).onclick = () => seekOut(o.start + 0.01);
    $('[data-b="here"]', pb).onclick = () => { const len = o.end - o.start; o.start = +outTime(master.currentTime).toFixed(2); o.end = +Math.min(o.start + len, outDur()).toFixed(2); mark(); renderTL(); renderProps(); };
    $('[data-b="none"]', pb).onclick = () => { selId = null; renderTL(); renderProps(); };
    $('[data-b="dup"]', pb).onclick = () => $('[data-x="dup"]', tlx).click();
    $('[data-b="del"]', pb).onclick = () => $('[data-x="del"]', tlx).click();
  }

  let ready = false;
  const init = (real) => {
    if (real) { iw = master.videoWidth || iw; ih = master.videoHeight || ih; dur = master.duration || dur; }
    if (ready && !real) return;
    const first = !ready; ready = true;
    master.playbackRate = E.speed;
    if (first) seek(E.trim[0]);
    buildStage(); if (first) showTab(0); renderTL();
  };
  master.addEventListener("loadedmetadata", () => init(true));
  dur = Math.max(...E.segments.map((g) => g.e), E.trim[1], clip.duration || 1) + 1;
  setTimeout(() => init(false), 2500);
  master.load();
  loop();

  /* ---- onglets */
  let wave = null;
  const pb = $("#pb");
  $$(".ptabs button").forEach((b) => b.onclick = () => showTab(+b.dataset.t));
  function showTab(i) {
    $$(".ptabs button").forEach((b) => b.classList.toggle("on", +b.dataset.t === i));
    pb.innerHTML = "";
    curTab = i;
    [tabTrim, tabWords, tabStyle, tabCrop, tabLayers, tabWhy, tabPublish][i]();
  }

  function tabTrim() {
    const T = tline();
    const trOpts = (v) => Object.entries(META.transitions).map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${l}</option>`).join("");
    const efOpts = (v) => Object.entries(META.effects).map(([k, l]) => `<option value="${k}" ${k === v ? "selected" : ""}>${l}</option>`).join("");
    pb.append(h(`<div>
      <div class="row"><b>${E.segments.length} passage${E.segments.length > 1 ? "s" : ""}</b><div class="spacer"></div><b id="dd"></b></div>
      <div class="tl" id="tl"><canvas class="wave"></canvas><div class="ph"></div></div>
      <small style="color:var(--mute)">Clic sur la frise = se déplacer · glisser les poignées = couper · source complète ${fmt(dur)}</small>
      <div class="row" style="margin-top:12px">
        <button class="btn sm" id="split">${ic("scissors")} Couper ici</button>
        <button class="btn sm" id="addp">${ic("plus")} Ajouter un passage ici</button>
        <button class="btn sm" id="snap">${ic("magnet")} Caler sur les phrases</button>
        <button class="btn sm" id="allT">${ic("sparkles")} Même transition partout</button>
      </div>
      <h3>Passages, effets &amp; transitions</h3>
      <div id="segl" style="display:grid;gap:8px"></div>
      <h3>Astuce</h3><p style="color:var(--mute);margin:0">Pour enlever un temps mort : « Couper ici » au début puis à la fin du passage ennuyeux, et supprime-le ${ic("trash-2")}. Les vidéos virales démarrent <b>dans l'action</b> et durent 25 – 45 s.</p></div>`));
    const tl = $("#tl");
    const upd = () => {
      const d = outDur(); $("#dd").textContent = `Durée finale ${d.toFixed(1)} s`;
      $("#dd").style.color = d < S.clip.min_seconds || d > S.clip.max_seconds ? "var(--warn)" : "";
    };
    for (const w of words) tl.append(h(`<div class="wd" style="left:${(w.s / dur) * 100}%;width:${Math.max(((w.e - w.s) / dur) * 100, .2)}%"></div>`));
    E.segments.forEach((g, i) => {
      tl.append(h(`<div class="sel ${i === curSeg ? "cur" : ""}" data-i="${i}" style="left:${(g.s / dur) * 100}%;width:${((g.e - g.s) / dur) * 100}%"><div class="h l">‹</div><div class="h r">›</div><span class="segn">${i + 1}</span></div>`));
    });
    drawWave($("canvas", tl)); upd();
    const x2t = (x) => clamp((x - tl.getBoundingClientRect().left) / tl.clientWidth, 0, 1) * dur;
    let drag = null;
    tl.onpointerdown = (e) => {
      const sel = e.target.closest(".sel"), hd = e.target.closest(".h");
      if (sel) curSeg = +sel.dataset.i;
      if (hd) { drag = { i: +sel.dataset.i, side: hd.classList.contains("l") ? "s" : "e" }; tl.setPointerCapture(e.pointerId); return; }
      seek(x2t(e.clientX));
      $$(".sel", tl).forEach((x) => x.classList.toggle("cur", +x.dataset.i === curSeg));
      $$(".segc").forEach((x) => x.classList.toggle("cur", +x.dataset.i === curSeg));
    };
    tl.onpointermove = (e) => {
      if (!drag) return;
      const g = E.segments[drag.i], t = x2t(e.clientX);
      const others = E.segments.filter((_, k) => k !== drag.i);
      const lo = Math.max(0, ...others.filter((o) => o.e <= g.s + 0.01).map((o) => o.e));
      const hi = Math.min(dur, ...others.filter((o) => o.s >= g.e - 0.01).map((o) => o.s));
      if (drag.side === "s") g.s = clamp(t, reordered ? 0 : lo, g.e - 1); else g.e = clamp(t, g.s + 1, reordered ? dur : hi);
      const el = $(`.sel[data-i="${drag.i}"]`, tl); el.style.left = `${(g.s / dur) * 100}%`; el.style.width = `${((g.e - g.s) / dur) * 100}%`;
      seek(drag.side === "s" ? g.s : g.e - 0.4); upd(); mark();
    };
    tl.onpointerup = () => { if (drag) { syncTrim(); showTab(0); } drag = null; };

    const segl = $("#segl");
    T.forEach((g, i) => {
      const sg = E.segments[i];
      if (i > 0) {
        const tr = sg.transition ||= { type: "cut", duration: 0.4 };
        const row = h(`<div class="row" style="gap:8px;padding-left:18px;color:var(--mute);font-size:13px">↓ transition
          <select data-tr style="width:auto;padding:5px 8px">${trOpts(tr.type)}</select>
          <input data-td type="number" step="0.1" min="0.1" max="2" value="${tr.duration ?? 0.4}" style="width:70px;padding:5px 8px" ${tr.type === "cut" ? "disabled" : ""}> s
          <button class="btn sm" data-pv title="Voir la transition">${ic("eye")}</button></div>`);
        $("[data-tr]", row).onchange = (e) => { tr.type = e.target.value; mark(); showTab(0); };
        $("[data-td]", row).oninput = (e) => { tr.duration = Number(e.target.value); mark(); upd(); };
        $("[data-pv]", row).onclick = () => { const p = E.segments[i - 1]; curSeg = i - 1; seek(Math.max(p.e - 1.5, p.s)); master.play(); };
        segl.append(row);
      }
      const c = h(`<div class="segc card ${i === curSeg ? "cur" : ""}" data-i="${i}" style="padding:10px 12px">
        <div class="row" style="gap:8px"><b>#${i + 1}</b><span style="color:var(--mute);font-size:13px">${fmt(g.s)} → ${fmt(g.e)} · ${g.od.toFixed(1)} s</span><div class="spacer"></div>
          <select data-ef style="width:auto;padding:5px 8px" title="Effet">${efOpts(sg.effect || "none")}</select>
          <button class="btn sm" data-go title="Lire">${ic("play")}</button>
          <button class="btn sm" data-up title="Monter" ${i ? "" : "disabled"}>${ic("arrow-up")}</button>
          <button class="btn sm bad" data-del title="Supprimer" ${E.segments.length > 1 ? "" : "disabled"}>${ic("trash-2")}</button></div></div>`);
      $("[data-ef]", c).onchange = (e) => { sg.effect = e.target.value; mark(); showTab(0); };
      $("[data-go]", c).onclick = () => { curSeg = i; seek(sg.s); master.play(); };
      $("[data-del]", c).onclick = () => { E.segments.splice(i, 1); curSeg = 0; syncTrim(); mark(); showTab(0); };
      $("[data-up]", c).onclick = () => { [E.segments[i - 1], E.segments[i]] = [E.segments[i], E.segments[i - 1]]; reordered = true; syncTrim(); mark(); showTab(0); };
      segl.append(c);
    });
    $("#split").onclick = () => {
      const t = master.currentTime, i = segAt(t); if (i < 0) return toast("Place la tête de lecture dans un passage");
      const g = E.segments[i]; if (t - g.s < 0.5 || g.e - t < 0.5) return toast("Trop près du bord du passage");
      E.segments.splice(i + 1, 0, { s: t, e: g.e, effect: g.effect, transition: { type: "cut", duration: 0.4 } }); g.e = t;
      curSeg = i + 1; mark(); showTab(0); toast("Passage coupé en deux");
    };
    $("#addp").onclick = () => {
      const t = master.currentTime; if (segAt(t) >= 0) return toast("Déplace-toi hors des passages existants (clic sur la frise)");
      const prev = E.segments.filter((g) => g.e <= t).sort((a, b) => b.e - a.e)[0], next = E.segments.filter((g) => g.s >= t).sort((a, b) => a.s - b.s)[0];
      E.segments.push({ s: Math.max(t - 3, prev ? prev.e : 0), e: Math.min(t + 7, next ? next.s : dur), effect: "none",
        transition: { type: S.compilation?.transition || "fade", duration: 0.4 } });
      syncTrim(); mark(); showTab(0);
    };
    $("#allT").onclick = () => {
      const t = E.segments.slice(1).map((g) => g.transition?.type).find((x) => x && x !== "cut") || "fade";
      E.segments.forEach((g, i) => { if (i) g.transition = { type: t, duration: g.transition?.duration ?? 0.4 }; }); mark(); showTab(0); toast(`Transition « ${META.transitions[t]} » partout`);
    };
    $("#snap").onclick = () => {
      const near = (t) => { let best = t, bd = 9; for (let i = 0; i < words.length - 1; i++) { const gp = words[i + 1].s - words[i].e; const m = (words[i].e + words[i + 1].s) / 2; const d = Math.abs(m - t) - gp; if (Math.abs(m - t) < 3 && d < bd) { bd = d; best = m; } } return best; };
      E.segments.forEach((g) => { g.s = near(g.s); g.e = Math.max(near(g.e), g.s + 1); }); syncTrim(); mark(); showTab(0); toast("Coupes calées sur les pauses");
    };
  }
  async function drawWave(cv) {
    try {
      if (!wave) {
        const buf = await (await fetch(src)).arrayBuffer();
        const ab = await new (window.AudioContext || window.webkitAudioContext)().decodeAudioData(buf);
        const ch = ab.getChannelData(0), n = 400, step = Math.floor(ch.length / n);
        wave = Array.from({ length: n }, (_, i) => { let m = 0; for (let j = i * step; j < (i + 1) * step; j += 32) m = Math.max(m, Math.abs(ch[j])); return m; });
      }
      cv.width = cv.clientWidth * 2; cv.height = cv.clientHeight * 2;
      const c = cv.getContext("2d"), bw = cv.width / wave.length; c.fillStyle = "#a78bfa";
      wave.forEach((m, i) => { const hh = m * cv.height * 0.9; c.fillRect(i * bw, (cv.height - hh) / 2, Math.max(bw - 1, 1), hh); });
    } catch { }
  }

  function tabWords() {
    pb.append(h(`<div>
      <div class="row"><label class="inline"><input type="checkbox" id="cOn" ${E.captions !== false ? "checked" : ""}> Sous-titres activés</label><div class="spacer"></div>
        <select id="lang" style="width:auto">${[["fr", "FR"], ["en", "EN"], ["es", "ES"], ["", "Auto"]].map(([k, l]) => `<option value="${k}" ${k === (S.clip.language || "") ? "selected" : ""}>${l}</option>`).join("")}</select>
        <button class="btn sm" id="retr">${ic("refresh-cw")} Re-transcrire</button></div>
      <label class="f" style="margin-top:14px"><b>Synchro : décaler tous les sous-titres <span id="shv">${shift.toFixed(2)} s</span></b>
        <input type="range" min="-1" max="1" step="0.05" id="sh" value="${shift}"><small>Si le texte arrive trop tôt → vers la droite. Appliqué à l'enregistrement.</small></label>
      <h3>Texte (clique un mot pour le corriger · Suppr pour l'effacer · double-clic pour s'y rendre)</h3>
      <div class="words" id="wl"></div></div>`));
    $("#cOn").onchange = (e) => { E.captions = e.target.checked; mark(); };
    $("#sh").oninput = (e) => { shift = Number(e.target.value); $("#shv").textContent = `${shift.toFixed(2)} s`; mark(); };
    $("#retr").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "transcription…";
      try { words = (await api(`/api/clips/${clip.id}/retranscribe`, { method: "POST", json: { language: $("#lang").value } })).words; toast("Transcription mise à jour"); mark(); showTab(1); } catch (er) { toast(er.message); e.target.disabled = false; }
    };
    const wl = $("#wl");
    words.forEach((w, i) => {
      const out = w.e <= E.trim[0] || w.s >= E.trim[1];
      const el = h(`<span class="w ${out || w.skip ? "out" : ""}" ${w.skip ? 'title="voix du jeu : masquée" style="text-decoration:line-through"' : ""} contenteditable="true" spellcheck="false" data-i="${i}">${esc(w.w)}</span>`);
      el.oninput = () => { w.w = el.textContent; mark(); };
      el.ondblclick = () => seek(w.s - 0.05);
      el.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); el.blur(); }
        if ((e.key === "Delete" || e.key === "Backspace") && !el.textContent.trim()) { e.preventDefault(); words.splice(i, 1); mark(); showTab(1); }
      };
      wl.append(el);
    });
  }

  function tabStyle() {
    const box = h(`<div></div>`); pb.append(box);
    styleControls(box, E.style, E.layout, E.hook, () => { buildStage(); mark(); });
  }

  function tabCrop() {
    const L = E.layout;
    pb.append(h(`<div>
      <div class="layouts">${layoutBtns(L.mode)}</div>
      <div class="srcv" id="sv"></div>
      <div id="cropopts" style="margin-top:12px"></div></div>`));
    $$("[data-lm]", pb).forEach((b) => b.onclick = () => { L.mode = b.dataset.lm; buildStage(); mark(); showTab(3); });
    const sv = $("#sv"), pv = h(`<video muted playsinline src="${src}"></video>`); sv.append(pv);
    pv.addEventListener("loadeddata", () => { pv.currentTime = master.currentTime; });
    const opts = $("#cropopts");
    const rects = [];
    if (L.mode === "split" || L.mode === "pip") {
      rects.push(["facecam", "face", "Cam"], ["gameplay", "game", "Jeu"]);
      const tools = h(`<div class="row" style="margin-bottom:12px">
        <button class="btn sm" id="dfc">${ic("crosshair")} Détecter la cam automatiquement</button>
        <button class="btn sm" id="svl">${ic("save")} Cadrage par défaut pour ${esc(clip.streamer || "ce streamer")}</button></div>`);
      opts.append(tools);
      $("#dfc").onclick = async (e) => {
        e.target.disabled = true; e.target.textContent = "analyse…";
        try { const r = await api(`/api/clips/${clip.id}/facecam`, { method: "POST" }); L.facecam = r.facecam; buildStage(); mark(); showTab(3); toast(r.full_cam ? "Visage trouvé (cam plein écran : le format « Fond flou » peut suffire)" : "Cam détectée"); }
        catch (er) { toast("Aucun visage trouvé — place le cadre rose à la main"); e.target.disabled = false; e.target.textContent = "Détecter la cam automatiquement"; }
      };
      $("#svl").onclick = async () => {
        const st = await api("/api/state"); const row = st.streamers.find((x) => x.channel.toLowerCase() === (clip.streamer || "").toLowerCase());
        if (!row) return toast("Ce streamer n'est pas dans ta liste (page Streamers)");
        await api(`/api/streamers/${row.id}`, { method: "PATCH", json: { overrides: { ...row.overrides, layout: { ...L, auto_facecam: false } } } });
        toast(`Les prochains clips de ${row.channel} utiliseront ce cadrage ${ic("check")}`);
      };
    }
    if (L.mode === "split") {
      opts.append(h(`<div><label class="f"><b>Répartition cam / jeu</b></label><div class="row" style="margin-bottom:10px">${[[0.5, "50 / 50"], [0.4, "40 / 60"], [0.33, "33 / 67"], [0.25, "25 / 75"]].map(([r, l]) => `<button class="btn sm ${Math.abs(L.split_ratio - r) < .01 ? "pri" : ""}" data-ratio="${r}">${l}</button>`).join("")}
        <button class="btn sm" id="swp">${ic("arrow-up-down")} Cam ${L.cam_position === "bottom" ? "en bas" : "en haut"}</button></div>
        <label class="f"><b>Réglage fin <span id="srv">${Math.round(L.split_ratio * 100)}%</span></b><input type="range" min="0.2" max="0.7" step="0.01" id="sr" value="${L.split_ratio}"></label></div>`));
      $$("[data-ratio]", opts).forEach((b) => b.onclick = () => { L.split_ratio = Number(b.dataset.ratio); buildStage(); mark(); showTab(3); });
      $("#swp").onclick = () => { L.cam_position = L.cam_position === "bottom" ? "top" : "bottom"; buildStage(); mark(); showTab(3); };
      $("#sr").oninput = (e) => { L.split_ratio = Number(e.target.value); $("#srv").textContent = `${Math.round(L.split_ratio * 100)}%`; buildStage(); mark(); };
    }
    if (L.mode === "pip") {
      opts.append(h(`<div><label class="f"><b>Taille de la cam <span id="psv">${Math.round((L.pip_size || .42) * 100)}%</span></b><input type="range" min="0.25" max="0.7" step="0.01" id="ps" value="${L.pip_size || .42}"></label>
        <div class="row" style="margin-bottom:10px">${[["tl", "↖ haut gauche"], ["tr", "↗ haut droite"], ["bl", "↙ bas gauche"], ["br", "↘ bas droite"]].map(([c, l]) => `<button class="btn sm ${(L.pip_corner || "tl") === c ? "pri" : ""}" data-pc="${c}">${l}</button>`).join("")}</div></div>`));
      $("#ps").oninput = (e) => { L.pip_size = Number(e.target.value); $("#psv").textContent = `${Math.round(L.pip_size * 100)}%`; buildStage(); mark(); };
      $$("[data-pc]", opts).forEach((b) => b.onclick = () => { L.pip_corner = b.dataset.pc; buildStage(); mark(); showTab(3); });
    }
    if (L.mode === "split" || L.mode === "pip")
      opts.append(h(`<small style="color:var(--mute)">Cadre <b style="color:#f472b6">rose</b> = la webcam, <b style="color:#38bdf8">bleu</b> = le jeu. Glisse pour déplacer, coin en bas à droite pour redimensionner.</small>`)); else if (L.mode === "fill") {
      rects.push(["focus", "focus", "Zone visible"]);
      opts.append(h(`<small style="color:var(--mute)">Fais glisser la bande jaune sur ce qui doit rester à l'écran.</small>`));
    } else if (L.mode === "blur") {
      opts.append(h(`<label class="f"><b>Zoom de la vidéo <span id="zv">${(L.zoom || 1).toFixed(2)}×</span></b><input type="range" min="1" max="1.8" step="0.02" id="zm" value="${L.zoom || 1}"><small>Agrandit la vidéo au centre (rogne les côtés)</small></label>`));
      $("#zm").oninput = (e) => { L.zoom = Number(e.target.value); $("#zv").textContent = `${L.zoom.toFixed(2)}×`; buildStage(); mark(); };
    }
    for (const [key, cls, label] of rects) {
      const r = key === "focus" ? null : (L[key] ||= { x: 0, y: 0, w: .3, h: .3 });
      const el = h(`<div class="rect ${cls}"><b>${label}</b><div class="rs"></div></div>`); sv.append(el);
      const pos = () => {
        if (key === "focus") { const fw = (ih * 9 / 16) / iw; const x = clamp((L.focus?.x ?? .5) - fw / 2, 0, 1 - fw); Object.assign(el.style, { left: `${x * 100}%`, width: `${fw * 100}%` }); }
        else Object.assign(el.style, { left: `${r.x * 100}%`, top: `${r.y * 100}%`, width: `${r.w * 100}%`, height: `${r.h * 100}%` });
      };
      pos();
      let mode = null, sx, sy, o;
      el.onpointerdown = (e) => { e.preventDefault(); el.setPointerCapture(e.pointerId); mode = e.target.classList.contains("rs") ? "size" : "move"; sx = e.clientX; sy = e.clientY; o = key === "focus" ? { x: L.focus?.x ?? .5 } : { ...r }; };
      el.onpointermove = (e) => {
        if (!mode) return; const dx = (e.clientX - sx) / sv.clientWidth, dy = (e.clientY - sy) / sv.clientHeight;
        if (key === "focus") { L.focus = { x: clamp(o.x + dx, 0, 1) }; }
        else if (mode === "move") { r.x = clamp(o.x + dx, 0, 1 - r.w); r.y = clamp(o.y + dy, 0, 1 - r.h); }
        else { r.w = clamp(o.w + dx, 0.05, 1 - r.x); r.h = clamp(o.h + dy, 0.05, 1 - r.y); }
        pos(); buildStage(); mark();
      };
      el.onpointerup = () => mode = null;
    }
  }

  function tabWhy() {
    const d = clip.detail || {}, a = d.analysis || {}, sig = d.signals || [];
    const col = (v) => v == null ? "var(--mute)" : v >= 70 ? "#4ade80" : v >= 45 ? "#facc15" : "#f87171";
    const box = h(`<div>
      <div class="why-score">
        <div><b style="color:${col(d.viral)}">${d.viral ?? "–"}</b><small>Score viral</small></div>
        <div><b style="color:${col(d.signal_score)}">${d.signal_score ?? "–"}</b><small>${clip.origin === "import" ? "Pics de son<br>(cris, rires)" : "Réaction du live<br>(chat + son)"}</small></div>
        <div><b style="color:${col(a.score)}">${a.score ?? "–"}</b><small>Contenu<br>(ce qui est dit)</small></div>
        <div><b style="color:${col(d.llm?.score)}">${d.llm?.score ?? "off"}</b><small>Avis IA<br>(optionnel)</small></div>
      </div>
      ${!d.viral ? `<p style="color:var(--mute)">Clip créé avant l'ajout de l'analyse : relance la détection sur de nouveaux clips pour voir le détail.</p>` : ""}
      <h3>Ce qui a déclenché le clip</h3><div id="wsig"></div>
      <div id="wcurve"></div>
      <h3>Ce qui est dit</h3><ul class="reasons" id="wreas"></ul>
      ${d.llm ? `<h3>Avis de l'IA</h3><p>${esc(d.llm.reason)}</p>` : ""}
      <h3>Le chat à ce moment ${d.chat ? `(${d.chat.length} messages)` : ""}</h3><div id="wchat"></div>
      ${d.facecam ? `<h3>Cadrage</h3><p style="color:var(--mute)">Cam détectée automatiquement (${d.facecam.hits} images sur 8)${d.facecam.full_cam ? " · stream en plein écran caméra" : ""}.</p>` : ""}
    </div>`);
    pb.append(box);
    const ws = $("#wsig", box);
    if (!sig.length) ws.innerHTML = `<p style="color:var(--mute)">${clip.origin === "import" ? "Vidéo importée : pas de chat, le moment a été choisi sur les pics de son (cris, rires, réactions)." : clip.origin === "compilation" ? "Résumé : assemblage des meilleurs moments choisis." : "Pas de détail disponible."}</p>`;
    for (const x of sig) {
      const val = x.value == null ? "–" : Math.round(x.value * 10) / 10, nor = x.normal == null ? "?" : Math.round(x.normal * 10) / 10;
      ws.append(h(`<div class="sigrow ${x.strong ? "strong" : ""}"><div class="lb">${x.strong ? "" : ""}${esc(x.label)}<small>${x.value == null ? "écart par rapport au reste de la vidéo" : `${val} pendant le moment · ${nor} habituellement`}</small></div>
        <div class="rt">${x.ratio ? `×${x.ratio}` : `${x.z > 0 ? "+" : ""}${x.z}σ`}</div>
        <div class="bar"><div style="width:${clamp(x.z / 6, 0, 1) * 100}%;background:${x.strong ? "var(--grad)" : "#555"}"></div></div></div>`));
    }
    if (d.curve?.length > 2) {
      const pts = d.curve, W = 600, H = 70, mx = Math.max(d.threshold * 1.5, ...pts.map((p) => p[1]));
      const x = (i) => (i / (pts.length - 1)) * W, y = (v) => H - (v / mx) * (H - 6) - 3;
      $("#wcurve", box).innerHTML = `<h3>Intensité du live avant le déclenchement</h3><svg class="spark" style="height:70px" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <path d="${pts.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p[1])}`).join("")}" fill="none" stroke="#a78bfa" stroke-width="2" vector-effect="non-scaling-stroke"/>
        <line x1="0" x2="${W}" y1="${y(d.threshold)}" y2="${y(d.threshold)}" stroke="#f59e0b" stroke-dasharray="5 5" vector-effect="non-scaling-stroke"/></svg>
        <small style="color:var(--mute)">Ligne orange = seuil de déclenchement (${d.threshold}). Le chat réagit ~${d.reaction ?? "?"} s après l'action : le clip est calé en conséquence.</small>`;
    }
    const wr = $("#wreas", box);
    (a.reasons || []).forEach((r) => wr.append(h(`<li>${ic("check")} ${esc(r)}</li>`)));
    (a.flags || []).forEach((r) => wr.append(h(`<li class="flag">${ic("triangle-alert")} ${esc(r)}</li>`)));
    if (!a.reasons && !a.flags) wr.append(h(`<li>–</li>`));
    const wc = $("#wchat", box);
    if (d.chat?.length) {
      const cl = h(`<div class="chatlog"></div>`);
      for (const m of d.chat) {
        const row = h(`<div class="${m.tag}"><span class="tm">${m.t > 0 ? "+" : ""}${m.t.toFixed(0)}s</span><span class="us">${esc(m.u)}</span>${esc(m.m)}</div>`);
        row.onclick = () => { if (d.peak_src != null) seek(d.peak_src + m.t - (d.reaction || 0)); };
        cl.append(row);
      }
      wc.append(cl, h(`<small style="color:var(--mute)">Vert = rire · orange = hype · violet = tes mots-clés. Clic = aller à ce moment.</small>`));
    } else wc.innerHTML = `<p style="color:var(--mute)">Aucun message enregistré pour ce clip.</p>`;
  }

  function tabPublish() {
    pb.append(h(`<div>
      <label class="f"><b>Légende de la publication</b><textarea id="cap">${esc(S.publish.caption_template.replace("{title}", E.title).replace("{streamer}", clip.streamer || "").replace("{platform}", clip.platform || ""))}</textarea></label>
      <div class="row">
        <button class="btn ok" id="ap">${ic("check")} Approuver</button><button class="btn bad" id="rj">${ic("x")} Rejeter</button>
        <button class="btn pri" id="pub">${ic("send")} Publier maintenant</button></div>
      <p style="color:var(--mute);font-size:13px">La publication utilise Post for Me (clé API + IDs de comptes dans Réglages). Le rendu final est refait si besoin.</p>
      ${clip.post_id ? `<p>Publié · post <code>${esc(clip.post_id)}</code></p>` : ""}
      ${clip.error ? `<p style="color:var(--bad)">${esc(clip.error)}</p>` : ""}
      <h3>Détection</h3><div class="zs">${Object.entries(clip.detail?.z || {}).map(([k, val]) => `<span class="${val > 1.5 ? "up" : ""}">${k} ${val}</span>`).join("")}</div></div>`));
    $("#ap").onclick = async () => { await saveEdit(); await api(`/api/clips/${clip.id}/approve`, { method: "POST" }); toast("Approuvé"); };
    $("#rj").onclick = async () => { await api(`/api/clips/${clip.id}/reject`, { method: "POST" }); toast("Rejeté"); location.hash = "#/clips"; };
    $("#pub").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "publication…";
      try { await saveEdit(); await api(`/api/clips/${clip.id}/publish`, { method: "POST", json: { caption: $("#cap").value } }); toast("Publié"); } catch (er) { toast("Échec : " + er.message, 5000); }
      e.target.disabled = false; e.target.textContent = "Publier maintenant";
    };
  }

  /* ---- transcription éditable (phrases) */
  function sentencesOf() {
    const out = []; let cur = [];
    words.forEach((w, i) => { cur.push(i); const n = words[i + 1]; if (/[.?!]$/.test(w.w.trim()) || (n && (n.s - w.e > 0.8 || !!n.skip !== !!w.skip))) { out.push(cur); cur = []; } });
    if (cur.length) out.push(cur); return out;
  }
  function renderTranscript() {
    const box = $("#trp"); box.innerHTML = "";
    box.append(h(`<small style="color:var(--mute)">Clique dans une phrase pour corriger. Les mots grisés sont hors du clip. Entrée = valider.</small>`));
    for (const idx of sentencesOf()) {
      const s0 = words[idx[0]], inClip = E.segments.some((g) => s0.s >= g.s - 0.01 && s0.s < g.e);
      const game = !!s0.skip;
      if (game || idx.length) {
        const tg = h(`<button class="btn sm trg ${game ? "" : "on"}" title="${game ? "Voix du jeu / autre langue : masquée des sous-titres. Cliquer pour l'afficher" : "Cliquer pour masquer cette phrase des sous-titres"}">${game ? "masquée" : ""}</button>`);
        tg.onclick = () => { idx.forEach((i) => { if (game) delete words[i].skip; else words[i].skip = true; }); capKey = ""; mark(); renderTranscript(); };
        box.append(tg);
      }
      const el = h(`<p class="trs ${inClip ? "" : "out"} ${game ? "game" : ""}" contenteditable="true" spellcheck="true"><span class="tt">${fmt(s0.s)}</span>${esc(idx.map((i) => words[i].w).join(" "))}</p>`);
      el.dataset.first = idx[0]; el.dataset.n = idx.length;
      el.onfocus = () => { seek(s0.s - 0.05); };
      el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); el.blur(); } };
      el.onblur = () => {
        const txt = el.textContent.replace(/^\d+:\d{2}/, "").trim(), toks = txt.split(/\s+/).filter(Boolean);
        const old = idx.map((i) => words[i]); if (toks.join(" ") === old.map((w) => w.w).join(" ")) return;
        let nw;
        if (toks.length === old.length) nw = old.map((w, j) => ({ ...w, w: toks[j] }));
        else { // nombre de mots différent : on répartit la durée de la phrase selon la longueur des mots
          const a = old[0].s, b = old.at(-1).e, L = toks.reduce((x, t) => x + t.length + 1, 0); let t = a;
          nw = toks.map((tk) => { const d = (b - a) * (tk.length + 1) / L, w = { w: tk, s: +t.toFixed(3), e: +(t + d * 0.92).toFixed(3), ...(old[0].skip ? { skip: true } : {}) }; t += d; return w; });
        }
        words.splice(idx[0], idx.length, ...nw); mark(); renderTranscript(); toast("Transcription corrigée");
      };
      box.append(el);
    }
  }
  $("#trb").onclick = () => { const p = $("#trp"); p.hidden = !p.hidden; $("#trb").textContent = p.hidden ? "Afficher la transcription" : "Masquer la transcription"; if (!p.hidden) renderTranscript(); };

  /* ---- sauvegarde & rendu */
  async function saveEdit() {
    if (shift) { words.forEach((w) => { w.s = +(w.s + shift).toFixed(3); w.e = +(w.e + shift).toFixed(3); }); shift = 0; }
    E.segments.forEach((g) => { g.s = +g.s.toFixed(3); g.e = +g.e.toFixed(3); }); syncTrim();
    await api(`/api/clips/${clip.id}`, { method: "PATCH", json: { edit: E, words, title: E.title } });
    dirty = false; $("#dirty").hidden = true;
  }
  const busy = async (btn, label, fn) => {
    const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `${ic("loader", "spin")} ${label}`;
    try { await fn(); } catch (e) { toast(`Échec : ${e.message}`, 6000); } finally { btn.disabled = false; btn.innerHTML = old; }
  };
  $("#save").onclick = () => busy($("#save"), "Enregistrement…", async () => { await saveEdit(); toast("Enregistré"); });
  $("#rend").onclick = () => busy($("#rend"), "Envoi…", async () => { await saveEdit(); await api(`/api/clips/${clip.id}/render`, { method: "POST" }); toast("Rendu lancé — 1 à 3 min"); pollRender(); });
  async function pollRender() {
    const c = await api(`/api/clips/${clip.id}`);
    const ob = $("#outbar"); if (!ob) return;
    if (["rendering", "queued"].includes(c.render_status)) { ob.innerHTML = `<span class="pill pending">${ic("loader")} rendu en cours…</span>`; setTimeout(pollRender, 2500); return; }
    ob.innerHTML = c.render_status === "done" && c.path
      ? `<a class="btn sm" target="_blank" href="${MB}/media/${c.id}/final?v=${Date.now()}">${ic("eye")} Voir le rendu</a><a class="btn sm" href="${MB}/media/${c.id}/final?dl=1">${ic("download")} Télécharger MP4</a>`
      : c.render_status === "error" ? `<span class="pill error" title="${esc(c.error)}">${ic("triangle-alert")} échec du rendu</span>` : "";
  }
  pollRender();
}

/* ===================================================================== boot */
refreshIntegrations(); setInterval(refreshIntegrations, 15000);
route();
