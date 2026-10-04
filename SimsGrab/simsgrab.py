"""SimsGrab: paste a Pinterest pin, get the Sims mod behind it as a zip.

Agents follow the trail from the pin to its source page and on through the usual
CC hosts (Tumblr, SimFileShare, MediaFire, Google Drive, Dropbox, Patreon, ...)
until a real mod file turns up. Standard library only.
"""
import base64, heapq, html, itertools, json, os, queue, re, sys, threading, webbrowser, zipfile
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

OUT = Path.home() / "Downloads" / "SimsGrab"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
PIN_API = "https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids="
KINDS = {b"PK\x03\x04": ".zip", b"Rar!": ".rar", b"7z\xbc\xaf": ".7z", b"DBPF": ".package"}  # magic bytes
EXTS = (*KINDS.values(), ".ts4script")
HOSTS = ("simfileshare.net/download", "mediafire.com/file", "mediafire.com/?", "drive.google.com", "dropbox.com/s",
         "patreon.com/posts", "patreon.com/file", "patreon.com/media-u", "getfile.php", "curseforge.com/sims4/")
JUNK = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".mp4")
MAX_PAGES, MAX_DEPTH = 30, 3
web = build_opener(HTTPCookieProcessor(CookieJar()))


class Fail(Exception):
    pass


def fetch(url):
    """GET url -> (response, first 4 bytes). The magic bytes tell mod files apart from pages."""
    r = web.open(Request(url, headers={"User-Agent": UA}), timeout=30)
    return r, r.read(4)


def agent(url):
    """Name of the agent handling url: the site's name, e.g. 'mediafire'."""
    parts = urlparse(url).netloc.split(".")
    return parts[-2] if len(parts) > 1 else "web"


def pin_source(url, log):
    """Pinterest agent: pin -> the page it was saved from."""
    if "pin.it/" in url:
        url = fetch(url)[0].geturl()
    pid = re.search(r"/pin/(?:[^/]*--)?(\d+)", url)
    if not pid:
        raise Fail("That Pinterest link isn't a pin")
    for src in (PIN_API + pid[1], f"https://www.pinterest.com/pin/{pid[1]}/"):
        try:
            r, head = fetch(src)
            text = (head + r.read()).decode("utf-8", "replace")
        except OSError:
            continue
        for link in re.findall(r'"link"\s*:\s*"(https?:[^"]+)"', text):
            link = json.loads(f'"{link}"')
            if "pinterest." not in urlparse(link).netloc:
                log("pinterest", f"pin {pid[1]} -> {link}")
                return link
    raise Fail("This pin has no source link")


def route(url):
    """Turn share links into direct ones where the host allows it."""
    if m := re.search(r"drive\.google\.com/.*?(?:/d/|[?&]id=)([\w-]{20,})", url):
        return f"https://drive.usercontent.google.com/download?id={m[1]}&export=download&confirm=t"
    if "dropbox.com/" in url:
        return re.sub(r"dl=0", "dl=1", url) if "dl=" in url else url + ("&" if "?" in url else "?") + "dl=1"
    if m := re.search(r"patreon\.com/posts/(?:[^/?]*-)?(\d+)", url):
        return f"https://www.patreon.com/api/posts/{m[1]}?include=attachments,attachments_media"
    return url


def unwrap(url):
    """Strip redirect wrappers like t.umblr.com/redirect?z=<real url>."""
    for v in parse_qs(urlparse(url).query).values():
        if v[0].startswith("http"):
            return unwrap(v[0])
    return url


