"""SimsGrab: one word or a Pinterest pin in, Sims mods installed.

Agents follow the trail from a pin (or a web search) through the usual CC hosts
(Tumblr, SimFileShare, MediaFire, Google Drive, Dropbox, Patreon, ...) until a
real mod file turns up. An optional local model (Ollama) writes the searches and
picks which link to click. The window is web/index.html shown by pywebview.
"""
import base64, heapq, html, itertools, json, os, re, shutil, sys, threading, time, webbrowser, zipfile
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

HOME = Path.home()
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
DOWNLOADS = HOME / "Downloads"
OUT = DOWNLOADS / "SimsGrab"
CONF = HOME / ".simsgrab.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
WIDGETS = "https://widgets.pinterest.com/v3/pidgets/"
PIN_API = WIDGETS + "pins/info/?pin_ids="
RELATED = "https://www.pinterest.com/resource/RelatedModulesResource/get/?data="
SEARCH = "https://html.duckduckgo.com/html/?q="
BING = "https://www.bing.com/search?q="
OLLAMA = "http://localhost:11434"
KINDS = {b"PK\x03\x04": ".zip", b"Rar!": ".rar", b"7z\xbc\xaf": ".7z", b"DBPF": ".package"}  # magic bytes
EXTS = (*KINDS.values(), ".ts4script")
HOSTS = ("simfileshare.net/download", "mediafire.com/file", "mediafire.com/?", "drive.google.com", "dropbox.com/s",
         "patreon.com/posts", "patreon.com/file", "patreon.com/media-u", "getfile.php", "curseforge.com/sims4/")
JUNK = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".ico", ".mp4")
CATEGORIES = ("outfits", "hair", "makeup", "shoes", "accessories", "furniture", "build", "gameplay", "poses")
SKIP = ("duckduckgo.", "bing.", "microsoft.", "pinterest.", "youtube.", "facebook.", "instagram.", "reddit.",
        "tiktok.", "twitter.", "x.com", "wikipedia.")
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


def grab(url, log=lambda agent, msg: None, model="", goal="a Sims 4 mod", pages=MAX_PAGES, see=lambda *a: None):
    """Follow the trail from url to a mod file. Returns the saved zip's path or raises Fail.
    see(url, title, [(link text, url, score)]) gets each page as the agent reads it."""
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
            links = anchors(r.geturl(), text)
            best = {}
            for s, l in [(s, l) for s, l in leads(r.geturl(), text) if s > 1 or depth == 0] + \
                        [(2.5, l) for l in pick(model, goal, links, log)]:
                if l not in seen:
                    best[l] = max(s, best.get(l, 0))
            ranked = sorted(best.items(), key=lambda x: -x[1])
            labels = dict(links)
            see(u, title(text), [(labels.get(l, ""), l, s) for l, s in ranked[:8]])
            log(agent(u), f"{len(ranked)} leads")
            for l, s in ranked:
                heapq.heappush(todo, (-s, depth + 1, next(tick), l))
    raise Fail(f"No mod file found ({len(seen)} pages checked)")


def title(text):
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.S | re.I)
    return " ".join(html.unescape(m[1]).split())[:120] if m else ""


def preview(url):
    """The page's share image (og:image), for the result cards."""
    try:
        r, head = fetch(url)
        text = (head + r.read(400_000)).decode("utf-8", "replace")
    except OSError:
        return ""
    m = re.search(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]*content=["\']([^"\']+)', text) \
        or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']og:image', text)
    return urljoin(r.geturl(), html.unescape(m[1])) if m else ""


def search(word, cat, model="", log=lambda agent, msg: None, see=lambda *a: None, n=50):
    """Top n pages for one word + a category, as dicts for the result cards."""
    topic = f"{word} {cat}".strip()
    queries = [f"sims 4 {topic} cc {extra}".strip() for extra in
               ("", "free download", "tumblr", "patreon", "maxis match", "alpha", "simfileshare", "pack", "lookbook")]
    if model:
        try:
            queries = ask(model, f"Write 8 different web searches that find free Sims 4 custom content for: {topic}. "
                                 'Answer JSON {"queries": [...]}')["queries"][:8] + queries
        except (OSError, ValueError, KeyError, TypeError) as e:
            log("ai", f"x {e}")
    found = {}
    for q in queries:
        if len(found) >= n:
            break
        log("search", q)
        hits = []
        for engine in (SEARCH, BING):
            try:
                r, head = fetch(engine + quote(q))
                hits = [(u, t) for u, t in anchors(r.geturl(), (head + r.read()).decode("utf-8", "replace"))
                        if t and not any(s in urlparse(u).netloc for s in SKIP)]
            except OSError as e:
                log("search", f"x {e}")
                continue
            if hits:
                see(engine + quote(q), f"search: {q}", [(t, u, 2) for u, t in hits[:8]])
                break
        for u, t in hits:
            found.setdefault(u, t)
    items = list(found.items())[:n]
    log("search", f"{len(items)} results, fetching previews")
    with ThreadPoolExecutor(12) as pool:
        images = list(pool.map(preview, [u for u, _ in items]))
    return [{"url": u, "title": t, "site": urlparse(u).netloc.removeprefix("www."), "image": img}
            for (u, t), img in zip(items, images)]


