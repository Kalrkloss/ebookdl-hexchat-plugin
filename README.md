# EbookDL – HexChat plugin for IRC ebook search & download

![EbookDL window](screenshots/ebookdl.png)

EbookDL automates ebook search and download via the "bookz" bots in IRC
(e.g. `#bookz` or `#ebooks` on `irc.irchighway.net`) — all in one window,
with a netiquette queue:

1. **Search**: sends `@search <term>` to the channel
2. **Results**: receives the result ZIP via DCC, extracts it and parses
   the hit list (filename + size)
3. **Select**: hits in a scrollable list with checkboxes
4. **Download**: selected books are requested one by one and received
   via DCC
5. **Storage**: finished files land in the target folder (real archives
   are optionally extracted — ebook files such as EPUB stay untouched)
6. **Overview**: status line, progress bar and log inside the window

License: **MIT** (see LICENSE). Please respect the rules of the
IRC network/channel you use — the netiquette defaults are built into the
plugin and adjustable.

> Deutsch? Die deutsche Version dieser Anleitung findest du in
> [README.de.md](README.de.md).

---

## Features

- Search and download window right inside HexChat (`/ebookdl`)
- Automatic detection of the result ZIP (no manual opening needed)
- Hit list with size, checkboxes and a status column
- Sortable list: clicking a column header sorts by name
  (case-insensitive), file type or size (numeric)
- **Copy results**: select one or more rows (Ctrl+click) and press
  **Ctrl+C** — or right-click a row and choose **Copy** — to copy the
  filenames to the clipboard (one per line)
- **Fixed column widths**: when the window opens and after results are
  loaded, all columns stay visible — long filenames and target paths are
  truncated with `…` instead of stretching the columns (the file column
  can still be resized with the mouse)
- **Ebook filter**: by default only ebooks and archives are shown in the
  results — cover images, OPF, NFO and similar files are hidden (the log
  shows how many were filtered; the option can be turned off in the
  settings)
- Queue with strict netiquette: one request per delay interval, limited
  parallel downloads, timeouts
- DCC assignment by bot nick and filename (with FIFO fallback)
- After a successful download the book is automatically unchecked —
  finished titles disappear from the selection (failed ones stay checked
  so you can retry them)
- Target folder, delay, parallelism and search command configurable
- Result ZIPs are deleted automatically after parsing
- **Single-instance guard**: the plugin can only be loaded once — further
  loads (even from other paths) are rejected with a message, no duplicate
  windows/hooks
- Runs inside HexChat's GTK2 — no separate window management needed

---

## Requirements

**Linux**

- HexChat (≥ 2.14, Python scripting enabled — default)
- Python 3 + PyGObject with GTK2 typelibs for the window:

      sudo apt-get install python3-gi gir1.2-gtk-2.0

**Windows**

- HexChat (official installer, includes Python integration)
- The GUI needs PyGObject (`gi`) with Gtk-2.0 typelibs — usually not
  included in the Windows installer. Without it the plugin prints a hint
  when opening the window; the search/download logic (hook-based) still
  works, just without a window.

---

## Installation

### Linux

1. Put the plugin file into the autoload folder. **Important:** Python
   scripts load from `addons/`, not from `plugins/`:

       mkdir -p ~/.config/hexchat/addons
       cp ebookdl.py ~/.config/hexchat/addons/
       # or a symlink if you develop inside the repo:
       ln -s "$PWD/ebookdl.py" ~/.config/hexchat/addons/ebookdl.py

2. Restart HexChat (or type `/py load /path/to/ebookdl.py` in a running
   HexChat). The plugin loads once an IRC connection is established.
3. Open the window: type `/ebookdl` in the input line.

### Windows

1. Install HexChat and connect once.
2. Copy `ebookdl.py` to `%APPDATA%\HexChat\addons\`.
3. Restart HexChat, type `/ebookdl`.

### Uninstalling

- Remove the file from `~/.config/hexchat/addons/` (or
  `%APPDATA%\HexChat\addons\`) and restart HexChat — or at runtime:
  `/py unload EbookDL`.

---

## Quick start

1. Join an ebook channel (e.g. `/join #ebooks` on irc.irchighway.net) —
   or set a channel later in the settings.
2. Type `/ebookdl` — the window opens.
3. Type a search term into the **Search** field and press Enter (or click
   **Start search**). The status shows *Searching …*.
4. When the bot answers, *Result file being received* appears in the log,
   followed by the hit count, e.g. *855 hits - select books and start
   download*.
5. Check the books in the list and click **Start download**. Requests go
   out with a delay between them, files land in the target folder
   (default: `~/Downloads/ebooks`).

---

## Usage in detail

### The window

| Area              | Contents                                                          |
|-------------------|-------------------------------------------------------------------|
| Header row        | Channel field (display), search field, **Start search** button    |
| Table             | Checkbox, filename, **file type** (extension), size, status       |
| Button bar        | Select all / Select none / Start download / Cancel waiting / Settings |
| Progress area     | Status line, progress bar, timestamped log                        |

