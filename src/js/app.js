import { loadConfig, getConfig } from "./config.js";
import { snapshot } from "../../data/snapshot.js";
import { resolveSheet, parseCSV, containerOf, containerRange, categorize, slugName, BOX_FULL, BOX_FULL_SLUG } from "./resolve.js";

const SERVED = typeof location !== "undefined" && (location.protocol === "http:" || location.protocol === "https:");

let SEED = snapshot;
let SHEET = null;
let IDENTIFY_URL = null;

// `let`, not `const`: the baked-in data is only the instant first paint — the
// live truth is the Google Sheet, fetched right after boot and after every save.


/* ----------------------------------------------------------- sheet backend
   The Google Sheet IS the database and a Google Form is the write API, so the
   PC server is no longer required for counts — only for photo identification.
   Reads: CSV export of the BOX tab + the form-responses tab (no auth; the
   sheet is link-view). Writes: a form POST (no auth; the form is link-respond).
   Appends resolve newest-wins, so a correction is just another row — which is
   also why single-user "collisions" are a non-issue: Google serializes form
   submits, and the later row simply wins. */


/* Category rules ported from build.py — keep the two lists in step when a rule
   changes (same order, first match wins). */






/** dd/mm/yyyy [hh:mm:ss] -> sortable ISO-ish string, or null. */


/** The resolver, ported from build.py: newest row wins per (box, item).
    Form rows carry a real time of day, main-tab rows only a date — so a form
    write on the same day as a hand edit deliberately wins. Form rows are also
    deliberate recounts by definition, so they never raise the ambiguity flag. */


function serverBase(){
  if(location.protocol === "http:" || location.protocol === "https:") return "";
  try{
    return window.BOXINV_SERVER || localStorage.getItem("boxinv.server")
        || "http://192.168.1.140:8781";
  }catch(e){ return "http://192.168.1.140:8781"; }
}

function sheetCsvUrl(gid){
  return `https://docs.google.com/spreadsheets/d/${SHEET.id}/export?format=csv&gid=${gid}&t=${Date.now()}`;
}

/** Fetch one tab as CSV text, straight from Google. Measured 2026-08-16: the
    CSV export answers a cross-origin fetch with status 200 from an http origin,
    so no proxy is needed anywhere. The server's /proxy stays as a fallback in
    served mode in case Google ever tightens that. */
async function fetchTab(gid){
  const get = url => new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("GET", url, true);
    x.timeout = 20000;
    x.onload = () => (x.status >= 200 && x.status < 300)
        ? resolve(x.responseText) : reject(new Error("HTTP " + x.status));
    x.onerror = () => reject(new Error("network"));
    x.ontimeout = () => reject(new Error("timeout"));
    x.send();
  });
  try{ return await get(sheetCsvUrl(gid)); }
  catch(e){
    if(SERVED) return get(`/proxy?gid=${gid}&t=${Date.now()}`);
    throw e;
  }
}

/** Append one row by submitting the hidden form. A form submission is a
    navigation, not an XHR, so CORS never applies — it works identically from
    the server page, the APK asset, and a desktop browser. The iframe's load
    event says "submitted"; the proof is the refetch afterwards. */
function sheetAppend({box, name, qty, note}){
  return new Promise(resolve => {
    let frame = document.getElementById("formsink");
    if(!frame){
      frame = document.createElement("iframe");
      frame.id = "formsink"; frame.name = "formsink"; frame.style.display = "none";
      document.body.appendChild(frame);
    }
    const f = document.createElement("form");
    f.action = SHEET.formAction; f.method = "POST"; f.target = "formsink";
    f.style.display = "none";
    const fields = {[SHEET.entries.box]: String(box),
                    [SHEET.entries.name]: name,
                    [SHEET.entries.qty]: String(qty),
                    [SHEET.entries.note]: note || ""};
    for(const [k, v] of Object.entries(fields)){
      const i = document.createElement("input");
      i.type = "hidden"; i.name = k; i.value = v;
      f.appendChild(i);
    }
    document.body.appendChild(f);
    let settled = false;
    const done = () => { if(!settled){ settled = true; f.remove(); resolve(); } };
    frame.addEventListener("load", done, {once: true});
    setTimeout(done, 5000);       // some browsers never fire load for iframes
    f.submit();
  });
}

async function refreshSeed(){
  try{
    const [boxCsv, formCsv] = await Promise.all(
      [fetchTab(SHEET.boxGid), fetchTab(SHEET.formGid).catch(() => "")]);
    const fresh = resolveSheet(boxCsv, formCsv, SEED.meta);
    if(fresh.items.length){ SEED = fresh; rebuild(); render(); return true; }
  }catch(e){ /* sheet unreachable — try local/static copy */ }
  try{
    const fresh = await (await fetch("./data/inventory.json", {cache:"no-store"})).json();
    if(fresh && Array.isArray(fresh.items)){ SEED = fresh; rebuild(); render(); return true; }
  }catch(e){ /* offline — keep the snapshot on screen */ }
  return false;
}

async function appendRow({name, box, qty, note, prev}){
  const qtyOut = (qty === "many" || qty === null) ? "many" : String(qty);
  const before = SEED.meta.rawRows || 0;
  await sheetAppend({box, name, qty: qtyOut, note: note || ""});
  for(const delay of [1200, 2500, 5000]){
    await new Promise(r => setTimeout(r, delay));
    if(await refreshSeed() && (SEED.meta.rawRows || 0) > before){
      if(prev !== undefined) showUndo(`${name}: ${prev ?? "new"} → ${qtyOut}`,
                                      {name, box, qty: prev});
      return true;
    }
  }
  toast("Could not confirm the save — check the connection");
  return false;
}



const STORE_KEY = "boxinv.v1";
const CAT = SEED.meta.categoryLabels;

const STALE_DAYS = 150;
// At or below this, a part is worth reordering before a build stalls on it.
const LOW_STOCK = 2;

/** Low means "you had more and now you don't", not "you own one of these".
    Owning a single GPS module is not a shortage; going from five TMC2209s to
    one is. Without the peak this flagged 128 of 242 parts and meant nothing. */
function isRunningLow(i){
  if(i.countType !== "exact") return false;
  const now = Number(i.qty);
  if(!(now > 0 && now <= LOW_STOCK)) return false;
  return Number(i.peak || now) >= LOW_STOCK + 1;
}

/* ------------------------------------------------------------------ state */
let overlay = load();
let items = [];            // live merged list
let ui = { tab:"find", q:"", cats:new Set(), zone:"all", flag:null, open:null, box:null,
           bom:"", level:2, cap:6, openCard:null };

function load(){
  try{
    const raw = localStorage.getItem(STORE_KEY);
    if(raw) return Object.assign({edits:{},added:[],journal:[]}, JSON.parse(raw));
  }catch(e){ console.warn("overlay unreadable, starting clean", e); }
  return {edits:{},added:[],journal:[]};
}
function save(){
  try{ localStorage.setItem(STORE_KEY, JSON.stringify(overlay)); }
  catch(e){ toast("Could not save locally"); }
}
/* Boxes 1..399 and 400+ are two physically separate sets of containers,
   so each set is numbered from its own start. */


function rebuild(){
  const out = [];
  for(const it of SEED.items){
    const e = overlay.edits[it.id];
    if(e && e.deleted) continue;
    out.push(e ? Object.assign({}, it, e, {edited:true}) : it);
  }
  for(const it of overlay.added){
    if(!(overlay.edits[it.id] && overlay.edits[it.id].deleted))
      out.push(Object.assign({}, it, overlay.edits[it.id]||{}, {added:true}));
  }
  for(const it of out){
    it.container = containerOf(it.box, SEED?.meta?.containerSize || 30);
    it.status = (it.countType === "exact" && Number(it.qty) === 0) ? "gone" : "active";
    const text = it.name + " " + (it.note||"") + " " + (CAT[it.category]||it.category);
    it._hay = (text + " " + glueNumbers(text) + " box " + it.box).toLowerCase();
    it._tokName = itemTokens(it.name);
    it._tokAll  = itemTokens(text);
  }
  out.sort((a,b)=> a.box - b.box || a.name.localeCompare(b.name));
  items = out;
}
/** Boxes marked physically full that still hold something. */
function fullBoxes(){
  const occupied = new Set(active().map(i => i.box));
  return new Set((SEED.fullBoxes || []).filter(b => occupied.has(b)));
}
const isFull = b => fullBoxes().has(Number(b));

/** Mark a box full / not full — one append to the sheet, undoable. */
async function setBoxFull(box, full){
  box = Number(box);
  if(!box || isFull(box) === full) return true;
  toast(full ? `Marking box ${box} full…` : `Marking box ${box} as having room…`);
  const ok = await appendRow({name: BOX_FULL, box, qty: full ? 1 : 0,
    note: full ? "box is physically full" : "box has room again", prev: full ? 0 : 1});
  if(ok) toast(full ? `Box ${box} is full — nothing more goes in` : `Box ${box} has room again`);
  return ok;
}
function fullToggleHTML(box, id){
  return `<label class="fullrow"><input type="checkbox" id="${id}"${isFull(box) ? " checked" : ""}>
    <span>Box <span data-fullbox>${esc(box)}</span> is physically full — nothing more fits</span></label>`;
}

function journal(entry){
  overlay.journal.push(Object.assign({at:new Date().toISOString()}, entry));
  if(overlay.journal.length > 800) overlay.journal.splice(0, overlay.journal.length - 800);
}
function edit(id, patch, label){
  overlay.edits[id] = Object.assign({}, overlay.edits[id], patch);
  journal({id, patch, label});
  save(); rebuild(); render();
}

/* ------------------------------------------------------------------ utils */
const esc = s => String(s==null?"":s).replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const active = () => items.filter(i => i.status === "active");
function daysAgo(iso){
  if(!iso) return null;
  return Math.round((Date.now() - new Date(iso+"T12:00:00").getTime()) / 864e5);
}
function toast(msg){
  const t = document.getElementById("toast");
  t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(()=>t.classList.remove("show"), 1900);
}
let undoTimer = null;
function showUndo(what, revert){
  document.getElementById("undobar")?.remove();
  const bar = document.createElement("div");
  bar.id = "undobar";
  bar.innerHTML = `<b>${esc(what)}</b><button>Undo</button>`;
  bar.querySelector("button").onclick = async () => {
    bar.querySelector("button").disabled = true;
    toast("Undoing…");
    try{
      if(revert){
        await appendRow({name: revert.name, box: revert.box, qty: revert.qty, note: "(undo)"});
        toast("Undone");
      }
    }catch(err){ toast("Undo failed: " + err.message); }
    bar.remove();
  };
  document.body.appendChild(bar);
  clearTimeout(undoTimer);
  undoTimer = setTimeout(() => bar.remove(), 9000);
}
function qtyHTML(it){
  if(it.countType === "bulk")    return `<div class="qty bulk">many<small>bulk</small></div>`;
  if(it.countType === "unknown") return `<div class="qty unknown">?<small>uncounted</small></div>`;
  const n = Number(it.qty)||0;
  return `<div class="qty${n===0?" zero":""}">${n}<small>${n===1?"pc":"pcs"}</small></div>`;
}
/* "3 pin", "3-pin", "3pin" and "(3-pin" are the same thing to a person, so a
   bare number is glued to the word after it — in the query and in each part's
   text alike. Only a PURE number glues: "m3 x 10" and "ESP32-C3" stay as-is. */
