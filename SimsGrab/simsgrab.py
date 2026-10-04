"""SimsGrab: paste a Pinterest pin or type a vibe, get Sims mods installed.

Agents follow the trail from a pin (or a web search) through the usual CC hosts
(Tumblr, SimFileShare, MediaFire, Google Drive, Dropbox, Patreon, ...) until a
real mod file turns up. An optional local model (Ollama) writes the searches and
picks which link to click. Standard library only.
"""
import base64, heapq, html, itertools, json, math, os, queue, random, re, sys, threading, webbrowser, zipfile
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

HOME = Path.home()
OUT = HOME / "Downloads" / "SimsGrab"
CONF = HOME / ".simsgrab.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
PIN_API = "https://widgets.pinterest.com/v3/pidgets/pins/info/?pin_ids="
SEARCH = "https://html.duckduckgo.com/html/?q="
OLLAMA = "http://localhost:11434"
KINDS = {b"PK\x03\x04": ".zip", b"Rar!": ".rar", b"7z\xbc\xaf": ".7z", b"DBPF": ".package"}  # magic bytes
EXTS = (*KINDS.values(), ".ts4script")
HOSTS = ("simfileshare.net/download", "mediafire.com/file", "mediafire.com/?", "drive.google.com", "dropbox.com/s",
         "patreon.com/posts", "patreon.com/file", "patreon.com/media-u", "getfile.php", "curseforge.com/sims4/")
JUNK = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".mp4")
CATEGORIES = ("hair", "clothes", "makeup", "furniture", "build", "gameplay", "poses")
MAX_PAGES, MAX_DEPTH = 30, 3
web = build_opener(HTTPCookieProcessor(CookieJar()))
local = build_opener(ProxyHandler({}))


class Fail(Exception):
    pass


def settings():
    docs = [HOME / "Documents", HOME / "OneDrive" / "Documents"]
    mods = next((p for p in (d / "Electronic Arts" / "The Sims 4" / "Mods" for d in docs) if p.exists()),
                docs[0] / "Electronic Arts" / "The Sims 4" / "Mods")
    try:
        return {"model": "", "mods": str(mods), **json.loads(CONF.read_text())}
    except (OSError, ValueError):
        return {"model": "", "mods": str(mods)}


def models():
    """Models installed in the local Ollama, or [] when it isn't running."""
    try:
        return [m["name"] for m in json.load(local.open(OLLAMA + "/api/tags", timeout=2))["models"]]
    except (OSError, ValueError, KeyError):
        return []


def ask(model, prompt):
    """One JSON answer from the local model."""
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json"}).encode()
    r = local.open(Request(OLLAMA + "/api/generate", body, {"Content-Type": "application/json"}), timeout=180)
    return json.loads(json.load(r)["response"])


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


def anchors(base, text):
    """(url, link text) for every <a> on a page: what a person would see and click."""
    out = {}
    for href, label in re.findall(r"<a\s[^>]*?href=[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", text, re.S | re.I):
        u = unwrap(urljoin(base, html.unescape(href)))
        if u.startswith("http") and not urlparse(u).path.lower().endswith(JUNK):
            out.setdefault(u, " ".join(html.unescape(re.sub(r"<[^>]+>", " ", label)).split())[:80])
    return list(out.items())[:80]


def pick(model, goal, links, log):
    """Let the model choose which links to click, like a person reading the page."""
    if not model or not links:
        return []
    menu = "\n".join(f"{i}. {t or '-'} | {u[:120]}" for i, (u, t) in enumerate(links))
    try:
        ans = ask(model, f"You are browsing the web for: {goal}.\nLinks on this page:\n{menu}\n\n"
                         'Which links most likely lead to the free file download? Answer JSON {"pick": [up to 3 '
                         "link numbers, best first]}, or an empty list if none fit.")
        picked = [links[i][0] for i in ans.get("pick", []) if isinstance(i, int) and 0 <= i < len(links)]
    except (OSError, ValueError, KeyError, AttributeError) as e:
        log("ai", f"x {e}")
        return []
    log("ai", f"clicks {len(picked)} of {len(links)} links")
    return picked


def filename(r):
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=(?:UTF-8'')?\"?([^\";]+)", cd, re.I) or re.search(r'filename="?([^";]+)', cd, re.I)
    return clean(unquote(m[1] if m else Path(urlparse(r.geturl()).path).name)) or "mod"


