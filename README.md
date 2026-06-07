# V01D Audio Reader — Ebook to Audio Read-Along Tool

> **Read and listen simultaneously.** Open any book, hit play, and watch every sentence highlight in real time as it's spoken aloud. A fully local, offline-capable audiobook player and e-reader in a single Python file.

---

## ✨ Features

### Read-Along Highlighting
- **Sentence-level** green highlight tracks the current spoken sentence
- **Word-level** bold highlight tracks the current spoken word within the sentence
- Highlights are time-locked to actual audio playback — no drift
- **Auto-scroll** follows playback automatically (toggle on/off)

### Text-to-Speech
- Auto-detects the best available engine on your system:
  - **Piper TTS** (best quality — 100+ voices, downloads on demand)
  - **espeak-ng / espeak** (Linux)
  - **say** (macOS built-in)
  - **SAPI** (Windows built-in)
  - **Silent mode** — highlights still work with no audio
- Piper installs via `TTS → Install / update Piper TTS`
- Full **Voice Settings** dialog: browse 100+ voices, filter by language, download & switch instantly
- Sliders for **Speed**, **Expressiveness**, and **Cadence**
- Settings persist across sessions

### E-Reader
- Supports **PDF, EPUB, TXT, MD, HTML, JSON**
- Auto-detects **Table of Contents** — chapter list in the right panel, click to jump
- **Double-click** anywhere in the text to seek playback to that exact spot
- **Search** finds all results at once, shows `1/N` count, ◀ ▶ step through and jump playback to each hit
- Font size zoom (A- / A+), word wrap toggle
- Remembers your last reading position per book

### Library
- Auto-indexes books on startup (looks in the same folder as the script, `~/Downloads`, `~/Desktop`)
- Persistent library saved to `~/.audioreader/library.json`
- Double-click to open, right-click to remove

### Export
- **File → Export audio…** renders the full book to audio
- Export as **MP3** (via `lameenc`, auto-installed) or **WAV**
- Choose output directory with a folder browser
- Custom filename (auto-filled from book title)
- MP3 bitrate selector: 96 / 128 / 160 / **192** / 256 / 320 kbps
- Progress shown inline; opens export folder when done

---

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/yourusername/V01D-Audio-Reader.git
cd V01D-Audio-Reader

# Run — no pip installs required for basic use
python3 audioreader.py
```

**That's it.** On first run it detects your TTS engine and loads any books it finds next to the script.

To get the best voice quality, go to **TTS → Install / update Piper TTS** after launch.

---

## 📋 Requirements

| Requirement | Notes |
|---|---|
| Python 3.9+ | Standard library only for core features |
| tkinter | Included with most Python installs. Linux: `sudo apt install python3-tk` |
| `pypdf` *(optional)* | PDF text extraction. `pip install pypdf` |
| `piper-tts` *(optional)* | Best voice quality. Install via the TTS menu in-app |
| `lameenc` *(optional)* | MP3 export. Auto-installs when you first export to MP3 |

No internet required after initial voice download. All processing is local.

---

## 🖥️ Platform Notes

| Platform | TTS Engine | Notes |
|---|---|---|
| **Linux** | Piper → espeak-ng → espeak | `sudo apt install espeak-ng` for fallback |
| **macOS** | Piper → say | `say` is built-in; Piper gives much better quality |
| **Windows** | Piper → SAPI | SAPI uses Windows built-in voices |

---

## 📁 File Layout

```
V01D-Audio-Reader/
├── audioreader.py          # The entire app — single file
├── README.md
├── LICENSE
├── .gitignore
└── books/                  # Optional: drop your PDFs/EPUBs here
    └── (your books)
```

User data is stored in `~/.audioreader/`:
```
~/.audioreader/
├── library.json            # Book library + reading positions
├── config.json             # TTS settings (voice, speed, etc.)
└── piper_voices/           # Downloaded Piper voice models
    ├── en_US-lessac-medium.onnx
    └── en_US-lessac-medium.onnx.json
```

---

## 🎛️ Controls

| Action | How |
|---|---|
| Play / Pause | **▶ / ⏸** button or `Space` |
| Stop | **⏹** button or `Escape` |
| Previous chapter | **⏮** |
| Next chapter | **⏭** |
| Seek to position | Drag the position slider |
| Seek to word | **Double-click** anywhere in the text |
| Open file | `Ctrl+O` or **File → Open** |
| Search | Type in Find box — all results highlight, ◀ ▶ to step |
| Zoom text | **A-** / **A+** buttons |
| Toggle auto-scroll | **↕ Auto** button in control bar |
| Export audio | **File → Export audio…** |
| Voice settings | **TTS → Voice Settings…** |

---

## 🔊 Piper Voices

[Piper TTS](https://github.com/rhasspy/piper) provides the best voice quality. The default voice is `en_US-lessac-medium`. To use a different voice:

1. Go to **TTS → Voice Settings…**
2. Click **Refresh** to load the full catalog (~300 voices, 40+ languages)
3. Filter by language code (e.g. `en`, `es`, `fr`, `de`)
4. Select a voice and click **⬇ Download & Use**

Voices are cached in `~/.audioreader/piper_voices/` and work offline once downloaded.

---

## 📚 Bundled Book Detection

On startup, the app scans for books in these locations (in order):

1. Same directory as `audioreader.py`
2. `~/Downloads`
3. `~/Desktop`

Any PDF, EPUB, TXT, MD, HTML, or JSON file found is added to the library automatically. The following public-domain titles are recognized by name if present:

- *A Voice from the South* — Anna Julia Cooper
- *Book of Wise Sayings*
- *Breadcrumbs — Spiritual and Philosophical Essays*
- *Fifteen Thousand Useful Phrases*
- *How to Use Your Mind*
- *Practical Stoicism* — Grey Freeman
- *Self-Help* — Samuel Smiles
- *The Analysis of Mind* — Bertrand Russell
- *The Bible*
- *The Power of Concentration*

---

## 🔧 Troubleshooting

**"No audio / silent mode"**
Install a TTS engine: `sudo apt install espeak-ng` (Linux), or use the in-app Piper installer.

**PDF shows garbled text**
Install pypdf: `pip install pypdf`

**MP3 export fails**
Go to **File → Export audio…**, click Export — it will auto-install `lameenc`. Or install manually: `pip install lameenc`

**tkinter not found (Linux)**
`sudo apt install python3-tk`

**Piper download fails**
Check your internet connection. The app will fall back to any already-downloaded voice, or to espeak if none are cached.

---

## 📄 License

MIT License — see [LICENSE](LICENSE)

---

## 🙏 Credits

- [Piper TTS](https://github.com/rhasspy/piper) — neural TTS engine
- [pypdf](https://github.com/py-pdf/pypdf) — PDF extraction
- [lameenc](https://github.com/niccokunzmann/lameenc) — MP3 encoding
- Public domain books via [Project Gutenberg](https://www.gutenberg.org) and [Standard Ebooks](https://standardebooks.org)
