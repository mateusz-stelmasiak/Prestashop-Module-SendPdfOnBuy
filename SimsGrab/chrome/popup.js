// SimsGrab for Chrome: scan the open page (or a Pinterest pin's source page) for mod downloads and grab them.
const FILE = /\.(zip|rar|7z|package|ts4script)$/i;
const JUNK = /\.(jpe?g|png|gif|webp|svg|css|js|ico|mp4|woff2?)$/i;
const HOSTS = ["simfileshare.net/download", "mediafire.com/file", "mediafire.com/?", "drive.google.com", "dropbox.com/s",
               "patreon.com/file", "patreon.com/media-u", "getfile.php", "curseforge.com/api/v1/mods"];
const $ = (s) => document.querySelector(s);
const site = (u) => new URL(u).hostname.replace(/^www\./, "");
const path = (u) => { const p = new URL(u).pathname; try { return decodeURIComponent(p); } catch { return p; } };

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

function leads(base, html, anchors = []) {  // every link on a page worth grabbing, best first
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
    if (!/^https?:/.test(u)) continue;
    const s = score(u, label), old = found.get(u);
    if (s && !old) found.set(u, { url: u, text: label, score: s });
    else if (old && label && !old.text) Object.assign(old, { text: label, score: Math.max(old.score, s) });
  }
  return [...found.values()].sort((a, b) => b.score - a.score);
}

function route(u) {  // share links -> direct downloads where the host allows it
  const d = u.match(/drive\.google\.com\/.*?(?:\/d\/|[?&]id=)([\w-]{20,})/);
  if (d) return `https://drive.usercontent.google.com/download?id=${d[1]}&export=download&confirm=t`;
  if (u.includes("dropbox.com/")) return u.includes("dl=") ? u.replace("dl=0", "dl=1") : `${u}${u.includes("?") ? "&" : "?"}dl=1`;
  return u;
}

async function resolve(url, depth = 0) {  // the real file behind a link, following host pages two deep; null if none
  const ctl = new AbortController(), r = await fetch(route(url), { signal: ctl.signal, credentials: "include" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  if (!/html|json|text\/plain/.test(r.headers.get("content-type") || "")) { ctl.abort(); return r.url; }
  const next = depth < 2 && leads(r.url, await r.text()).find((l) => l.score >= 2 && l.url !== url);
  return next ? resolve(next.url, depth + 1) : null;
}

async function scan(tab) {  // the live page as Chrome shows it, so logins and scripts work
  const [{ result: page }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => ({ url: location.href, html: document.documentElement.outerHTML,
                   anchors: [...document.links].map((a) => [a.href, a.innerText.trim().slice(0, 90)]) }),
  });
  if (!/pinterest\.|pin\.it\//.test(page.url) || !/\/pin\/\d/.test(page.url)) return { where: site(page.url), links: leads(page.url, page.html, page.anchors) };
  const src = [...page.html.matchAll(/"link"\s*:\s*"(https?:[^"]+)"/g)]
    .map((m) => { try { return JSON.parse(`"${m[1]}"`); } catch { return ""; } })
    .find((u) => u && !/pinterest\./.test(site(u)));
  if (!src) return { where: "pin has no source link", links: [] };
  const where = `pin → ${site(src)}`;
  $("#where").textContent = `${where}...`;
  if (score(src) >= 2) return { where, links: [{ url: src, text: "The pin's download link", score: score(src) }] };
  const r = await fetch(src, { credentials: "include" });
  return { where, links: leads(r.url, await r.text()) };
}

async function grab(l, li) {
  const b = li.querySelector("button");
  if (b.disabled) return;
  b.disabled = true; b.textContent = "...";
  try {
    const file = l.score === 3 ? route(l.url) : await resolve(l.url);
    if (file) { await chrome.downloads.download({ url: file, conflictAction: "uniquify" }); li.classList.add("done"); b.textContent = "✓"; }
    else { chrome.tabs.create({ url: l.url, active: false }); li.classList.add("open"); b.textContent = "OPEN"; b.title = "No direct file, opened it in a tab"; }
  } catch (e) { b.textContent = "✗"; b.title = e.message; }
}

function show(where, links) {
  links = links.slice(0, 60);
  $("#where").textContent = $("#where").title = where;
  $("#empty").hidden = links.length > 0;
  $("#list").replaceChildren(...links.map((l) => {
    const li = (l.li = document.createElement("li"));
    li.className = `s${l.score}`;
    li.innerHTML = "<em></em><div><b></b><small></small></div><button>GET</button>";
    li.querySelector("em").textContent = l.score === 3 ? "FILE" : /^[\d.:]+$/.test(site(l.url)) ? "LINK" : site(l.url).split(".").slice(-2)[0].toUpperCase();
    li.querySelector("b").textContent = l.text || path(l.url).split("/").filter(Boolean).pop() || site(l.url);
    li.querySelector("small").textContent = l.url.replace(/^https?:\/\/(www\.)?/, "");
    li.querySelector("button").onclick = () => grab(l, li);
    return li;
  }));
  const best = links.filter((l) => l.score >= 2);
  $("#all").disabled = !best.length;
  $("#all").textContent = `GRAB ALL ${best.length}`;
  $("#all").onclick = async () => { $("#all").disabled = true; for (const l of best) await grab(l, l.li); };
}

async function main(tab) {
  try { const { where, links } = await scan(tab); show(where, links); }
  catch (e) { show(`can't scan this page: ${e.message}`, []); }
}

chrome.tabs.query({ active: true, currentWindow: true }).then(([tab]) => tab && !tab.url?.startsWith(location.origin) && main(tab));