**Sorting**: clicking a column header sorts the list — **File**
(case-insensitive), **Type** (alphabetical) or **Size** (numeric).
Clicking again reverses the order; the arrow in the header shows the
active sort.

### Search

- **Search field**: enter a term, press Enter. Sent as
  `@search <term>` (the command is configurable in the settings).
- **Channel**: if the channel field is empty, the currently active
  channel is used. If a channel is set (from the settings), the search
  goes there.
- **During a running search** a second search is rejected with
  *Search already running - please wait.*
- **Result**: the bot sends a ZIP via DCC. The plugin detects it
  automatically (*Result file being received*), extracts it in the
  background, parses the hits and fills the list. The ZIP is then
  deleted (*Result ZIP deleted*).
- **Timeout**: if no file arrives within the search timeout (default
  180 s), the search is aborted (*Timeout: No result file received.*).

### Result list

- Each row: **checkbox** (ticked = selected), **filename**, **size**,
  **status** (filled in during download).
- **Select all / Select none** ticks or clears all checkboxes.
- The selection survives closing the window (the result list is stored
  independently of the window) — it is back when you reopen.

### Download

- **Start download**: all checked books are queued (*N download(s)
  queued*).
- Requests are sent **one at a time with a delay** (default 10 s); at
  most `max_concurrent` downloads run in parallel (default 2).
- The status column shows each row's progress:
  `waiting → requested → receiving → done` (or `error`).
- **Cancel waiting** removes all requests that have not been sent yet.
- On completion the file is **moved** to the target folder (not copied).
  **Real archives** (zip, 7z, rar, tar/tar.gz/tar.bz2/tar.xz/tgz, cab,
  iso, arj, lzh plus single-file gz/bz2/xz) are optionally extracted —
  zip natively, everything else via the installed `7z` (p7zip).
  **Ebook files such as EPUB (technically a ZIP file) are deliberately
  left untouched.** Name collisions automatically get ` (1)`, ` (2)`, …
  appended.
- **Auto-uncheck**: after a successful download the row's checkbox is
  removed — you immediately see what is still missing. Failed downloads
  stay checked (status `error`) so you can request them again.
- A download that does not start receiving within the timeout (default
  300 s) is marked as failed.

### Progress area

- **Status line**: summarizes the current state (search, hits, running
  download, errors).
- **Progress bar**: appears during downloads.
- **Log**: timestamped plugin messages (search sent, receiving, parsing,
  downloads, errors).

---

## Settings

- **Settings** in the window opens a modal window (the main window is
  blocked while it is open — a second click just brings it forward).
  **OK** saves, **Cancel** or closing the window discards. If the main
  window is closed, the settings window closes along with it. All values
  are stored in `~/.config/hexchat/ebookdl.json` (or
  `%APPDATA%\HexChat\ebookdl.json`) and loaded on start.

| Option                | Default                    | Meaning                                             |
|-----------------------|----------------------------|-----------------------------------------------------|
| Channel               | (empty)                    | Fixed channel for search/downloads; empty = current |
| Search command        | `@search {query}`          | Template; `{query}` is replaced by the term         |
| Target folder         | `~/Downloads/ebooks`       | Where finished files go                             |
| Delay between requests| 10 s                       | Minimum gap between two requests (netiquette)       |
| Max. parallel downloads | 2                        | Simultaneously running downloads                    |
| Download timeout      | 300 s                      | Abort if no transfer starts                         |
| Search timeout        | 180 s                      | Abort search without a result file                  |
| Unzip                 | on                         | Automatically extract archives in the target folder |
| Ebook filter          | on                         | Show only ebooks and archives in the results (hide cover images, OPF, NFO, etc.); the log reports how many files were hidden |
| Conversion            | off                        | After download, automatically convert to **EPUB**, **MOBI** or **PDF** (Calibre). If `ebook-convert` is not installed, the selection is greyed out and a hint appears (`sudo apt install calibre`). Conversion runs after moving; failures leave the original file untouched. |

---

## Conversion (Calibre)

After a download, the plugin can automatically convert the book to
**EPUB**, **MOBI** or **PDF** — useful because many books in the bookz
networks are distributed as `.lit` or other formats.

- Set the target format in the settings (**Conversion** option).
- Conversion runs after the file has been moved to the target folder.
- Only ebook files are converted (archives are never touched), and only
  if the target format differs from the source format.
- If the conversion fails, the original file stays untouched and the
  error is shown in the log.