function glueNumbers(s){
  return String(s).toLowerCase()
    .replace(/(^|[^a-z0-9.])(\d+(?:\.\d+)?)[\s_-]+(?=[a-z])/g, "$1$2");
}
/* Split on everything except digits, letters, "." and "+" so that "m3.5" and
   "5v+" survive whole but "timing-belt" becomes two matchable words. One-letter
   words are noise, but a lone digit is not: dropping it turned "3-pin" into
   "pin" and listed every 2-, 4- and 6-pin part instead. */
function tokens(s){
  return glueNumbers(s).split(/[^a-z0-9.+]+/).filter(t => t.length > 1 || /\d/.test(t));
}
/* A part's words in both spellings, so "pin" on its own still finds "3-pin". */
function itemTokens(s){
  const plain = String(s).toLowerCase().split(/[^a-z0-9.+]+/).filter(t => t.length > 1);
  return [...new Set([...plain, ...tokens(s)])];
}
/* A needle word matches an item word only on a whole-word or prefix basis.
   Substring matching is wrong here: it made "TOF" match "cu-tof-fs". */
function wordHit(needle, list){
  for(const w of list){
    if(w === needle) return 1;
    if(needle.length >= 3 && w.startsWith(needle)) return 0.9;
    if(w.length >= 3 && needle.startsWith(w)) return 0.8;
  }
  return 0;
}
/* 0..1.25 — name matches outrank matches that only hit the note. */
function matchScore(needle, it){
  const words = tokens(needle);
  if(!words.length) return 0;
  let name = 0, all = 0;
  for(const w of words){ name += wordHit(w, it._tokName); all += wordHit(w, it._tokAll); }
  return (name / words.length) + 0.25 * (all / words.length);
}

/* The two box ranges actually in use, derived from the data (not hard-coded),
   so adding box 129 or 439 keeps the Boxes view and free-slot list correct. */
function boxRanges(){
  const elec = items.filter(i => i.box < 400).map(i => i.box);
  const house = items.filter(i => i.box >= 400).map(i => i.box);
  const out = [];
  if(elec.length)  out.push([1,   Math.max(...elec),  "Electronics"]);
  if(house.length) out.push([401, Math.max(...house), "Household"]);
  return out;
}

/* ------------------------------------------------------------------ issues */
function issues(){
  const list = active();
  const conflicts = items.filter(i => i.conflict && !i.edited);
  const bulk = list.filter(i => i.countType === "bulk" || i.countType === "unknown");
  const stale = list.filter(i => (daysAgo(i.updated)||0) > STALE_DAYS);
  const byName = new Map();
  for(const i of list){
    const k = i.name.toLowerCase().trim();
    if(!byName.has(k)) byName.set(k, []);
    byName.get(k).push(i.box);
  }
  const splits = [...byName.entries()]
    .filter(([,b]) => new Set(b).size > 1)
    .map(([n,b]) => ({name:n, boxes:[...new Set(b)].sort((x,y)=>x-y)}))
    .sort((a,b)=>a.name.localeCompare(b.name));
  const used = new Set(list.map(i => i.box));
  const known = new Set(items.map(i => i.box));
  const free = [];
  for(const [lo,hi] of boxRanges())
    for(let b=lo; b<=hi; b++)
      if(!used.has(b)) free.push({box:b, reason: known.has(b) ? "emptied" : "never used"});
  return {conflicts, bulk, stale, splits, free,
          total: conflicts.length + splits.length + free.length};
}

/* --------------------------------------------------------------- Reorganize
   Three effort levels. Each returns concrete part-moves you can apply.
   Bulk piles are never merged into a shared box — a pile of 99 screws fills
   its own box physically, whatever the data says. */
function planMoves(level, cap){
  const list = active().map(i => ({it:i, box:i.box}));
  const moves = [];
  const full = fullBoxes();
  const blocked = [];
  // A part in a full box fills it like a bulk pile does: it stays put when
  // consolidating, and a full box never receives anything.
  const mergeable = r => r.it.countType === "exact" && !full.has(r.it.box);
  const move = (r, to, why) => { if(r.box !== to){ moves.push({id:r.it.id, name:r.it.name,
      from:r.box, to, why}); r.box = to; } };
  const load = () => {                       // current box -> rows, using planned boxes
    const m = new Map();
    for(const r of list){ if(!m.has(r.box)) m.set(r.box, []); m.get(r.box).push(r); }
    return m;
  };

  // level 1 — the same part sitting in two boxes
  const byName = new Map();
  for(const r of list){
    const k = r.it.name.toLowerCase().trim();
    if(!byName.has(k)) byName.set(k, []);
    byName.get(k).push(r);
  }
  for(const [,rows] of byName){
    if(new Set(rows.map(r => r.box)).size < 2) continue;
    // keep it where the larger amount already is; ties go to the lower box
    // number — but only a box with room can take the rest
    const open = rows.filter(r => !full.has(r.box));
    if(!open.length){ blocked.push({name: rows[0].it.name, boxes: [...new Set(rows.map(r => r.box))]}); continue; }
    const home = open.slice().sort((a,b) =>
      (Number(b.it.qty)||0) - (Number(a.it.qty)||0) || a.box - b.box)[0].box;
    for(const r of rows) move(r, home, "same part was in two boxes");
  }

  // level 2 — merge one-item boxes of the same category inside one container.
  // Repeat until stable: each pass empties boxes, which can leave new singles.
  const consolidate = () => {
    for(let pass = 0; pass < 8; pass++){
      const before = moves.length;
      const byCC = new Map();
      for(const r of list){
        const k = containerOf(r.box, SEED?.meta?.containerSize || 30) + "|" + r.it.category;
        if(!byCC.has(k)) byCC.set(k, []);
        byCC.get(k).push(r);
      }
      const l = load();                       // recomputed per pass
      for(const [,rows] of byCC){
        const singles = rows.filter(r => mergeable(r) && (l.get(r.box)||[]).length === 1);
        if(singles.length < 2) continue;
        const home = Math.min(...singles.map(r => r.box));
        let n = (l.get(home)||[]).length;
        for(const r of singles.sort((a,b)=>a.box-b.box)){
          if(r.box === home || n >= cap) continue;
          move(r, home, "one-item boxes of the same type, same container"); n++;
        }
      }
      if(moves.length === before) break;
    }
  };
  if(level >= 2) consolidate();

  // level 3 — give each category one home container and pack it there
  if(level >= 3){
    const cats = new Map();
    for(const r of list){
      if(!cats.has(r.it.category)) cats.set(r.it.category, []);
      cats.get(r.it.category).push(r);
    }
    for(const [cat, rows] of cats){
      const elec = rows.filter(r => r.box < 400);
      if(elec.length < 3) continue;                 // not worth moving crates for
      const tally = {};
      for(const r of elec) tally[containerOf(r.box, SEED?.meta?.containerSize || 30)] = (tally[containerOf(r.box, SEED?.meta?.containerSize || 30)]||0) + 1;
      const home = Object.entries(tally).sort((a,b)=>b[1]-a[1])[0][0];
      const inHome = elec.filter(r => containerOf(r.box, SEED?.meta?.containerSize || 30) === home).map(r => r.box);
      if(!inHome.length) continue;
      const targets = [...new Set(inHome)].filter(b => !full.has(b)).sort((a,b)=>a-b);
      const l = load();
      let ti = 0;
      for(const r of elec.sort((a,b)=>a.box-b.box)){
        if(containerOf(r.box, SEED?.meta?.containerSize || 30) === home) continue;
        if(!mergeable(r)) continue;                 // piles stay where they are
        while(ti < targets.length &&
              (l.get(targets[ti])||[]).length + moves.filter(m=>m.to===targets[ti]).length >= cap) ti++;
        if(ti >= targets.length) break;
        move(r, targets[ti], `${esc(CAT[cat]||cat)} belongs in container ${home}`);
      }
    }
    consolidate();   // regrouping leaves new one-item boxes behind; sweep them up
  }

  const boxesBefore = new Set(active().map(i => i.box));
  const boxesAfter  = new Set(list.map(r => r.box));
  const spread = rows => {
    const m = {};
    for(const r of rows){
      const c = r.it.category;
      (m[c] = m[c] || new Set()).add(containerOf(r.box, SEED?.meta?.containerSize || 30));
    }
    return Object.values(m).reduce((a,s)=>a+s.size, 0) / Math.max(1, Object.keys(m).length);
  };
  return {
    moves,
    freed: [...boxesBefore].filter(b => !boxesAfter.has(b)).sort((a,b)=>a-b),
    spreadBefore: spread(active().map(i => ({it:i, box:i.box}))),
    spreadAfter: spread(list),
    pinned: list.filter(r => r.it.countType !== "exact").length,
    fullKept: full.size,
    blocked
  };
}

/* ------------------------------------------------------------------ views */
function render(){
  document.getElementById("stat-line").textContent =
    `${active().length} parts · ${new Set(active().map(i=>i.box)).size} boxes`;
  renderTabs();
  const v = document.getElementById("view");
  v.innerHTML = ({find:viewFind, boxes:viewBoxes, issues:viewIssues, build:viewBuild,
                  reorg:viewReorg, labels:viewLabels, data:viewData})[ui.tab]();
  wire();
}
function renderTabs(){
  // The badge counts jobs worth doing now, not every finding. It used to show
  // 22 — a number that only made the tab look like a chore.
  const n = todoCards().filter(c => c.tone === "now").length;
  const tabs = [["find","Find"],["boxes","Boxes"],["issues","To do"],["build","Build check"],
                ["reorg","Reorganize"],["labels","Labels"],["data","Data"]];
  document.getElementById("tabs").innerHTML = tabs.map(([k,label]) =>
    `<button role="tab" data-tab="${k}" aria-selected="${ui.tab===k}">${esc(label)}${
      k==="issues" && n ? `<span class="badge">${n}</span>` : ""}</button>`).join("");
}

