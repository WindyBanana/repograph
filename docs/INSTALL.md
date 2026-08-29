# Installing repograph

Three ways in, depending on what you have.

| | What you need | Best for |
|---|---|---|
| **A downloaded build** | nothing | most people — a single file, no Python |
| **From source** | Python 3.9+ | contributors, or if you want it on your PATH via pipx |
| **From a clone, uninstalled** | Python 3.9+ | trying it once |

## 1. A downloaded build (no Python required)

Standalone builds are produced by the release workflow for Windows, macOS (Apple silicon and
Intel) and Linux. Each archive contains one executable of about 9 MB with everything inside it.

> There is no published release yet. Push a tag (`git tag v0.1.0 && git push --tags`) to have CI
> build and publish them, or build one locally with `make binary` — see [building](#building-them-yourself).

### Windows

1. Download `repograph-windows-x86_64.zip` and unzip it.
2. **Double-click `repograph.exe`** — the UI opens in your browser.
3. To put it on your PATH and get a Start Menu entry, run in PowerShell:

   ```powershell
   .\install.ps1 -Binary .\repograph.exe
   ```

   Then `repograph scan C:\path\to\repo` works from any terminal.

Windows SmartScreen will warn about an unsigned executable: choose **More info → Run anyway**.

### macOS

1. Download `repograph-macos-arm64.zip` (Apple silicon) or `repograph-macos-x86_64.zip` (Intel).
2. Unzip. You get `repograph.app` and the bare `repograph` binary.
3. **Double-click `repograph.app`** — the UI opens. Drag it to `/Applications` to keep it.
4. For the terminal:

   ```bash
   ./install.sh --binary ./repograph
   ```

macOS will say the app is from an unidentified developer, because it is unsigned. Right-click it
and choose **Open**, or clear the quarantine flag:

```bash
xattr -dr com.apple.quarantine repograph.app
```

### Linux

```bash
tar xzf repograph-linux-x86_64.tar.gz
./repograph scan /path/to/repo          # works immediately
./install.sh --binary ./repograph       # PATH + application launcher entry
```

The installer writes `~/.local/share/applications/repograph.desktop`, so repograph appears in your
launcher and opens the UI when clicked.

## 2. From source

```bash
git clone https://github.com/WindyBanana/repograph
cd repograph
./scripts/install.sh          # pipx if available, otherwise a symlink into ~/.local/bin
```

Or directly:

```bash
pipx install .                # recommended
python3 -m pip install --user .
```

Both give you the `repograph` command. There are no third-party dependencies.

## 3. From a clone, without installing

```bash
./bin/repograph scan /path/to/repo
./bin/repograph ui
```

The launcher sets up the import paths itself. Nothing is written outside the output folder.

## Terminal or window — both, everywhere

The same binary is both:

| How you start it | What you get |
|---|---|
| `repograph scan .` (or any subcommand) | the CLI |
| `repograph ui` | the desktop app: pick a folder, scan, then browse the dashboard in place |
| `repograph tui` | the terminal UI, for browsing a scan over SSH (macOS/Linux) |
| double-clicking the app or Start Menu entry | the desktop UI |

The UI binds to `127.0.0.1` only, mints a fresh token each run, and rejects cross-origin
requests — a page open elsewhere in your browser cannot drive it.

## Building them yourself

```bash
make binary        # builds dist/repograph (or dist\repograph.exe) for this machine
make app           # + the .app bundle / .desktop entry / shortcut script
```

Requires `pip install pyinstaller`. Cross-building is not supported: build on the platform you
are targeting, or let the release workflow do all four in CI.

## Uninstalling

```bash
rm -f ~/.local/bin/repograph
rm -f ~/.local/share/applications/repograph.desktop ~/.local/share/icons/repograph.svg  # Linux
rm -rf ~/Applications/repograph.app                                                     # macOS
pipx uninstall repograph                                                                # if used
```

On Windows, delete `%LOCALAPPDATA%\Programs\repograph`, remove it from your user PATH and delete
the Start Menu shortcut.

Scan output lives wherever you pointed it (`repograph-out/` by default) and is never written
anywhere else. The only other file repograph creates is `~/.config/repograph/history.json`, the
list of recently scanned folders shown in the UI.
