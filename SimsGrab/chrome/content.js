// On Pinterest: hover a pin and SimsGrab scans it in the background, showing a badge. Click the badge for one zip of all its files.
const badges = new Map();  // pin id -> badge
let timer;

function pinAt(el) {
  if (!el.closest || el.closest(".sg-badge")) return null;
  const a = el.closest('a[href*="/pin/"]');
  let id = a?.href.match(/\/pin\/(\d+)/)?.[1], host = a?.parentElement;
  if (!id && el.tagName === "IMG" && el.width > 200) {  // the big picture on a pin's own page
    id = location.pathname.match(/\/pin\/(\d+)/)?.[1];
    host = el.parentElement;
  }
  return id && host ? { id, host } : null;
}

function badge({ id, host }) {
  const old = badges.get(id);
  if (old?.isConnected) return;
  const b = document.createElement("div");
  b.className = "sg-badge";
  b.dataset.state = "scan";
  b.innerHTML = "<i></i><span>SCANNING...</span><small></small>";
  b.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (b.dataset.state === "ready") chrome.runtime.sendMessage({ type: "zip", pin: id });
    else if (b.dataset.src) chrome.runtime.sendMessage({ type: "open", url: b.dataset.src });
  }, true);
  if (getComputedStyle(host).position === "static") host.style.position = "relative";
  host.append(b);
  badges.set(id, b);
  chrome.runtime.sendMessage({ type: "hunt", pin: id });
}

addEventListener("mouseover", (e) => {
  const spot = pinAt(e.target);
  clearTimeout(timer);
  if (spot) timer = setTimeout(() => badge(spot), 350);  // a short pause, so scrolling past pins doesn't scan them all
}, true);

chrome.runtime.onMessage.addListener((m) => {
  const b = m.type === "progress" && badges.get(m.pin);
  if (!b) return;
  b.dataset.state = m.state;
  b.querySelector("span").textContent = m.text;
  b.querySelector("small").textContent = m.state === "files" ? `${m.count} FOUND` : m.state === "none" && m.src ? "OPEN SOURCE ↗" : "";
  if (m.src) b.dataset.src = m.src;
});