function filtered(){
  let list = items.filter(i => i.status === "active" || ui.flag === "gone");
  if(ui.zone === "elec")  list = list.filter(i => i.box < 400);
  if(ui.zone === "house") list = list.filter(i => i.box >= 400);
  if(ui.cats.size)        list = list.filter(i => ui.cats.has(i.category));
  if(ui.box != null)      list = list.filter(i => i.box === ui.box);
  if(ui.flag === "gone")  list = list.filter(i => i.status === "gone");
  if(ui.flag === "bulk")  list = list.filter(i => i.countType !== "exact");
  if(ui.flag === "conflict") list = list.filter(i => i.conflict);
  if(ui.flag === "stale") list = list.filter(i => (daysAgo(i.updated)||0) > STALE_DAYS);
  if(ui.flag === "low") list = list.filter(i =>
    isRunningLow(i));
  const q = ui.q.trim().toLowerCase();
  // Typing a bare box number (or "box 12") jumps to that box instead of
  // searching for the digits — with 154 boxes that is what you nearly always
  // mean. A bare "3" can also be the start of "3-pin", so parts named like that
  // follow the box's own contents; "box 3" means the box and nothing else.
  const boxQ = q.match(/^(box\s*)?(\d{1,3})$/);
  if(boxQ && items.some(i => i.box === Number(boxQ[2]))){
    const n = Number(boxQ[2]);
    const inBox = list.filter(i => i.box === n);
    if(boxQ[1]) return inBox;
    const named = list.filter(i => i.box !== n && i._tokName.some(w =>
      w.startsWith(boxQ[2]) && /^[a-z]/.test(w.slice(boxQ[2].length))));
    return [...inBox, ...named];
  }
  if(q){
    const ts = tokens(q);
    list = list.filter(i => ts.every(t => i._hay.includes(t)))
               .map(i => [i, matchScore(q, i) + (i.name.toLowerCase().startsWith(q) ? .5 : 0)])
               .sort((a,b) => b[1]-a[1] || a[0].box-b[0].box)
               .map(p => p[0]);
  }
  return list;
}

function viewFind(){
  const counts = {};
  for(const i of active()) counts[i.category] = (counts[i.category]||0) + 1;
  const cats = Object.keys(CAT).filter(c => counts[c])
    .sort((a,b) => counts[b]-counts[a]);
  const rng = Object.fromEntries(boxRanges().map(([lo,hi,n]) => [n, `${lo}–${hi}`]));
  const zoneLabel = {all:"All", elec:`Electronics (${rng.Electronics||"—"})`,
                     house:`Household (${rng.Household||"—"})`};
  const chips =
    `<div class="chips">
      ${["all","elec","house"].map(z =>
        `<button class="chip" data-zone="${z}" aria-pressed="${ui.zone===z}">${zoneLabel[z]}</button>`).join("")}
      <span style="width:10px"></span>
      ${[["low","Running low"],["bulk","Uncounted"],["conflict","Ambiguous"],
         ["stale","Stale"],["gone","Removed"]].map(([k,l]) =>
        `<button class="chip" data-flag="${k}" aria-pressed="${ui.flag===k}">${l}</button>`).join("")}
    </div>
    <div class="chips">
      ${cats.map(c => `<button class="chip" data-cat="${c}" aria-pressed="${ui.cats.has(c)}">${
        esc(CAT[c])}<span class="n">${counts[c]}</span></button>`).join("")}
    </div>`;
  const list = filtered();
  const boxNote = ui.box != null
    ? `<div class="hint">Showing box ${ui.box} only${isFull(ui.box) ? ` · <span class="tag err">full</span>` : ""}
       · <button class="iconbtn" data-clearbox="1">show all</button>
       ${active().some(i => i.box === ui.box)
         ? `· <button class="iconbtn" data-setfull="${ui.box}" data-v="${isFull(ui.box) ? 0 : 1}">${
             isFull(ui.box) ? "it has room again" : "mark box full"}</button>` : ""}</div>` : "";
  if(!list.length)
    return chips + boxNote + `<div class="empty">Nothing matches.<br><br>
      <button class="btn" data-add="1">+ Add a part</button></div>`;
  return chips + boxNote +
    `<div class="hint">${list.length} result${list.length===1?"":"s"}${
       /^\d{1,3}$/.test(ui.q.trim()) && items.some(i => i.box === Number(ui.q.trim()))
         ? ` · box ${esc(ui.q.trim())} first, then parts like “${esc(ui.q.trim())}-pin”` : ""}
       · <button class="iconbtn" data-add="1">+ add part</button></div>
     <div class="list">${list.map(itemHTML).join("")}</div>`;
}

function itemHTML(it){
  const flags = [];
  if(it.conflict) flags.push(`<span class="tag err" title="The sheet recorded different quantities for this same box+item">ambiguous</span>`);
  if(it.status === "gone") flags.push(`<span class="tag err">removed</span>`);
  if(it.edited) flags.push(`<span class="tag flag">edited</span>`);
  if(it.added)  flags.push(`<span class="tag flag">new</span>`);
  if(isFull(it.box)) flags.push(`<span class="tag err" title="Box ${it.box} is marked physically full">box full</span>`);
  const d = daysAgo(it.updated);
  const open = ui.open === it.id;
  const exact = it.countType === "exact";
  const low = isRunningLow(it);
  if(low) flags.push(`<span class="tag flag">was ${it.peak}, now ${it.qty}</span>`);
  return `<div class="item${low ? " low" : ""}" data-id="${esc(it.id)}">
    <button class="row" data-toggle="${esc(it.id)}">
      <span class="boxno"><b>${it.box}</b><span>box</span></span>
      <span class="itemmain">
        <span class="itemname">${esc(it.name)}</span>
        <span class="itemmeta">
          <span class="tag">${esc(CAT[it.category]||it.category)}</span>
          <span class="tag">cont. ${it.container}</span>
          ${d!=null?`<span class="tag"${d>STALE_DAYS?' style="opacity:.85"':''}>${d}d ago</span>`:""}
          ${flags.join("")}
        </span>
        ${it.note?`<span class="note">${esc(it.note)}</span>`:""}
      </span>
      ${qtyHTML(it)}
    </button>
    ${SERVED && exact ? `<span class="tally">
        <button data-tally="1" data-t-id="${esc(it.id)}" title="Put one back">+</button>
        <button data-tally="-1" data-t-id="${esc(it.id)}" title="Take one out"
          ${Number(it.qty) <= 0 ? "disabled" : ""}>−</button>
      </span>` : ""}
    ${open ? editorHTML(it) : ""}
  </div>`;
}

function editorHTML(it){
  const optCats = Object.keys(CAT).map(c =>
    `<option value="${c}"${c===it.category?" selected":""}>${esc(CAT[c])}</option>`).join("");
  const optCount = [["exact","exact count"],["bulk","bulk / many"],["unknown","uncounted"]]
    .map(([v,l]) => `<option value="${v}"${v===it.countType?" selected":""}>${l}</option>`).join("");
  const hist = (it.history&&it.history.length)
    ? `<div class="hist"><b>sheet history</b>${it.history.map(h =>
        `<div>${h.date||"?"} · qty ${h.qty===""?"—":h.qty}${h.note?" · "+esc(h.note):""}</div>`).join("")}</div>`
    : "";
  return `<div class="editor">
    <div class="eline">
      <label>Qty</label>
      <button class="step" data-step="-1">−</button>
      <input type="number" data-f="qty" value="${it.countType==="exact"?(Number(it.qty)||0):""}"
             ${it.countType!=="exact"?"disabled placeholder=\"—\"":""}>
      <button class="step" data-step="1">+</button>
      <select data-f="countType">${optCount}</select>
    </div>
    <div class="eline"><label>Box</label>
      <input type="number" data-f="box" value="${it.box}" min="1">
      <label>Type</label><select data-f="category" class="grow">${optCats}</select>
    </div>
    <div class="eline"><label>Name</label>
      <input type="text" data-f="name" class="grow" value="${esc(it.name)}"></div>
    <div class="eline"><label>Note</label>
      <input type="text" data-f="note" class="grow" value="${esc(it.note||"")}"
             placeholder="spec, where it came from, what it fits…"></div>
    ${fullToggleHTML(it.box, "efull")}
    <div class="ebtns">
      <button class="btn" data-savechanges="1">Save</button>
      <button class="btn ghost" data-onlybox="${it.box}">Show box ${it.box}</button>
      <button class="btn danger" data-del="1">Delete</button>
    </div>
    ${hist}
  </div>`;
}

function viewBoxes(){
  const byBox = new Map();
  for(const i of active()){
    if(!byBox.has(i.box)) byBox.set(i.box, []);
    byBox.get(i.box).push(i);
  }
  const q = ui.q.trim().toLowerCase();
  const hitBoxes = new Set(q ? filtered().map(i => i.box) : []);
  const fullSet = fullBoxes();
  let html = `<div class="hint">Tap a box to list its contents. Dashed green = free slot you can reuse.
    Red = marked physically full; nothing gets moved or suggested into it.</div>`;
  for(const [lo,hi,name] of boxRanges()){
    let last = null;
    for(let b=lo; b<=hi; b++){
      const c = containerOf(b, SEED?.meta?.containerSize || 30);
      if(c !== last){
        if(last!==null) html += `</div>`;
        const [rlo,rhi] = containerRange(b, SEED?.meta?.containerSize || 30);
        html += `<div class="container-h">${name} · container ${c} (boxes ${rlo}–${rhi})</div><div class="boxgrid">`;
        last = c;
      }
      const contents = byBox.get(b);
      const free = !contents, full = !free && fullSet.has(b);
      html += `<button class="boxcell${free?" free":""}${full?" full":""}${hitBoxes.has(b)?" hit":""}" data-box="${b}">
        <b>${b}</b><span>${free?"free":(full?"full · ":"")+contents.length+(contents.length===1?" item":" items")}</span></button>`;
    }
    html += `</div>`;
  }
  return html;
}

/* Ranked jobs rather than a flat dump of every finding. Order is impact first:
   data that is wrong, then time wasted at the bench, then opportunities, then
   hygiene. Each card names one action and shows only a handful of targets. */
