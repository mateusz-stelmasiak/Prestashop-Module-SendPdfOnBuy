// Hidden page behind hover-to-zip: scans a pin, fetches its files and builds the zip. One job per pin, kept for repeat hovers.
const jobs = new Map();  // pin -> { tab, last progress, result }

function tell(pin, progress) {
  const job = jobs.get(pin);
  job.last = progress;
  chrome.runtime.sendMessage({ type: "progress", tab: job.tab, pin, ...progress }).catch(() => {});
}

chrome.runtime.onMessage.addListener(({ target, type, pin, tab }) => {
  if (target !== "offscreen") return;
  const job = jobs.get(pin);
  if (type === "hunt" && job) { job.tab = tab; tell(pin, job.last); }  // seen it already: just say where it is
  else if (type === "hunt") {
    jobs.set(pin, { tab });
    tell(pin, { state: "scan", text: "SCANNING..." });
    hunt(pin, (p) => tell(pin, p)).then((r) => {
      jobs.get(pin).result = r;
      const n = r.files.length;
      tell(pin, n ? { state: "ready", text: `GET ZIP · ${n} FILE${n > 1 ? "S" : ""}` } : { state: "none", text: r.why, src: r.src });
    }, () => { tell(pin, { state: "none", text: "SCAN FAILED" }); jobs.delete(pin); });
  } else if (type === "zip" && job?.result?.files.length) {
    job.tab = tab;
    const url = URL.createObjectURL(zip(job.result.files));
    chrome.runtime.sendMessage({ type: "download", url, filename: `${job.result.name}.zip` }).catch(() => {});
    setTimeout(() => URL.revokeObjectURL(url), 120000);
    const n = job.result.files.length;
    tell(pin, { state: "ready", text: `SAVED! · ${n} FILE${n > 1 ? "S" : ""}` });
  }
});