def pins_in(data, found):
    """Collect every pin with an outside link anywhere in a Pinterest JSON reply, as result cards."""
    if isinstance(data, dict):
        imgs, link = data.get("images"), data.get("link") or ""
        if isinstance(imgs, dict) and data.get("id") and link.startswith("http") and "pinterest." not in link:
            img = next((imgs[k]["url"] for k in ("564x", "474x", "236x", "237x", "orig") if isinstance(imgs.get(k), dict)), "")
            text = " ".join(str(data.get("grid_title") or data.get("title") or data.get("description") or "").split())
            found.setdefault(link, {"url": link, "title": text[:90] or agent(link), "image": img,
                                    "site": urlparse(link).netloc.removeprefix("www.")})
        data = list(data.values())
    for v in data if isinstance(data, list) else []:
        pins_in(v, found)
    return found


def pinterest_json(url):
    r = web.open(Request(url, headers={"User-Agent": UA, "Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                                       "X-Pinterest-PWS-Handler": "www/pin/[id].js"}), timeout=30)
    return json.load(r)


def similar(url, model="", log=lambda agent, msg: None, see=lambda *a: None, n=50):
    """Pin mode: the pasted pin, Pinterest's related pins, the rest of its board, then a web search on its
    description. A board or profile link gives its pins. Returns (pack name, result cards)."""
    if "pin.it/" in url:
        url = fetch(url)[0].geturl()
    path = [p for p in urlparse(url).path.split("/") if p]
    found, name, words, sources = {}, "Pinterest Pack", "", []
    if pid := re.search(r"/pin/(?:[^/]*--)?(\d+)", url):
        pid = pid[1]
        try:
            info = pinterest_json(PIN_API + pid)
            pins_in(info, found)
            if found:
                next(iter(found.values()))["this"] = True
            pin = (info.get("data") or [{}])[0]
            board = pin.get("board") or {}
            name = board.get("name") or name
            words = " ".join(str(pin.get("grid_title") or pin.get("description") or "").split()[:6])
            sources.append(WIDGETS + "boards" + board["url"].rstrip("/") + "/pins/" if board.get("url") else "")
        except (OSError, ValueError, AttributeError) as e:
            log("pinterest", f"x {e}")
        options = {"pin_id": pid, "context_pin_ids": [], "search_query": "", "source": "deep_linking",
                   "top_level_source": "deep_linking", "top_level_source_depth": 1, "is_pdp": False}
        sources.insert(0, RELATED + quote(json.dumps({"options": options, "context": {}})))
    elif len(path) >= 2:
        sources, name = [WIDGETS + f"boards/{path[0]}/{path[1]}/pins/"], path[1].replace("-", " ").title()
    elif path:
        sources, name = [WIDGETS + f"users/{path[0]}/pins/"], f"{path[0]}'s Pins"
    for src in filter(None, sources):
        log("pinterest", src.split("?")[0])
        try:
            before = len(found)
            pins_in(pinterest_json(src), found)
            log("pinterest", f"{len(found) - before} pins with links")
        except (OSError, ValueError) as e:
            log("pinterest", f"x {e}")
    cards = list(found.values())[:n]
    see(url, f"pinterest: {name}", [(c["title"], c["url"], 2.5 if c.get("this") else 2) for c in cards[:8]])
    if len(cards) < n and words:
        log("search", f"topping up with '{words}'")
        cards += [c for c in search(words, "", model, log, see, n - len(cards)) if c["url"] not in found]
    if not cards:
        raise Fail("No pins with download links found there")
    return clean(name), cards[:n]


def loose_mods():
    """Mods sitting in Downloads: .package / .ts4script files and zips that contain them."""
    found = []
    for f in sorted(DOWNLOADS.glob("*")) if DOWNLOADS.is_dir() else []:
        ext = f.suffix.lower()
        if ext in (".package", ".ts4script"):
            found.append(f)
        elif ext == ".zip":
            try:
                with zipfile.ZipFile(f) as z:
                    if any(n.lower().endswith((".package", ".ts4script")) for n in z.namelist()):
                        found.append(f)
            except (OSError, zipfile.BadZipFile):
                pass
    return found


def tidy(mods):
    """Move loose mods from Downloads into Mods/SimsGrab. Zips are unpacked, then kept in OUT."""
    n = 0
    for f in loose_mods():
        if f.suffix.lower() == ".zip":
            n += install(f, mods, f.stem)
            dest = OUT / f.name
        else:
            n += 1
            dest = Path(mods) / "SimsGrab" / ("" if f.suffix.lower() == ".ts4script" else "Downloads") / f.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        shutil.move(f, dest)
    return n


class Api:
    """Everything the page can call as pywebview.api.<name>(...). Each call runs on its own thread."""

    def __init__(self):
        self._win, self._cfg = None, settings()

    def _emit(self, kind, **data):
        self._win.evaluate_js(f"ui.on({json.dumps({'kind': kind, **data})})")

    def _log(self, name, msg):
        self._emit("log", agent=name, msg=msg)

    def _see(self, url, page, links):
        self._emit("see", url=url, title=page, links=[{"text": t, "url": u, "hot": s >= 2.5} for t, u, s in links])

    def _store(self):
        try:
            CONF.write_text(json.dumps(self._cfg))
        except OSError:
            pass

    def hello(self):
        threading.Thread(target=self._watch, daemon=True).start()
        return {"models": ["no AI"] + models(), "model": self._cfg["model"] or "no AI", "mods": self._cfg["mods"],
                "categories": CATEGORIES}

    def _watch(self):
        """Tell the page whenever new loose mods show up in Downloads."""
        told = set()
        while True:
            now = {str(f) for f in loose_mods()}
            if now - told:
                self._emit("loose", count=len(now), names=[Path(f).name for f in sorted(now)][:4])
            told = now
            time.sleep(20)

    def setting(self, key, value):
        self._cfg[key] = "" if value == "no AI" else value
        self._store()

    def choose_mods(self):
        picked = self._win.create_file_dialog(webview.FileDialog.FOLDER, directory=self._cfg["mods"])
        if picked:
            self.setting("mods", picked[0])
        return self._cfg["mods"]

    def open_mods(self):
        p = Path(self._cfg["mods"]) / "SimsGrab"
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(p) if os.name == "nt" else webbrowser.open(p.as_uri())

    def search(self, word, cat):
        return search(word, cat, self._cfg["model"], self._log, self._see)

    def similar(self, url):
        name, cards = similar(url, self._cfg["model"], self._log, self._see)
        return {"name": name, "results": cards}

    def grab(self, url):
        p = grab(url, self._log, self._cfg["model"], see=self._see)
        return {"name": p.name, "files": install(p, self._cfg["mods"], p.stem)}

    def download(self, items, name):
        """Grab a pack of pages four at a time, install into Mods/SimsGrab/<name>, zip the pack."""
        name = clean(name) or "Pack"

        def one(item):
            i, url, label = item
            self._emit("item", i=i, state="work")
            try:
                p = grab(url, self._log, self._cfg["model"], f"the download for the Sims 4 CC '{label}'", 12, self._see)
                ok = install(p, self._cfg["mods"], name) > 0
            except Exception as e:
                self._log("agent", f"x {e}")
                ok = False
            self._emit("item", i=i, state="done" if ok else "fail")
            return ok

        with ThreadPoolExecutor(4) as pool:
            ok = sum(pool.map(one, items))
        folder = Path(self._cfg["mods"]) / "SimsGrab" / name
        if folder.is_dir():
            OUT.mkdir(parents=True, exist_ok=True)
            shutil.make_archive(str(OUT / name), "zip", folder)
        return {"ok": ok, "total": len(items), "name": name}

    def tidy(self):
        return tidy(self._cfg["mods"])


def app():
    global webview
    import webview

    api = Api()
    api._win = webview.create_window("SimsGrab", str(HERE / "web" / "index.html"), js_api=api, width=1240, height=800,
                                     min_size=(960, 640), background_color="#12141C")
    webview.start(http_server=True)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        app()
    else:
        try:
            p = grab(sys.argv[1], lambda a, m: print(f"{a:<14}{m}"))
            print(p, install(p, settings()["mods"], p.stem), "files installed")
        except Fail as e:
            sys.exit(f"FAILED  {e}")
