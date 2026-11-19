"use strict";
/* ClipAuto — interface web (vanilla JS, pas de build). */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (html) => { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; };
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (s) => { s = Math.max(0, s || 0); return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`; };
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
const deep = (o) => JSON.parse(JSON.stringify(o));

async function api(path, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; delete o.json; }
  const r = await fetch(path, o);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch { } throw new Error(m); }
  return r.status === 204 ? null : r.json();
}
function toast(msg, ms = 2600) {
  const d = h(`<div>${esc(msg)}</div>`); $("#toast").append(d); setTimeout(() => d.remove(), ms);
}
let META = null, timers = [];
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
  if (!META) META = await api("/api/meta");
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
    <div class="spacer"></div><a class="btn pri" href="#/import">⬆️ Importer une vidéo</a></div>`));
  const tabs = h(`<div class="tabs"></div>`); v.append(tabs);
  const grid = h(`<div class="clips"></div>`); v.append(grid);
  const T = [["", "Tous"], ["pending", "À valider"], ["approved", "Approuvés"], ["published", "Publiés"], ["rejected", "Rejetés"]];
  let sig = "";
  async function load() {
    const [clips, st] = await Promise.all([api("/api/clips" + (filter ? `?status=${filter}` : "")), api("/api/state")]);
    tabs.innerHTML = T.map(([k, l]) => `<button data-k="${k}" class="${k === filter ? "on" : ""}">${l}${k && st.counts[k] ? ` · ${st.counts[k]}` : ""}</button>`).join("");
    $$("button", tabs).forEach((b) => b.onclick = () => { filter = b.dataset.k; sessionStorage.setItem("cf", filter); sig = ""; load(); });
    const nsig = JSON.stringify(clips.map((c) => [c.id, c.status, c.render_status, c.title]));
    if (nsig === sig) return; sig = nsig;
    grid.innerHTML = "";
    if (!clips.length) { grid.append(h(`<div class="empty" style="grid-column:1/-1">Aucun clip pour l'instant.<br>Ajoute des streamers ou importe une VOD.</div>`)); return; }
    for (const c of clips) grid.append(clipCard(c, load));
  }
  every(load, 5000);
}

