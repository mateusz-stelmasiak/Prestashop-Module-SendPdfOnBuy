# SimsGrab

Paste a Pinterest pin, get the Sims mod behind it as a zip. If it can't be done, it says **FAILED** and why.

![SimsGrab](screenshot.png)

## How it works

1. **Pinterest agent** reads the pin and finds the page it was saved from.
2. **Site agents** follow the trail from there: Tumblr, SimFileShare, MediaFire, Google Drive, Dropbox, Patreon (public posts), ModTheSims, plain `.zip` / `.rar` / `.7z` / `.package` / `.ts4script` links. Redirect wrappers like `t.umblr.com` are stripped.
3. The first real mod file found (checked by its file signature, not its name) is saved to `Downloads\SimsGrab`. A `.zip` is kept as is. Anything else is put inside a zip.

Up to 30 pages are checked, at most 3 links deep. Sites behind logins, captchas or ad gates (The Sims Resource, CurseForge, paid Patreon posts) will fail.

## Get it

**Windows:** download `SimsGrab.exe` from the latest release, or from the newest *SimsGrab exe* run under Actions. No install needed.

**Any OS with Python 3.8+:**

```
python simsgrab.py                      # window
python simsgrab.py https://pin.it/xxxx  # command line
```

## Build the exe yourself

```
pip install pyinstaller
pyinstaller --onefile --windowed --name SimsGrab simsgrab.py
```

Pushing a tag named `simsgrab-v*` (for example `simsgrab-v1.0`) builds the exe and attaches it to a GitHub release.