function todoCards(){
  const s = issues();
  const cards = [];
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  if(s.conflicts.length) cards.push({
    tone:"now", when:"Do first",
    title:`Count ${plural(s.conflicts.length, "part", "parts")} the sheet contradicts itself on`,
    why:"These were written down twice with different numbers, so the count you see is the newest guess, not a fact. One count each settles it permanently.",
    effort:`~${s.conflicts.length} min`,
    targets: s.conflicts.map(i => ({box:i.box, label:`${esc(i.name)} — showing ${
      i.countType === "exact" ? i.qty : "many"}`})),
  });

  // A merge needs somewhere to go: at least one of the boxes must have room.
  const full = fullBoxes();
  const fullTag = b => full.has(b) ? `${b} (full)` : `${b}`;
  const canMerge = s.splits.filter(x => x.boxes.some(b => !full.has(b)));
  const stuck = s.splits.filter(x => x.boxes.every(b => full.has(b)));
  if(canMerge.length) cards.push({
    tone:"now", when:"Do first",
    title:`Merge ${plural(canMerge.length, "part", "parts")} living in two boxes`,
    why:"Every time you look one of these up you can open the wrong box. The Reorganize tab does all of them in one pass — always into a box that is not marked full.",
    effort:`${canMerge.length} moves`,
    targets: canMerge.map(x => ({box:x.boxes.find(b => !full.has(b)),
      label:`${esc(x.name)} — boxes ${x.boxes.map(fullTag).join(" and ")}`})),
    go:{tab:"reorg", level:1, label:"Plan the merge"},
  });
  if(stuck.length) cards.push({
    tone:"later", when:"When a box frees up",
    title:`${plural(stuck.length, "part is", "parts are")} split, but every box ${stuck.length === 1 ? "it is" : "they are"} in is full`,
    why:"There is no room to merge these. Leave them, or give the part one new free box and move both halves there. Tick “has room” on a box once you have made space.",
    effort:"only if it bothers you",
    targets: stuck.map(x => ({box:x.boxes[0],
      label:`${esc(x.name)} — boxes ${x.boxes.join(" and ")}, all full`})),
  });

  // Down to the last one or two — the thing you find out at the worst moment.
  const low = active()
    .filter(i => i.countType === "exact" && Number(i.qty) > 0 && Number(i.qty) <= LOW_STOCK)
    .sort((a,b) => a.qty - b.qty || a.box - b.box);
  if(low.length) cards.push({
    tone:"soon", when:"Before your next order",
    title:`${plural(low.length, "part is", "parts are")} nearly used up`,
    why:"You had more of these and now you do not — the count has actually come down. Parts you simply own one of are not listed here. Worth a glance before you next order anything.",
    effort:"reading, not work",
    targets: low.map(i => ({box:i.box, label:`${esc(i.name)} — was ${i.peak}, ${i.qty} left`})),
  });

  const gone = active().filter(i => i.countType === "exact" && Number(i.qty) === 0);
  if(gone.length) cards.push({
    tone:"soon", when:"Worth knowing",
    title:`${plural(gone.length, "part is", "parts are")} at zero but still listed`,
    why:"The box is empty. Either the part is genuinely used up — in which case the box number is free — or the count is wrong.",
    effort:"a look each",
    targets: gone.map(i => ({box:i.box, label:`${esc(i.name)} — box ${i.box} is empty`})),
  });

  const risky = s.bulk.filter(i => ["mcu","sensor","driver","power","motor","interface","comms"]
    .includes(i.category));
  if(risky.length) cards.push({
    tone:"soon", when:"Worth doing",
    title:`Put a real number on ${plural(risky.length, "pile", "piles")} you could run out of`,
    why:"“Many” is fine for screws — it is not fine for parts a build depends on, because Build check cannot warn you that four are left. These are the electronics ones.",
    effort:"a few minutes each",
    targets: risky.map(i => ({box:i.box, label:esc(i.name)})),
  });

  if(s.free.length) cards.push({
    tone:"later", when:"When you feel like it",
    title:`Reuse ${plural(s.free.length, "free box number", "free box numbers")}`,
    why:"Empty or never used. Fill these before buying more boxes — and the Reorganize tab can free a lot more.",
    effort:"no work, just useful",
    targets: s.free.slice(0, 6).map(f => ({box:f.box, label:`box ${f.box} — ${f.reason}`})),
    extra: s.free.length - 6,
    go:{tab:"reorg", level:2, label:"See what else frees up"},
  });

  const bulkRest = s.bulk.length - risky.length;
  if(bulkRest > 0 || s.stale.length) cards.push({
    tone:"later", when:"No hurry",
    title:"Spot-check the rest when a container is open anyway",
    why:`${bulkRest} more uncounted piles (screws, scrap, consumables) and ${s.stale.length} parts not touched in over ${STALE_DAYS} days. Nothing here is wrong — it is just old. Do not make a job of it.`,
    effort:"opportunistic",
    targets: s.stale.slice(0, 4).map(i => ({box:i.box, label:`box ${i.box} · ${esc(i.name)}`})),
    extra: Math.max(0, s.stale.length - 4),
  });

  return cards;
}

