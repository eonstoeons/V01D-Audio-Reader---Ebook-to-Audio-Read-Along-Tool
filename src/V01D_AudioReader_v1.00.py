#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V01D AudioReader v1.2  —  single-file · stdlib + tkinter · zero hard deps
Simultaneous e-reader + real-time word/sentence highlighting synced to TTS.
TTS backends (auto-detected): piper > espeak-ng > espeak > say (mac) > sapi (win) > silent
Piper auto-installs via TTS menu. All 12 bundled books load on startup.
"""
from __future__ import annotations
import os, sys, re, io, wave, json, time, zipfile
import threading, subprocess, tempfile, textwrap, html.parser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple, Optional, Dict

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

def _ensure_lameenc() -> bool:
    """Try to import lameenc; pip-install it if missing. Returns True if available."""
    try: import lameenc; return True
    except ImportError: pass
    try:
        subprocess.run([sys.executable,"-m","pip","install","--user",
                        "--no-input","lameenc","--break-system-packages"],
                       capture_output=True,timeout=120,check=True)
        import importlib, site
        try: site.main()
        except: pass
        us=site.getusersitepackages()
        if us and us not in sys.path: sys.path.insert(0,us)
        import lameenc; return True
    except Exception: return False

def wav_to_mp3(wav_path: Path, mp3_path: Path, bitrate: int=192,
               progress=None, cancel=None) -> None:
    """Convert WAV to MP3 using lameenc (pure-Python, no ffmpeg needed)."""
    import lameenc
    with wave.open(str(wav_path),"rb") as wf:
        ch=wf.getnchannels(); sr=wf.getframerate()
        sw=wf.getsampwidth(); nf=wf.getnframes()
        if sw!=2: raise RuntimeError("Need 16-bit PCM WAV")
        enc=lameenc.Encoder()
        enc.set_bit_rate(bitrate); enc.set_in_sample_rate(sr)
        enc.set_channels(ch); enc.set_quality(2)
        fpb=sr; bpb=fpb*ch*sw; total=nf*ch*sw; done=0
        tmp=mp3_path.with_suffix(".mp3.part")
        mp3_path.parent.mkdir(parents=True,exist_ok=True)
        with open(tmp,"wb") as out:
            while True:
                if cancel and cancel(): raise InterruptedError("Cancelled")
                data=wf.readframes(fpb)
                if not data: break
                out.write(enc.encode(data))
                done+=len(data)
                if progress and total:
                    progress(f"Encoding MP3… {int(100*done/total)}%",done/total)
            out.write(enc.flush())
        tmp.replace(mp3_path)
        if progress: progress("MP3 done.",1.0)

# ── constants ─────────────────────────────────────────────────────────────────
APP  = "V01D AudioReader"
VER  = "1.2"
DIR  = Path.home() / ".audioreader"
LIB  = DIR / "library.json"
DIR.mkdir(parents=True, exist_ok=True)
VOICES_DIR       = DIR / "piper_voices"
CFG_FILE         = DIR / "config.json"
VOICES_CATALOG   = "https://huggingface.co/rhasspy/piper-voices/raw/main/voices.json"
VOICES_FILE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
FALLBACK_VOICE   = "en_US-lessac-medium"
VOICES_DIR.mkdir(parents=True, exist_ok=True)

BG="#0d0d0d"; PNL="#141414"; PNL2="#1c1c1c"; FG="#e8e8e8"; DIM="#555"
ACC="#00ff88"; ACC2="#0088ff"; HL_BG="#003322"; HL_FG="#00ff88"
WD_BG="#005533"; WD_FG="#fff"; SM=("Courier",9); MN=("Courier",12)

BOOKS = [
    "anna-julia-cooper_a-voice-from-the-south.pdf",
    "Book-of-Wise-Sayings.pdf",
    "Breadcrumbs-A-Collection-of-Spiritual-and-Philosophical-Essays.pdf",
    "Fifteen-Thousand-Useful-Phrases.pdf",
    "How-to-Use-Your-Mind.pdf",
    "Practical_Stoicism_-_Grey_Freeman.pdf",
    "Self-Help.pdf",
    "The-Analysis-of-Mind.pdf",
    "The-Bible.pdf",
    "The-Power-of-Concentration.pdf",
    "arts.txt",
    "decor.txt",
]
SEARCH_DIRS = [
    Path(__file__).parent,
    Path.home()/"Downloads",
    Path.home()/"Desktop",
    Path("/mnt/user-data/uploads"),
]

# ── text extraction ───────────────────────────────────────────────────────────
def extract_text(path: Path) -> str:
    try:
        x = path.suffix.lower()
        if x == ".pdf":            return _pdf(path)
        if x == ".epub":           return _epub(path)
        if x in (".html",".htm"): return _html(path.read_bytes())
        if x == ".json":           return _json(path)
        return _plain(path)
    except Exception as e:
        return f"[Error: {e}]"

def _plain(p: Path) -> str:
    raw = p.read_bytes()
    for enc in ("utf-8","utf-8-sig","utf-16","cp1252","latin-1"):
        try: return raw.decode(enc)
        except: pass
    return raw.decode("utf-8", errors="replace")

def _pdf(p: Path) -> str:
    try:
        import pypdf
        pages = []
        for pg in pypdf.PdfReader(str(p)).pages:
            try:
                t = pg.extract_text() or ""
                if t.strip(): pages.append(t)
            except: pass
        return "\n\n".join(pages)
    except ImportError: pass
    # raw fallback
    chunks = re.findall(rb'\(([^\)]{2,300})\)', p.read_bytes())
    out = []
    for c in chunks:
        try:
            t = c.decode("latin-1")
            if sum(32<=ord(ch)<127 for ch in t)/max(len(t),1) > .7: out.append(t)
        except: pass
    return " ".join(out)

def _epub(p: Path) -> str:
    parts = []
    try:
        with zipfile.ZipFile(p) as z:
            ns  = {"o":"http://www.idpf.org/2007/opf"}
            opf = next((n for n in z.namelist() if n.endswith(".opf")), None)
            order = []
            if opf:
                try:
                    root = ET.fromstring(z.read(opf))
                    mf   = {i.get("id"):i.get("href","") for i in root.findall(".//o:item",ns)}
                    for ir in root.findall(".//o:itemref",ns):
                        h = mf.get(ir.get("idref",""),"")
                        if h: order.append(h)
                except: pass
            html_f = [n for n in z.namelist() if n.endswith((".xhtml",".html",".htm"))]
            if order:
                ordered = [next((n for n in html_f if n.endswith(h)),None) for h in order]
                html_f  = [x for x in ordered if x] or html_f
            for n in html_f: parts.append(_html(z.read(n)))
    except Exception as e: parts.append(f"[EPUB error: {e}]")
    return "\n\n".join(p for p in parts if p.strip())

class _Strip(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(); self._b=[]; self._sk=False
    def handle_starttag(self,t,a):
        if t in ("script","style"): self._sk=True
        if t in ("p","div","br","li","h1","h2","h3","h4","h5","h6","tr"):
            self._b.append("\n")
    def handle_endtag(self,t):
        if t in ("script","style"): self._sk=False
    def handle_data(self,d):
        if not self._sk: self._b.append(d)
    def text(self): return "".join(self._b)

def _html(raw: bytes) -> str:
    for enc in ("utf-8","latin-1"):
        try: s=raw.decode(enc); break
        except: pass
    else: s=raw.decode("utf-8",errors="replace")
    p=_Strip()
    try: p.feed(s)
    except: pass
    t=p.text()
    for a,b in [("&nbsp;"," "),("&amp;","&"),("&lt;","<"),("&gt;",">"),
                ("&quot;",'"'),("&#39;","'")]:
        t=t.replace(a,b)
    return re.sub(r"\n{3,}","\n\n",t)

def _json(p: Path) -> str:
    try:
        data=json.loads(p.read_text(encoding="utf-8",errors="replace"))
        def j(o):
            if isinstance(o,str): return o
            if isinstance(o,(int,float,bool)) or o is None: return str(o)
            if isinstance(o,list): return "\n".join(j(x) for x in o)
            if isinstance(o,dict): return "\n".join(f"{k}: {j(v)}" for k,v in o.items())
            return ""
        return j(data)
    except: return _plain(p)

# ── TOC + metadata ────────────────────────────────────────────────────────────
_TOC_PATS = [
    re.compile(r'^#{1,3}\s+(.+)$', re.M),
    re.compile(r'^(Chapter|CHAPTER|Part|PART|Section|SECTION)\s+[\dIVXivx]+[.:)—\s].*$', re.M),
    re.compile(r'^([A-Z][A-Z\s\d:,\'".—\-]{3,78})$', re.M),
    re.compile(r'^(\d{1,2}\.\s+[A-Z][^\n]{3,60})$', re.M),
]

def extract_toc(text: str) -> List[Tuple[str,int]]:
    toc=[]; seen=set()
    for pat in _TOC_PATS:
        for m in pat.finditer(text):
            c = re.sub(r'^#+\s*',"",m.group(0).strip()).strip()
            if not c or c in seen or not 3<=len(c)<=120: continue
            seen.add(c); toc.append((c, m.start()))
    toc.sort(key=lambda x:x[1])
    out=[]; prev=-200
    for e in toc:
        if e[1]-prev>100: out.append(e); prev=e[1]
    return out[:500]

def extract_meta(path: Path, text: str) -> Dict[str,str]:
    m = {"title":path.stem,"path":str(path),
         "size":f"{path.stat().st_size//1024} KB",
         "words":str(len(re.findall(r'\b\w+\b',text[:50000]))),
         "fmt":path.suffix.upper().lstrip(".")}
    for line in text.splitlines():
        s=line.strip()
        if s and len(s)<120: m["title"]=s[:80]; break
    mo=re.search(r'(?:by|By|BY)\s+([A-Z][a-zA-Z\s\.,]{3,60})',text[:2000])
    if mo: m["author"]=mo.group(1).strip()
    return m

# ── sentence tokenizer ────────────────────────────────────────────────────────
def tokenize(text: str) -> List[Tuple[int,int]]:
    splits=[0]
    for m in re.finditer(r'(?<=[.!?])[ \t]+(?=[A-Z"\(\[])|(?<=\n)\n+',text):
        splits.append(m.end())
    splits.append(len(text))
    spans=[]
    for i in range(len(splits)-1):
        s,e = splits[i],splits[i+1]
        chunk=text[s:e]
        if len(chunk)>500:
            sub=[s]
            for m2 in re.finditer(r'[.!?][ \t]+',chunk):
                sub.append(s+m2.end())
            sub.append(e)
            for j in range(len(sub)-1):
                if text[sub[j]:sub[j+1]].strip():
                    spans.append((sub[j],sub[j+1]))
        elif chunk.strip():
            spans.append((s,e))
    return spans

# ── silence / wav util ────────────────────────────────────────────────────────
def _sil(secs: float) -> bytes:
    SR=22050; n=int(SR*max(0.05,secs))
    buf=io.BytesIO()
    with wave.open(buf,"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes(b"\x00\x00"*n)
    return buf.getvalue()

def _dur(wav: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav)) as w: return w.getnframes()/w.getframerate()
    except: return 0.5

# ── TTS engine ────────────────────────────────────────────────────────────────
class TTS:
    """
    TTS engine with full Piper voice catalog support.
    Priority: piper > espeak-ng > espeak > say (mac) > sapi (win) > silent
    Offline fallback: uses any already-downloaded .onnx voice, or silent timing mode.
    """
    def __init__(self):
        self._rate   = 175
        self._noise  = 0.667   # expressiveness
        self._noise_w= 0.8     # cadence
        self._voice  = None    # loaded PiperVoice
        self._vkey   = None    # active voice key e.g. "en_US-lessac-medium"
        self._catalog: dict = {}
        self._back   = self._probe()
        self._load_cfg()

    # ── config persistence ───────────────────────────────────────────────────
    def _load_cfg(self):
        try:
            if CFG_FILE.exists():
                c=json.loads(CFG_FILE.read_text(encoding="utf-8"))
                self._rate    = int(c.get("rate",   175))
                self._noise   = float(c.get("noise",  0.667))
                self._noise_w = float(c.get("noise_w",0.8))
                self._vkey    = c.get("voice_key", None)
        except: pass

    def save_cfg(self):
        try:
            c={"rate":self._rate,"noise":self._noise,
               "noise_w":self._noise_w,"voice_key":self._vkey}
            CFG_FILE.write_text(json.dumps(c,indent=2),encoding="utf-8")
        except: pass

    # ── backend detection ────────────────────────────────────────────────────
    def _probe(self) -> str:
        try: from piper import PiperVoice; return "piper"  # type: ignore
        except ImportError: pass
        for c in ("espeak-ng","espeak"):
            if self._ex(c): return c
        if sys.platform=="darwin" and self._ex("say"): return "say"
        if sys.platform=="win32": return "sapi"
        return "silent"

    @staticmethod
    def _ex(c):
        try: return subprocess.run(["which",c],capture_output=True,timeout=3).returncode==0
        except: return False

    # ── setters ──────────────────────────────────────────────────────────────
    def set_rate(self,wpm):    self._rate=max(80,min(400,int(float(wpm))))
    def set_noise(self,v):     self._noise=max(0.0,min(1.0,float(v)))
    def set_noise_w(self,v):   self._noise_w=max(0.0,min(1.5,float(v)))

    # ── catalog ──────────────────────────────────────────────────────────────
    def fetch_catalog(self, cb=None) -> dict:
        """Fetch voice catalog from HuggingFace; falls back to cached copy."""
        cache = VOICES_DIR / "voices_catalog.json"
        try:
            import urllib.request
            if cb: cb("Fetching voice catalog…")
            req = urllib.request.Request(VOICES_CATALOG,
                  headers={"User-Agent":"V01D-AudioReader/1.2"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode())
            cache.write_text(json.dumps(data),encoding="utf-8")
            self._catalog = data
            return data
        except Exception:
            if cache.exists():
                try:
                    self._catalog = json.loads(cache.read_text(encoding="utf-8"))
                    return self._catalog
                except: pass
        return {}

    def list_voices(self, lang_filter="en") -> list:
        """Return sorted list of voice dicts for display."""
        cat = self._catalog or self.fetch_catalog()
        rows = []
        for key, info in cat.items():
            lc = (info.get("language") or {}).get("code","")
            if lang_filter and not lc.startswith(lang_filter): continue
            name    = info.get("name", key)
            quality = info.get("quality","?")
            lang_n  = (info.get("language") or {}).get("name_english","")
            country = (info.get("language") or {}).get("country_english","")
            display = f"{name}  ·  {lang_n}"
            if country and country!=lang_n: display += f" ({country})"
            display += f"  ·  {quality}"
            rows.append({"key":key,"display":display,"quality":quality,
                         "files":info.get("files",{}),"name":name})
        q_ord={"high":0,"medium":1,"low":2,"x_low":3}
        rows.sort(key=lambda v:(q_ord.get(v["quality"],9),v["name"]))
        return rows

    def is_downloaded(self, key: str) -> bool:
        onnx = VOICES_DIR / f"{key}.onnx"
        conf = VOICES_DIR / f"{key}.onnx.json"
        return onnx.exists() and onnx.stat().st_size>10000 and conf.exists()

    def download_voice(self, key: str, cb=None):
        """Download a voice by key. Raises on error."""
        cat = self._catalog or self.fetch_catalog(cb)
        if key not in cat:
            raise ValueError(f"Unknown voice key: {key}")
        files = cat[key].get("files",{})
        import urllib.request
        for rel, _info in files.items():
            if not (rel.endswith(".onnx") or rel.endswith(".onnx.json")): continue
            dest = VOICES_DIR / Path(rel).name
            if dest.exists() and dest.stat().st_size>1000: continue
            url  = VOICES_FILE_BASE + rel
            if cb: cb(f"Downloading {dest.name}…")
            tmp  = dest.with_suffix(dest.suffix+".part")
            urllib.request.urlretrieve(url, str(tmp))
            tmp.replace(dest)

    # ── voice loading ─────────────────────────────────────────────────────────
    def ensure_voice(self, key: str|None=None, cb=None) -> bool:
        """
        Load a piper voice. Order of preference:
          1. Requested key (download if needed)
          2. Any already-downloaded voice (offline fallback)
          3. FALLBACK_VOICE download attempt
          4. Return False (silent mode)
        """
        if self._back != "piper": return False
        target = key or self._vkey or FALLBACK_VOICE

        # Already loaded the right voice
        if self._voice is not None and self._vkey == target:
            return True

        from piper import PiperVoice  # type: ignore

        # Try to ensure target is downloaded
        if not self.is_downloaded(target):
            try:
                self.download_voice(target, cb)
            except Exception as e:
                if cb: cb(f"Download failed: {e}  — trying offline fallback…")
                # Find any already-downloaded voice
                existing = [f.stem for f in VOICES_DIR.glob("*.onnx")
                            if f.stat().st_size>10000]
                if existing:
                    target = existing[0]
                    if cb: cb(f"Using cached voice: {target}")
                else:
                    if cb: cb("No voices available — using silent timing mode.")
                    return False

        try:
            if cb: cb(f"Loading {target}…")
            onnx = VOICES_DIR / f"{target}.onnx"
            self._voice = PiperVoice.load(str(onnx))
            self._vkey  = target
            self.save_cfg()
            if cb: cb(f"Voice ready: {target}")
            return True
        except Exception as e:
            if cb: cb(f"Voice load error: {e}")
            return False

    # ── synthesis ─────────────────────────────────────────────────────────────
    def synth(self, text: str) -> bytes:
        text=text.strip()
        if not text: return _sil(0.2)
        try:
            b=self._back
            if b=="piper":               return self._piper(text)
            if b in ("espeak-ng","espeak"): return self._espeak(text)
            if b=="say":                 return self._say(text)
            if b=="sapi":                return self._sapi(text)
        except: pass
        return _sil(len(text.split())/max(1,self._rate/60))

    def _piper(self, text: str) -> bytes:
        if self._voice is None: return _sil(0.5)
        from piper import SynthesisConfig  # type: ignore
        sc=SynthesisConfig(
            length_scale=max(0.5,min(2.0,175/max(1,self._rate))),
            noise_scale=self._noise,
            noise_w_scale=self._noise_w)
        buf=io.BytesIO()
        with wave.open(buf,"wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(self._voice.config.sample_rate)
            for chunk in self._voice.synthesize(text,syn_config=sc):
                wf.writeframes(chunk.audio_int16_bytes)
        return buf.getvalue()

    def _espeak(self, text: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as f: tmp=f.name
        try:
            r=subprocess.run([self._back,"-s",str(self._rate),"-w",tmp,text],
                             capture_output=True,timeout=30)
            if r.returncode==0:
                d=Path(tmp).read_bytes()
                if d: return d
        finally:
            try: os.unlink(tmp)
            except: pass
        return _sil(0.5)

    def _say(self, text: str) -> bytes:
        ta=tempfile.mktemp(suffix=".aiff"); tw=tempfile.mktemp(suffix=".wav")
        try:
            subprocess.run(["say","-r",str(int(self._rate*1.2)),"-o",ta,text],
                           capture_output=True,timeout=30)
            subprocess.run(["afconvert","-f","WAVE","-d","LEI16@22050",ta,tw],
                           capture_output=True,timeout=10)
            if Path(tw).exists():
                d=Path(tw).read_bytes()
                if d: return d
        finally:
            for t in(ta,tw):
                try: os.unlink(t)
                except: pass
        return _sil(0.5)

    def _sapi(self, text: str) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav",delete=False) as f: tmp=f.name
        r=max(-10,min(10,(self._rate-175)//15))
        ps=(f'Add-Type -AssemblyName System.Speech;'
            f'$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;'
            f'$s.Rate={r};$s.SetOutputToWaveFile("{tmp}");'
            f'$s.Speak("{text}");$s.Dispose();')
        try:
            subprocess.run(["powershell","-Command",ps],capture_output=True,timeout=30)
            if Path(tmp).exists():
                d=Path(tmp).read_bytes()
                if d: return d
        finally:
            try: os.unlink(tmp)
            except: pass
        return _sil(0.5)

    @property
    def backend(self): return self._back

    @property
    def active_voice(self): return self._vkey or FALLBACK_VOICE


# ── audio player ──────────────────────────────────────────────────────────────
class Player:
    """
    Thin WAV-playback wrapper. One subprocess at a time.
    stop() kills audio and waits. done_cb fires ONLY on natural finish.
    play() always hard-stops any prior playback before starting new.
    """
    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._thr:  Optional[threading.Thread] = None
        self._kill  = threading.Event()
        self._lock  = threading.Lock()
        self._cmd   = self._detect()

    def _detect(self):
        if sys.platform == "win32": return None
        if sys.platform == "darwin":
            if self._ex("afplay"): return ["afplay"]
        for c, x in [("aplay",[]),("paplay",[]),
                     ("ffplay",["-nodisp","-autoexit","-loglevel","quiet"])]:
            if self._ex(c): return [c]+x
        return None

    @staticmethod
    def _ex(c):
        try: return subprocess.run(["which",c],capture_output=True,timeout=3).returncode==0
        except: return False

    def play(self, wav: bytes, done_cb=None):
        self._kill_wait()          # hard-stop any prior audio and wait
        self._kill.clear()         # arm for new playback
        def _run():
            self._play_wav(wav)
            if done_cb and not self._kill.is_set():
                done_cb()
        self._thr = threading.Thread(target=_run, daemon=True)
        self._thr.start()

    def stop(self):
        self._kill_wait()
        # leave _kill SET so any racing done_cb sees it and no-ops

    def _kill_wait(self):
        self._kill.set()
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try: self._proc.terminate()
                except: pass
        cur = threading.current_thread()
        if self._thr and self._thr.is_alive() and self._thr is not cur:
            self._thr.join(timeout=1.5)

    def _play_wav(self, wav: bytes):
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(wav, winsound.SND_MEMORY)
            except: pass
            return
        if self._cmd:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav); tmp = f.name
            try:
                with self._lock:
                    self._proc = subprocess.Popen(
                        self._cmd + [tmp],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while self._proc.poll() is None:
                    if self._kill.is_set():
                        self._proc.terminate(); break
                    time.sleep(0.02)
            finally:
                with self._lock: self._proc = None
                try: os.unlink(tmp)
                except: pass
        else:
            try:
                import ossaudiodev
                buf = io.BytesIO(wav)
                with wave.open(buf) as wf:
                    sr=wf.getframerate(); sw=wf.getsampwidth()
                    ch=wf.getnchannels(); data=wf.readframes(wf.getnframes())
                dsp = ossaudiodev.open("w")
                fmt = {1:ossaudiodev.AFMT_S8,
                       2:ossaudiodev.AFMT_S16_LE}.get(sw,ossaudiodev.AFMT_S16_LE)
                dsp.setparameters(fmt, ch, sr)
                pos = 0
                while pos < len(data):
                    if self._kill.is_set(): break
                    dsp.write(data[pos:pos+4096]); pos += 4096
                dsp.close()
            except: pass
# ── playback controller ───────────────────────────────────────────────────────
class Controller:
    """
    Sentence loop with generation counter to eliminate all race conditions.

    _gen increments on every stop/seek/pause.
    Every async callback (done_cb, prefetch, word highlights) captures _gen
    at creation time and no-ops if the current _gen has moved on.
    This makes all in-flight work self-invalidating on any state change.
    """
    def __init__(self, tts, player, root, on_sent, on_word, on_done):
        self.tts    = tts
        self.player = player
        self.root   = root
        self._on_sent = on_sent
        self._on_word = on_word
        self._on_done = on_done
        self._text  = ""; self._sents = []; self._idx = 0
        self._run   = False; self._paused = False
        self._gen   = 0
        self._mu    = threading.Lock()
        self._resume_ev = threading.Event(); self._resume_ev.set()
        self._thr   = None
        self._cache = {}

    def load(self, text, sents, idx=0):
        self._halt()
        with self._mu:
            self._text = text; self._sents = sents
            self._idx  = max(0, min(idx, len(sents)-1 if sents else 0))
            self._run  = False; self._paused = False
        self._cache.clear()

    def play(self):
        with self._mu:
            if self._run: return
            self._run = True; self._paused = False
            self._resume_ev.set()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def pause(self):
        with self._mu:
            if not self._run or self._paused: return
            self._paused = True
            self._gen   += 1
            self._resume_ev.clear()
        self.player.stop()

    def resume(self):
        with self._mu:
            if not self._paused: return
            self._paused = False
            self._resume_ev.set()

    def stop(self):
        self._halt()
        self.player.stop()

    def seek(self, idx):
        was = self._run
        self._halt()
        self.player.stop()
        with self._mu:
            self._idx = max(0, min(idx, len(self._sents)-1 if self._sents else 0))
        if was:
            self.play()

    def _halt(self):
        with self._mu:
            self._run    = False
            self._paused = False
            self._gen   += 1
            self._resume_ev.set()
        cur = threading.current_thread()
        if self._thr and self._thr.is_alive() and self._thr is not cur:
            self._thr.join(timeout=2.0)

    def _loop(self):
        while True:
            with self._mu:
                if not self._run: break
                paused = self._paused
                gen    = self._gen
                idx    = self._idx

            if paused:
                self._resume_ev.wait(timeout=0.05)
                continue

            if idx >= len(self._sents):
                self.root.after(0, self._on_done); break

            s, e  = self._sents[idx]
            chunk = self._text[s:e]
            self.root.after(0, self._on_sent, idx)

            # synth
            if idx not in self._cache:
                self._cache[idx] = self.tts.synth(chunk)
                nxt = idx + 1
                if nxt < len(self._sents) and nxt not in self._cache:
                    _s, _e = self._sents[nxt]; _ch = self._text[_s:_e]
                    def _pre(i=nxt, c=_ch, g=gen):
                        with self._mu:
                            if self._gen != g: return
                        self._cache[i] = self.tts.synth(c)
                    threading.Thread(target=_pre, daemon=True).start()

            wav = self._cache[idx]
            dur = _dur(wav)

            # word highlights — gated by gen
            words = list(re.finditer(r'\S+', chunk))
            if words and dur > 0.05:
                pw = dur / len(words); t0 = time.monotonic()
                def _w(wi=0, _wds=words, _ss=s, _pw=pw, _t0=t0, _g=gen):
                    with self._mu:
                        if self._gen != _g: return
                    if wi >= len(_wds): return
                    wm = _wds[wi]
                    self.root.after(0, self._on_word, _ss+wm.start(), _ss+wm.end())
                    elapsed = time.monotonic() - _t0
                    delay   = max(1, int((_pw*(wi+1) - elapsed)*1000))
                    self.root.after(delay,
                        lambda wi=wi+1,_wds=_wds,_ss=_ss,_pw=_pw,_t0=_t0,_g=_g:
                            _w(wi,_wds,_ss,_pw,_t0,_g))
                self.root.after(0, _w)

            # play — done_cb gated by gen
            done_ev = threading.Event()
            def _cb(ev=done_ev, g=gen):
                with self._mu:
                    if self._gen != g: return
                ev.set()
            self.player.play(wav, done_cb=_cb)

            # wait
            while True:
                with self._mu:
                    if not self._run:    break
                    if self._gen != gen: break
                if done_ev.is_set():    break
                done_ev.wait(timeout=0.05)

            with self._mu:
                if not self._run:    break
                if self._gen != gen: continue
                if not self._paused:
                    self._idx += 1
# ── library ───────────────────────────────────────────────────────────────────
class Library:
    def __init__(self):
        self._books:List[Dict]=[]
        try:
            if LIB.exists():
                self._books=json.loads(LIB.read_text(encoding="utf-8"))
        except: pass

    def save(self):
        try: LIB.write_text(json.dumps(self._books,indent=2),encoding="utf-8")
        except: pass

    def add(self, meta: Dict):
        p=meta.get("path","")
        if any(b.get("path")==p for b in self._books): return
        self._books.insert(0,meta)
        if len(self._books)>200: self._books=self._books[:200]
        self.save()

    def remove(self, path: str):
        self._books=[b for b in self._books if b.get("path")!=path]; self.save()

    def update_pos(self, path: str, pos: int):
        for b in self._books:
            if b.get("path")==path: b["last_pos"]=pos; self.save(); return

    @property
    def books(self): return self._books

# ── piper installer ───────────────────────────────────────────────────────────
def install_piper(root: tk.Tk, on_done):
    win=tk.Toplevel(root); win.title("Installing Piper TTS")
    win.configure(bg=BG); win.geometry("460x160"); win.resizable(False,False)
    tk.Label(win,text="Installing piper-tts  (~30 MB, one-time)",
             bg=BG,fg=ACC,font=MN).pack(pady=(20,6))
    sv=tk.StringVar(value="Starting…")
    tk.Label(win,textvariable=sv,bg=BG,fg=FG,font=SM,wraplength=420).pack()
    pb=ttk.Progressbar(win,mode="indeterminate",length=400)
    pb.pack(pady=10); pb.start(12)
    def _work():
        def upd(s): root.after(0,sv.set,s)
        try:
            upd("Running pip install piper-tts…")
            r=subprocess.run(
                [sys.executable,"-m","pip","install","--user","--upgrade",
                 "--no-input","piper-tts","--break-system-packages"],
                capture_output=True,text=True,timeout=300)
            if r.returncode!=0:
                upd(f"pip failed: {r.stderr[-200:]}"); root.after(3000,win.destroy); return
            import site
            try: site.main()
            except: pass
            us=site.getusersitepackages()
            if us and us not in sys.path: sys.path.insert(0,us)
            upd("Done! Restart the app to use Piper.")
            root.after(1500,win.destroy); root.after(1600,on_done)
        except Exception as ex:
            upd(f"Error: {ex}"); root.after(3000,win.destroy)
    threading.Thread(target=_work,daemon=True).start()

# ── main app ──────────────────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.root=tk.Tk()
        self.root.title(f"{APP} {VER}")
        self.root.configure(bg=BG)
        self.root.geometry("1280x800"); self.root.minsize(800,500)
        self.root.protocol("WM_DELETE_WINDOW",self._close)

        self.tts=TTS(); self.player=Player(); self.lib=Library()
        self._text=""; self._sents=[]; self._toc=[]; self._meta={}
        self._path:Optional[Path]=None
        self._fs=tk.IntVar(value=12); self._wrap=tk.BooleanVar(value=True)
        self._speed=tk.IntVar(value=175)
        self._playing=False; self._paused=False; self._sent=0
        self._autoscroll=True
        self._find_hits=[]; self._find_pos=0  # search result tracking
        self._export_dir=tk.StringVar(value=str(Path.home()/"Downloads"))
        self._export_fmt=tk.StringVar(value="mp3")
        self._export_name=tk.StringVar(value="audioreader_export")
        self._export_br=tk.IntVar(value=192)
        self._export_busy=False

        self.ctrl=Controller(self.tts,self.player,self.root,
                             self._hl_sent,self._hl_word,self._play_done)
        self._build()
        self._st(f"TTS: {self.tts.backend}  |  Ready.")
        threading.Thread(target=self._scan_books,daemon=True).start()

    # ── bundled books scan ────────────────────────────────────────────────────
    def _scan_books(self):
        """Add bundled book paths to library without blocking on full text extraction."""
        for d in SEARCH_DIRS:
            if not d.exists(): continue
            for name in BOOKS:
                p=d/name
                if not p.exists(): continue
                # Check not already in library
                if any(b.get("path")==str(p) for b in self.lib.books): continue
                # Light metadata — no full extract, just path/size/title from filename
                meta={"title":p.stem.replace("_"," ").replace("-"," "),
                      "path":str(p),
                      "size":f"{p.stat().st_size//1024} KB",
                      "fmt":p.suffix.upper().lstrip(".")}
                self.root.after(0,self._add_meta,meta)

    def _add_meta(self, meta: Dict):
        self.lib.add(meta); self._refresh_lib()
        self._st(f"Library: {len(self.lib.books)} books  |  TTS: {self.tts.backend}")

    # ── UI build ──────────────────────────────────────────────────────────────
    def _build(self):
        self._menu()
        pw=tk.PanedWindow(self.root,orient=tk.HORIZONTAL,
                          bg=BG,sashwidth=4,sashrelief="flat")
        pw.pack(fill=tk.BOTH,expand=True,padx=4,pady=(2,0))
        self._lib_panel(pw); self._reader_panel(pw); self._toc_panel(pw)
        pw.paneconfigure(pw.panes()[0],minsize=150,width=185)
        pw.paneconfigure(pw.panes()[1],minsize=400)
        pw.paneconfigure(pw.panes()[2],minsize=150,width=210)
        self._ctrl_bar(); self._export_bar(); self._status_bar()

    def _menu(self):
        mc=dict(bg=PNL,fg=FG,activebackground=PNL2,activeforeground=ACC,bd=0,tearoff=False)
        mb=tk.Menu(self.root,**mc); self.root.config(menu=mb)
        fm=tk.Menu(mb,**mc); mb.add_cascade(label="File",menu=fm)
        fm.add_command(label="Open…  Ctrl+O",command=self._open)
        fm.add_command(label="Export audio…",command=self._show_export)
        fm.add_separator(); fm.add_command(label="Quit",command=self._close)
        tm=tk.Menu(mb,**mc); mb.add_cascade(label="TTS",menu=tm)
        tm.add_command(label="Voice Settings…",command=self._voice_settings)
        tm.add_separator()
        tm.add_command(label="Install / update Piper TTS",
                       command=lambda:install_piper(self.root,self._reinit))
        self.root.bind("<Control-o>",lambda _:self._open())
        self.root.bind("<Escape>",   lambda _:self._stop())

    def _lb(self,p,col=PNL) -> tk.Listbox:
        f=tk.Frame(p,bg=col,bd=0)
        lb=tk.Listbox(f,bg=col,fg=FG,selectbackground=HL_BG,selectforeground=HL_FG,
                      font=SM,relief="flat",bd=0,activestyle="none",highlightthickness=0)
        sb=tk.Scrollbar(f,orient=tk.VERTICAL,command=lb.yview,
                        bg=col,troughcolor=BG,bd=0,highlightthickness=0)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        sb.pack(side=tk.RIGHT,fill=tk.Y)
        f.pack(fill=tk.BOTH,expand=True)
        return lb

    def _lib_panel(self,pw):
        f=tk.Frame(pw,bg=PNL,bd=0); pw.add(f)
        h=tk.Frame(f,bg=PNL2); h.pack(fill=tk.X)
        tk.Label(h,text="LIBRARY",bg=PNL2,fg=ACC,font=SM).pack(side=tk.LEFT,padx=8,pady=6)
        tk.Button(h,text="+",bg=PNL2,fg=ACC,relief="flat",font=SM,
                  cursor="hand2",command=self._open).pack(side=tk.RIGHT,padx=6)
        self._lib_lb=self._lb(f)
        self._lib_lb.bind("<Double-Button-1>",self._lib_open)
        self._lib_lb.bind("<Return>",         self._lib_open)
        self._lib_lb.bind("<Button-3>",        self._lib_ctx)

    def _reader_panel(self,pw):
        f=tk.Frame(pw,bg=BG,bd=0); pw.add(f)
        tb=tk.Frame(f,bg=PNL2); tb.pack(fill=tk.X)
        def btn(t,cmd,fg=FG):
            tk.Button(tb,text=t,bg=PNL2,fg=fg,relief="flat",font=SM,
                      cursor="hand2",command=cmd).pack(side=tk.LEFT,padx=2,pady=4)
        btn("A-",lambda:self._zoom(-1))
        btn("A+",lambda:self._zoom(+1))
        ttk.Checkbutton(tb,text="Wrap",variable=self._wrap,
                        command=self._apply_wrap).pack(side=tk.LEFT,padx=6)
        tk.Label(tb,text="Find:",bg=PNL2,fg=DIM,font=SM).pack(side=tk.LEFT,padx=(8,2))
        self._sv=tk.StringVar()
        se=tk.Entry(tb,textvariable=self._sv,width=16,bg="#1a1a1a",fg=FG,
                    insertbackground=ACC,relief="flat",font=SM,bd=4)
        se.pack(side=tk.LEFT,padx=2)
        se.bind("<Return>",lambda _:self._find_next_result())
        self._sv.trace_add("write",lambda *_:self._find_all())
        btn("◀",self._find_prev_result,fg=ACC)
        btn("▶",self._find_next_result,fg=ACC)
        self._find_count_v=tk.StringVar(value="")
        tk.Label(tb,textvariable=self._find_count_v,bg=PNL2,fg=DIM,
                 font=SM).pack(side=tk.LEFT,padx=4)
        self._title_v=tk.StringVar(value="(no file)")
        tk.Label(tb,textvariable=self._title_v,bg=PNL2,fg=ACC2,
                 font=("Helvetica",10,"bold")).pack(side=tk.RIGHT,padx=12)
        # text area
        tf=tk.Frame(f,bg=BG); tf.pack(fill=tk.BOTH,expand=True)
        self._tw=tk.Text(tf,wrap=tk.WORD,bg="#080808",fg=FG,
                         insertbackground=ACC,selectbackground=PNL2,
                         font=("Courier",self._fs.get()),relief="flat",bd=0,
                         padx=16,pady=12,state=tk.NORMAL,spacing1=2,spacing3=4,
                         cursor="arrow")
        ysb=tk.Scrollbar(tf,orient=tk.VERTICAL,command=self._tw.yview,
                         bg=PNL,troughcolor=BG,bd=0,highlightthickness=0)
        xsb=tk.Scrollbar(f,orient=tk.HORIZONTAL,command=self._tw.xview,
                         bg=PNL,troughcolor=BG,bd=0,highlightthickness=0)
        self._tw.config(yscrollcommand=ysb.set,xscrollcommand=xsb.set)
        self._tw.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        ysb.pack(side=tk.RIGHT,fill=tk.Y)
        xsb.pack(side=tk.BOTTOM,fill=tk.X)
        # Block editing keys but keep widget interactive for clicks
        self._tw.bind("<Key>", lambda e: "break" if e.state&4==0 else None)
        self._tw.bind("<Double-Button-1>", self._tw_dbl_click)
        self._tw.bind("<Button-1>",        self._tw_click)
        self._tw.tag_configure("sent_hl",background=HL_BG,foreground=HL_FG)
        self._tw.tag_configure("word_hl",background=WD_BG,foreground=WD_FG,
                               font=("Courier",self._fs.get(),"bold"))
        self._tw.tag_configure("search",    background="#443300",foreground="#ffff00")
        self._tw.tag_configure("search_cur",background="#886600",foreground="#ffffff",
                               font=("Courier",self._fs.get(),"bold"))

    def _toc_panel(self,pw):
        f=tk.Frame(pw,bg=PNL,bd=0); pw.add(f)
        h=tk.Frame(f,bg=PNL2); h.pack(fill=tk.X)
        tk.Label(h,text="CONTENTS",bg=PNL2,fg=ACC,font=SM).pack(side=tk.LEFT,padx=8,pady=6)
        self._toc_lb=self._lb(f)
        self._toc_lb.bind("<Double-Button-1>",self._toc_jump)
        self._toc_lb.bind("<Return>",          self._toc_jump)

    def _ctrl_bar(self):
        c=tk.Frame(self.root,bg=PNL,pady=6); c.pack(fill=tk.X,side=tk.BOTTOM)
        bc=dict(bg=PNL2,fg=FG,relief="flat",font=("Courier",14),cursor="hand2",
                width=3,bd=0,activebackground=PNL,activeforeground=ACC)
        tk.Button(c,text="⏮",command=self._prev,**bc).pack(side=tk.LEFT,padx=(10,2))
        self._pbtn=tk.Button(c,text="▶",command=self._toggle,
                             **{**bc,"fg":ACC,"font":("Courier",18)})
        self._pbtn.pack(side=tk.LEFT,padx=2)
        tk.Button(c,text="⏹",command=self._stop,**bc).pack(side=tk.LEFT,padx=2)
        tk.Button(c,text="⏭",command=self._next,**bc).pack(side=tk.LEFT,padx=(2,10))
        tk.Label(c,text="Speed:",bg=PNL,fg=DIM,font=SM).pack(side=tk.LEFT,padx=(14,4))
        tk.Scale(c,variable=self._speed,from_=80,to=400,orient=tk.HORIZONTAL,
                 bg=PNL,fg=FG,troughcolor=PNL2,highlightthickness=0,length=110,
                 showvalue=True,font=SM,relief="flat",bd=0,
                 command=lambda v:self.tts.set_rate(int(float(v)))).pack(side=tk.LEFT)
        tk.Label(c,text="wpm",bg=PNL,fg=DIM,font=SM).pack(side=tk.LEFT,padx=2)
        self._asbtn=tk.Button(c,text="↕ Auto",bg=ACC,fg="#000",relief="flat",
                              font=SM,cursor="hand2",
                              command=self._toggle_autoscroll)
        self._asbtn.pack(side=tk.LEFT,padx=(12,2))
        self._pos_v=tk.StringVar(value="0%")
        tk.Label(c,textvariable=self._pos_v,bg=PNL,fg=ACC2,font=SM).pack(side=tk.RIGHT,padx=14)
        self._ss_v=tk.IntVar(value=0)
        self._ss=tk.Scale(c,variable=self._ss_v,from_=0,to=100,orient=tk.HORIZONTAL,
                          bg=PNL,fg=FG,troughcolor=PNL2,highlightthickness=0,length=250,
                          showvalue=False,relief="flat",bd=0,command=self._seek)
        self._ss.pack(side=tk.RIGHT,padx=8)
        tk.Label(c,text="Pos:",bg=PNL,fg=DIM,font=SM).pack(side=tk.RIGHT)

    def _status_bar(self):
        f=tk.Frame(self.root,bg=PNL2,pady=2); f.pack(fill=tk.X,side=tk.BOTTOM)
        self._stv=tk.StringVar(value="Ready.")
        tk.Label(f,textvariable=self._stv,bg=PNL2,fg=DIM,
                 font=SM,anchor="w",padx=8).pack(fill=tk.X)

    def _export_bar(self):
        """Collapsible export panel — hidden until File > Export audio."""
        self._exp_frm=tk.Frame(self.root,bg=PNL2)
        # Row 1: directory
        r1=tk.Frame(self._exp_frm,bg=PNL2); r1.pack(fill=tk.X,padx=8,pady=(6,2))
        tk.Label(r1,text="Export dir:",bg=PNL2,fg=DIM,font=SM,width=10,anchor="e"
                 ).pack(side=tk.LEFT)
        tk.Entry(r1,textvariable=self._export_dir,bg=PNL,fg=FG,
                 insertbackground=ACC,relief="flat",font=SM,bd=4
                 ).pack(side=tk.LEFT,fill=tk.X,expand=True,padx=4)
        tk.Button(r1,text="Browse…",bg=PNL,fg=FG,relief="flat",font=SM,
                  cursor="hand2",command=self._export_browse
                  ).pack(side=tk.LEFT)
        tk.Button(r1,text="Open",bg=PNL,fg=DIM,relief="flat",font=SM,
                  cursor="hand2",command=lambda:self._open_folder(Path(self._export_dir.get()))
                  ).pack(side=tk.LEFT,padx=(2,0))
        # Row 2: filename + format + bitrate + export button
        r2=tk.Frame(self._exp_frm,bg=PNL2); r2.pack(fill=tk.X,padx=8,pady=(0,6))
        tk.Label(r2,text="Filename:",bg=PNL2,fg=DIM,font=SM,width=10,anchor="e"
                 ).pack(side=tk.LEFT)
        tk.Entry(r2,textvariable=self._export_name,bg=PNL,fg=FG,
                 insertbackground=ACC,relief="flat",font=SM,bd=4,width=24
                 ).pack(side=tk.LEFT,padx=4)
        tk.Label(r2,text="Format:",bg=PNL2,fg=DIM,font=SM).pack(side=tk.LEFT,padx=(8,2))
        self._fmt_cb=ttk.Combobox(r2,textvariable=self._export_fmt,
                                   values=["mp3","wav"],width=5,state="readonly")
        self._fmt_cb.pack(side=tk.LEFT)
        self._fmt_cb.bind("<<ComboboxSelected>>",self._fmt_changed)
        self._br_lbl=tk.Label(r2,text="Bitrate:",bg=PNL2,fg=DIM,font=SM)
        self._br_lbl.pack(side=tk.LEFT,padx=(8,2))
        self._br_cb=ttk.Combobox(r2,textvariable=self._export_br,
                                  values=[96,128,160,192,256,320],width=5,state="readonly")
        self._br_cb.pack(side=tk.LEFT)
        self._exp_prog_v=tk.StringVar(value="")
        tk.Label(r2,textvariable=self._exp_prog_v,bg=PNL2,fg=DIM,
                 font=SM).pack(side=tk.LEFT,padx=12)
        self._exp_btn=tk.Button(r2,text="⬇ Export",bg=ACC,fg="#000",
                                relief="flat",font=SM,cursor="hand2",
                                command=self._do_export)
        self._exp_btn.pack(side=tk.RIGHT,padx=(4,0))
        tk.Button(r2,text="✕",bg=PNL2,fg=DIM,relief="flat",font=SM,
                  cursor="hand2",command=self._hide_export
                  ).pack(side=tk.RIGHT)
        # hidden by default
        self._exp_visible=False

    def _show_export(self):
        if not self._exp_visible:
            self._exp_frm.pack(fill=tk.X,side=tk.BOTTOM)
            self._exp_visible=True

    def _hide_export(self):
        self._exp_frm.pack_forget(); self._exp_visible=False

    def _fmt_changed(self,event=None):
        is_mp3=self._export_fmt.get()=="mp3"
        self._br_lbl.config(fg=DIM if is_mp3 else "#333")
        self._br_cb.config(state="readonly" if is_mp3 else "disabled")

    def _export_browse(self):
        d=filedialog.askdirectory(title="Select export folder",
                                  initialdir=self._export_dir.get())
        if d: self._export_dir.set(d)

    @staticmethod
    def _open_folder(p: Path):
        try:
            if sys.platform=="win32": os.startfile(str(p))
            elif sys.platform=="darwin": subprocess.run(["open",str(p)])
            else: subprocess.run(["xdg-open",str(p)])
        except: pass

    def _do_export(self):
        if not self._text:
            messagebox.showinfo(APP,"Open a book first."); return
        if self._export_busy:
            messagebox.showinfo(APP,"Export already running."); return
        fmt=self._export_fmt.get()
        if fmt=="mp3" and not _ensure_lameenc():
            messagebox.showerror(APP,
                "lameenc not available and could not be installed.\n"
                "Switch to WAV format, or install lameenc manually:\n"
                "  pip install lameenc"); return
        out_dir=Path(self._export_dir.get())
        try: out_dir.mkdir(parents=True,exist_ok=True)
        except Exception as e:
            messagebox.showerror(APP,f"Cannot create directory:\n{e}"); return
        name=re.sub(r'[<>:"/\\|?*\' ]',"-",self._export_name.get().strip()) or "export"
        wav_path=out_dir/f"{name}.wav"
        out_path=out_dir/f"{name}.{fmt}"
        if out_path.exists():
            if not messagebox.askyesno(APP,f"{out_path.name} exists. Overwrite?"): return
        self._export_busy=True
        self._exp_btn.config(state="disabled",text="Exporting…")
        self._exp_prog_v.set("Starting…")
        threading.Thread(target=self._export_worker,
                         args=(wav_path,out_path,fmt),daemon=True).start()

    def _export_worker(self,wav_path,out_path,fmt):
        def prog(msg,frac=0):
            self.root.after(0,self._exp_prog_v.set,msg)
        try:
            prog("Synthesizing…")
            # synthesize the full text sentence by sentence
            SR=22050
            with wave.open(str(wav_path),"wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
                total=len(self._sents)
                for i,(s,e) in enumerate(self._sents):
                    prog(f"Synthesizing {i+1}/{total}…", i/max(1,total))
                    chunk=self._text[s:e].strip()
                    if not chunk: continue
                    wav_bytes=self._tts_synth_for_export(chunk)
                    if not wav_bytes: continue
                    try:
                        buf=io.BytesIO(wav_bytes)
                        with wave.open(buf,"rb") as src_wf:
                            wf.writeframes(src_wf.readframes(src_wf.getnframes()))
                    except: pass
            prog("WAV written.")
            if fmt=="mp3":
                prog("Encoding MP3…")
                wav_to_mp3(wav_path,out_path,
                           bitrate=int(self._export_br.get()),
                           progress=lambda m,f:prog(m,f))
                try: wav_path.unlink()
                except: pass
            else:
                wav_path.rename(out_path)
            sz=out_path.stat().st_size/1e6
            self.root.after(0,prog,f"✓ {out_path.name}  ({sz:.1f} MB)")
            def _done(p=out_path):
                if messagebox.askyesno(APP,f"Exported:\n{p}\n\nOpen folder?"):
                    self._open_folder(p.parent)
            self.root.after(0,_done)
        except Exception as ex:
            import traceback
            self.root.after(0,prog,f"Error: {ex}")
            self.root.after(0,messagebox.showerror,APP,traceback.format_exc()[-400:])
        finally:
            self._export_busy=False
            self.root.after(0,self._exp_btn.config,{"state":"normal","text":"⬇ Export"})

    def _tts_synth_for_export(self,text:str) -> Optional[bytes]:
        """Synth a chunk, resampling to 22050 Hz mono if needed."""
        try:
            raw=self.tts.synth(text)
            if not raw: return None
            buf=io.BytesIO(raw)
            with wave.open(buf,"rb") as wf:
                sr=wf.getframerate(); ch=wf.getnchannels()
                data=wf.readframes(wf.getnframes())
            # If stereo, mix down to mono
            if ch==2:
                import array
                s=array.array("h",data)
                data=array.array("h",
                    [(s[i]+s[i+1])//2 for i in range(0,len(s)-1,2)]).tobytes()
            # Rebuild as proper WAV at native SR
            out=io.BytesIO()
            with wave.open(out,"wb") as wf:
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(sr)
                wf.writeframes(data)
            return out.getvalue()
        except: return None

    # ── file loading ──────────────────────────────────────────────────────────
    def _open(self):
        p=filedialog.askopenfilename(title="Open book",
            filetypes=[("All","*.pdf *.epub *.txt *.md *.html *.htm *.json"),
                       ("PDF","*.pdf"),("EPUB","*.epub"),("Text","*.txt *.md"),
                       ("HTML","*.html *.htm"),("JSON","*.json"),("All","*.*")])
        if p: self._load(Path(p))

    def _load(self, path: Path):
        self._st(f"Loading {path.name}…"); self.root.update_idletasks()
        def work():
            try:
                text  = extract_text(path)
                meta  = extract_meta(path,text)
                toc   = extract_toc(text)
                sents = tokenize(text)
                self.root.after(0,self._finish,path,text,meta,toc,sents)
            except Exception as ex:
                import traceback
                self.root.after(0,self._st,f"Load error: {ex} — {traceback.format_exc()[-150:]}")
        threading.Thread(target=work,daemon=True).start()

    def _finish(self, path, text, meta, toc, sents):
        self._stop()
        self._path=path; self._text=text; self._meta=meta
        self._toc=toc; self._sents=sents; self._sent=0
        self._playing=False; self._paused=False; self._pbtn.config(text="▶")
        self._find_hits=[]; self._find_pos=0
        self._find_count_v.set(""); self._sv.set("")

        # Insert text in chunks to keep GUI responsive for large files
        self._tw.delete("1.0",tk.END)
        CHUNK=50000
        for i in range(0,len(text),CHUNK):
            self._tw.insert(tk.END,text[i:i+CHUNK])
            if i==0: self.root.update_idletasks()

        self._toc_lb.delete(0,tk.END)
        for h,_ in toc: self._toc_lb.insert(tk.END," "+textwrap.shorten(h,30))
        self._ss.config(to=max(1,len(sents)-1)); self._ss_v.set(0)
        self._title_v.set(textwrap.shorten(meta.get("title",""),50))

        self.lib.add(meta); self._refresh_lib()

        # Restore last position
        start_idx=0
        for b in self.lib.books:
            if b.get("path")==str(path) and "last_pos" in b:
                cp=b["last_pos"]; self._scroll(cp)
                for i,(s,e) in enumerate(sents):
                    if s>=cp: start_idx=i; break
                break

        self.ctrl.load(text,sents,start_idx)
        self._st(f"{path.name}  ·  {len(sents)} sentences  ·  {len(toc)} sections")
        # Pre-fill export filename from book title
        safe=re.sub(r'[<>:"/\\|?*]',"-",meta.get("title",path.stem))[:60]
        self._export_name.set(safe)

        if self.tts.backend=="piper":
            threading.Thread(
                target=lambda:self.tts.ensure_voice(
                    key=self.tts.active_voice,
                    cb=lambda s:self.root.after(0,self._st,s)),
                daemon=True).start()

    # ── library ───────────────────────────────────────────────────────────────
    def _refresh_lib(self):
        self._lib_lb.delete(0,tk.END)
        for b in self.lib.books:
            t=b.get("title",Path(b.get("path","")).stem)
            self._lib_lb.insert(tk.END," "+textwrap.shorten(t,26))

    def _lib_open(self,event=None):
        sel=self._lib_lb.curselection()
        if not sel: return
        b=self.lib.books[sel[0]]; p=Path(b.get("path",""))
        if p.exists(): self._load(p)
        else:
            messagebox.showerror("Not found",f"File not found:\n{p}")
            self.lib.remove(str(p)); self._refresh_lib()

    def _lib_ctx(self,event):
        sel=self._lib_lb.nearest(event.y)
        if sel<0 or sel>=len(self.lib.books): return
        self._lib_lb.selection_clear(0,tk.END); self._lib_lb.selection_set(sel)
        m=tk.Menu(self.root,tearoff=False,bg=PNL,fg=FG,
                  activebackground=PNL2,activeforeground=ACC)
        m.add_command(label="Open",command=self._lib_open)
        m.add_command(label="Remove from library",command=lambda:(
            self.lib.remove(self.lib.books[sel].get("path","")),
            self._refresh_lib()))
        m.post(event.x_root,event.y_root)

    # ── TOC ───────────────────────────────────────────────────────────────────
    def _toc_jump(self,event=None):
        sel=self._toc_lb.curselection()
        if not sel or sel[0]>=len(self._toc): return
        _,cp=self._toc[sel[0]]; self._scroll(cp)
        near=0
        for i,(s,_) in enumerate(self._sents):
            if s>=cp: near=i; break
        self._sent=near; self.ctrl.seek(near); self._ss_v.set(near)

    def _scroll(self,cp:int):
        idx=f"1.0 + {cp} chars"
        self._tw.see(idx); self._tw.mark_set("insert",idx)

    # ── playback ──────────────────────────────────────────────────────────────
    def _toggle(self):
        if not self._text or not self._sents:
            messagebox.showinfo(APP,"Open a file first."); return
        if self._playing and not self._paused:
            self._paused=True; self.ctrl.pause()
            self._pbtn.config(text="▶"); self._st("Paused.")
        elif self._playing and self._paused:
            self._paused=False; self.ctrl.resume()
            self._pbtn.config(text="⏸"); self._st("Playing…")
        else:
            self._playing=True; self._paused=False
            self.ctrl.load(self._text,self._sents,self._sent)
            self.ctrl.play()
            self._pbtn.config(text="⏸"); self._st("Playing…")

    def _stop(self):
        if self._path and self._sents and self._sent<len(self._sents):
            self.lib.update_pos(str(self._path),self._sents[self._sent][0])
        self._playing=False; self._paused=False
        self.ctrl.stop(); self._pbtn.config(text="▶")
        self._clr(); self._st("Stopped.")

    def _prev(self):
        if not self._toc: return
        cp=self._sents[self._sent][0] if self._sents else 0
        tgt=0
        for _,p in reversed(self._toc):
            if p<cp-10: tgt=p; break
        near=0
        for i,(s,_) in enumerate(self._sents):
            if s>=tgt: near=i; break
        self._sent=near; self.ctrl.seek(near); self._ss_v.set(near); self._scroll(tgt)

    def _next(self):
        if not self._toc: return
        cp=self._sents[self._sent][0] if self._sents else 0
        tgt=len(self._text)
        for _,p in self._toc:
            if p>cp+10: tgt=p; break
        near=max(0,len(self._sents)-1)
        for i,(s,_) in enumerate(self._sents):
            if s>=tgt: near=i; break
        self._sent=near; self.ctrl.seek(near); self._ss_v.set(near); self._scroll(tgt)

    def _seek(self,val):
        idx=max(0,min(int(float(val)),len(self._sents)-1 if self._sents else 0))
        self._sent=idx
        if self._sents: self._scroll(self._sents[idx][0])
        if self._playing: self.ctrl.seek(idx)

    def _play_done(self):
        self._playing=False; self._pbtn.config(text="▶")
        self._clr(); self._st("Finished.")

    # ── highlights ────────────────────────────────────────────────────────────
    def _hl_sent(self,idx:int):
        if not self._sents or idx>=len(self._sents): return
        s,e=self._sents[idx]; self._sent=idx
        self._tw.tag_remove("sent_hl","1.0",tk.END)
        self._tw.tag_remove("word_hl","1.0",tk.END)
        self._tw.tag_add("sent_hl",f"1.0+{s}c",f"1.0+{e}c")
        if self._autoscroll:
            self._tw.see(f"1.0+{s}c")
        self._ss_v.set(idx)
        self._pos_v.set(f"{int(100*idx/max(1,len(self._sents)-1))}%")

    def _hl_word(self,a:int,b:int):
        self._tw.tag_remove("word_hl","1.0",tk.END)
        self._tw.tag_add("word_hl",f"1.0+{a}c",f"1.0+{b}c")

    def _clr(self):
        self._tw.tag_remove("sent_hl","1.0",tk.END)
        self._tw.tag_remove("word_hl","1.0",tk.END)

    # ── reader helpers ────────────────────────────────────────────────────────
    def _zoom(self,d):
        ns=max(6,min(48,self._fs.get()+d)); self._fs.set(ns)
        self._tw.config(font=("Courier",ns))
        self._tw.tag_configure("word_hl",font=("Courier",ns,"bold"))

    def _apply_wrap(self):
        self._tw.config(wrap=tk.WORD if self._wrap.get() else tk.NONE)

    # ── search ────────────────────────────────────────────────────────────
    def _find_all(self):
        """Find all occurrences of search term and highlight them all."""
        n=self._sv.get().strip()
        self._tw.tag_remove("search","1.0",tk.END)
        self._tw.tag_remove("search_cur","1.0",tk.END)
        self._find_hits=[]; self._find_pos=0
        self._find_count_v.set("")
        if len(n)<1: return
        # collect all hit positions
        pos="1.0"
        while True:
            idx=self._tw.search(n,pos,nocase=True,stopindex=tk.END)
            if not idx: break
            end=f"{idx}+{len(n)}c"
            self._tw.tag_add("search",idx,end)
            self._find_hits.append((idx,end))
            pos=end
        if not self._find_hits:
            self._find_count_v.set("0 results"); return
        self._find_count_v.set(f"1/{len(self._find_hits)}")
        self._find_pos=0
        self._find_show_current()

    def _find_show_current(self):
        """Highlight current result differently, scroll to it, seek playback."""
        if not self._find_hits: return
        self._tw.tag_remove("search_cur","1.0",tk.END)
        idx,end=self._find_hits[self._find_pos]
        self._tw.tag_add("search_cur",idx,end)
        self._tw.see(idx)
        self._find_count_v.set(f"{self._find_pos+1}/{len(self._find_hits)}")
        # Convert text index to char offset and seek playback
        cp=self._tw_idx_to_char(idx)
        if cp is not None and self._sents:
            near=0
            for i,(s,_) in enumerate(self._sents):
                if s>=cp: near=i; break
            self._sent=near; self._ss_v.set(near)
            if self._playing: self.ctrl.seek(near)
            else: self._scroll(self._sents[near][0])

    def _find_next_result(self):
        if not self._find_hits:
            self._find_all(); return
        self._find_pos=(self._find_pos+1)%len(self._find_hits)
        self._find_show_current()

    def _find_prev_result(self):
        if not self._find_hits:
            self._find_all(); return
        self._find_pos=(self._find_pos-1)%len(self._find_hits)
        self._find_show_current()

    def _tw_idx_to_char(self, tk_idx: str) -> int|None:
        """Convert tkinter text index "line.col" to absolute char offset."""
        try:
            row,col=map(int,tk_idx.split("."))
            lines=self._text.splitlines(keepends=True)
            return sum(len(l) for l in lines[:row-1])+col
        except: return None

    # ── click-to-seek ──────────────────────────────────────────────────────
    def _tw_click(self,event):
        """Single click: just move the insert cursor, do not seek."""
        pass  # default tk behaviour is fine; we just need to not block it

    def _tw_dbl_click(self,event):
        """Double-click: seek playback to the clicked position."""
        tw=self._tw
        tk_idx=tw.index(f"@{event.x},{event.y}")
        cp=self._tw_idx_to_char(tk_idx)
        if cp is None or not self._sents: return
        near=0
        for i,(s,_) in enumerate(self._sents):
            if s>=cp: near=i; break
        self._sent=near; self._ss_v.set(near)
        self._scroll(self._sents[near][0])
        # Seek regardless of pause state
        if self._playing:
            self.ctrl.seek(near)
        else:
            # Not playing — just position cursor and start if desired
            self._st(f"Positioned at sentence {near+1}/{len(self._sents)}  — press ▶ to read from here")
        return "break"  # prevent default word-select on double-click

    # ── autoscroll toggle ──────────────────────────────────────────────────
    def _toggle_autoscroll(self):
        self._autoscroll=not self._autoscroll
        self._asbtn.config(
            text="↕ Auto" if self._autoscroll else "↕ Free",
            bg=ACC if self._autoscroll else PNL2,
            fg="#000" if self._autoscroll else FG)

    def _voice_settings(self):
        """Full voice settings dialog: catalog, download, expressiveness sliders."""
        win=tk.Toplevel(self.root); win.title("Voice Settings")
        win.configure(bg=BG); win.geometry("680x540"); win.resizable(True,True)
        win.grab_set()

        mc=dict(bg=PNL,fg=FG,activebackground=PNL2,activeforeground=ACC,bd=0,tearoff=False)

        # ── top: backend info ────────────────────────────────────────────────
        hf=tk.Frame(win,bg=PNL2); hf.pack(fill=tk.X,padx=0,pady=0)
        tk.Label(hf,text="TTS Backend:",bg=PNL2,fg=DIM,font=SM).pack(side=tk.LEFT,padx=10,pady=8)
        self._vs_back=tk.StringVar(value=self.tts.backend)
        tk.Label(hf,textvariable=self._vs_back,bg=PNL2,fg=ACC,font=SM).pack(side=tk.LEFT)
        tk.Label(hf,text="Active voice:",bg=PNL2,fg=DIM,font=SM).pack(side=tk.LEFT,padx=(20,4))
        self._vs_active=tk.StringVar(value=self.tts.active_voice)
        tk.Label(hf,textvariable=self._vs_active,bg=PNL2,fg=ACC2,font=SM).pack(side=tk.LEFT)

        # ── lang filter ──────────────────────────────────────────────────────
        ff=tk.Frame(win,bg=BG); ff.pack(fill=tk.X,padx=10,pady=(8,2))
        tk.Label(ff,text="Filter:",bg=BG,fg=DIM,font=SM).pack(side=tk.LEFT)
        lang_v=tk.StringVar(value="en")
        tk.Entry(ff,textvariable=lang_v,width=6,bg=PNL,fg=FG,
                 insertbackground=ACC,font=SM,relief="flat",bd=4).pack(side=tk.LEFT,padx=4)
        stv=tk.StringVar(value="")
        tk.Label(ff,textvariable=stv,bg=BG,fg=DIM,font=SM).pack(side=tk.LEFT,padx=8)

        def _fetch():
            stv.set("Fetching catalog…"); win.update_idletasks()
            def _work():
                cat=self.tts.fetch_catalog(cb=lambda s:self.root.after(0,stv.set,s))
                rows=self.tts.list_voices(lang_filter=lang_v.get().strip())
                self.root.after(0,_populate,rows)
            threading.Thread(target=_work,daemon=True).start()

        def _populate(rows):
            lb.delete(0,tk.END)
            for r in rows:
                mark="✓ " if self.tts.is_downloaded(r["key"]) else "  "
                lb.insert(tk.END, mark+r["display"])
            lb._rows=rows
            stv.set(f"{len(rows)} voices")

        tk.Button(ff,text="Refresh",bg=PNL2,fg=FG,relief="flat",font=SM,
                  cursor="hand2",command=_fetch).pack(side=tk.LEFT)
        tk.Button(ff,text="All languages",bg=PNL2,fg=DIM,relief="flat",font=SM,
                  cursor="hand2",command=lambda:(lang_v.set(""),_fetch())).pack(side=tk.LEFT,padx=4)

        # ── voice list ───────────────────────────────────────────────────────
        lf=tk.Frame(win,bg=BG); lf.pack(fill=tk.BOTH,expand=True,padx=10,pady=4)
        lb=tk.Listbox(lf,bg=PNL,fg=FG,selectbackground=HL_BG,selectforeground=HL_FG,
                      font=SM,relief="flat",bd=0,activestyle="none",highlightthickness=0)
        sb=tk.Scrollbar(lf,orient=tk.VERTICAL,command=lb.yview,
                        bg=PNL,troughcolor=BG,bd=0,highlightthickness=0)
        lb.config(yscrollcommand=sb.set)
        lb.pack(side=tk.LEFT,fill=tk.BOTH,expand=True)
        sb.pack(side=tk.RIGHT,fill=tk.Y)
        lb._rows=[]

        # ── download + use button ────────────────────────────────────────────
        bf=tk.Frame(win,bg=BG); bf.pack(fill=tk.X,padx=10,pady=2)
        prog_v=tk.StringVar(value="Select a voice above, then Download & Use.")
        tk.Label(bf,textvariable=prog_v,bg=BG,fg=DIM,font=SM,anchor="w").pack(side=tk.LEFT,fill=tk.X,expand=True)

        def _use():
            sel=lb.curselection()
            if not sel: return
            rows=lb._rows
            if not rows or sel[0]>=len(rows): return
            row=rows[sel[0]]
            key=row["key"]
            prog_v.set(f"Preparing {row['name']}…")
            win.update_idletasks()
            def _work():
                ok=self.tts.ensure_voice(key,cb=lambda s:self.root.after(0,prog_v.set,s))
                if ok:
                    self.root.after(0,self._vs_active.set,self.tts.active_voice)
                    self.root.after(0,lambda:_populate(self.tts.list_voices(lang_filter=lang_v.get().strip())))
                    self.root.after(0,self._st,f"Voice: {self.tts.active_voice}")
                    self.ctrl.tts=self.tts
                    # clear synth cache so next play uses new voice
                    self.ctrl._cache.clear()
            threading.Thread(target=_work,daemon=True).start()

        tk.Button(bf,text="⬇ Download & Use",bg=ACC,fg="#000",relief="flat",font=SM,
                  cursor="hand2",command=_use).pack(side=tk.RIGHT,padx=(8,0))

        # ── sliders ──────────────────────────────────────────────────────────
        sf=tk.Frame(win,bg=PNL2); sf.pack(fill=tk.X,padx=0,pady=(6,0))

        def _slider(parent, label, var, lo, hi, fmt, setter, row):
            tk.Label(parent,text=label,bg=PNL2,fg=DIM,font=SM,width=16,anchor="e"
                     ).grid(row=row,column=0,padx=(10,4),pady=4,sticky="e")
            vl=tk.Label(parent,text=fmt(var.get()),bg=PNL2,fg=FG,font=SM,width=8)
            tk.Scale(parent,variable=var,from_=lo,to=hi,orient=tk.HORIZONTAL,
                     bg=PNL2,fg=FG,troughcolor=PNL,highlightthickness=0,length=320,
                     showvalue=False,relief="flat",bd=0,resolution=0.01,
                     command=lambda v:(setter(float(v)),vl.config(text=fmt(float(v))))
                     ).grid(row=row,column=1,padx=4,pady=4)
            vl.grid(row=row,column=2,padx=4,pady=4)

        spd_v=tk.DoubleVar(value=self.tts._rate)
        noi_v=tk.DoubleVar(value=self.tts._noise)
        nw_v =tk.DoubleVar(value=self.tts._noise_w)

        _slider(sf,"Speed (wpm)",    spd_v, 80, 400, lambda v:f"{int(v)} wpm",
                lambda v:(self.tts.set_rate(v),self._speed.set(int(v))), 0)
        _slider(sf,"Expressiveness", noi_v, 0.0, 1.0, lambda v:f"{v:.2f}",
                self.tts.set_noise, 1)
        _slider(sf,"Cadence",        nw_v,  0.0, 1.5, lambda v:f"{v:.2f}",
                self.tts.set_noise_w, 2)
        sf.columnconfigure(1,weight=1)

        # ── save / close ─────────────────────────────────────────────────────
        def _save_close():
            self.tts.save_cfg()
            win.destroy()

        tk.Button(win,text="Save & Close",bg=ACC,fg="#000",relief="flat",
                  font=SM,cursor="hand2",command=_save_close).pack(pady=8)

        # auto-fetch on open
        _fetch()

    def _reinit(self):
        self.tts=TTS(); self.ctrl.tts=self.tts
        self._st(f"TTS: {self.tts.backend}")

    def _st(self,msg:str): self._stv.set(msg)

    def _close(self):
        self._stop(); self.root.destroy()

    def run(self): self.root.mainloop()

# ── entry point ───────────────────────────────────────────────────────────────
def main():
    try: App().run()
    except Exception:
        import traceback
        try:
            r=tk.Tk(); r.withdraw()
            messagebox.showerror(APP,traceback.format_exc())
        except: sys.stderr.write(traceback.format_exc())
        sys.exit(1)

if __name__=="__main__": main()