def clean(name):
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip(" .")


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


def install(path, mods, folder):
    """Unpack a grabbed zip into Mods/SimsGrab. Packages may sit deep, scripts only one folder down."""
    n = 0
    with zipfile.ZipFile(path) as z:
        for f in z.namelist():
            ext = Path(f).suffix.lower()
            if ext in (".package", ".ts4script"):
                out = Path(mods) / "SimsGrab" / (clean(folder) if ext == ".package" else "") / Path(f).name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(z.read(f))
                n += 1
    return n


def grab(url, log=lambda agent, msg: None, model="", goal="a Sims 4 mod", pages=MAX_PAGES):
    """Follow the trail from url to a mod file. Returns the saved zip's path or raises Fail."""
    url = url.strip() if url.strip().startswith("http") else "https://" + url.strip()
    if re.search(r"pinterest\.|pin\.it/", url):
        url = pin_source(url, log)
    tick = itertools.count()
    todo, seen = [(0, 0, 0, url)], set()
    while todo and len(seen) < pages:
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
            found = [(s, l) for s, l in leads(r.geturl(), text) if s > 1 or depth == 0]
            found += [(2.5, l) for l in pick(model, goal, anchors(r.geturl(), text), log)]
            found = [(s, l) for s, l in found if l not in seen]
            log(agent(u), f"{len(found)} leads")
            for s, l in found:
                heapq.heappush(todo, (-s, depth + 1, next(tick), l))
    raise Fail(f"No mod file found ({len(seen)} pages checked)")


def pack(words, cats, model, log):
    """Search the web for a themed set of mods. Returns (pack name, [zip paths])."""
    cats = cats or ["cc"]
    name, queries = (words or " ".join(cats)).title(), [f"sims 4 {c} cc {words} free download" for c in cats]
    if model:
        try:
            ans = ask(model, f"Plan a Sims 4 custom content pack. Categories: {', '.join(cats)}. Style: {words or 'any'}."
                             '\nAnswer JSON {"name": "short catchy pack name", "queries": [one web search query per '
                             "category, aimed at free CC downloads on Tumblr, SimFileShare or Patreon]}")
            name, queries = ans.get("name") or name, ans.get("queries") or queries
        except (OSError, ValueError, KeyError, AttributeError) as e:
            log("ai", f"x {e}")
    log("pack", f"{name}: {len(queries)} searches")
    got = []
    for q in queries[:8]:
        log("search", q)
        try:
            r, head = fetch(SEARCH + quote(q))
            results = [(u, t) for u, t in anchors(r.geturl(), (head + r.read()).decode("utf-8", "replace"))
                       if "duckduckgo." not in urlparse(u).netloc]
        except OSError as e:
            log("search", f"x {e}")
            continue
        for u in (pick(model, q, results, log) or [u for u, _ in results])[:2]:
            try:
                got.append(grab(u, log, model, q, pages=12))
                break
            except (Fail, OSError, ValueError) as e:
                log("agent", f"x {e}")
    if not got:
        raise Fail("No mods found for that pack")
    return name, got


def run(text, cats, cfg, log):
    """The one input line: a link grabs that mod, anything else builds a pack. Installs into Mods."""
    if re.match(r"\s*(https?://|pin\.it/|www\.)", text):
        name, paths = None, [grab(text, log, cfg["model"])]
    else:
        name, paths = pack(text.strip(), cats, cfg["model"], log)
    files = sum(install(p, cfg["mods"], name or p.stem) for p in paths)
    log("install", f"{files} files -> {Path(cfg['mods']) / 'SimsGrab'}")
    return f"{name}: {len(paths)} mods" if name else paths[0].name


