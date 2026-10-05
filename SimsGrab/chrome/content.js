// SimsGrab on Pinterest: a GRAB MODS button on every pin (shown on hover, like Save) and one on the pin page.
// Resting on a pin or clicking the button scans its source in the background; then GET ZIP gives one zip of all mod files.
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
  b.querySelector("small").textContent = p.state === "files" ? `${p.count} FOUND` : p.state === "none" && p.src ? "OPEN SOURCE ↗" : "";
}

const update = (pin) => document.querySelectorAll(`.sg-badge[data-pin="${pin}"]`).forEach((b) => paint(b, known.get(pin)));

function sourceShown(pin) {  // the source link Pinterest prints on the pin card, if it does
  const host = document.querySelector(`.sg-pin[data-pin="${pin}"]`)?.parentElement;
  if (!host?.matches('[data-grid-item], [data-test-id="pin"]')) return null;
  return [...host.querySelectorAll('a[href^="http"]')].map((a) => a.href).find(offSite) || null;
}

function scan(pin) {
  if (known.has(pin)) return;
  known.set(pin, { state: "scan", text: "SCANNING..." });
  update(pin);
  chrome.runtime.sendMessage({ type: "hunt", pin, src: sourceShown(pin) });
}

function press(pin) {
  const p = known.get(pin);
  if (!p) scan(pin);
  else if (p.state === "ready") chrome.runtime.sendMessage({ type: "zip", pin });
  else if (p.state === "none" && p.src) chrome.runtime.sendMessage({ type: "open", url: p.src });
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
  if (m.type !== "progress") return;
  known.set(m.pin, m);
  update(m.pin);
});

sweep();
setInterval(sweep, 700);