function viewIssues(){
  const cards = todoCards();
  if(!cards.length)
    return `<div class="empty">Nothing needs attention.<br>Every count is unambiguous and no part is in two places.</div>`;

  const urgent = cards.filter(c => c.tone === "now").length;
  const html = cards.map((c, idx) => `
    <div class="card ${c.tone}">
      <div class="cardtop">
        <span class="when">${esc(c.when)}</span>
        <span class="effort">${esc(c.effort)}</span>
      </div>
      <h3>${esc(c.title)}</h3>
      <p class="why">${esc(c.why)}</p>
      ${c.targets.length ? `<ul class="targets">${c.targets.slice(0, ui.openCard === idx ? 99 : 3)
        .map(t => `<li><a href="#" data-box="${t.box}">${t.label}</a></li>`).join("")}</ul>` : ""}
      ${(c.targets.length > 3 || c.extra)
        ? `<button class="more" data-card="${idx}">${
            ui.openCard === idx
              ? "show less"
              : `show all ${c.targets.length + (c.extra || 0)}`}</button>`
        : ""}
      ${c.go ? `<div class="ebtns"><button class="btn" data-go='${
        JSON.stringify(c.go)}'>${esc(c.go.label)}</button></div>` : ""}
    </div>`).join("");

  return `<div class="hint">${urgent
      ? `${urgent} thing${urgent===1?"":"s"} worth doing now, ${cards.length-urgent} that can wait.`
      : `Nothing urgent — ${cards.length} thing${cards.length===1?"":"s"} for when you have time.`}
    </div>${html}
    <div class="donebar">That is the whole list — the rest of the inventory is fine.</div>`;
}

function viewBuild(){
  const lines = ui.bom.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const list = active();
  const MIN = 0.55;
  let results = "";
  if(lines.length){
    let have = 0, missing = 0;
    const boxes = new Set();
    const rows = lines.map(line => {
      const m = line.match(/^(\d+)\s*[x×*]?\s+(.*)$/i);
      const need = m ? parseInt(m[1],10) : 1;
      const term = m ? m[2] : line;
      let ranked = list.map(i => [i, matchScore(term, i)])
                         .filter(p => p[1] >= MIN)
                         // equal score: the shorter name is the more specific part
                         .sort((a,b) => b[1]-a[1] || a[0].name.length-b[0].name.length || a[0].box-b[0].box)
                         .slice(0,4);
      // Among near-equally good name matches, prefer one that actually covers
      // the quantity: a bulk pile of limit switches beats the single odd one.
      let best = ranked[0];
      if(best){
        const covers = p => p[0].countType !== "exact" || Number(p[0].qty) >= need;
        best = ranked.filter(p => p[1] >= best[1] * 0.9).find(covers) || ranked[0];
        ranked = [best, ...ranked.filter(p => p !== best)];
      }
      let pill, detail;
      if(!best){ pill = `<span class="pill no">not in any box</span>`; detail = ""; missing++; }
      else{
        const it = best[0];
        boxes.add(it.box);
        const enough = it.countType !== "exact" || Number(it.qty) >= need;
        pill = enough ? `<span class="pill ok">box ${it.box}</span>`
                      : `<span class="pill maybe">box ${it.box} · only ${it.qty}</span>`;
        if(enough) have++; else missing++;
        detail = `<div>${esc(it.name)} — ${it.countType==="exact"?it.qty+" pcs":"bulk"}
          · container ${it.container}</div>` +
          (ranked.length>1 ? `<div class="alt">also: ${ranked.slice(1).map(p =>
            `box ${p[0].box} ${esc(p[0].name)}`).join(" · ")}</div>` : "");
      }
      return `<div class="bomrow"><div class="bomq">${need}×</div>
        <div class="bomhit"><div><b>${esc(term)}</b> ${pill}</div>${detail}</div></div>`;
    }).join("");
    const boxList = [...boxes].sort((a,b)=>a-b);
    results = `<div class="panel">
      <h2>Result <span class="count">${have} found · ${missing} to sort out</span></h2>
      ${boxList.length?`<p class="sub"><b>Open these boxes:</b> ${boxList.map(b=>
        `<a href="#" data-box="${b}">${b}</a>`).join(" · ")}
        &nbsp;(container${boxList.length>1?"s":""} ${[...new Set(boxList.map(b => containerOf(b, SEED?.meta?.containerSize || 30)))].join(", ")})</p>`:""}
      ${rows}</div>`;
  }
  return `<div class="panel">
    <h2>Build check</h2>
    <p class="sub">Paste a parts list — one per line, optionally “2x ” in front.
      It tells you which boxes to open and what you are missing.</p>
    <textarea class="bom" id="bomtext" placeholder="1x ESP32-C3&#10;1x TMC2209&#10;2x limit switch&#10;1x TOF sensor&#10;4x M3 bolt&#10;1x GT2 belt">${esc(ui.bom)}</textarea>
    <div class="ebtns" style="margin-top:9px">
      <button class="btn" id="runbom">Check</button>
      <button class="btn ghost" id="clearbom">Clear</button>
    </div>
  </div>${results}`;
}

function viewReorg(){
  const cap = ui.cap, lvl = ui.level;
  const p = planMoves(lvl, cap);
  const levels = [
    [1, "Merge duplicates", "Only pull the same part out of two boxes into one."],
    [2, "Consolidate singles", "Also merge one-item boxes of the same type inside the same container."],
    [3, "Regroup by type", "Also drag each category into one home container. Most work, best result."]
  ];
  const byWhy = new Map();
  for(const m of p.moves){
    if(!byWhy.has(m.why)) byWhy.set(m.why, []);
    byWhy.get(m.why).push(m);
  }
  return `<div class="panel">
    <h2>Reorganize</h2>
    <p class="sub">Measured now: <b>${active().filter((i,_,a)=>
        a.filter(x=>x.box===i.box).length===1).length}</b> of your
      ${new Set(active().map(i=>i.box)).size} boxes hold a single item, and the average
      category is spread over <b>${p.spreadBefore.toFixed(1)}</b> containers.</p>
    <div class="chips">${levels.map(([n,t]) =>
      `<button class="chip" data-level="${n}" aria-pressed="${lvl===n}">${n}. ${t}</button>`).join("")}</div>
    <p class="sub">${levels.find(l=>l[0]===lvl)[2]}</p>
    <div class="eline"><label>Max per box</label>
      <button class="step" data-cap="-1">−</button>
      <input type="number" id="capval" value="${cap}" min="2" max="20" readonly>
      <button class="step" data-cap="1">+</button></div>
    <div class="kv">
      <b>${p.moves.length}</b><span>parts to move</span>
      <b>${p.freed.length}</b><span>boxes freed up${p.freed.length?": "+p.freed.join(", "):""}</span>
      <b>${p.spreadBefore.toFixed(1)} → ${p.spreadAfter.toFixed(1)}</b><span>containers per category (lower is better)</span>
      <b>${p.pinned}</b><span>bulk piles left alone on purpose</span>
      <b>${p.fullKept}</b><span>boxes marked full — nothing is moved into them</span>
    </div>
    ${p.moves.length ? `<div class="ebtns" style="margin-top:11px">
        <button class="btn" id="applyplan">Apply these ${p.moves.length} moves</button>
        <button class="btn ghost" id="printplan">Print worksheet</button>
      </div>` : `<p class="sub">Nothing to do at this level.</p>`}
  </div>
  ${p.blocked.length ? `<div class="panel">
      <h2>Cannot merge — every box is full <span class="count">${p.blocked.length}</span></h2>
      <p class="sub">Left where they are. Make room in one of the boxes and tick “has room”, or move both halves to a free box.</p>
      ${p.blocked.map(b => `<div class="bomrow"><div class="bomq">${b.boxes.join("+")}</div>
        <div class="bomhit">${esc(b.name)}</div></div>`).join("")}
    </div>` : ""}
  ${[...byWhy.entries()].map(([why, ms]) => `<div class="panel">
      <h2>${esc(why)} <span class="count">${ms.length}</span></h2>
      ${ms.sort((a,b)=>a.from-b.from).map(m => `<div class="bomrow">
        <div class="bomq">${m.from}→${m.to}</div>
        <div class="bomhit">${esc(m.name)}
          <span class="alt">container ${containerOf(m.from, SEED?.meta?.containerSize || 30)} → ${containerOf(m.to, SEED?.meta?.containerSize || 30)}</span></div>
      </div>`).join("")}
    </div>`).join("")}`;
}

function viewLabels(){
  const byBox = new Map();
  for(const i of active()){
    if(!byBox.has(i.box)) byBox.set(i.box, []);
    byBox.get(i.box).push(i);
  }
  const boxes = [...byBox.keys()].sort((a,b)=>a-b);
  return `<div class="panel noprint">
      <h2>Printable box labels</h2>
      <p class="sub">One label per non-empty box, in box order. Print, cut, stick.</p>
      <button class="btn" onclick="window.print()">Print</button>
    </div>
    <div class="labelsheet">${boxes.map(b => {
      const c = byBox.get(b);
      return `<div class="label"><b>${b}</b>
        <span class="c">container ${containerOf(b, SEED?.meta?.containerSize || 30)}</span>
        <ul>${c.slice(0,4).map(i => `<li>${esc(i.name.slice(0,42))}${
          i.countType==="exact"?" ("+i.qty+")":""}</li>`).join("")}
        ${c.length>4?`<li>+${c.length-4} more</li>`:""}</ul></div>`;
    }).join("")}</div>`;
}

function viewData(){
  const s = issues();
  const nEdit = Object.keys(overlay.edits).length;
  return `<div class="panel">
    <h2>Where this data came from</h2>
    <p class="sub">Built from your Google Sheet export
      (${SEED.meta.rawRows} rows, ${SEED.meta.source.split("(")[0].trim()}), generated ${SEED.meta.generated}.
      The sheet is an append log: the same box+item can appear several times.
      This app keeps the <b>newest row per box+item</b> and flags the ones where
      the number changed, instead of silently guessing.</p>
    <div class="kv">
      <b>${SEED.meta.rawRows}</b><span>rows in the sheet</span>
      <b>${SEED.items.length}</b><span>merged records</span>
      <b>${active().length}</b><span>parts you actually have</span>
      <b>${items.length - active().length}</b><span>removed / zero-qty (hidden by default)</span>
      <b>${s.bulk.length}</b><span>uncounted piles (the old “99”)</span>
      <b>${s.conflicts.length}</b><span>ambiguous quantities</span>
      <b>${s.splits.length}</b><span>parts split across boxes</span>
      <b>${s.free.length}</b><span>free box numbers</span>
      <b>${fullBoxes().size}</b><span>boxes marked physically full</span>
      <b>${nEdit}</b><span>local edits not yet exported</span>
    </div>
  </div>
  <div class="panel">
    <h2>Export</h2>
    <p class="sub">CSV comes back in the exact same columns as the sheet, so you can paste
      it straight over the Google Sheet — but with one row per part and the real numbers.</p>
    <div class="ebtns">
      <button class="btn" id="exp-csv">Export CSV</button>
      <button class="btn ghost" id="exp-json">Export JSON backup</button>
      <button class="btn ghost" id="exp-log">Export change log (${overlay.journal.length})</button>
    </div>
  </div>
  <div class="panel">
    <h2>Re-sync from the sheet</h2>
    <p class="sub">Downloaded a fresh CSV from Google Sheets? Drop it here — it replaces the
      base data. Your local edits stay on top of it.</p>
    <input type="file" id="imp" accept=".csv,text/csv">
  </div>
  <div class="panel">
    <h2>Reset</h2>
    <p class="sub">Throws away all ${nEdit} local edits and returns to the sheet snapshot.</p>
    <button class="btn danger" id="reset">Discard local edits</button>
  </div>`;
}

/* ------------------------------------------------------------------ export */
function toCSV(){
  const head = ["Box","Item","Qty","Note","UpdatedAt"];
  // Text starting with = + - @ tab or CR is run as a formula when the file is
  // opened in Excel/Sheets (CSV injection). A leading ' makes it plain text and
  // is not shown. Numbers stay numbers, so a real count is never altered.
  const safe = v => typeof v === "string" && /^[=+\-@\t\r]/.test(v) ? "'" + v : String(v);
  const q = v => { const s = safe(v); return /[",\r\n]/.test(s) ? '"'+s.replace(/"/g,'""')+'"' : s; };
  const d = new Date(), pad = n => String(n).padStart(2,"0");
  const today = `${pad(d.getDate())}/${pad(d.getMonth()+1)}/${d.getFullYear()}`;
  const rows = items.filter(i => i.status === "active").map(i => [
    i.box, i.name,
    i.countType === "exact" ? i.qty : (i.countType === "bulk" ? "many" : ""),
    i.note || "", i.edited || i.added ? today : (i.updated ? i.updated.split("-").reverse().join("/") : "")
  ].map(q).join(","));
  // keep the box-full flags, so pasting this over the sheet does not lose them
  for(const b of fullBoxes()) rows.push([b, BOX_FULL, 1, "", today].map(q).join(","));
  return [head.join(","), ...rows].join("\r\n");
}
function download(name, text, mime){
  const b = new Blob([text], {type: mime||"text/plain;charset=utf-8"});
  const u = URL.createObjectURL(b), a = document.createElement("a");
  a.href = u; a.download = name; document.body.appendChild(a); a.click();
  a.remove(); setTimeout(()=>URL.revokeObjectURL(u), 4000);
  toast("Saved " + name);
}


/* ------------------------------------------------------------------ wiring */
function wire(){
  const v = document.getElementById("view");

  v.querySelectorAll("[data-tab]").forEach(b => b.onclick = () => { ui.tab = b.dataset.tab; render(); });
  v.querySelectorAll("[data-zone]").forEach(b => b.onclick = () => { ui.zone = b.dataset.zone; render(); });
  v.querySelectorAll("[data-flag]").forEach(b => b.onclick = () => {
    ui.flag = ui.flag === b.dataset.flag ? null : b.dataset.flag; render(); });
  v.querySelectorAll("[data-cat]").forEach(b => b.onclick = () => {
    const c = b.dataset.cat;
    ui.cats.has(c) ? ui.cats.delete(c) : ui.cats.add(c); render(); });
  v.querySelectorAll("[data-toggle]").forEach(b => b.onclick = () => {
    ui.open = ui.open === b.dataset.toggle ? null : b.dataset.toggle; render(); });
  v.querySelectorAll("[data-box]").forEach(b => b.onclick = ev => {
    ev.preventDefault(); ui.box = Number(b.dataset.box); ui.tab = "find"; ui.q = ""; ui.flag = null;
    document.getElementById("q").value = ""; render(); });
  v.querySelectorAll("[data-clearbox]").forEach(b => b.onclick = () => { ui.box = null; render(); });
  v.querySelectorAll("[data-setfull]").forEach(b => b.onclick = async () => {
    b.disabled = true;
    await setBoxFull(Number(b.dataset.setfull), b.dataset.v === "1");
    render();
  });
  v.querySelectorAll("[data-onlybox]").forEach(b => b.onclick = () => {
    ui.box = Number(b.dataset.onlybox); ui.open = null; ui.tab = "find"; render(); });
  v.querySelectorAll("[data-add]").forEach(b => b.onclick = () => showAdd());

  const ed = v.querySelector(".editor");
  if(ed){
    const id = ed.closest(".item").dataset.id;
    const get = f => ed.querySelector(`[data-f="${f}"]`);
    ed.querySelectorAll("[data-step]").forEach(b => b.onclick = () => {
      const inp = get("qty");
      if(inp.disabled){ toast("Set count type to “exact” first"); return; }
      inp.value = Math.max(0, (Number(inp.value)||0) + Number(b.dataset.step));
    });
    get("countType").onchange = e => { get("qty").disabled = e.target.value !== "exact"; };
    const fullBox = ed.querySelector("#efull");
    const label = ed.querySelector("[data-fullbox]");
    get("box").oninput = () => {        // the checkbox is about the box it will be in
      const b = Number(get("box").value) || 1;
      label.textContent = b; fullBox.checked = isFull(b);
    };
    ed.querySelector("[data-savechanges]").onclick = () => {
      const ct = get("countType").value;
      const from = items.find(i => i.id === id)?.box;
      const to = Math.max(1, Number(get("box").value)||1);
      if(to !== from && isFull(to) &&
         !confirm(`Box ${to} is marked full. Move this part into it anyway?`)) return;
      const wantFull = fullBox.checked;
      edit(id, {
        qty: ct === "exact" ? (Number(get("qty").value)||0) : null,
        countType: ct,
        box: Math.max(1, Number(get("box").value)||1),
        category: get("category").value,
        name: get("name").value.trim() || "(unnamed)",
        note: get("note").value.trim(),
        updated: new Date().toISOString().slice(0,10),
        conflict: false
      }, "edit");
      ui.open = null; toast("Saved");
      if(wantFull !== isFull(to)) setBoxFull(to, wantFull);
    };
    ed.querySelector("[data-del]").onclick = () => {
      if(confirm("Delete this entry from the inventory?")){
        edit(id, {deleted:true}, "delete"); ui.open = null; toast("Deleted");
      }
    };
  }

  // One tap = one part in or out. This is the commonest thing you do at the
  // bench and it used to cost four taps through the editor.
  v.querySelectorAll("[data-tally]").forEach(b => b.onclick = async ev => {
    ev.stopPropagation();
    const it = items.find(i => i.id === b.dataset.tId);
    if(!it || it.countType !== "exact") return;
    const next = Math.max(0, Number(it.qty) + Number(b.dataset.tally));
    b.disabled = true;
    toast("Saving…");
    await appendRow({name: it.name, box: it.box, qty: next,
                     note: "(photo-counted)", prev: it.qty});
  });

  v.querySelectorAll("[data-card]").forEach(b => b.onclick = () => {
    const i = Number(b.dataset.card);
    ui.openCard = ui.openCard === i ? null : i;
    render();
  });
  v.querySelectorAll("[data-go]").forEach(b => b.onclick = () => {
    const go = JSON.parse(b.dataset.go);
    ui.tab = go.tab;
    if(go.level != null) ui.level = go.level;
    render();
  });

  const on2 = (id, fn) => { const el = document.getElementById(id); if(el) el.onclick = fn; };
  v.querySelectorAll("[data-level]").forEach(b => b.onclick = () => {
    ui.level = Number(b.dataset.level); render(); });
  v.querySelectorAll("[data-cap]").forEach(b => b.onclick = () => {
    ui.cap = Math.min(20, Math.max(2, ui.cap + Number(b.dataset.cap))); render(); });
  on2("applyplan", () => {
    const p = planMoves(ui.level, ui.cap);
    if(!confirm(`Move ${p.moves.length} parts and free ${p.freed.length} boxes?\n\n`
      + `This only changes the app. Print the worksheet first if you want to follow it at the bench.`)) return;
    const today = new Date().toISOString().slice(0,10);
    for(const m of p.moves)
      overlay.edits[m.id] = Object.assign({}, overlay.edits[m.id], {box:m.to, updated:today});
    journal({label:"Reorganize", patch:{level:ui.level, moves:p.moves.length}});
    save(); rebuild(); render();
    toast(`Moved ${p.moves.length} parts · ${p.freed.length} boxes free`);
  });
  on2("printplan", () => window.print());

  const bt = document.getElementById("bomtext");
  if(bt){
    document.getElementById("runbom").onclick = () => { ui.bom = bt.value; render(); };
    document.getElementById("clearbom").onclick = () => { ui.bom = ""; render(); };
    bt.onkeydown = e => { if(e.key === "Enter" && (e.ctrlKey||e.metaKey)){ ui.bom = bt.value; render(); } };
  }

  const on = (id, fn) => { const el = document.getElementById(id); if(el) el.onclick = fn; };
  on("exp-csv",  () => download("box_inventory.csv", toCSV(), "text/csv;charset=utf-8"));
  on("exp-json", () => download("box_inventory_backup.json",
        JSON.stringify({items, overlay, meta:SEED.meta}, null, 2), "application/json"));
  on("exp-log",  () => download("box_inventory_changes.json",
        JSON.stringify(overlay.journal, null, 2), "application/json"));
  on("reset",    () => {
    if(confirm("Discard all local edits and return to the sheet snapshot?")){
      overlay = {edits:{},added:[],journal:[]}; save(); rebuild(); render(); toast("Reset");
    }
  });
  const imp = document.getElementById("imp");
  if(imp) imp.onchange = e => {
    const f = e.target.files[0]; if(!f) return;
    const r = new FileReader();
    r.onload = () => {
      try{
        const rows = parseCSV(r.result);
        const head = rows[0].map(h => h.trim().toLowerCase());
        const ix = n => head.indexOf(n);
        if(ix("box") < 0 || ix("item") < 0) throw new Error("need Box and Item columns");
        toast(`Read ${rows.length-1} rows — re-run build.py to rebuild the app from this file`);
      }catch(err){ toast("Could not read: " + err.message); }
    };
    r.readAsText(f);
  };
}

/* ------------------------------------------------------------------ camera
   Identification runs in the cloud (see setupCamera below) — this flag only
   decides whether to add a browser install manifest link. */

/* ------------------------------------------------------- speech (local)
   Dictation uses the browser's own recognizer. In Chrome on Android that runs
   on the device — no key, no per-minute cost. It is NOT available inside a
   plain WebView, so the APK needs a native bridge; `speechAvailable` says
   which of the two you are in rather than failing silently. */
const NativeSpeech = window.AndroidSpeech || null;
const WebSpeech = window.SpeechRecognition || window.webkitSpeechRecognition || null;
const speechAvailable = () => Boolean(NativeSpeech || WebSpeech);

let recognizer = null, onHeard = null;

function listen(handler, {continuous = false} = {}){
  onHeard = handler;
  if(NativeSpeech){                       // APK: Android's on-device recognizer
    try{ NativeSpeech.start(continuous); return true; }
    catch(e){ toast("Speech failed: " + e.message); return false; }
  }
  if(!WebSpeech){
    toast("This app cannot listen here — open it in Chrome, or type it");
    return false;
  }
  stopListening();
  recognizer = new WebSpeech();
  recognizer.lang = "en-US";
  recognizer.continuous = continuous;
  recognizer.interimResults = true;
  recognizer.onresult = ev => {
    let finalText = "", interim = "";
    for(let i = ev.resultIndex; i < ev.results.length; i++){
      const r = ev.results[i];
      if(r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    if(onHeard) onHeard({final: finalText.trim(), interim: interim.trim()});
  };
  // Android stops the recognizer after a short silence whatever `continuous`
  // says. Restart it so the channel stays open while you walk to a container.
  recognizer.onend = () => { if(recognizer && recognizer._keep) try{ recognizer.start(); }catch(e){} };
  recognizer.onerror = ev => {
    if(ev.error === "not-allowed") toast("Microphone permission refused");
    else if(ev.error === "no-speech" && recognizer?._keep) return;
    else if(ev.error !== "aborted") toast("Speech error: " + ev.error);
  };
  recognizer._keep = continuous;
  try{ recognizer.start(); return true; }
  catch(e){ toast("Could not start listening"); return false; }
}

function stopListening(){
  if(NativeSpeech){ try{ NativeSpeech.stop(); }catch(e){} }
  if(recognizer){ recognizer._keep = false; try{ recognizer.abort(); }catch(e){} recognizer = null; }
}

// The APK calls these from Java.
window.onSpeechResult = (text, isFinal) => {
  if(onHeard) onHeard({final: isFinal ? String(text||"").trim() : "",
                       interim: isFinal ? "" : String(text||"").trim()});
};
window.onSpeechError = err => { if(onSpeechErr) onSpeechErr(String(err||"")); };
window.onSpeechState = s => { if(onSpeechSt) onSpeechSt(String(s||"")); };
window.onSpeechSpoken = () => { if(onSpoken){ const f = onSpoken; onSpoken = null; f(); } };
let onSpeechErr = null, onSpeechSt = null, onSpoken = null;

/** Speak, and resolve once the phone has finished talking. */
function say(text){
  return new Promise(resolve => {
    if(NativeSpeech && NativeSpeech.speak){
      onSpoken = resolve;
      try{ NativeSpeech.speak(text); }catch(e){ onSpoken = null; resolve(); }
      return;
    }
    if(window.speechSynthesis){
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-US";
      u.onend = u.onerror = () => resolve();
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
      // Some browsers never fire onend; do not let the flow hang on it.
      setTimeout(resolve, Math.min(9000, 1200 + text.length * 70));
      return;
    }
    resolve();
  });
}

/* ------------------------------------------------------- understanding speech
   Numbers arrive as words, and a part number arrives in pieces: "TMC twenty two
   zero nine" is five tokens for one string. Both are normalized before matching. */
const NUM_WORD = {zero:0, oh:0, o:0, one:1, two:2, three:3, four:4, five:5, six:6,
  seven:7, eight:8, nine:9, ten:10, eleven:11, twelve:12, thirteen:13, fourteen:14,
  fifteen:15, sixteen:16, seventeen:17, eighteen:18, nineteen:19, twenty:20,
  thirty:30, forty:40, fifty:50, sixty:60, seventy:70, eighty:80, ninety:90,
  hundred:100, none:0};
// "a" and "an" are deliberately not numbers here: spelling a part out loud
// ("a d s eleven fifteen") turned the letter A into a 1.

function wordsToDigits(text){
  const out = [];
  const toks = String(text).toLowerCase().replace(/[,.]/g, " ").split(/\s+/).filter(Boolean);
  for(let i = 0; i < toks.length; i++){
    const t = toks[i].replace(/-/g, " ").trim();
    if(t.includes(" ")){ toks.splice(i, 1, ...t.split(" ")); i--; continue; }
    if(NUM_WORD[t] !== undefined){
      let v = NUM_WORD[t];
      // "twenty two" is one number; "two zero" is two digits of a part number.
      if(v >= 20 && v < 100 && v % 10 === 0 && NUM_WORD[toks[i+1]] !== undefined
         && NUM_WORD[toks[i+1]] < 10 && NUM_WORD[toks[i+1]] > 0){
        v += NUM_WORD[toks[++i]];
      }
      out.push(String(v));
    } else out.push(t);
  }
  return out.join(" ");
}

/** "tmc twenty two zero nine" -> "tmc2209", so it can match the inventory. */
function spokenPartName(text){
  let s = wordsToDigits(text);
  // "a d s" -> "ads": a part spelled out letter by letter.
  s = s.replace(/\b([a-z](?:\s+[a-z]){1,5})\b/g, m => m.replace(/\s+/g, ""));
  // "tmc 22 0 9" -> "tmc2209"
  s = s.replace(/\b([a-z]{2,6})\s+((?:\d+\s*){1,6})/g,
                (m, letters, digits) => letters + digits.replace(/\s+/g, ""));
  // "1 8 6 5 0" -> "18650". A run of three or more single digits is a part
  // number spelled out, not three separate quantities.
  s = s.replace(/\b(\d(?:\s+\d){2,})\b/g, m => m.replace(/\s+/g, ""));
  return s.replace(/\s{2,}/g, " ").trim();
}

function spokenNumber(text){
  const s = wordsToDigits(text);
  const m = s.match(/-?\d+/);
  return m ? parseInt(m[0], 10) : null;
}

const YES = /\b(yes|yeah|yep|yup|correct|right|affirmative|it is|sure|ok|okay)\b/i;
const NO  = /\b(no|nope|nah|negative|it is not|isn'?t|not)\b/i;
const STOP_WORDS = /\b(stop|done|finished|that'?s all|quit|exit|end|no more|nothing else)\b/i;

/* ------------------------------------------------------------- voice mode
   A fixed question tree, run entirely on the phone: no model, no API call, no
   cost, and no reason for it to close while you walk to a shelf. It ends when
   you say so, or when you tap the button. */
const ATTRS = {
  driver:    [["Are the pins soldered on?", "pins soldered", "pins not soldered"],
              ["Does it have a heat sink?", "with heat sink", "no heat sink"]],
  mcu:       [["Are the headers soldered on?", "headers soldered", "headers loose"]],
  sensor:    [["Are the headers soldered on?", "headers soldered", "headers loose"]],
  interface: [["Are the headers soldered on?", "headers soldered", "headers loose"]],
  power:     [["Are the wires attached?", "wired", "bare board"]],
};

let voiceOn = false, voiceLog = [];

function voiceBanner(text, sub){
  let el = document.getElementById("vbanner");
  if(!voiceOn){ el?.remove(); return; }
  if(!el){
    el = document.createElement("div");
    el.id = "vbanner";
    document.body.appendChild(el);
  }
  el.innerHTML = `<div class="vtext">${esc(text)}</div>
    <div class="vsub">${esc(sub || "")}</div>
    <button id="vstop">Stop</button>`;
  el.querySelector("#vstop").onclick = () => stopVoice("Stopped.");
}

/** Wait for one spoken answer. No timeout — silence is expected. */
function hear(){
  return new Promise(resolve => {
    let settled = false;
    onHeard = ({final, interim}) => {
      if(interim) voiceBanner(document.querySelector("#vbanner .vtext")?.textContent || "",
                              "…" + interim);
      if(final && !settled){ settled = true; onHeard = null; resolve(final); }
    };
    if(!listen(() => {}, {continuous: true})) resolve(null);
    // listen() replaced onHeard; put ours back.
    onHeard = ({final, interim}) => {
      if(interim) voiceBanner(document.querySelector("#vbanner .vtext")?.textContent || "",
                              "…" + interim);
      if(final && !settled){ settled = true; onHeard = null; resolve(final); }
    };
  });
}

async function ask(question, sub){
  voiceBanner(question, sub);
  await say(question);
  if(!voiceOn) return null;
  const answer = await hear();
  if(!voiceOn) return null;
  if(answer && STOP_WORDS.test(answer)){ await stopVoice("Okay, stopping."); return null; }
  return answer;
}

async function startVoice(){
  if(voiceOn) return stopVoice("Stopped.");
  if(!speechAvailable()){
    toast("No speech here — open the app in Chrome, or type it");
    return;
  }
  voiceOn = true; voiceLog = [];
  document.getElementById("say")?.classList.add("live");
  await say("Voice mode on. Which part?");

  while(voiceOn){
    const spoken = await ask("Which part?", "say a part name, or “stop”");
    if(!voiceOn || !spoken) break;

    const guess = spokenPartName(spoken);
    const hits = active().map(i => [i, matchScore(guess, i)])
      .filter(p => p[1] >= 0.5)
      .sort((a,b) => b[1]-a[1] || a[0].name.length-b[0].name.length);
    const found = hits[0]?.[0] || null;

    // Attribute questions, from the part's own category — a note, not a new part.
    const notes = [];
    const cat = found ? found.category : "misc";
    for(const [q, yes, no] of (ATTRS[cat] || [])){
      const a = await ask(q, "yes or no");
      if(!voiceOn) return;
      if(a && YES.test(a)) notes.push(yes);
      else if(a && NO.test(a)) notes.push(no);
    }

    let box = found ? found.box : null;
    if(box === null){
      const free = (SEED.freeBoxes || []).filter(f => f.box < 400)[0];
      const a = await ask(`I do not have ${guess}. Which box number?`,
                          free ? `free: ${free.box}` : "");
      if(!voiceOn) return;
      box = spokenNumber(a || "") ?? (free ? free.box : null);
      if(box === null){ await say("I did not catch a box number. Skipping."); continue; }
    }

    const recorded = found
      ? (found.countType === "exact" ? found.qty : "many")
      : null;
    const a = await ask(
      found ? `${found.name}, box ${box}. I have ${recorded}. How many now?`
            : `New part in box ${box}. How many?`,
      "say the total in the box");
    if(!voiceOn) return;

    let qty = spokenNumber(a || "");
    if(a && /\b(many|a pile|lots|loads|uncounted)\b/i.test(a)) qty = "many";
    if(qty === null){ await say("I did not catch a number. Skipping that one."); continue; }

    const vName = found ? found.name : guess;
    const vNote = notes.length ? notes.join("; ") + " (photo-counted)" : "(photo-counted)";
    const ok = await appendRow({name: vName, box, qty, note: vNote,
                                prev: found ? recorded : undefined});
    if(ok){
      voiceLog.push(`${vName} = ${qty} in box ${box}`);
      await say(`Logged. ${vName}, ${qty === "many" ? "a pile" : qty} in box ${box}.`);
    } else {
      await say("I could not save that.");
    }
    if(!voiceOn) return;

    const more = await ask("Anything else?", "say a part name, or “stop”");
    if(!voiceOn || !more) break;
    if(NO.test(more) || STOP_WORDS.test(more)) break;
    // Treat anything else as the next part rather than making you repeat it.
    if(!YES.test(more)){
      // reuse the answer by looping with it already spoken
      voiceLog.push("");   // marker only
      // fall through: the next loop asks again; keeping this simple beats
      // guessing wrong about what was said.
    }
  }
  await stopVoice();
}

async function stopVoice(finalWord){
  const wasOn = voiceOn;
  voiceOn = false;
  stopListening();
  onHeard = null;
  document.getElementById("say")?.classList.remove("live");
  document.getElementById("vbanner")?.remove();
  if(wasOn){
    const done = voiceLog.filter(Boolean);
    if(finalWord) await say(finalWord);
    toast(done.length ? `Voice mode: ${done.length} logged` : "Voice mode off");
  }
}

/* ------------------------------------------------------- typed / spoken add
   For a part you can name, this is the whole pipeline: it matches against the
   inventory in the page, so there is no photo, no vision call and no cost. */
function showAdd(prefill = ""){
  document.getElementById("sheetwrap")?.remove();

  const wrap = document.createElement("div");
  wrap.id = "sheetwrap"; wrap.dataset.id = "__add__";
  wrap.innerHTML = `
    <div id="sheet">
      <div class="grab"></div>
      <h2>Which part?</h2>
      <p class="sub2">Type or say the name — a part number is enough.</p>
      <div class="namerow">
        <input id="aname" placeholder="e.g. TMC2209" value="${esc(prefill)}"
               autocomplete="off" autocapitalize="off" spellcheck="false">
        <button id="amic" title="Dictate">🎤</button>
      </div>
      <div class="heard" id="aheard"></div>
      <ul class="matches" id="amatches"></ul>
      <div class="row2">
        <button class="btn ghost" id="anew">Not listed — add as new</button>
        <button class="btn ghost" id="aclose">Close</button>
      </div>
    </div>`;
  document.body.appendChild(wrap);

  const input = wrap.querySelector("#aname");
  const list = wrap.querySelector("#amatches");
  const heard = wrap.querySelector("#aheard");
  const mic = wrap.querySelector("#amic");

  const paint = () => {
    const q = input.value.trim();
    if(!q){ list.innerHTML = ""; return; }
    const hits = active()
      .map(i => [i, matchScore(q, i)])
      .filter(p => p[1] >= 0.5)
      .sort((a,b) => b[1]-a[1] || a[0].name.length-b[0].name.length)
      .slice(0, 8);
    list.innerHTML = hits.length ? hits.map(([i]) => `
      <li><button data-id="${esc(i.id)}">
        <span class="nm">${esc(i.name)}</span>
        <span class="bx">box ${i.box}${isFull(i.box) ? " · full" : ""}</span>
        <span class="qt">${i.countType === "exact" ? i.qty : "many"}</span>
      </button></li>`).join("")
      : `<li><button disabled><span class="nm" style="color:var(--ink-3)">
           No match — use “add as new” below</span></button></li>`;
    list.querySelectorAll("[data-id]").forEach(b => b.onclick = () => {
      const it = items.find(i => i.id === b.dataset.id);
      stopListening();
      askCount({name: it.name, box: it.box,
                recorded: it.countType === "exact" ? it.qty : "many",
                recordedName: it.name, seen: 0});
    });
  };

  input.oninput = paint;
  paint();
  if(!prefill) setTimeout(() => input.focus(), 60);

  mic.onclick = () => {
    if(mic.classList.contains("live")){ stopListening(); mic.classList.remove("live"); return; }
    const ok = listen(({final, interim}) => {
      heard.textContent = interim ? `…${interim}` : "";
      if(final){ input.value = final; heard.textContent = ""; paint(); }
    }, {continuous: false});
    if(ok) mic.classList.add("live");
  };

  wrap.querySelector("#anew").onclick = () => {
    const name = input.value.trim();
    if(!name){ input.focus(); return; }
    stopListening();
    const free = (SEED.freeBoxes || []).filter(f => f.box < 400)[0];
    askCount({name, box: free ? free.box : 1, recorded: null, recordedName: null, seen: 1,
              isNew: true});
  };
  wrap.querySelector("#aclose").onclick = () => { stopListening(); wrap.remove(); };
}

/* ---------------------------------------------------- count confirmation
   A photo does not mean "+1". You may have taken parts out without logging it,
   so the only number that can be trusted is the one you read off the box now.
   The recorded count is pre-filled; whatever you leave here becomes the truth. */
let confirmQueue = [];

function showConfirm(){
  const q = confirmQueue[0];
  const old = document.getElementById("sheetwrap");
  // Only ever close a sheet that belongs to the photo queue. Closing on
  // "anything that is not the add sheet" tore down a typed count sheet on the
  // next poll, two and a half seconds after it opened.
  if(!q){
    if(old && old.dataset.src === "photo") old.remove();
    return;
  }
  if(old) return;                                 // never interrupt an open sheet
  askCount(q);
}

/** The count sheet, for a photo (q.id set) or a typed entry (no id). */
function askCount(q){
  document.getElementById("sheetwrap")?.remove();

  const recorded = q.recorded;
  const known = recorded !== null && recorded !== undefined && recorded !== "many";
  const start = known ? Number(recorded) : Math.max(1, Number(q.seen) || 1);

  const wrap = document.createElement("div");
  wrap.id = "sheetwrap"; wrap.dataset.id = q.id || "__count__";
  if(q.id) wrap.dataset.src = "photo";
  wrap.innerHTML = `
    <div id="sheet">
      <div class="grab"></div>
      ${q.photo ? `<img class="shot" src="${serverBase()}/data/review/${
        encodeURIComponent(q.photo)}" alt="">` : ""}
      <h2>${esc(q.recordedName || q.name)}</h2>
      <p class="sub2">${known
          ? `Box ${esc(q.box)} · recorded ${esc(recorded)}${
              Number(q.seen) ? ` · ${esc(q.seen)} in the photo` : ""}`
          : (recorded === "many"
              ? `Box ${esc(q.box)} · recorded as a bulk pile`
              : `Not in the inventory yet · going to box ${esc(q.box)}`)}</p>
      <input class="wrongname" id="cname" value="${esc(q.recordedName || q.name)}">
      ${q.isNew ? `<div class="counter" style="margin-bottom:10px">
          <label style="font-size:12px;color:var(--ink-3);min-width:34px">Box</label>
          <input id="cbox" type="number" inputmode="numeric" value="${esc(q.box)}" min="1"
                 style="height:44px;font-size:19px">
        </div>` : ""}
      <p class="fullwarn" id="cfullwarn"></p>
      ${fullToggleHTML(q.box, "cfull")}
      <p class="ask">How many are in the box now?</p>
      <div class="counter">
        <button id="cminus">−</button>
        <input id="cqty" type="number" inputmode="numeric" value="${start}" min="0">
        <button id="cplus">+</button>
      </div>
      <div class="quick" id="cquick"></div>
      <div class="row2">
        <button class="btn" id="csave">Save count</button>
        <button class="btn ghost" id="cskip">${q.id ? "Not this" : "Cancel"}</button>
      </div>
      <div class="queued">${confirmQueue.length > 1
        ? `${confirmQueue.length - 1} more waiting` : ""}</div>
    </div>`;
  document.body.appendChild(wrap);

  const qty = wrap.querySelector("#cqty");
  const quick = wrap.querySelector("#cquick");
  const fullBox = wrap.querySelector("#cfull");
  const fullWarn = wrap.querySelector("#cfullwarn");
  const boxNow = () => Number(wrap.querySelector("#cbox")?.value) || Number(q.box);
  // Warn only when something would go INTO a full box: a new part, or a part
  // the photo service reports as sitting in a box already marked full.
  const paintFull = () => {
    const b = boxNow();
    wrap.querySelector("[data-fullbox]").textContent = b;
    fullBox.checked = isFull(b);
    fullWarn.textContent = isFull(b)
      ? (q.isNew ? `Box ${b} is marked full — pick another box, or untick below if it fits after all.`
                 : `Box ${b} is marked full. Counting what is in it is fine; adding more is not.`)
      : "";
  };
  wrap.querySelector("#cbox")?.addEventListener("input", paintFull);
  paintFull();
  // The two answers you give most: the count is unchanged, or one came back.
  const options = [];
  if(known){
    options.push([Number(recorded), `still ${recorded}`]);
    options.push([Number(recorded) + 1, `${Number(recorded) + 1} — one back`]);
    if(Number(recorded) > 0) options.push([Number(recorded) - 1, `${Number(recorded) - 1} — one gone`]);
  } else {
    options.push([Number(q.seen) || 1, `${Number(q.seen) || 1} in the photo`]);
  }
  options.push(["many", "a pile — do not count"]);

  const paintQuick = () => {
    quick.innerHTML = options.map(([v, label]) =>
      `<button data-v="${v}" class="${String(v) === qty.dataset.v ? "sel" : ""}">${label}</button>`).join("");
    quick.querySelectorAll("button").forEach(b => b.onclick = () => {
      qty.dataset.v = b.dataset.v;
      if(b.dataset.v === "many"){ qty.value = ""; qty.placeholder = "many"; qty.disabled = true; }
      else { qty.disabled = false; qty.value = b.dataset.v; }
      paintQuick();
    });
  };
  qty.dataset.v = String(start);
  paintQuick();

  const bump = d => { qty.disabled = false; qty.value = Math.max(0, (Number(qty.value)||0) + d);
                      qty.dataset.v = qty.value; paintQuick(); };
  wrap.querySelector("#cminus").onclick = () => bump(-1);
  wrap.querySelector("#cplus").onclick = () => bump(1);

  wrap.querySelector("#csave").onclick = async () => {
    const isBulk = qty.dataset.v === "many";
    const wantFull = fullBox.checked;
    if(q.isNew && isFull(boxNow()) && wantFull &&
       !confirm(`Box ${boxNow()} is marked full. Put the new part in it anyway?`)) return;
    const boxField = wrap.querySelector("#cbox");
    const body = {id: q.id,
                  qty: isBulk ? "many" : (Number(qty.value)||0),
                  box: boxField ? (Number(boxField.value)||q.box) : q.box,
                  name: wrap.querySelector("#cname").value.trim()};
    wrap.querySelector("#csave").disabled = true;
    try{
      if(q.id){
        // A photo has a pending record on the server (which archives the photo
        // and posts the count to the sheet itself).
        const res = await fetch(serverBase() + "/confirm", {method:"POST",
          headers:{"Content-Type":"application/json"}, body: JSON.stringify(body)});
        const out = await res.json();
        if(!res.ok) throw new Error(out.error || res.status);
        toast(`${out.name} → box ${out.box} = ${isBulk ? "many" : body.qty}`);
        confirmQueue.shift();
        wrap.remove();
        await refreshSeed();
        if(wantFull !== isFull(out.box)) await setBoxFull(out.box, wantFull);
        showConfirm();
        if(typeof q.then === "function") q.then(body);
      } else {
        toast("Saving…");
        const ok = await appendRow({name: body.name, box: body.box, qty: body.qty,
                                    note: "(photo-counted)",
                                    prev: q.recorded ?? undefined});
        if(ok) toast(`${body.name} → box ${body.box} = ${isBulk ? "many" : body.qty}`);
        if(ok && wantFull !== isFull(body.box)) await setBoxFull(body.box, wantFull);
        if(typeof q.then === "function") q.then(body);
      }
    }catch(err){
      toast("Could not save: " + err.message);
      wrap.querySelector("#csave").disabled = false;
    }
  };

  wrap.querySelector("#cskip").onclick = async () => {
    if(q.id){
      await fetch(serverBase() + "/dismiss",
                  {method:"POST", headers:{"Content-Type":"application/json"},
                   body: JSON.stringify({id:q.id})}).catch(()=>{});
      confirmQueue.shift();
      wrap.remove();
      showConfirm();
      if(typeof q.then === "function") q.then(null);
    } else {
      wrap.remove();
      if(typeof q.then === "function") q.then(null);
    }
  };
}

function setupCamera(){
  if(SERVED){
    const link = document.createElement("link");
    link.rel = "manifest"; link.href = "/manifest.webmanifest";
    document.head.appendChild(link);
  }

  const mkInput = (capture) => {
    const i = document.createElement("input");
    i.type = "file"; i.accept = "image/*"; i.multiple = true;
    if(capture) i.setAttribute("capture", "environment");
    i.style.display = "none";
    document.body.appendChild(i);
    return i;
  };
  const camInput = mkInput(true);
  const galInput = mkInput(false);

  const btn = document.createElement("button");
  btn.id = "cam"; btn.title = "Take a photo of a part";
  btn.innerHTML = `<span>📷</span>`;
  document.body.appendChild(btn);

  const gal = document.createElement("button");
  gal.id = "gal"; gal.title = "Pick photos you already took";
  gal.innerHTML = `<span>🖼️</span>`;
  document.body.appendChild(gal);

  const sayBtn = document.createElement("button");
  sayBtn.id = "say"; sayBtn.title = "Type a part name — hold for voice mode";
  sayBtn.innerHTML = `<span>⌨️</span>`;
  document.body.appendChild(sayBtn);

  let holdTimer = null, wentVoice = false;
  const armHold = () => {
    wentVoice = false;
    holdTimer = setTimeout(() => {
      wentVoice = true;
      if(navigator.vibrate) navigator.vibrate(30);
      startVoice();
    }, 550);
  };
  const releaseHold = ev => {
    clearTimeout(holdTimer);
    if(!wentVoice){ ev.preventDefault(); showAdd(); }
  };
  sayBtn.addEventListener("touchstart", armHold, {passive:true});
  sayBtn.addEventListener("touchend", releaseHold);
  sayBtn.addEventListener("mousedown", armHold);
  sayBtn.addEventListener("mouseup", releaseHold);

  btn.onclick = () => { camInput.value = ""; camInput.click(); };
  gal.onclick = () => { galInput.value = ""; galInput.click(); };

  const upload = async (input) => {
    const files = [...input.files];
    if(!files.length) return;

    let apiKey = localStorage.getItem("IDENTIFY_API_KEY");
    if(!apiKey){
      apiKey = prompt("Please enter the API Key to identify photos:");
      if(!apiKey) return;
      localStorage.setItem("IDENTIFY_API_KEY", apiKey);
    }

    btn.dataset.busy = gal.dataset.busy = "1";
    for(const f of files){
      toast("Identifying…");
      try{
        const headers = {
          "X-Filename": f.name || "photo.jpg",
          "Content-Type": f.type || "image/jpeg"
        };
        if(apiKey) headers["Authorization"] = "Bearer " + apiKey;

        const res = await fetch(IDENTIFY_URL, {
          method: "POST",
          headers: headers,
          body: f,
        });

        if (res.status === 401) {
          localStorage.removeItem("IDENTIFY_API_KEY");
        }
        const out = await res.json();
        if(!res.ok) throw new Error(out.error || res.status);
        await new Promise(resolve => askCount(Object.assign({}, out, {then: resolve})));
      }catch(err){
        toast("Could not identify: " + err.message);
      }
    }
    delete btn.dataset.busy; delete gal.dataset.busy;
  };

  camInput.onchange = () => upload(camInput);
  galInput.onchange = () => upload(galInput);
}

/* ------------------------------------------------------------------- boot */
document.getElementById("tabs").onclick = e => {
  const b = e.target.closest("[data-tab]"); if(!b) return;
  ui.tab = b.dataset.tab; ui.open = null; render();
};
const qEl = document.getElementById("q");
qEl.oninput = () => { ui.q = qEl.value; if(ui.q) ui.box = null; render(); };
document.getElementById("clearq").onclick = () => {
  qEl.value = ""; ui.q = ""; ui.box = null; ui.flag = null; qEl.focus(); render(); };
document.getElementById("theme-btn").onclick = () => {
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur === "dark" ? "light" : cur === "light" ? "" : "dark";
  next ? document.documentElement.setAttribute("data-theme", next)
       : document.documentElement.removeAttribute("data-theme");
  try{ localStorage.setItem("boxinv.theme", next); }catch(e){}
};
try{
  const t = localStorage.getItem("boxinv.theme");
  if(t) document.documentElement.setAttribute("data-theme", t);
}catch(e){}
document.addEventListener("keydown", e => {
  if(e.key === "/" && document.activeElement !== qEl && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)){
    e.preventDefault(); qEl.focus(); qEl.select();
  }
  if(e.key === "Escape" && document.activeElement === qEl){
    qEl.value = ""; ui.q = ""; render();
  } else if(e.key === "Escape"){
    const wrap = document.getElementById("sheetwrap");
    if(wrap) wrap.remove();
  }
});

(async function init() {
  rebuild();
  render();
  try {
    const cfg = await loadConfig();
    SHEET = {
      id: cfg.sheet_id,
      boxGid: cfg.box_gid,
      formGid: cfg.form_gid,
      formAction: cfg.form_url,
      entries: cfg.form_entries,
    };
    IDENTIFY_URL = cfg.identify_endpoint || "https://box-identify-463126624138.us-central1.run.app/identify";
  } catch(err) {
    console.warn("Using offline defaults:", err);
  }
  refreshSeed();
  setupCamera();
})();