def ui():
    import tkinter as tk
    from tkinter import filedialog

    font = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "PressStart2P.ttf"
    if os.name == "nt":
        import ctypes
        ctypes.windll.gdi32.AddFontResourceExW(str(font), 0x10, 0)  # private pixel font
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp on high-DPI screens
        except (AttributeError, OSError):
            pass
    NIGHT, PANEL, INK, MUTED, GREEN, DEEP, RED = "#12141C", "#1D2030", "#ECE8DA", "#7B8099", "#3DDC6F", "#1A6B39", "#FF5A4E"
    PIX = lambda size: ("Press Start 2P", size)
    cfg, events, busy, smoke = settings(), queue.Queue(), [False], []
    choices = ["no AI"] + models()
    root = tk.Tk()
    root.title("SimsGrab")
    root.configure(bg=NIGHT, padx=24, pady=20)
    root.minsize(700, 560)
    icon = tk.PhotoImage(width=32, height=32)  # plumbob
    for y in range(2, 30):
        w = round(9 * (1 - abs(y - 16) / 14))
        icon.put(GREEN, to=(16 - w, y, 16 + w + 1, y + 1))
    root.iconphoto(True, icon)

    # header: pixel title, bobbing plumbob, smoke while the agents work
    sky = tk.Canvas(root, width=700, height=130, bg=NIGHT, highlightthickness=0)
    sky.pack(fill="x")
    for y in range(0, 36, 4):
        w = round(12 * (1 - abs(y - 16) / 18) / 4) * 4
        sky.create_rectangle(26 - w, 30 + y, 26 + w, 34 + y, fill=GREEN if y < 18 else DEEP, width=0, tags="bob")
    sky.create_text(67, 51, text="SIMSGRAB", font=PIX(26), fill=DEEP, anchor="w")
    sky.create_text(64, 48, text="SIMSGRAB", font=PIX(26), fill=INK, anchor="w")
    sky.create_text(66, 88, text="PASTE A PIN OR TYPE A VIBE", font=PIX(8), fill=MUTED, anchor="w")

    def animate(t=itertools.count()):
        f = next(t)
        sky.move("bob", 0, 2 if f % 20 < 10 else -2) if f % 5 == 0 else None
        for _ in range(2 if busy[0] else 0):
            smoke.append([random.randrange(0, sky.winfo_width(), 4), 130, random.choice((8, 12, 16)), 1.0])
        sky.delete("smoke")
        for p in smoke:
            p[1] -= 2
            p[0] += round(math.sin(p[1] / 12)) * 2
            p[3] -= 0.02
            g = int(0x14 + (0x8A - 0x14) * max(p[3], 0))
            x, y, s = p[0] // 4 * 4, int(p[1]) // 4 * 4, p[2]
            sky.create_rectangle(x, y, x + s, y + s, fill=f"#{g:02x}{g:02x}{g + 12:02x}", width=0, tags="smoke")
        smoke[:] = [p for p in smoke if p[3] > 0]
        sky.tag_lower("smoke")
        root.after(50, animate)

    # category chips
    chips, picked = tk.Frame(root, bg=NIGHT), set()
    chips.pack(fill="x", pady=(4, 10))

    def toggle(b, c):
        picked.symmetric_difference_update({c})
        b.config(bg=GREEN if c in picked else PANEL, fg=NIGHT if c in picked else MUTED)

    flat = dict(relief="flat", bd=0, highlightthickness=0, cursor="hand2")
    for c in CATEGORIES:
        b = tk.Button(chips, text=c.upper(), font=PIX(7), bg=PANEL, fg=MUTED, activebackground=GREEN, padx=8, pady=6, **flat)
        b.config(command=lambda b=b, c=c: toggle(b, c))
        b.pack(side="left", padx=(0, 6))

    # the one line
    box = tk.Frame(root, bg=GREEN, padx=3, pady=3)
    box.pack(fill="x")
    entry = tk.Entry(box, font=("Consolas", 13), bg=PANEL, fg=INK, relief="flat", insertbackground=GREEN,
                     insertwidth=8)
    entry.pack(side="left", fill="both", expand=True, ipadx=10, ipady=10)
    go = tk.Button(box, text="GO", font=PIX(12), bg=GREEN, fg=NIGHT, activebackground=NIGHT, activeforeground=GREEN,
                   disabledforeground=DEEP, padx=22, **flat)
    go.pack(side="left", fill="y")

    # settings: model + Mods folder
    row = tk.Frame(root, bg=NIGHT)
    row.pack(fill="x", pady=(10, 0))
    saved = cfg["model"] or "no AI"
    model = tk.StringVar(value=saved if saved in choices else choices[-1])
    tk.Label(row, text="AI", font=PIX(7), bg=NIGHT, fg=MUTED).pack(side="left")
    menu = tk.OptionMenu(row, model, *choices)
    menu.config(font=PIX(7), bg=PANEL, fg=INK, activebackground=GREEN, activeforeground=NIGHT, padx=8, **flat)
    menu["menu"].config(font=PIX(7), bg=PANEL, fg=INK, activebackground=GREEN, activeforeground=NIGHT, bd=0)
    menu.pack(side="left", padx=(8, 18))
    tk.Label(row, text="MODS", font=PIX(7), bg=NIGHT, fg=MUTED).pack(side="left")
    mods = tk.Button(row, text=cfg["mods"], font=("Consolas", 9), bg=NIGHT, fg=INK, activebackground=PANEL,
                     activeforeground=INK, anchor="w", padx=8, **flat)
    mods.pack(side="left", fill="x", expand=True)

    def choose_mods():
        d = filedialog.askdirectory(initialdir=cfg["mods"], title="Your Sims 4 Mods folder")
        if d:
            cfg["mods"] = d
            mods.config(text=d)
            store()

    def store(*_):
        cfg["model"] = "" if model.get() == "no AI" else model.get()
        try:
            CONF.write_text(json.dumps(cfg))
        except OSError:
            pass

    mods.config(command=choose_mods)
    model.trace_add("write", store)
    store()

    log = tk.Text(root, font=("Consolas", 10), bg=NIGHT, fg=INK, relief="flat", bd=0, highlightthickness=0,
                  width=80, height=11, wrap="none", state="disabled", cursor="arrow")
    log.pack(fill="both", expand=True, pady=12)
    log.tag_config("agent", foreground=MUTED)
    log.tag_config("ai", foreground=GREEN)
    log.tag_config("bad", foreground=RED)

    def open_mods():
        p = Path(cfg["mods"]) / "SimsGrab"
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(p) if os.name == "nt" else webbrowser.open(p.as_uri())

    bar = tk.Frame(root, bg=PANEL)
    bar.pack(fill="x")
    status = tk.Label(bar, text="READY", font=PIX(8), bg=PANEL, fg=INK, anchor="w", padx=14, pady=12)
    status.pack(side="left", fill="x", expand=True)
    folder = tk.Button(bar, text="OPEN MODS", font=PIX(7), bg=PANEL, fg=INK, activebackground=INK,
                       activeforeground=NIGHT, padx=14, command=open_mods, **flat)
    folder.pack(side="right", fill="y")

    def show(text, bg, fg=INK):
        bar.config(bg=bg)
        status.config(text=text, bg=bg, fg=fg)
        folder.config(bg=bg, fg=fg)

    def write(name, msg):
        log.config(state="normal")
        log.insert("end", f"{name:<14}", "ai" if name == "ai" else "agent")
        log.insert("end", msg + "\n", "bad" if msg.startswith("x ") else ())
        log.see("end")
        log.config(state="disabled")

    def work(text, cats):
        try:
            events.put(("done", run(text, cats, dict(cfg), lambda a, m: events.put(("log", a, m)))))
        except Exception as e:
            events.put(("fail", e))

    def start(*_):
        text = entry.get().strip()
        if not (text or picked) or busy[0]:
            return
        busy[0] = True
        go.config(state="disabled")
        log.config(state="normal")
        log.delete("1.0", "end")
        log.config(state="disabled")
        show("WORKING...", PANEL)
        threading.Thread(target=work, args=(text, sorted(picked)), daemon=True).start()

    def poll():
        while not events.empty():
            kind, arg, *rest = events.get()
            if kind == "log":
                write(arg, *rest)
                continue
            busy[0] = False
            go.config(state="normal")
            show(f"INSTALLED  {arg}", GREEN, NIGHT) if kind == "done" else show(f"FAILED  {arg}", RED, NIGHT)
        root.after(80, poll)

    def autopaste(_):
        try:
            clip = root.clipboard_get().strip()
        except tk.TclError:
            return
        if not entry.get() and re.match(r"https?://\S*(pinterest\.|pin\.it/)", clip):
            entry.insert(0, clip)

    go.config(command=start)
    entry.bind("<Return>", start)
    root.bind("<FocusIn>", autopaste)
    entry.focus_set()
    poll()
    animate()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        ui()
    else:
        try:
            print(run(" ".join(sys.argv[1:]), [], settings(), lambda a, m: print(f"{a:<14}{m}")))
        except Fail as e:
            sys.exit(f"FAILED  {e}")
