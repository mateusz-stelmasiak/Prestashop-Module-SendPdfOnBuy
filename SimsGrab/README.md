# SimsGrab

One line. Paste a Pinterest pin, or type a vibe and pick categories. The mods get downloaded and installed into your Sims 4 `Mods` folder. If it can't be done, it says **FAILED** and why.

![SimsGrab](screenshot.png)

## Use it

- **Pin link** (`https://pin.it/...` or `pinterest.com/pin/...`): grabs that one mod.
- **Words** (`cottagecore witchy`) plus category chips (HAIR, CLOTHES, ...): builds a mod pack. It searches the web for each category and grabs the best hit.
- **AI**: pick any model from your local [Ollama](https://ollama.com). Free, open source, runs on your PC, nothing sent to a cloud AI. It names the pack, writes the searches, and reads each page's links to choose what to click, like a person would. Pick **no AI** to use the built-in rules only.
- **MODS**: click the path to change it. Defaults to `Documents\Electronic Arts\The Sims 4\Mods`.

Mods are installed to `Mods\SimsGrab\<mod or pack name>\`. `.ts4script` files go one level up, where the game can load them. The original zips are kept in `Downloads\SimsGrab`.

## How it works

1. **Pinterest agent** reads the pin and finds the page it was saved from.
2. **Site agents** follow the trail: Tumblr, SimFileShare, MediaFire, Google Drive, Dropbox, Patreon (public posts), ModTheSims, and direct `.zip` / `.rar` / `.7z` / `.package` / `.ts4script` links. Redirect wrappers like `t.umblr.com` are stripped.
3. With a model picked, it also gets each page's link texts and chooses up to 3 to follow.
4. The first real mod file (checked by its file signature, not its name) is saved and installed.

Up to 30 pages are checked, at most 3 links deep. Sites behind logins, captchas or ad gates (The Sims Resource, CurseForge, paid Patreon posts) will fail. `.rar` / `.7z` downloads are saved but have to be unpacked by hand.

## Get it

**Windows:** download `SimsGrab.exe` from the latest release. No install needed. For AI, install Ollama and pull a model, for example `ollama pull llama3.2`.

**Any OS with Python 3.8+:**

```
python simsgrab.py                      # window
python simsgrab.py https://pin.it/xxxx  # command line
```

## Build the exe yourself

```
pip install pyinstaller
pyinstaller --onefile --windowed --name SimsGrab --add-data "PressStart2P.ttf;." simsgrab.py
```

Pushing a tag named `simsgrab-v*` (for example `simsgrab-v1.0`) builds the exe and attaches it to a GitHub release.

Pixel font: [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) by CodeMan38, SIL Open Font License (`PressStart2P-OFL.txt`).