def leads(base, text):
    """Links on a page worth following, as (score, url): 3 = file, 2 = file host, 1 = 'download'."""
    text = html.unescape(text.replace("\\/", "/").replace("\\u002F", "/").replace("\\u0026", "&"))
    found = re.findall(r"https?://[^\s\"'<>\\)]+", text)
    found += [urljoin(base, h) for h in re.findall(r"href=[\"']([^\"'#]+)", text)]
    for b64 in re.findall(r'data-scrambled-url="([^"]+)"', text):  # MediaFire hides its button link
        try:
            found.append(base64.b64decode(b64).decode())
        except ValueError:
            pass
    out = {}
    for u in map(unwrap, found):
        path = unquote(urlparse(u).path).lower()
        s = 3 if path.endswith(EXTS) else 2 if any(h in u for h in HOSTS) else 1 if "download" in u.lower() else 0
        if s and not path.endswith(JUNK):
            out.setdefault(u, s)
    return [(s, u) for u, s in out.items()]


def filename(r):
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?\"?([^\";]+)", cd, re.I) or re.search(r'filename="?([^";]+)', cd, re.I)
    name = unquote(m[1] if m else Path(urlparse(r.geturl()).path).name)
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .") or "mod"


def save(data, name):
    """Store a mod in OUT as a zip: zips are kept as they are, anything else gets zipped."""
    ext = ".ts4script" if name.lower().endswith(".ts4script") else KINDS[data[:4]]
    stem = Path(name).stem if Path(name).suffix.lower() in EXTS else name
    OUT.mkdir(parents=True, exist_ok=True)
    path, i = OUT / f"{stem}.zip", 1
    while path.exists():
        i += 1
        path = OUT / f"{stem} ({i}).zip"
    if ext == ".zip":
        path.write_bytes(data)
    else:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(stem + ext, data)
    return path


def grab(url, log=lambda agent, msg: None):
    """Follow the trail from url to a mod file. Returns the saved zip's path or raises Fail."""
    url = url.strip() if url.strip().startswith("http") else "https://" + url.strip()
    if re.search(r"pinterest\.|pin\.it/", url):
        url = pin_source(url, log)
    tick = itertools.count()
    todo, seen = [(0, 0, 0, url)], set()
    while todo and len(seen) < MAX_PAGES:
        _, depth, _, u = heapq.heappop(todo)
        if u in seen:
            continue
        seen.add(u)
        log(agent(u), u)
        try:
            r, head = fetch(route(u))
            if head in KINDS:
                log("download", filename(r))
                return save(head + r.read(), filename(r))
            text = (head + r.read(5_000_000)).decode("utf-8", "replace")
        except OSError as e:
            log(agent(u), f"x {e}")
            continue
        if depth < MAX_DEPTH:
            found = [(s, l) for s, l in leads(r.geturl(), text) if l not in seen and (s > 1 or depth == 0)]
            log(agent(u), f"{len(found)} leads")
            for s, l in found:
                heapq.heappush(todo, (-s, depth + 1, next(tick), l))
    raise Fail(f"No mod file found ({len(seen)} pages checked)")