function clipCard(c, reload) {
  const sc = Math.round(100 * (1 - Math.exp(-Math.max(c.score, 0) / 2))); // 1.4→50, 3→78, 5→92
  const cls = sc >= 70 ? "hi" : sc >= 40 ? "mid" : "lo";
  const rendering = ["rendering", "queued"].includes(c.render_status);
  const el = h(`<div class="clipc">
    <div class="thumb">
      ${c.thumb ? `<img loading="lazy" src="/media/${c.id}/thumb?v=${c.render_status}">` : ""}
      <div class="score ${cls}">${sc}<small>VIRAL</small></div>
      <div class="dur">${fmt(c.duration)}</div>
      ${rendering ? `<div class="rstat">⏳ rendu en cours…</div>` : ""}
      ${c.render_status === "error" ? `<div class="rstat">⚠️ échec du rendu</div>` : ""}
    </div>
    <div class="meta">
      <div class="t">${esc(c.title || "Sans titre")}</div>
      <div class="row" style="gap:6px"><span class="pill">${esc(c.streamer || "—")}</span><span class="pill ${c.status}">${statusLabel(c.status)}</span></div>
      <div class="acts">
        <a class="btn sm" href="#/edit/${c.id}" title="Éditer">✂️</a>
        <button class="btn sm ok" data-a="approve" title="Approuver">✅</button>
        <button class="btn sm bad" data-a="reject" title="Rejeter">✖</button>
        ${c.path ? `<a class="btn sm" href="/media/${c.id}/final?dl=1" title="Télécharger">⬇️</a>` : ""}
      </div>
    </div></div>`);
  const th = $(".thumb", el);
  th.onclick = () => location.hash = `#/edit/${c.id}`;
  if (c.path && !rendering) {
    let vid;
    th.onmouseenter = () => { vid = h(`<video muted loop playsinline src="/media/${c.id}/final"></video>`); vid.style.position = "absolute"; vid.style.inset = 0; th.append(vid); vid.play().catch(() => { }); };
    th.onmouseleave = () => vid && vid.remove();
  }
  $$("[data-a]", el).forEach((b) => b.onclick = async () => { await api(`/api/clips/${c.id}/${b.dataset.a}`, { method: "POST" }); toast(b.dataset.a === "approve" ? "Clip approuvé ✅" : "Clip rejeté"); reload(); });
  return el;
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
        ${ss ? `<div style="color:var(--mute);font-size:13px;margin-top:4px">${esc(ss.title || "")} · 👁 ${ss.viewers ?? "?"} · 💬 ${ss.chat_msgs} msgs · depuis ${fmt((Date.now() / 1000 - ss.since))}</div>` : ""}
      </div>
      <div class="row" style="gap:6px">
        <label class="inline" title="Surveiller"><input type="checkbox" ${s.enabled ? "checked" : ""} data-x="en"> actif</label>
        <button class="btn sm" data-x="cfg">⚙️</button>
        <button class="btn sm bad" data-x="del">🗑</button>
      </div>
    </div>
    ${ss ? sparkline(ss) : ""}
    <div class="ovr" ${open.has(s.id) ? "" : "hidden"}></div>
  </div>`);
  $('[data-x="en"]', el).onchange = async (e) => { await api(`/api/streamers/${s.id}`, { method: "PATCH", json: { enabled: e.target.checked } }); rerender(true); };
  $('[data-x="del"]', el).onclick = async () => { if (!confirm(`Ne plus suivre ${s.channel} ?`)) return; await api(`/api/streamers/${s.id}`, { method: "DELETE" }); rerender(true); };
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
      <button class="btn pri" id="ig" style="width:100%;justify-content:center">✨ Trouver les moments forts</button>
      <p style="color:var(--mute);font-size:12px">Astuce : ajoute des mots-clés dans Réglages → Détection pour repérer aussi ce qui est <i>dit</i> (plus lent : transcription complète).</p>
    </div></div>`);
  v.append(f);
  let file = null;
  const dz = $("#dz", f), fi = $("#if", f);
  dz.onclick = () => fi.click();
  fi.onchange = () => { file = fi.files[0]; dz.textContent = file ? `📁 ${file.name}` : dz.textContent; };
  dz.ondragover = (e) => { e.preventDefault(); dz.classList.add("on"); };
  dz.ondragleave = () => dz.classList.remove("on");
  dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove("on"); file = e.dataTransfer.files[0]; dz.textContent = `📁 ${file.name}`; };
  $("#ig", f).onclick = async () => {
    const fd = new FormData();
    const url = $("#iu", f).value.trim();
    if (!url && !file) return toast("Colle un lien ou choisis un fichier");
    if (url) fd.append("url", url); if (file) fd.append("file", file);
    fd.append("streamer", $("#is", f).value); fd.append("max_clips", $("#in", f).value || 5);
    if ($("#imin", f).value) fd.append("min_seconds", $("#imin", f).value);
    if ($("#imax", f).value) fd.append("max_seconds", $("#imax", f).value);
    $("#ig", f).disabled = true;
    try { await api("/api/import", { method: "POST", body: fd }); toast("Import lancé 🚀"); } catch (e) { toast(e.message); }
    $("#ig", f).disabled = false; file = null; $("#iu", f).value = "";
  };
  const jobs = h(`<div class="card"><h2>Imports récents</h2><div id="jl"></div></div>`); v.append(jobs);
  every(async () => {
    const js = await api("/api/jobs");
    $("#jl", jobs).innerHTML = js.length ? js.map((j) => `<div class="job"><div class="row"><b style="overflow:hidden;text-overflow:ellipsis;max-width:70%">${esc(j.label)}</b><div class="spacer"></div>
      <span class="pill ${j.status === "error" ? "error" : j.status === "done" ? "published" : "pending"}">${j.status === "running" ? "en cours" : j.status === "done" ? "terminé" : "erreur"}</span></div>
      <div class="bar"><div style="width:${Math.round((j.progress || 0) * 100)}%"></div></div><small style="color:var(--mute)">${esc(j.message || "")}</small></div>`).join("")
      : `<div style="color:var(--mute)">Aucun import.</div>`;
  }, 3000);
}

