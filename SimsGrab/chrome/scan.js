// Shared by the popup and the hidden offscreen page: find mod links on pages, fetch the files behind them, zip them.
const FILE = /\.(zip|rar|7z|package|ts4script)$/i;
const JUNK = /\.(jpe?g|png|gif|webp|svg|css|js|ico|mp4|woff2?)$/i;
const HOSTS = ["simfileshare.net/download", "mediafire.com/file", "mediafire.com/?", "drive.google.com", "dropbox.com/s",
               "patreon.com/file", "patreon.com/media-u", "getfile.php", "curseforge.com/api/v1/mods"];
const POSTS = /tumblr\.com\/(post\/|[\w-]+\/\d)|patreon\.com\/posts\/|modthesims\.info\/d\/|curseforge\.com\/sims4\/|itch\.io\//i;
const MAGIC = { "504b0304": ".zip", "52617221": ".rar", "377abcaf": ".7z", "44425046": ".package" };
const PIN_API = "https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids=", PIN_PAGE = "https://www.pinterest.com/pin/";
const site = (u) => new URL(u).hostname.replace(/^www\./, "");
const path = (u) => { const p = new URL(u).pathname; try { return decodeURIComponent(p); } catch { return p; } };
const clean = (s) => s.replace(/&#?\w+;/g, " ").replace(/[\\/:*?"<>|~]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 60);
const pool = (items, n, fn) => { const q = [...items]; return Promise.all(Array.from({ length: n }, async () => { while (q.length) await fn(q.shift()); })); };

function unwrap(u) {  // t.umblr.com/redirect?z=<real url> and friends
  for (const v of new URL(u).searchParams.values()) if (/^https?:\/\//.test(v)) return unwrap(v);
  return u;
}

function score(u, text = "") {  // 3 = a mod file, 2 = a file host page, 1 = says "download", 0 = skip
  if (JUNK.test(path(u))) return 0;
  if (FILE.test(path(u))) return 3;
  if (HOSTS.some((h) => u.includes(h))) return 2;
  return /download/i.test(`${u} ${text}`) ? 1 : 0;
}

function links(base, html, anchors = []) {  // every link on a page as url -> link text, redirect wrappers removed
  const text = html.replace(/\\\//g, "/").replace(/\\u002F/gi, "/").replace(/\\u0026/gi, "&").replace(/&amp;/g, "&");
  const tags = [...text.matchAll(/<a\s[^>]*?href=["']([^"'#]+)["'][^>]*>([\s\S]*?)<\/a>/gi)]  // links in fetched pages, with their text
    .map((m) => [m[1], m[2].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 90)]);
  const raw = [...anchors, ...tags, ...[...text.matchAll(/https?:\/\/[^\s"'<>\\)]+/g)].map((m) => [m[0], ""])];
  for (const m of text.matchAll(/data-scrambled-url="([^"]+)"/g)) {  // MediaFire hides its button link
    try { raw.push([atob(m[1]), "MediaFire download"]); } catch {}
  }
  const found = new Map();
  for (const [href, label] of raw) {
    let u;
    try { u = unwrap(new URL(href, base).href); } catch { continue; }
    if (/^https?:/.test(u) && !found.get(u)) found.set(u, label);
  }
  return found;
}

function leads(base, html, anchors = []) {  // the links worth grabbing, best first
  return [...links(base, html, anchors)].map(([url, text]) => ({ url, text, score: score(url, text) }))
    .filter((l) => l.score).sort((a, b) => b.score - a.score);
}

function route(u) {  // share links -> direct downloads or data the host gives out
  const d = u.match(/drive\.google\.com\/.*?(?:\/d\/|[?&]id=)([\w-]{20,})/);
  if (d) return `https://drive.usercontent.google.com/download?id=${d[1]}&export=download&confirm=t`;
  if (u.includes("dropbox.com/")) return u.includes("dl=") ? u.replace("dl=0", "dl=1") : `${u}${u.includes("?") ? "&" : "?"}dl=1`;
  const p = /(^|\.)patreon\.com$/.test(site(u)) && u.match(/\/posts\/(?:[^/?]*-)?(\d+)/);
  return p ? `https://www.patreon.com/api/posts/${p[1]}?include=attachments,attachments_media` : u;
}

const get = (u) => fetch(route(u), { credentials: "include" });

async function page(url) {
  const r = await get(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return { url: r.url, html: await r.text() };
}

async function resolve(url, depth = 0) {  // the address of the file behind a link, two host pages deep; null if none
  const ctl = new AbortController(), r = await fetch(route(url), { signal: ctl.signal, credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  if (!/html|json|text\/plain/.test(r.headers.get("content-type") || "")) { ctl.abort(); return r.url; }
  const next = depth < 2 && leads(r.url, await r.text()).find((l) => l.score >= 2 && l.url !== url);
  return next ? resolve(next.url, depth + 1) : null;
}

async function getFile(url, depth = 0) {  // the mod file behind a link as {name, data}, two host pages deep; null if none
  const r = await get(url);
  if (!r.ok) return null;
  if (/html|json|text\/plain/.test(r.headers.get("content-type") || "")) {
    const next = depth < 2 && leads(r.url, await r.text()).find((l) => l.score >= 2 && l.url !== url);
    return next ? getFile(next.url, depth + 1) : null;
  }
  const data = new Uint8Array(await r.arrayBuffer());
  const kind = MAGIC[[...data.slice(0, 4)].map((b) => b.toString(16).padStart(2, "0")).join("")];
  if (!kind) return null;  // not a mod: an image, an ad, an error page
  let name = (r.headers.get("content-disposition") || "").match(/filename\*?=(?:UTF-8'')?"?([^";]+)/i)?.[1]
             || path(r.url).split("/").filter(Boolean).pop() || "mod";
  try { name = decodeURIComponent(name); } catch {}
  name = clean(name) || "mod";
  return { name: FILE.test(name) ? name : name + kind, data };
}

async function pinSource(pin) {  // the page a pin was saved from
  for (const u of [PIN_API + pin, `${PIN_PAGE}${pin}/`]) {
    try {
      for (const m of (await page(u)).html.matchAll(/"link"\s*:\s*"(https?:[^"]+)"/g)) {
        try { const link = JSON.parse(`"${m[1]}"`); if (!/pinterest\./.test(site(link))) return link; } catch {}
      }
    } catch {}
  }
  return null;
}

async function hunt(pin, say, known) {  // pin -> its source page -> (the CC posts it lists) -> the mod files
  say({ state: "scan", text: "FINDING SOURCE" });
  const src = known || (await pinSource(pin));  // known: the source link Pinterest already shows on the pin
  if (!src) return { files: [], why: "PIN HAS NO LINK" };
  say({ state: "scan", text: `READING ${site(src).toUpperCase()}` });
  let targets = [], name = "";
  if (score(src) >= 2) targets = [src];
  else {
    const p = await page(src);
    name = clean(p.html.match(/<title[^>]*>([^<]*)/i)?.[1] || "");
    targets = leads(p.url, p.html).filter((l) => l.score >= 2).map((l) => l.url);
    if (!targets.length) {  // a list of CC posts: read each one for its download links
      const posts = [...links(p.url, p.html)].filter(([u, t]) => u !== p.url && (POSTS.test(u) || score(u, t))).map(([u]) => u).slice(0, 24);
      let read = 0;
      await pool(posts, 4, async (u) => {
        try { const q = await page(u); targets.push(...leads(q.url, q.html).filter((l) => l.score >= 2).map((l) => l.url)); } catch {}
        say({ state: "scan", text: `READING POSTS ${++read}/${posts.length}` });
      });
    }
  }
  targets = [...new Set(targets)].slice(0, 40);
  const files = [];
  let done = 0;
  await pool(targets, 4, async (u) => {
    try {
      const f = await getFile(u);
      if (f && !files.some((x) => x.name === f.name && x.data.length === f.data.length)) files.push(f);
    } catch {}
    say({ state: "files", text: `GOING TO FILES ${++done}/${targets.length}`, count: files.length });
  });
  return { files, src, name: name || `Pin ${pin}`, why: files.length ? "" : targets.length ? "FILES ARE LOCKED" : "NO DOWNLOAD LINKS" };
}

const CRC = Array.from({ length: 256 }, (_, n) => { for (let k = 0; k < 8; k++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1; return n >>> 0; });
const crc32 = (b) => { let c = -1; for (const x of b) c = CRC[(c ^ x) & 255] ^ (c >>> 8); return ~c >>> 0; };

function zip(files) {  // [{name, data}] -> one .zip Blob; stored as is, mod files are compressed already
  const parts = [], dir = [], used = new Set(), enc = new TextEncoder();
  let offset = 0;
  for (const f of files) {
    let name = f.name;
    for (let i = 2; used.has(name.toLowerCase()); i++) name = f.name.replace(/(\.\w+)?$/, ` (${i})$1`);
    used.add(name.toLowerCase());
    const n = enc.encode(name), crc = crc32(f.data), size = f.data.length;
    const head = new DataView(new ArrayBuffer(30)), entry = new DataView(new ArrayBuffer(46));
    [[0, 0x04034b50, 4], [4, 20, 2], [6, 0x800, 2], [12, 33, 2], [14, crc, 4], [18, size, 4], [22, size, 4], [26, n.length, 2]]
      .forEach(([at, v, len]) => (len === 4 ? head.setUint32(at, v, true) : head.setUint16(at, v, true)));
    [[0, 0x02014b50, 4], [4, 20, 2], [6, 20, 2], [8, 0x800, 2], [14, 33, 2], [16, crc, 4], [20, size, 4], [24, size, 4], [28, n.length, 2], [42, offset, 4]]
      .forEach(([at, v, len]) => (len === 4 ? entry.setUint32(at, v, true) : entry.setUint16(at, v, true)));
    parts.push(head, n, f.data);
    dir.push(entry, n);
    offset += 30 + n.length + size;
  }
  const end = new DataView(new ArrayBuffer(22)), dirSize = dir.reduce((s, p) => s + p.byteLength, 0);
  [[0, 0x06054b50, 4], [8, files.length, 2], [10, files.length, 2], [12, dirSize, 4], [16, offset, 4]]
    .forEach(([at, v, len]) => (len === 4 ? end.setUint32(at, v, true) : end.setUint16(at, v, true)));
  return new Blob([...parts, ...dir, end], { type: "application/zip" });
}
