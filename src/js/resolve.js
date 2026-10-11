/**
 * Shared resolver logic.
 * Parses the sheet CSVs and resolves newest-wins per box+item.
 */

export const BOX_FULL = "[BOX FULL]";
export const BOX_FULL_SLUG = "box full";

export const CATEGORY_RULES = [
  ["mcu",        /esp32|esp8266|xiao|microcontroller|\bmcu\b/],
  ["sensor",     /\bmq-|mq gas|guva|heart-rate|neo-6m|gps|ens160|aht2|gyro|accelerom|mpu6050|hc-sr04|tilt sensor|tof|vl53|veml|hall sensor|reed |vibration (sensor|switch)|pressure sensor|load cell|current sensor|current transformer|ina219|audio-wave|lm393|magnetic switch|rd-03d|capacitive touch|ir receiver|laser sensor|mps20n|voltage sensor|coil-type vibration|pressure-sensitive/],
  ["power",      /charger|converter|buck|boost|step-up|step-down|mt3608|mini-360|hw-187|mp1584|cr6030|pd trigger|fast-charge|solar charge|18650|battery|batteries|lr44|\bac\/dc\b|power module|power meter|v meter|level indicator|usb-a power/],
  ["driver",     /tmc2209|uln2003|motor driver|h-bridge|tc1508|mosfet|relay|\bssr\b|pwm controller|speed controller|stepper driver|xy-mos|lr7843/],
  ["motor",      /stepper motor|servo|dc motor|gear motor|brushed dc|vibration motor|\bfan\b|micro dc/],
  ["display",    /oled|7-seg|\bled\b|leds|cob|rgb|traffic-light|candle|flasher|display/],
  ["comms",      /wi-fi|wifi|uart|ir transmitter|nfc|sim card|rj-45|tracker tag|walkie|receiver \(dongle\)|wireless mouse|laser diode/],
  ["interface",  /ads1115|\badc\b|hx711|pcm1808|i2s|555 timer|breakout|serial adapter|usb-to-ttl|hw-477|sku7810/],
  ["switch",     /switch|button|potentiometer|encoder|knob|key lock|\bkeys?\b|navigation tactile|piezoelectric spark/],
  ["connector",  /xt60|usb|hdmi|barrel|header pin|terminal|alligator|wire connector|kroonsteentje|audio plug|adapter|coupling|connector|iec panel|strip connector|cable reel/],
  ["fastener",   /bolt|screw|\bnuts?\b|washer|standoff|tap bits|drill|countersink|barrel nut|mounting hardware|lock nut|lock washer/],
  ["mechanical", /gear|pulley|belt|bearing|idler|rail|carriage|tube|tubing|heatsink|disk|bracket|mechanical parts|nozzle|clamp|padlock|clip|elastic band|spacer/],
  ["tool",       /tool|bit set|measuring tape|keycap remover|radiator valve|tape|lens kit|hemming/],
  ["material",   /scrap|shavings|sawdust|flakes|granules|seeds|salts|foam|earplug|popsicle|hot-glue|shoelace|gemstone|coil|sticker|label/],
];

export function categorize(name, note) {
  const hay = (name + " " + (note || "")).toLowerCase();
  for(const [cat, re] of CATEGORY_RULES) if(re.test(hay)) return cat;
  return "misc";
}

export const slugName = s => String(s).normalize("NFKD").replace(/[̀-ͯ]/g, "")
  .replace(/[^a-z0-9]+/gi, " ").toLowerCase().trim();

export function parseSheetDate(text) {
  const m = String(text || "").trim()
    .match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:\s+(\d{1,2}):(\d{2}):(\d{2}))?$/);
  if(!m) return null;
  const p = n => String(n).padStart(2, "0");
  return `${m[3]}-${p(m[2])}-${p(m[1])}T${p(m[4]||0)}:${m[5]||"00"}:${m[6]||"00"}`;
}

export function parseCSV(text) {
  const rows = []; let row = [], cell = "", inQ = false;
  text = text.replace(/^﻿/, "");
  for(let i=0;i<text.length;i++){
    const c = text[i];
    if(inQ){
      if(c === '"'){ if(text[i+1] === '"'){ cell += '"'; i++; } else inQ = false; }
      else cell += c;
    } else if(c === '"') inQ = true;
    else if(c === ","){ row.push(cell); cell = ""; }
    else if(c === "\n"){ row.push(cell); rows.push(row); row = []; cell = ""; }
    else if(c !== "\r") cell += c;
  }
  if(cell.length || row.length){ row.push(cell); rows.push(row); }
  return rows.filter(r => r.some(c => c.trim() !== ""));
}

export function containerOf(box, containerSize) {
  const base = box >= 400 ? 400 : 0;
  const n = Math.floor((box - base - 1) / containerSize) + 1;
  return (base ? "H" : "") + n;
}