/* ===================================================================== SETTINGS */
async function viewSettings(v) {
  const S = await api("/api/settings");
  v.append(h(`<div class="row"><div><h1>Réglages</h1><p class="sub">Appliqués à chaud aux lives en cours. Chaque streamer peut avoir ses propres réglages (page Streamers → ⚙️).</p></div>
    <div class="spacer"></div><button class="btn pri" id="sv">💾 Enregistrer</button></div>`));
  const d = S.detect, c = S.clip, p = S.publish;
  const names = { chat_rate: "Activité du chat", unique_chatters: "Viewers qui écrivent", laugh_emotes: "Rires (KEKW, 😂, mdr…)", hype_emotes: "Hype (Pog, W, 🔥…)", keywords: "Vos mots-clés", audio: "Pics de volume" };
  const g = h(`<div class="grid2">
   <div class="card"><h2>🎯 Détection des moments forts</h2>
     <label class="f"><b>Sensibilité — seuil : <span id="thv">${d.threshold}</span></b><input type="range" min="0.5" max="5" step="0.1" data-p="detect.threshold" value="${d.threshold}" oninput="thv.textContent=this.value"><small>À gauche = plus de clips (plus de déchets) · à droite = seulement les gros moments</small></label>
     <label class="f"><b>Signaux qui doivent monter ensemble</b><select data-p="detect.min_signals" data-n>${[1, 2, 3, 4].map((n) => `<option ${n == d.min_signals ? "selected" : ""}>${n}</option>`).join("")}</select><small>2 recommandé : un spammeur seul ne déclenche rien</small></label>
     <h3>Poids de chaque signal</h3>
     <div class="weights">${Object.keys(names).map((k) => `<span>${names[k]}</span><input type="range" min="0" max="3" step="0.1" data-p="detect.weights.${k}" value="${d.weights[k] ?? 0}" oninput="this.nextElementSibling.textContent=this.value"><b>${d.weights[k] ?? 0}</b>`).join("")}</div>
     <h3>Timing</h3>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Délai du chat (s)</b><input type="number" data-p="detect.chat_delay_seconds" data-n value="${d.chat_delay_seconds}"><small>Le chat réagit en retard</small></label>
      <label class="f"><b>Pause entre 2 clips (s)</b><input type="number" data-p="detect.cooldown_seconds" data-n value="${d.cooldown_seconds}"></label>
      <label class="f"><b>Calibrage au début (s)</b><input type="number" data-p="detect.warmup_seconds" data-n value="${d.warmup_seconds}"></label>
      <label class="f"><b>Max clips / heure</b><input type="number" data-p="detect.max_clips_per_hour" data-n value="${d.max_clips_per_hour}"></label>
     </div>
   </div>
   <div class="card"><h2>🔤 Mots &amp; emotes</h2>
     <label class="f"><b>Mots-clés perso</b><textarea data-p="detect.keywords" data-l placeholder="clip, braquage, la police, nom d'un perso…">${esc(d.keywords.join(", "))}</textarea><small>Dans le chat (live) et dans ce qui est dit (imports). Terminer par * = préfixe (ex. brakage*)</small></label>
     <label class="f"><b>Rires</b><textarea data-p="detect.laugh_words" data-l>${esc(d.laugh_words.join(", "))}</textarea></label>
     <label class="f"><b>Hype</b><textarea data-p="detect.hype_words" data-l>${esc(d.hype_words.join(", "))}</textarea></label>
   </div>
   <div class="card"><h2>✂️ Clips</h2>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Durée min (s)</b><input type="number" data-p="clip.min_seconds" data-n value="${c.min_seconds}"></label>
      <label class="f"><b>Durée max (s)</b><input type="number" data-p="clip.max_seconds" data-n value="${c.max_seconds}"></label>
      <label class="f"><b>Avant le pic (s)</b><input type="number" data-p="clip.pre_roll" data-n value="${c.pre_roll}"><small>La montée en tension</small></label>
      <label class="f"><b>Après le pic (s)</b><input type="number" data-p="clip.post_roll" data-n value="${c.post_roll}"><small>La réaction</small></label>
     </div>
     <label class="inline f"><input type="checkbox" data-p="clip.snap_to_sentences" ${c.snap_to_sentences ? "checked" : ""}><b>Couper entre deux phrases (jamais au milieu d'un mot)</b></label>
     <label class="inline f"><input type="checkbox" data-p="clip.auto_render" ${c.auto_render ? "checked" : ""}><b>Rendu final automatique</b></label>
     <div class="grid2" style="gap:10px">
      <label class="f"><b>Langue des sous-titres</b><select data-p="clip.language">${[["fr", "Français"], ["en", "Anglais"], ["es", "Espagnol"], ["", "Auto"]].map(([k, l]) => `<option value="${k}" ${k === (c.language || "") ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <label class="f"><b>Précision transcription</b><select data-p="clip.whisper_model">${[["base", "Rapide"], ["small", "Équilibrée"], ["medium", "Précise (lent)"], ["large-v3", "Max (GPU)"]].map(([k, l]) => `<option value="${k}" ${k === c.whisper_model ? "selected" : ""}>${l}</option>`).join("")}</select></label>
     </div>
   </div>
   <div class="card"><h2>🎨 Style par défaut des nouveaux clips</h2><div id="stylebox"></div></div>
   <div class="card"><h2>📤 Publication (Post for Me)</h2>
     <label class="inline f"><input type="checkbox" data-p="publish.auto_publish" ${p.auto_publish ? "checked" : ""}><b>Publier automatiquement quand j'approuve</b></label>
     <label class="f"><b>Comptes sociaux (IDs Post for Me)</b><input type="text" data-p="publish.social_accounts" data-l value="${esc(p.social_accounts.join(", "))}" placeholder="spc_xxx, spc_yyy"></label>
     <label class="f"><b>Légende</b><input type="text" data-p="publish.caption_template" value="${esc(p.caption_template)}"><small>Variables : {title} {streamer} {platform}</small></label>
   </div>
   <div class="card"><h2>📡 Surveillance</h2>
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
    await api("/api/settings", { method: "PUT", json: out }); toast("Réglages enregistrés ✅");
  };
}

/* ---------- contrôles de style partagés (réglages + éditeur) */
function styleControls(box, st, layout, hook, onChange) {
  const ch = () => onChange();
  box.innerHTML = `
    <div class="presets">${Object.keys(META.presets).map((k) => `<button data-pr="${k}" style="font-family:'${META.presets[k].font}';color:${META.presets[k].highlight}" class="${st.preset === k ? "on" : ""}">${k.toUpperCase()}</button>`).join("")}</div>
    <div class="grid2" style="gap:10px">
      <label class="f"><b>Police</b><select data-s="font">${META.fonts.map((f) => `<option ${f === st.font ? "selected" : ""} style="font-family:'${f}'">${f}</option>`).join("")}</select></label>
      <label class="f"><b>Taille <span>${st.size}</span></b><input type="range" min="36" max="130" data-s="size" data-n value="${st.size}"></label>
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
      <label class="inline"><input type="checkbox" data-s="pop" ${st.pop ? "checked" : ""}> Animation « pop »</label>
    </div>
    <h3>Format</h3>
    <div class="layouts">${layoutBtns(layout.mode)}</div>
    <h3>Titre d'accroche (hook)</h3>
    <div class="row"><label class="inline"><input type="checkbox" data-hk="enabled" ${hook.enabled ? "checked" : ""}> Afficher</label>
      <label class="inline">pendant <input type="number" step="0.5" style="width:70px" data-hk="seconds" value="${hook.seconds}"> s</label>
      <label class="inline">Texte <input type="color" data-hk="color" value="${hook.color}"></label>
      <label class="inline">Fond <input type="color" data-hk="bg" value="${hook.bg}"></label></div>`;
  $$("[data-pr]", box).forEach((b) => b.onclick = () => { Object.assign(st, META.presets[b.dataset.pr], { preset: b.dataset.pr }); styleControls(box, st, layout, hook, onChange); ch(); });
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
    split: ["Facecam + jeu", `<rect x="1" y="1" width="26" height="18" rx="3" fill="#f472b6"/><rect x="1" y="21" width="26" height="24" rx="3" fill="#38bdf8"/>`],
    fit: ["Bandes noires", `<rect x="1" y="1" width="26" height="44" rx="3" fill="#111"/><rect x="1" y="16" width="26" height="14" fill="#a78bfa"/>`],
  };
  return Object.entries(L).map(([k, [n, svg]]) => `<button data-lm="${k}" class="${mode === k ? "on" : ""}"><svg viewBox="0 0 28 46">${svg}</svg>${n}</button>`).join("");
}