def ui():
    import tkinter as tk

    if os.name == "nt":  # crisp text on high-DPI screens
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    PAPER, INK, MUTED, GREEN, RED = "#EFECE4", "#151515", "#8C887E", "#22A94F", "#D8412F"
    events = queue.Queue()
    root = tk.Tk()
    root.title("SimsGrab")
    root.configure(bg=PAPER, padx=28, pady=24)
    root.minsize(560, 420)
    icon = tk.PhotoImage(width=32, height=32)  # plumbob
    for y in range(2, 30):
        w = round(9 * (1 - abs(y - 16) / 14))
        icon.put(GREEN, to=(16 - w, y, 16 + w + 1, y + 1))
    root.iconphoto(True, icon)

    tk.Label(root, text="SIMSGRAB", font=("Segoe UI Black", 24, "bold"), bg=PAPER, fg=INK).pack(anchor="w")
    tk.Label(root, text="Paste a Pinterest pin. Get the mod as a zip.", font=("Segoe UI", 10),
             bg=PAPER, fg=MUTED).pack(anchor="w")

    box = tk.Frame(root, bg=INK, padx=2, pady=2)
    box.pack(fill="x", pady=(18, 0))
    entry = tk.Entry(box, font=("Consolas", 12), bg="#FFFFFF", fg=INK, relief="flat", insertbackground=INK)
    entry.pack(side="left", fill="both", expand=True, ipadx=10, ipady=9)
    flat = dict(relief="flat", bd=0, highlightthickness=0, cursor="hand2")
    go = tk.Button(box, text="GRAB", font=("Segoe UI Black", 11, "bold"), bg=GREEN, fg=INK, activebackground=INK,
                   activeforeground=GREEN, disabledforeground=MUTED, padx=24, **flat)
    go.pack(side="left", fill="y")

    tk.Label(root, text="AGENTS", font=("Segoe UI Semibold", 8), bg=PAPER, fg=MUTED).pack(anchor="w", pady=(18, 4))
    log = tk.Text(root, font=("Consolas", 10), bg=PAPER, fg=INK, relief="flat", bd=0, highlightthickness=0,
                  width=72, height=12, wrap="none", state="disabled", cursor="arrow")
    log.pack(fill="both", expand=True)
    log.tag_config("agent", foreground=MUTED)
    log.tag_config("bad", foreground=RED)

    def open_folder():
        OUT.mkdir(parents=True, exist_ok=True)
        os.startfile(OUT) if os.name == "nt" else webbrowser.open(OUT.as_uri())

    bar = tk.Frame(root, bg=INK)
    bar.pack(fill="x", pady=(16, 0))
    status = tk.Label(bar, text="READY", font=("Segoe UI Semibold", 10), bg=INK, fg=PAPER, anchor="w", padx=14, pady=10)
    status.pack(side="left", fill="x", expand=True)
    folder = tk.Button(bar, text="OPEN FOLDER", font=("Segoe UI Semibold", 9), bg=INK, fg=PAPER, activebackground=PAPER,
                       activeforeground=INK, padx=14, command=open_folder, **flat)
    folder.pack(side="right", fill="y")

    def show(text, bg, fg=PAPER):
        bar.config(bg=bg)
        status.config(text=text, bg=bg, fg=fg)
        folder.config(bg=bg, fg=fg)

    def write(name, msg):
        log.config(state="normal")
        log.insert("end", f"{name:<14}", "agent")
        log.insert("end", msg + "\n", "bad" if msg.startswith("x ") else ())
        log.see("end")
        log.config(state="disabled")

    def work(url):
        try:
            events.put(("done", grab(url, lambda a, m: events.put(("log", a, m)))))
        except Exception as e:
            events.put(("fail", e))

    def start(*_):
        url = entry.get().strip()
        if not url or go["state"] == "disabled":
            return
        go.config(state="disabled")
        log.config(state="normal")
        log.delete("1.0", "end")
        log.config(state="disabled")
        show("WORKING ...", INK)
        threading.Thread(target=work, args=(url,), daemon=True).start()

    def poll():
        while not events.empty():
            kind, arg, *rest = events.get()
            if kind == "log":
                write(arg, *rest)
                continue
            go.config(state="normal")
            show(f"DONE    {arg.name}", GREEN, INK) if kind == "done" else show(f"FAILED    {arg}", RED)
        root.after(80, poll)

    def autopaste(_):
        try:
            clip = root.clipboard_get().strip()
        except tk.TclError:
            return
        if not entry.get() and re.match(r"https?://\S*(pinterest\.|pin\.it/)", clip):
            entry.insert(0, clip)

    go.config(command=start)
    go.bind("<Enter>", lambda _: go.config(bg=INK, fg=GREEN))
    go.bind("<Leave>", lambda _: go.config(bg=GREEN, fg=INK))
    entry.bind("<Return>", start)
    root.bind("<FocusIn>", autopaste)
    entry.focus_set()
    poll()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        ui()
    else:
        try:
            print(grab(sys.argv[1], lambda a, m: print(f"{a:<14}{m}")))
        except Fail as e:
            sys.exit(f"FAILED  {e}")
