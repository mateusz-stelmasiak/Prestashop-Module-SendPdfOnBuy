// Routes messages between the Pinterest tab, the hidden offscreen page that does the work, and Chrome's downloads.
// Also runs the browser agent: when a quick look can't find the file, it opens the page in a minimized window,
// waits out countdowns, presses Download and catches the file, the way a person would.
importScripts("scan.js");
let made = null, agents = Promise.resolve();
const offscreen = () => (made ??= chrome.offscreen.createDocument({
  url: "offscreen.html", reasons: ["BLOBS"], justification: "Fetch mod files and zip them",
}).catch(() => {}));  // already open after a worker restart: fine

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.target === "offscreen") return;
  if (["hunt", "zip", "want"].includes(msg.type)) {
    offscreen().then(() => chrome.runtime.sendMessage({ ...msg, target: "offscreen", tab: sender.tab.id }).catch(() => {}));
  } else if (msg.type === "progress" || msg.type === "queue") chrome.tabs.sendMessage(msg.tab, msg).catch(() => {});
  else if (msg.type === "download") chrome.downloads.download({ url: msg.url, filename: msg.filename, conflictAction: "uniquify" });
  else if (msg.type === "open") chrome.tabs.create({ url: msg.url, active: false });
  else if (msg.type === "drop") drop(msg.id);
  else if (msg.type === "agent") {
    const job = agents.then(() => agent(msg.url));  // one agent at a time, so a download that starts is surely its own
    agents = job.catch(() => {});
    job.then(reply, () => reply(null));
    return true;
  }
});

async function agent(url) {
  const win = await chrome.windows.create({ url, focused: false, state: "minimized" });
  const tabId = win.tabs[0].id, hosts = new Set([site(url)]), urls = new Set(), downloads = [];
  const ours = (u) => { try { return hosts.has(site(u)); } catch { return false; } };
  const caught = (d) => !d.byExtensionId && (ours(d.referrer) || ours(d.url)) && downloads.push({ id: d.id, url: d.finalUrl || d.url });
  chrome.downloads.onCreated.addListener(caught);
  try {
    for (let s = 2; s <= 40 && !downloads.length; s += 2) {
      await sleep(2000);
      const [res] = await chrome.scripting.executeScript({ target: { tabId }, func: look, args: [s >= 8 && s % 6 === 2] }).catch(() => []);
      const p = res?.result;
      if (!p) continue;
      hosts.add(site(p.url));
      for (const l of leads(p.url, p.html, p.anchors)) if (l.score >= 2 && l.url !== url) urls.add(l.url);
      if ([...urls].some((u) => score(u) === 3)) break;  // a direct file link showed up
    }
    if (downloads.length) await sleep(1500);  // let Chrome settle on the file's final address
    for (const d of downloads) d.url = (await chrome.downloads.search({ id: d.id }))[0]?.finalUrl || d.url;
  } finally {
    chrome.downloads.onCreated.removeListener(caught);
    chrome.windows.remove(win.id).catch(() => {});  // its pop-up tabs go with it
  }
  return { urls: [...urls].slice(0, 6), downloads };
}

function look(press) {  // runs inside the agent's page: report its links; after a while, press the Download button once
  if (press) {
    [...document.querySelectorAll("a, button, input[type=submit], [role=button]")].find((e) => e.offsetParent &&
      /^\s*(free\s+)?download(\s+(now|file|here))?\s*!?\s*$|click here to download|get (the )?file/i.test(e.innerText || e.value || ""))?.click();
  }
  return { url: location.href, html: document.documentElement.outerHTML.slice(0, 3e6),
           anchors: [...document.querySelectorAll("a[href]")].map((a) => [a.href, (a.innerText || "").trim().slice(0, 90)]) };
}

async function drop(id) {  // we got the file into the zip ourselves: remove Chrome's own copy
  const [d] = await chrome.downloads.search({ id });
  if (!d) return;
  await (d.state === "complete" ? chrome.downloads.removeFile(id) : chrome.downloads.cancel(id)).catch(() => {});
  chrome.downloads.erase({ id });
}