**Dependency:** the conversion requires [Calibre](https://calibre-ebook.com)
and its `ebook-convert` command line tool. If Calibre is not installed,
the format selection in the settings is greyed out and a hint is shown.

Install Calibre on Debian/Ubuntu/Mint:

    sudo apt install calibre

or download it from the [Calibre website](https://calibre-ebook.com/download).

---

## Netiquette & queue

The bookz networks expect polite behaviour. EbookDL enforces this by
default and does not let you bypass it:

- **One request per delay interval** — even if many books are checked,
  at most one request is sent every `delay` seconds.
- **Max. `max_concurrent` active downloads** — further requests wait in
  the queue until a download finishes or fails.
- **Timeouts** prevent hung searches or downloads from blocking the
  queue.
- **No spam**: the search command is configurable, and requests are
  generated exactly from the hit list (no self-made constructs).

---

## Language

The plugin UI (window, buttons, columns, log and status messages)
automatically follows HexChat's language — German or English. It uses the
same locale priority as HexChat/gettext:
`LANGUAGE` → `LC_ALL` → `LC_MESSAGES` → `LANG`.

Note: a set `LANGUAGE` variable overrides `LANG`. To run German even
though the system locale is English:

    LANGUAGE=de hexchat

or permanently via a `.desktop` file or
`~/.config/environment.d/language.conf` with `LANGUAGE=de`.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `/ebookdl` → *Unknown command* | Plugin not loaded. Is `ebookdl.py` in `~/.config/hexchat/addons/`? Check with `/py list` (entry *EbookDL*), reload with `/py load /path/ebookdl.py`. HexChat must be connected once. |
| Window does not open, message *GUI bindings missing* | Install `python3-gi` / `gir1.2-gtk-2.0` (Linux) or provide PyGObject (Windows). Search/download logic still works. |
| *ERROR: No channel* | Join a channel or set one in the settings. |
| Result ZIP arrives but no hits | Result file not found or parse error — check the log; consider raising the timeout. |
| Downloads stay at *requested* | The bot did not answer (offline/different name). The timeout marks the row as failed; check whether the bot is active in the channel. |
| File does not end up in the target folder | Check the target folder in the settings (write permissions); the plugin only moves files after a successful DCC transfer. |
| Multiple EbookDL windows after reloads | Since the single-instance guard only one instance is possible. To reload deliberately: close the EbookDL window, then `/py unload EbookDL` and `/py load /path/ebookdl.py`. |

---

## How it works (technical)

1. **Search**: the plugin sends the search command (default
   `@search <term>`) as a message to the channel. The bookz bots reply
   with a ZIP file via DCC (filename e.g.
   `SearchBot_results_for__term.txt.zip`).
2. **Detection**: HexChat reports incoming DCC transfers through the
   print events `DCC RECV Connect` and `DCC RECV Complete` (note:
   `DCC Offer` is the event for *outgoing* offers). EbookDL listens to
   these events, recognizes the result ZIP by its filename and parses it
   in a background thread.
3. **Parsing**: the ZIP contains a text file with lines like
   `!bot id | file.pdf ::INFO:: 49.78MB`. The plugin extracts filename,
   size and bot nick and builds the list from them.
4. **Download**: for checked rows, the part before `::INFO::` (the `!`
   request) is sent as a message. The bot sends the file via DCC; the
   row is matched via bot nick → filename → FIFO. After receiving, the
   plugin moves the file to the target folder (ZIPs are extracted).
5. **Netiquette**: the queue strictly sends one request per interval and
   limits parallel transfers (see above).

### Important HexChat Python API findings (for developers)

- In print-hook callbacks the `word[]` array starts with the **first
  argument** of the event (`word[0]` = $1) — the event name is NOT in
  the array (the Python bridge shifts it; in the C API it differs).
  Example `DCC RECV Connect` → `word = [nick, host, filename]`.
- **`DCC Offer` does not fire for incoming files** (only for outgoing
  offers). Incoming transfers: `DCC RECV Connect` (start) and
  `DCC RECV Complete` (done; `word = [filename, target, nick, cps]`).
- Event names (hookable) exactly as in `src/common/textevents.in`.
- **Gtk2 typelib limits** (Ubuntu): many constructors take no arguments
  (`Gtk.TreeView(model)` etc. fail) — the plugin therefore consistently
  uses the `Widget()` + setter pattern. `Gtk.Dialog().run()` can cause a
  segfault in the HexChat context — the settings therefore use their own
  window with OK/Cancel buttons.
- `/py reload` leaves old windows behind as "zombies" with still
  registered hooks (GTK keeps the plugin objects alive) — for testing use
  `unload` + `load` or a restart.
- The Python API has **no** `hexchat.set_prefs` — preferences
  (`dcc_auto_recv` etc.) are set via `/set` through `hexchat.command()`.

---

## Development & tests

The plugin is a single Python script (no build needed).

    python3 test_ebookdl.py          # unit tests (HexChat stub, no GUI/IRC)

Structure:

- `ebookdl.py` – the plugin (hooks, queue, parser, GUI)
- `test_ebookdl.py` – test harness with a mocked `hexchat` module
- `screenshots/` – screenshots for the documentation

---

## License & disclaimer

MIT license, see [LICENSE](LICENSE). Copyright © 2026 Kalrkloss.

This project is a tool for automating public IRC channel functions.
Please follow the rules of the network/channel you use; the author
accepts no liability for its use or for the downloaded content.