export function containerRange(box, containerSize) {
  const base = box >= 400 ? 400 : 0;
  const c = Math.floor((box - base - 1) / containerSize);
  return [base + c * containerSize + 1, base + (c + 1) * containerSize];
}

export function resolveSheet(boxCsv, formCsv, seedMeta) {
  const raw = [];
  const boxRows = parseCSV(boxCsv);
  for(let i = 1; i < boxRows.length; i++){
    const [box, name, qty, note, updated] = boxRows[i];
    if(!String(box || "").trim()) continue;
    raw.push({line: i, src: 0, box: parseInt(box, 10), name: (name||"").trim(),
              qtyTxt: (qty||"").trim(), note: (note||"").trim(),
              when: parseSheetDate(updated)});
  }
  const formRows = parseCSV(formCsv || "");
  for(let i = 1; i < formRows.length; i++){
    const [ts, box, name, qty, note] = formRows[i];
    if(!String(box || "").trim() || !String(name || "").trim()) continue;
    const b = parseInt(box, 10);
    if(!Number.isFinite(b)) continue;
    raw.push({line: i, src: 1, box: b, name: (name||"").trim(),
              qtyTxt: (qty||"").trim(), note: (note||"").trim(),
              when: parseSheetDate(ts)});
  }

  const groups = new Map();
  const flags = new Map();
  const newer = (a, b) => (a.when||"").localeCompare(b.when||"") || a.src - b.src || a.line - b.line;
  for(const r of raw){
    if(slugName(r.name) === BOX_FULL_SLUG){
      if(!flags.has(r.box) || newer(r, flags.get(r.box)) >= 0) flags.set(r.box, r);
      continue;
    }
    const k = r.box + "|" + slugName(r.name);
    if(!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }

  const items = [];
  for(const [key, history] of groups){
    history.sort((a, b) => (a.when||"").localeCompare(b.when||"")
                        || a.src - b.src || a.line - b.line);
    const latest = history[history.length - 1];
    if(!latest.name) continue;

    let countType, qty;
    const qt = latest.qtyTxt.toLowerCase();
    if(qt === "") { countType = "unknown"; qty = null; }
    else if(qt === "many" || parseInt(qt, 10) === 99){ countType = "bulk"; qty = null; }
    else if(/^-?\d+$/.test(qt)){ countType = "exact"; qty = parseInt(qt, 10); }
    else { countType = "unknown"; qty = null; }

    let peak = countType === "exact" ? qty : null;
    for(const r of history){
      const n = parseInt(r.qtyTxt, 10);
      if(/^\d+$/.test(r.qtyTxt) && n !== 99) peak = Math.max(peak ?? 0, n);
    }

    const distinct = new Set(history.map(r => r.qtyTxt.toLowerCase()));
    const deliberate = latest.src === 1
        || (latest.note || "").toLowerCase().includes("photo-counted");
    const conflict = history.length > 1 && distinct.size > 1 && !deliberate;

    items.push({
      id: `${latest.box}-${slugName(latest.name)}`,
      box: latest.box, name: latest.name, qty, peak, countType,
      status: (countType === "exact" && qty === 0) ? "gone" : "active",
      note: latest.note || [...history].reverse().find(r => r.note)?.note || "",
      category: categorize(latest.name, latest.note),
      updated: latest.when ? latest.when.slice(0, 10) : null,
      conflict, restated: history.length > 1 && distinct.size === 1,
      history: history.length > 1
        ? history.map(r => ({qty: r.qtyTxt, date: r.when ? r.when.slice(0,10) : null,
                             note: r.note}))
        : [],
    });
  }
  items.sort((a, b) => a.box - b.box || a.name.localeCompare(b.name));

  const used = new Set(items.filter(i => i.status === "active").map(i => i.box));
  const fullBoxes = [...flags].filter(([b, r]) => used.has(b)
      && /^-?\d+$/.test(r.qtyTxt) && parseInt(r.qtyTxt, 10) !== 0)
    .map(([b]) => b).sort((a, b) => a - b);
  const known = new Set(items.map(i => i.box));
  const freeBoxes = [];
  const lows = [...known].filter(b => b < 400), highs = [...known].filter(b => b >= 400);
  for(const [lo, hi] of [[1, Math.max(0, ...lows)], [400, Math.max(0, ...highs)]])
    for(let b = lo; b <= hi; b++)
      if(!used.has(b)) freeBoxes.push({box: b, container: containerOf(b, seedMeta?.containerSize || 30),
        reason: known.has(b) ? "emptied" : "never used"});

  return {meta: Object.assign({}, seedMeta, {
            source: "Google Sheet (live)", rawRows: raw.length,
            generated: new Date().toISOString().slice(0, 10)}),
          items, freeBoxes, splitItems: [], fullBoxes};
}
