// SimsGrab on Pinterest: a GRAB MODS button on every pin (shown on hover, like Save) and one on the pin page.
// Resting on a pin queues a scan of its source; clicking the button queues it first and it saves itself when done
// (into Mods through the SimsGrab app, or Downloads). GET ZIP saves a finished one.
const PIN = /\/pin\/(?:[^/]*--)?(\d+)/;
const known = new Map();  // pin -> its last progress, so every button for that pin shows the same thing
let timer, shown;

const offSite = (u) => { try { return !/(^|\.)pinterest\.|(^|\.)pin\.it$/.test(new URL(u).hostname); } catch { return false; } };
const cardOf = (a) => a.closest('[data-grid-item], [data-test-id="pin"]') || a.parentElement;

function button(pin, kind) {
  const b = document.createElement("div");
  b.className = `sg-badge ${kind}`;
  b.dataset.pin = pin;
  b.title = "SimsGrab: get every mod from this pin in one zip";
  b.innerHTML = "<i></i><span></span><small></small>";
  for (const type of ["pointerdown", "mousedown", "mouseup", "click"]) {  // keep Pinterest from opening the pin
    b.addEventListener(type, (e) => { e.preventDefault(); e.stopPropagation(); if (type === "click") press(pin); }, true);
  }
  paint(b, known.get(pin));
  return b;
}

function paint(b, p = { state: "idle", text: "GRAB MODS" }) {
  b.dataset.state = p.state;
  b.querySelector("span").textContent = b.classList.contains("sg-dock") && p.state === "idle" ? "SIMSGRAB · GRAB MODS" : p.text;
  const busy = !["ready", "none", "idle"].includes(p.state);
  b.querySelector("small").textContent = p.state === "none" && p.src ? "OPEN SOURCE ↗"
    : [p.state === "files" && `${p.count} FOUND`, busy && p.want && "AUTO-SAVE ON", p.note].filter(Boolean).join(" · ");
}

const update = (pin) => document.querySelectorAll(`.sg-badge[data-pin="${pin}"]`).forEach((b) => paint(b, known.get(pin)));

function sourceShown(pin) {  // the source link Pinterest prints on the pin card, if it does
  const host = document.querySelector(`.sg-pin[data-pin="${pin}"]`)?.parentElement;
  if (!host?.matches('[data-grid-item], [data-test-id="pin"]')) return null;
  return [...host.querySelectorAll('a[href^="http"]')].map((a) => a.href).find(offSite) || null;
}

function scan(pin, want = false) {
  if (known.has(pin)) return;
  known.set(pin, { state: "queued", text: "QUEUED", want });
  update(pin);
  chrome.runtime.sendMessage({ type: "hunt", pin, src: sourceShown(pin), want });
}

function press(pin) {
  const p = known.get(pin);
  if (!p) scan(pin, true);  // clicked: first in line, and it saves itself when done
  else if (p.state === "ready") chrome.runtime.sendMessage({ type: "zip", pin });
  else if (p.state === "none") p.src && chrome.runtime.sendMessage({ type: "open", url: p.src });
  else chrome.runtime.sendMessage({ type: "want", pin });  // still busy: save it when done
}

function queueBar(q) {  // the little counter: what's working, waiting and going to save itself
  let bar = document.querySelector(".sg-queue");
  if (!bar) {
    bar = document.createElement("div");
    bar.className = "sg-queue";
    bar.innerHTML = "<i></i><span></span><small></small>";
    document.body.append(bar);
  }
  bar.hidden = !(q.working || q.waiting || q.saved);
  bar.classList.toggle("sg-up", !!document.querySelector(".sg-dock"));
  bar.querySelector("span").textContent = q.working || q.waiting
    ? [`QUEUE: ${q.working} WORKING`, q.waiting && `${q.waiting} WAITING`, q.auto && `${q.auto} AUTO-SAVE`].filter(Boolean).join(" · ") : "QUEUE DONE";
  bar.querySelector("small").textContent = q.saved ? `LAST: ${q.saved}` : "";
}

function sweep() {  // buttons for pins Pinterest loads while you scroll, and for the pin page you're on
  for (const a of document.querySelectorAll('a[href*="/pin/"]')) {
    const pin = a.href.match(PIN)?.[1], host = pin && a.querySelector("img") && cardOf(a);
    if (!host || host.querySelector(":scope > .sg-badge")) continue;
    if (getComputedStyle(host).position === "static") host.style.position = "relative";
    host.append(button(pin, "sg-pin"));
  }
  const pin = location.pathname.match(PIN)?.[1], dock = document.querySelector(".sg-dock");
  if (dock?.dataset.pin === pin) return;
  dock?.remove();
  if (pin) { document.body.append(button(pin, "sg-dock")); scan(pin); }
}

addEventListener("mouseover", (e) => {  // resting on a pin starts its scan
  clearTimeout(timer);
  const host = e.target.closest?.('[data-grid-item], [data-test-id="pin"]') || e.target.closest?.('a[href*="/pin/"]')?.parentElement;
  const b = host?.querySelector(":scope > .sg-pin");
  if (b !== shown) { shown?.classList.remove("sg-show"); b?.classList.add("sg-show"); shown = b; }  // show it, like Save
  if (b) timer = setTimeout(() => scan(b.dataset.pin), 350);
}, true);

chrome.runtime.onMessage.addListener((m) => {
  if (m.type === "queue") return queueBar(m);
  if (m.type !== "progress") return;
  known.set(m.pin, m);
  update(m.pin);
});

sweep();
setInterval(sweep, 700);
