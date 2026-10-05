// Hidden page behind the Pinterest buttons: a queue of pins, scanned two at a time. Pins you clicked go first and save
// themselves when done: straight into Mods through the SimsGrab app if it's open, otherwise into Downloads.
const APP = "http://127.0.0.1:47323/install";  // the desktop app's door to the Mods folder
const MAX = 2;
const jobs = new Map();  // pin -> { tab, src, want, tries, last, result }
const waiting = [];      // pins in line
let running = 0, lastSaved = "";
const send = (msg) => chrome.runtime.sendMessage(msg).catch(() => {});
const plural = (n) => `${n} FILE${n > 1 ? "S" : ""}`;
const agent = async (url) => ({ ...(await chrome.runtime.sendMessage({ type: "agent", url })), drop: (id) => send({ type: "drop", id }) });

function tell(pin, progress) {
  const job = jobs.get(pin);
  job.last = { ...progress, want: job.want };
  send({ type: "progress", tab: job.tab, pin, ...job.last });
}

function line() {  // the queue counter, for every tab that has pins in it
  const all = [...jobs.values()], auto = all.filter((j) => j.want && !j.result).length;
  for (const tab of new Set(all.map((j) => j.tab))) send({ type: "queue", tab, working: running, waiting: waiting.length, auto, saved: lastSaved });
}

function pump() {
  while (running < MAX && waiting.length) work(waiting.shift());
  waiting.forEach((pin, i) => tell(pin, { state: "queued", text: `QUEUED · #${i + 1}` }));
  line();
}

async function work(pin) {
  running++;
  const job = jobs.get(pin);
  try {
    const r = (job.result = await hunt(pin, (p) => tell(pin, p), job.src, agent));
    const n = r.files.length;
    if (n && job.want) await save(pin);
    else if (n) tell(pin, { state: "ready", text: `GET ZIP · ${plural(n)}`, note: r.saved ? `+${r.saved} IN DOWNLOADS` : "" });
    else if (r.saved) tell(pin, { state: "none", text: `${plural(r.saved)} IN DOWNLOADS` });
    else tell(pin, { state: "none", text: r.why, src: r.src });
  } catch {  // don't give up on a hiccup: back in line a bit later, twice
    job.result = null;
    if ((job.tries = (job.tries || 0) + 1) <= 2) {
      tell(pin, { state: "queued", text: "HICCUP · RETRYING SOON" });
      setTimeout(() => { waiting.push(pin); pump(); }, 20000 * job.tries);
    } else tell(pin, { state: "none", text: "SCAN FAILED" });
  } finally {
    running--;
    pump();
  }
}

async function save(pin) {
  const job = jobs.get(pin), { files, name } = job.result, blob = zip(files);
  job.want = false;
  tell(pin, { state: "scan", text: "MOVING TO MODS..." });
  try {  // the app unpacks it into Mods
    const r = await fetch(`${APP}?name=${encodeURIComponent(name)}`, { method: "POST", body: blob, headers: { "X-SimsGrab": "1" } });
    if (!r.ok) throw new Error(r.status);
    const { files: n } = await r.json();
    lastSaved = `${name} → MODS`;
    tell(pin, { state: "ready", text: `IN MODS! · ${plural(n)}` });
  } catch {  // app not open: Downloads, and the app offers to move it later
    const url = URL.createObjectURL(blob);
    send({ type: "download", url, filename: `${name}.zip` });
    setTimeout(() => URL.revokeObjectURL(url), 120000);
    lastSaved = `${name}.zip → DOWNLOADS`;
    tell(pin, { state: "ready", text: `SAVED! · ${plural(files.length)}`, note: "IN DOWNLOADS · OPEN THE APP FOR MODS" });
  }
  line();
}

chrome.runtime.onMessage.addListener(({ target, type, pin, tab, src, want }) => {
  if (target !== "offscreen") return;
  const job = jobs.get(pin);
  if (job) job.tab = tab;
  if (type === "hunt" && !job) {
    jobs.set(pin, { tab, src, want });
    want ? waiting.unshift(pin) : waiting.push(pin);
    pump();
  } else if (type === "hunt") tell(pin, job.last);
  else if (type === "zip" && job?.result?.files.length) save(pin);
  else if (type === "want" && job) {  // clicked while it's still busy: it will save itself when done
    if (job.result?.files.length) return save(pin);
    job.want = true;
    const i = waiting.indexOf(pin);
    if (i > 0) { waiting.splice(i, 1); waiting.unshift(pin); }  // clicked pins jump the line
    tell(pin, job.last);
    pump();
  }
});
