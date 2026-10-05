// Routes messages between the Pinterest tab, the hidden offscreen page that does the work, and Chrome's downloads.
let made = null;
const offscreen = () => (made ??= chrome.offscreen.createDocument({
  url: "offscreen.html", reasons: ["BLOBS"], justification: "Fetch mod files and zip them",
}).catch(() => {}));  // already open after a worker restart: fine

chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.target === "offscreen") return;
  if (msg.type === "hunt" || msg.type === "zip") {
    offscreen().then(() => chrome.runtime.sendMessage({ ...msg, target: "offscreen", tab: sender.tab.id }).catch(() => {}));
  } else if (msg.type === "progress") chrome.tabs.sendMessage(msg.tab, msg).catch(() => {});
  else if (msg.type === "download") chrome.downloads.download({ url: msg.url, filename: msg.filename, conflictAction: "uniquify" });
  else if (msg.type === "open") chrome.tabs.create({ url: msg.url, active: false });
});