/* ===================================================================== EDITOR */
function groupWords(words, perLine, maxChars) { // identique à captions.group_words (Python)
  const lines = []; let cur = [];
  for (const w of words) {
    if (!(w.w || "").trim()) continue;
    if (cur.length) {
      const gap = w.s - cur.at(-1).e;
      const chars = cur.reduce((a, x) => a + x.w.trim().length + 1, 0) + w.w.trim().length;
      if (cur.length >= perLine || gap > 0.6 || chars > maxChars || ".?!,".includes(cur.at(-1).w.trim().slice(-1))) { lines.push(cur); cur = []; }
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
  let dirty = false, shift = 0;
  const mark = () => { dirty = true; $("#dirty").hidden = false; draw(); };

  v.append(h(`<div class="row" style="margin-bottom:16px">
    <a class="btn sm" href="#/clips">← Clips</a>
    <input type="text" id="ttl" value="${esc(E.title)}" placeholder="Titre d'accroche du clip" style="flex:1;min-width:200px;font-weight:600;font-size:16px">
    <span class="pill ${clip.status}">${statusLabel(clip.status)}</span></div>`));
  const ed = h(`<div class="ed">
    <div class="stage">
      <div class="phone" id="ph"></div>
      <div class="controls">
        <button class="btn sm" id="pp">▶︎</button><button class="btn sm" id="rw">⟲ début</button>
        <select id="spd" style="width:auto;padding:5px 8px">${[0.9, 1, 1.1, 1.2, 1.25].map((s) => `<option ${s == E.speed ? "selected" : ""}>${s}</option>`).join("")}</select>
        <span class="time" id="tm"></span></div>
      <div class="savebar">
        <button class="btn" id="save">💾 Enregistrer</button>
        <button class="btn pri" id="rend">🎬 Rendu final</button>
        <span id="dirty" class="pill pending" hidden>modifs non enregistrées</span>
      </div>
      <div class="savebar" id="outbar"></div>
    </div>
    <div class="panel">
      <div class="ptabs">${["Découpe", "Sous-titres", "Style", "Cadrage", "Publier"].map((t, i) => `<button data-t="${i}" class="${i ? "" : "on"}">${t}</button>`).join("")}</div>
      <div class="pbody" id="pb"></div>
    </div></div>`);
  v.append(ed);
  $("#ttl").oninput = (e) => { E.title = e.target.value; mark(); };

  /* ---- lecteurs vidéo (un maître avec le son + des copies muettes pour les calques) */
  const src = `/media/${clip.id}/source`;
  const master = h(`<video preload="auto" playsinline src="${src}"></video>`);
  master.style.display = "none"; ed.append(master);
  let iw = 1920, ih = 1080, dur = 1;
  const ph = $("#ph"), copies = [];
  const mk = () => { const x = h(`<video muted playsinline preload="auto" src="${src}"></video>`); copies.push(x); return x; };
  const capEl = h(`<div class="capl"></div>`), hookEl = h(`<div class="hookl"></div>`);

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
      place(mk(), box(0, th), W, th, cropRect(L.facecam, iw, ih, W / th));
      place(mk(), box(th, bh), W, bh, cropRect(L.gameplay, iw, ih, W / bh));
    } else if (L.mode === "fill") {
      const nw = ih * 9 / 16; const x = clamp((L.focus?.x ?? .5) * iw - nw / 2, 0, iw - nw);
      place(mk(), box(0, H), W, H, { x, y: 0, w: nw, h: ih });
    } else {
      const b = box(0, H);
      if (L.mode === "blur") { const bg = mk(); bg.classList.add("bgv"); const s = Math.max(W / iw, H / ih); Object.assign(bg.style, { width: `${iw * s}px`, height: `${ih * s}px`, left: `${(W - iw * s) / 2}px`, top: `${(H - ih * s) / 2}px` }); b.append(bg); }
      const fg = mk(); const fw = W * (L.mode === "blur" ? (L.zoom || 1) : 1), fh = fw * ih / iw;
      Object.assign(fg.style, { width: `${fw}px`, height: `${fh}px`, left: `${(W - fw) / 2}px`, top: `${(H - fh) / 2}px` }); b.append(fg);
    }
    ph.append(capEl, hookEl);
    copies.forEach((c) => { c.currentTime = master.currentTime; });
    draw();
  }

  /* ---- sous-titres & hook (même logique que le rendu ASS) */
  let lines = [];
  function draw() {
    const st = E.style, k = ph.clientWidth / 1080, t = master.currentTime - shift;
    lines = groupWords(words.filter((w) => w.e > E.trim[0] && w.s < E.trim[1]), st.words_per_line, st.max_chars || 18);
    let html = "";
    for (const L of lines) {
      const end = L.at(-1).e + 0.15;
      if (t >= L[0].s && t < end) {
        const ai = L.findIndex((w, i) => t >= w.s && (i + 1 >= L.length || t < L[i + 1].s));
        html = L.map((w, i) => { const tx = esc(st.uppercase ? w.w.trim().toUpperCase() : w.w.trim()); return i === ai ? `<span style="color:${st.highlight};${st.pop ? "transform:scale(1.12)" : ""}">${tx}</span>` : `<span>${tx}</span>`; }).join(" ");
        break;
      }
    }
    Object.assign(capEl.style, {
      top: `${st.position}%`, fontFamily: `'${st.font}'`, fontSize: `${st.size * k}px`, color: st.color,
      WebkitTextStroke: `${st.outline * 2 * k}px ${st.outline_color}`, textShadow: st.shadow ? `${st.shadow * k}px ${st.shadow * k}px 0 #00000080` : "none",
    });
    capEl.innerHTML = E.captions === false ? "" : html;
    const hk = E.hook, showH = hk.enabled && E.title && master.currentTime - E.trim[0] < hk.seconds;
    Object.assign(hookEl.style, { top: `${170 * k}px`, fontFamily: `'${st.font}'`, fontSize: `${(hk.size || 72) * k}px`, color: hk.color });
    hookEl.innerHTML = showH ? `<span style="background:${hk.bg}">${esc(E.title)}</span>` : "";
    $("#tm").textContent = `${fmt(master.currentTime - E.trim[0])} / ${fmt(E.trim[1] - E.trim[0])}`;
    $$(".words .w").forEach((el) => { const w = words[el.dataset.i]; el.classList.toggle("cur", !!w && t >= w.s && t < w.e); });
    const tlph = $(".tl .ph"); if (tlph) tlph.style.left = `${(master.currentTime / dur) * 100}%`;
  }
  let raf;
  const loop = () => {
    if (!master.paused && master.currentTime >= E.trim[1]) { master.pause(); master.currentTime = E.trim[0]; }
    for (const c of copies) { if (Math.abs(c.currentTime - master.currentTime) > 0.12) c.currentTime = master.currentTime; if (master.paused !== c.paused) master.paused ? c.pause() : c.play().catch(() => { }); }
    $("#pp").textContent = master.paused ? "▶︎" : "❚❚";
    draw(); raf = requestAnimationFrame(loop);
  };
  const seek = (t) => { master.currentTime = clamp(t, 0, dur); copies.forEach((c) => c.currentTime = master.currentTime); };
  $("#pp").onclick = () => { if (master.paused) { if (master.currentTime < E.trim[0] || master.currentTime >= E.trim[1] - 0.05) seek(E.trim[0]); master.play(); } else master.pause(); };
  $("#rw").onclick = () => seek(E.trim[0]);
  $("#spd").onchange = (e) => { E.speed = Number(e.target.value); master.playbackRate = E.speed; mark(); };
  const ro = new ResizeObserver(() => buildStage()); ro.observe(ph);
  window._edCleanup = () => { cancelAnimationFrame(raf); ro.disconnect(); master.pause(); window.onbeforeunload = null; };
  window.onbeforeunload = () => dirty ? "" : undefined;
  master.addEventListener("loadedmetadata", () => { iw = master.videoWidth; ih = master.videoHeight; dur = master.duration; master.playbackRate = E.speed; seek(E.trim[0]); buildStage(); showTab(0); });
  loop();

  /* ---- onglets */
  let wave = null;
  const pb = $("#pb");
  $$(".ptabs button").forEach((b) => b.onclick = () => showTab(+b.dataset.t));
  function showTab(i) {
    $$(".ptabs button").forEach((b) => b.classList.toggle("on", +b.dataset.t === i));
    pb.innerHTML = "";
    [tabTrim, tabWords, tabStyle, tabCrop, tabPublish][i]();
  }

  function tabTrim() {
    pb.append(h(`<div>
      <div class="row"><b>Début ${fmt(E.trim[0])}</b><div class="spacer"></div><b id="dd"></b><div class="spacer"></div><b>Fin ${fmt(E.trim[1])}</b></div>
      <div class="tl" id="tl"><canvas class="wave"></canvas><div class="sel"><div class="h l">‹</div><div class="h r">›</div></div><div class="ph"></div></div>
      <small style="color:var(--mute)">Glisse les poignées pour couper · clic sur la frise pour se déplacer · source complète : ${fmt(dur)}</small>
      <div class="row" style="margin-top:14px">
        <button class="btn sm" id="sI">⇤ Début ici</button><button class="btn sm" id="sO">Fin ici ⇥</button>
        <button class="btn sm" id="snap">🧲 Caler sur les phrases</button>
        <button class="btn sm" id="m5">−5 s</button><button class="btn sm" id="p5">+5 s</button></div>
      <h3>Astuce</h3><p style="color:var(--mute);margin:0">Les vidéos les plus virales démarrent <b>directement dans l'action</b> : coupe les 2-3 premières secondes « vides ». Durée idéale TikTok / Shorts : 25 – 45 s.</p></div>`));
    const tl = $("#tl"), sel = $(".sel", tl);
    const upd = () => {
      sel.style.left = `${(E.trim[0] / dur) * 100}%`; sel.style.width = `${((E.trim[1] - E.trim[0]) / dur) * 100}%`;
      const d = E.trim[1] - E.trim[0]; $("#dd").textContent = `${d.toFixed(1)} s`; $("#dd").style.color = d < S.clip.min_seconds || d > S.clip.max_seconds ? "var(--warn)" : "";
    };
    for (const w of words) tl.append(h(`<div class="wd" style="left:${(w.s / dur) * 100}%;width:${Math.max(((w.e - w.s) / dur) * 100, .2)}%"></div>`));
    drawWave($("canvas", tl));
    upd();
    const x2t = (x) => clamp((x - tl.getBoundingClientRect().left) / tl.clientWidth, 0, 1) * dur;
    let drag = null;
    tl.onpointerdown = (e) => {
      drag = e.target.closest(".h.l") ? "l" : e.target.closest(".h.r") ? "r" : null;
      if (!drag) seek(x2t(e.clientX)); else tl.setPointerCapture(e.pointerId);
    };
    tl.onpointermove = (e) => {
      if (!drag) return; const t = x2t(e.clientX);
      if (drag === "l") E.trim[0] = clamp(t, 0, E.trim[1] - 3); else E.trim[1] = clamp(t, E.trim[0] + 3, dur);
      seek(drag === "l" ? E.trim[0] : E.trim[1] - 0.5); upd(); mark();
    };
    tl.onpointerup = () => { if (drag) showTab(0); drag = null; };
    $("#sI").onclick = () => { E.trim[0] = clamp(master.currentTime, 0, E.trim[1] - 3); mark(); showTab(0); };
    $("#sO").onclick = () => { E.trim[1] = clamp(master.currentTime, E.trim[0] + 3, dur); mark(); showTab(0); };
    $("#m5").onclick = () => { E.trim[1] = clamp(E.trim[1] - 5, E.trim[0] + 3, dur); mark(); showTab(0); };
    $("#p5").onclick = () => { E.trim[1] = clamp(E.trim[1] + 5, E.trim[0] + 3, dur); mark(); showTab(0); };
    $("#snap").onclick = () => {
      const near = (t, edge) => { let best = t, bd = 9; for (let i = 0; i < words.length - 1; i++) { const g = words[i + 1].s - words[i].e; const m = (words[i].e + words[i + 1].s) / 2; const d = Math.abs(m - t) - g; if (Math.abs(m - t) < 3 && d < bd) { bd = d; best = m; } } return best; };
      E.trim = [near(E.trim[0]), near(E.trim[1])]; mark(); showTab(0); toast("Coupes calées sur les pauses 🧲");
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
        <button class="btn sm" id="retr">🔁 Re-transcrire</button></div>
      <label class="f" style="margin-top:14px"><b>Synchro : décaler tous les sous-titres <span id="shv">${shift.toFixed(2)} s</span></b>
        <input type="range" min="-1" max="1" step="0.05" id="sh" value="${shift}"><small>Si le texte arrive trop tôt → vers la droite. Appliqué à l'enregistrement.</small></label>
      <h3>Texte (clique un mot pour le corriger · Suppr pour l'effacer · double-clic pour s'y rendre)</h3>
      <div class="words" id="wl"></div></div>`));
    $("#cOn").onchange = (e) => { E.captions = e.target.checked; mark(); };
    $("#sh").oninput = (e) => { shift = Number(e.target.value); $("#shv").textContent = `${shift.toFixed(2)} s`; mark(); };
    $("#retr").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "⏳ transcription…";
      try { words = (await api(`/api/clips/${clip.id}/retranscribe`, { method: "POST", json: { language: $("#lang").value } })).words; toast("Transcription mise à jour"); mark(); showTab(1); } catch (er) { toast(er.message); e.target.disabled = false; }
    };
    const wl = $("#wl");
    words.forEach((w, i) => {
      const out = w.e <= E.trim[0] || w.s >= E.trim[1];
      const el = h(`<span class="w ${out ? "out" : ""}" contenteditable="true" spellcheck="false" data-i="${i}">${esc(w.w)}</span>`);
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
    if (L.mode === "split") {
      rects.push(["facecam", "face", "Facecam"], ["gameplay", "game", "Jeu"]);
      opts.append(h(`<label class="f"><b>Hauteur de la facecam <span id="srv">${Math.round(L.split_ratio * 100)}%</span></b><input type="range" min="0.2" max="0.6" step="0.01" id="sr" value="${L.split_ratio}"></label>`));
      $("#sr").oninput = (e) => { L.split_ratio = Number(e.target.value); $("#srv").textContent = `${Math.round(L.split_ratio * 100)}%`; buildStage(); mark(); };
      opts.append(h(`<small style="color:var(--mute)">Déplace le cadre <b style="color:#f472b6">rose</b> sur la webcam du streamer et le <b style="color:#38bdf8">bleu</b> sur le jeu. Coin en bas à droite = redimensionner.</small>`));
    } else if (L.mode === "fill") {
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

  function tabPublish() {
    pb.append(h(`<div>
      <label class="f"><b>Légende de la publication</b><textarea id="cap">${esc(S.publish.caption_template.replace("{title}", E.title).replace("{streamer}", clip.streamer || "").replace("{platform}", clip.platform || ""))}</textarea></label>
      <div class="row">
        <button class="btn ok" id="ap">✅ Approuver</button><button class="btn bad" id="rj">✖ Rejeter</button>
        <button class="btn pri" id="pub">📤 Publier maintenant</button></div>
      <p style="color:var(--mute);font-size:13px">La publication utilise Post for Me (clé API + IDs de comptes dans Réglages). Le rendu final est refait si besoin.</p>
      ${clip.post_id ? `<p>Publié · post <code>${esc(clip.post_id)}</code></p>` : ""}
      ${clip.error ? `<p style="color:var(--bad)">${esc(clip.error)}</p>` : ""}
      <h3>Détection</h3><div class="zs">${Object.entries(clip.detail?.z || {}).map(([k, val]) => `<span class="${val > 1.5 ? "up" : ""}">${k} ${val}</span>`).join("")}</div></div>`));
    $("#ap").onclick = async () => { await saveEdit(); await api(`/api/clips/${clip.id}/approve`, { method: "POST" }); toast("Approuvé ✅"); };
    $("#rj").onclick = async () => { await api(`/api/clips/${clip.id}/reject`, { method: "POST" }); toast("Rejeté"); location.hash = "#/clips"; };
    $("#pub").onclick = async (e) => {
      e.target.disabled = true; e.target.textContent = "⏳ publication…";
      try { await saveEdit(); await api(`/api/clips/${clip.id}/publish`, { method: "POST", json: { caption: $("#cap").value } }); toast("Publié 🚀"); } catch (er) { toast("Échec : " + er.message, 5000); }
      e.target.disabled = false; e.target.textContent = "📤 Publier maintenant";
    };
  }

  /* ---- sauvegarde & rendu */
  async function saveEdit() {
    if (shift) { words.forEach((w) => { w.s = +(w.s + shift).toFixed(3); w.e = +(w.e + shift).toFixed(3); }); shift = 0; }
    E.trim = E.trim.map((x) => +x.toFixed(2));
    await api(`/api/clips/${clip.id}`, { method: "PATCH", json: { edit: E, words, title: E.title } });
    dirty = false; $("#dirty").hidden = true;
  }
  $("#save").onclick = async () => { await saveEdit(); toast("Enregistré 💾"); };
  $("#rend").onclick = async () => { await saveEdit(); await api(`/api/clips/${clip.id}/render`, { method: "POST" }); toast("Rendu lancé 🎬"); pollRender(); };
  async function pollRender() {
    const c = await api(`/api/clips/${clip.id}`);
    const ob = $("#outbar"); if (!ob) return;
    if (["rendering", "queued"].includes(c.render_status)) { ob.innerHTML = `<span class="pill pending">⏳ rendu en cours…</span>`; setTimeout(pollRender, 2500); return; }
    ob.innerHTML = c.render_status === "done" && c.path
      ? `<a class="btn sm" target="_blank" href="/media/${c.id}/final?v=${Date.now()}">👁 Voir le rendu</a><a class="btn sm" href="/media/${c.id}/final?dl=1">⬇️ Télécharger MP4</a>`
      : c.render_status === "error" ? `<span class="pill error" title="${esc(c.error)}">⚠️ échec du rendu</span>` : "";
  }
  pollRender();
}

/* ===================================================================== boot */
refreshIntegrations(); setInterval(refreshIntegrations, 15000);
route();
