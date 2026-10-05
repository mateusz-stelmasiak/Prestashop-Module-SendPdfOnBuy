// SimsGrab toolbar popup: scan the open page (or a Pinterest pin's source page) for mod downloads and grab them.
const $ = (s) => document.querySelector(s);  // the shared scanning code is in scan.js

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
