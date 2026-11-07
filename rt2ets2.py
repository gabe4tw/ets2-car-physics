#!/usr/bin/env python3
"""rt2ets2 - port an American Truck Simulator "Road Trip" car DLC to
Euro Truck Simulator 2, where the cars are sold as trucks at truck dealers.

This tool contains no SCS Software content. It reads the game files from YOUR
own installs (ATS + the Road Trip DLC + ETS2) and builds a local mod from them.
The resulting .scs contains SCS Software content: keep it for personal use and
do not redistribute it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Extractor (https://github.com/sk-zk/Extractor) - pinned release + checksums
# ---------------------------------------------------------------------------
EXTRACTOR_VERSION = "2026-07-29"
EXTRACTOR_ASSETS = {
    "windows": ("extractor-2026-07-29-win-x64.zip",
                "d493dc7d1834854effe12b80f6598cd1a8d5e754b069d7321f8802f72d64b2f7",
                "extractor.exe"),
    "linux": ("extractor-2026-07-29-linux-x64.zip",
              "8d6e046e2ac2a98d6ac3f11ea13ef049d3ac31526d7e8be129d5516ede3c5e88",
              "extractor"),
}
EXTRACTOR_URL = "https://github.com/sk-zk/Extractor/releases/download/{ver}/{name}"

# Absolute game paths inside files. The look-behind rejects relative paths
# ("accessory/exhaust/gt.sii") and templated ones ("$driver_type$/x.pma").
PATH_RE = re.compile(
    rb"(?<![A-Za-z0-9_.\-/$])/[A-Za-z0-9_][A-Za-z0-9_./\-]*"
    rb"\.(?:mat|tobj|pmd|pmg|sii|sui|soundref|bank|dds|pma|pmc|ppd|font|ogg)"
)
SCAN_SKIP = (".dds", ".pmg", ".bank", ".guids", ".jpg", ".png", ".txt")
DEF_TEXT = (".sii", ".sui")
TOKEN_RE = re.compile(r"@@([A-Za-z0-9_]+)@@")
LOC_RE = re.compile(r'key\[\]:\s*"([^"]+)"\s*\n\s*val\[\]:\s*"((?:[^"\\]|\\.)*)"')
CAMERA_REF_RE = re.compile(r":\s*(camera\.[A-Za-z0-9_.]+)")
CAMERA_DEF_RE = re.compile(r"^\s*[A-Za-z0-9_]+\s*:\s*(camera\.[A-Za-z0-9_.]+)\s*\{?", re.M)
CAMERA_SUFFIX = "rt2ets2"  # unit name tokens must be <= 12 chars
# unit header: "class : name" followed by "{" (same or next line); ".name" is anonymous
UNIT_DEF_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*:\s*([a-z0-9_][a-z0-9_.]*)\s*(?:\{|\r?\n\s*\{)", re.M)
DRIVER_ANIM_RE = re.compile(r'driver_animation:\s*"([^"]+)"')
ATTR_LINE_RE = re.compile(r"^(\s*)([a-z_][a-z_0-9]*)(\[\d*\])?\s*:", re.M)
# Attributes known to exist only in ATS; used when the game executables can't be read.
ATS_ONLY_ATTRS_FALLBACK = {"drivetrain_loss"}
# --- handling patch for other car mods ------------------------------------
# chassis settings that make up the ATS car feel; all are valid ETS2 chassis attributes
HANDLING_SCALARS = ("suspension_class", "max_steering_angle", "sway_bar_stiffness", "cog_height", "air_resistance")
HANDLING_ARRAYS = ("axle_suspension_type", "suspension_damping_factor")  # one entry per axle
HANDLING_MARK = "# rt2ets2 car handling"
# Built-in handling profiles: tuning numbers modelled on the ATS Road Trip cars
# (Crown Victoria, Bronco, F-150, Mustang). No game files needed, so anyone can run
# --handling-only with just ETS2. Both axles use independent (wishbone) suspension
# because a solid rear axle needs a 3D axle model that other car mods don't have.
HANDLING_PROFILES = {
    "sedan":  {"suspension_class": "standard", "max_steering_angle": 28, "sway_bar_stiffness": 0.35,
               "cog_height": 0.56, "air_resistance": 0.37, "suspension_damping_factor": (0.7, 0.5),
               "grip_factor": 1.2},
    "suv":    {"suspension_class": "standard", "max_steering_angle": 30, "sway_bar_stiffness": 0.4,
               "cog_height": 0.72, "air_resistance": 0.55, "suspension_damping_factor": (0.8, 0.6),
               "grip_factor": 1.2},
    "pickup": {"suspension_class": "standard", "max_steering_angle": 35, "sway_bar_stiffness": 0.4,
               "cog_height": 0.738, "air_resistance": 0.596, "suspension_damping_factor": (0.8, 0.6),
               "grip_factor": 1.2},
    "sports": {"suspension_class": "standard", "max_steering_angle": 31, "sway_bar_stiffness": 0.3,
               "cog_height": 0.52, "air_resistance": 0.5, "suspension_damping_factor": (0.7, 0.5),
               "grip_factor": 1.2},
}
# Chassis whose name starts with one of these are heavy vehicles, never patched.
NON_CAR_KEYWORDS = ("bus", "citybus", "tourliner", "coach", "firetruck", "forklift", "harvester", "tractor",
                    "sweeper", "hymer", "motorhome", "camper", "lowcab", "duck", "invis", "tram", "lorry",
                    "garbage", "crane", "excavator", "loader", "dumper", "truck", "semi")
# Vans and light commercials: closest Road Trip car is the F-150 (high centre of gravity).
VAN_KEYWORDS = ("van", "crafter", "transit", "ducato", "daily", "boxer", "t5", "t6", "sprinter", "vito",
                "master", "trafic", "jumper", "movano", "vivaro", "transporter", "berlingo", "kangoo",
                "caddy", "partner", "doblo")
BODY_KEYWORDS = {
    "pickup": ("pickup", "pick_up", "f150", "f_150", "ram", "hilux", "ranger", "raptor", "silverado",
               "tundra", "amarok", "navara", "l200", "sierra", "tacoma", "cybertruck") + VAN_KEYWORDS,
    "suv": ("suv", "x5", "x6", "x7", "q5", "q7", "q8", "cayenne", "touareg", "tiguan", "kodiaq", "karoq",
            "rav4", "land", "cruiser", "defender", "discovery", "range", "rover", "gclass", "g_class",
            "wrangler", "jeep", "bronco", "explorer", "tahoe", "suburban", "escalade", "xc60", "xc90",
            "duster", "qashqai", "sportage", "tucson", "macan", "urus", "4x4", "offroad", "santafe",
            "renegade", "niva", "p3008", "cx3", "cx5", "liberty", "kuga", "x3", "x1", "q3", "ix35"),
    "sports": ("gt", "gti", "rs", "amg", "m3", "m4", "m5", "911", "porsche", "mustang", "camaro",
               "corvette", "supra", "gtr", "skyline", "ferrari", "lamborghini", "challenger", "charger",
               "muscle", "coupe", "roadster", "spider", "miata", "mx5", "huracan", "aventador", "m2"),
}
CAR_CAMERA_RE = re.compile(r"_camera:\s*camera\.[a-z]+\.(?:car|suv)\b")
CHASSIS_UNIT_RE = re.compile(r"accessory_chassis_data\s*:\s*[A-Za-z0-9_.]+\s*\{")
GAME_EXES = {
    "ets2": ("bin/win_x64/eurotrucks2.exe", "bin/linux_x64/eurotrucks2"),
    "ats": ("bin/win_x64/amtrucks.exe", "bin/linux_x64/amtrucks"),
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"  ! {msg}", flush=True)


class Extractor:
    def __init__(self, exe: Path, cache: Path):
        self.exe = exe
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    @classmethod
    def obtain(cls, explicit: str | None, tools_dir: Path, cache: Path) -> "Extractor":
        if explicit:
            exe = Path(explicit)
            if not exe.is_file():
                sys.exit(f"Extractor not found: {exe}")
            return cls(exe.resolve(), cache)
        key = "windows" if os.name == "nt" else "linux" if platform.system() == "Linux" else None
        if key is None:
            sys.exit("No prebuilt extractor for this OS; pass --extractor PATH.")
        name, sha, binary = EXTRACTOR_ASSETS[key]
        dest = tools_dir / f"extractor-{EXTRACTOR_VERSION}"
        exe = dest / binary
        if not exe.is_file():
            dest.mkdir(parents=True, exist_ok=True)
            url = EXTRACTOR_URL.format(ver=EXTRACTOR_VERSION, name=name)
            log(f"Downloading extractor {EXTRACTOR_VERSION} from {url}")
            data = urllib.request.urlopen(url, timeout=120).read()
            got = hashlib.sha256(data).hexdigest()
            if got != sha:
                sys.exit(f"Extractor checksum mismatch (got {got}, expected {sha}). Aborting.")
            zp = dest / name
            zp.write_bytes(data)
            with zipfile.ZipFile(zp) as z:
                z.extractall(dest)
            zp.unlink()
            if os.name != "nt":
                exe.chmod(0o755)
        return cls(exe.resolve(), cache)

    def _run(self, args: list[str]) -> str:
        r = subprocess.run([str(self.exe), *args], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0 and not r.stdout:
            raise RuntimeError(f"extractor failed: {' '.join(args)}\n{r.stderr[-800:]}")
        return r.stdout

    def list(self, archive: Path, deep: bool = False) -> set[str]:
        st = archive.stat()
        key = hashlib.sha1(f"{archive.resolve()}|{st.st_size}|{st.st_mtime_ns}|{deep}".encode()).hexdigest()[:16]
        cf = self.cache / f"{archive.stem}-{key}.txt"
        if cf.is_file():
            return set(cf.read_text(encoding="utf-8").split("\n")) - {""}
        args = [str(archive), "--list"] + (["--deep"] if deep else [])
        paths = {l.strip() for l in self._run(args).splitlines() if l.startswith("/")}
        cf.write_text("\n".join(sorted(paths)), encoding="utf-8")
        return paths

    def extract(self, archive: Path, dest: Path, paths: list[str] | None = None,
                partial: list[str] | None = None, deep: bool = False) -> None:
        args = [str(archive), f"-d={dest}", "-q"]
        if deep:
            args.append("--deep")
        tmp = None
        if paths:
            tmp = dest.parent / f"_paths_{archive.stem}.txt"
            tmp.write_text("\n".join(sorted(paths)) + "\n", encoding="utf-8")
            args.append(f"-P={tmp}")
        if partial:
            args.append("-p=" + ",".join(partial))
        try:
            out = self._run(args)
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)
        tail = [l for l in out.splitlines() if "extracted" in l]
        if tail and " 0 failed" not in tail[-1]:
            warn(f"{archive.name}: {tail[-1]}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def files_under(root: Path) -> set[str]:
    out = set()
    for dp, _, fs in os.walk(root):
        for fn in fs:
            out.add("/" + os.path.relpath(os.path.join(dp, fn), root).replace("\\", "/"))
    return out


def scan_refs(root: Path) -> set[str]:
    found = set()
    for dp, _, fs in os.walk(root):
        for fn in fs:
            if fn.lower().endswith(SCAN_SKIP):
                continue
            data = Path(dp, fn).read_bytes()
            if fn.endswith(DEF_TEXT):  # ignore commented-out lines
                data = b"\n".join(l for l in data.split(b"\n")
                                  if not l.lstrip().startswith((b"#", b"//")))
            found.update(m.decode() for m in PATH_RE.findall(data))
    return found


def read_text(p: Path) -> str:
    return p.read_bytes().decode("utf-8-sig", errors="replace")


def find_documents() -> Path | None:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:
            pass
    p = Path.home() / "Documents"
    return p if p.is_dir() else None


def write_icon(src: Path, dst: Path) -> bool:
    """Make the 276x162 mod icon from the DLC banner (uncompressed 32bpp DDS)."""
    try:
        from PIL import Image
    except ImportError:
        warn("Pillow not installed - skipping mod icon (pip install pillow)")
        return False
    try:
        d = src.read_bytes()
        if d[:4] != b"DDS ":
            return False
        h, w = struct.unpack_from("<II", d, 12)
        off = 128 + (20 if d[84:88] == b"DX10" else 0)
        if len(d) - off < w * h * 4:
            return False
        im = Image.frombuffer("RGBA", (w, h), d[off:off + w * h * 4], "raw", "BGRA", 0, 1).convert("RGB")
        tw, th = 276, 162
        s = max(tw / w, th / h)
        im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
        l, t = (im.width - tw) // 2, (im.height - th) // 2
        im.crop((l, t, l + tw, t + th)).save(dst, quality=92)
        return True
    except Exception as e:  # icon is cosmetic
        warn(f"could not make icon: {e}")
        return False


def set_unit_attrs(text: str, unit_re: re.Pattern, new_lines: list[str], replace: set[str],
                   only_missing: bool = False) -> tuple[str, int]:
    """Rewrite every unit matching unit_re: drop existing attributes named in `replace`
    and append new_lines before the unit's closing brace. Returns (text, units changed)."""
    out, pos, n = [], 0, 0
    drop = re.compile(r"(?m)^[ \t]*(?:" + "|".join(map(re.escape, sorted(replace))) + r")(?:\[\d*\])?[ \t]*:.*\r?\n?") \
        if replace else None
    for m in unit_re.finditer(text):
        if m.start() < pos:
            continue
        end = re.compile(r"\n[ \t]*\}").search(text, m.end())
        if not end:
            break
        body = text[m.end():end.start()]
        if only_missing and drop and drop.search(body):
            continue
        if drop:
            body = drop.sub("", body)
        body = body.rstrip() + f"\n\n\t{HANDLING_MARK}\n" + "".join(f"\t{l}\n" for l in new_lines).rstrip("\n")
        out.append(text[pos:m.end()] + body)
        pos = end.start()
        n += 1
    out.append(text[pos:])
    return "".join(out), n


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w]


def _hit(words: list[str], keywords) -> bool:
    """Exact match for short keywords (gt, m5, t6), prefix match for longer ones (transit2016)."""
    for w in words:
        for k in keywords:
            if w == k or (len(k) >= 4 and w.startswith(k)):
                return True
    return False


def classify_chassis(name_text: str, data_text: str = "") -> str | None:
    """Body type for one chassis (file stem + unit name + its name/info), or None if not a car."""
    words = _words(name_text)
    if _hit(words, NON_CAR_KEYWORDS):
        return None
    for body in ("pickup", "suv", "sports"):
        if _hit(words, BODY_KEYWORDS[body]):
            return body
    return classify_body("", data_text) if data_text else "sedan"


def classify_body(model: str, data_text: str) -> str:
    words = _words(model + " " + " ".join(re.findall(r'info\[\]:\s*"([^"]*)"', data_text)))
    for body in ("pickup", "suv", "sports"):
        if _hit(words, BODY_KEYWORDS[body]):
            return body
    tags = set(re.findall(r'tags\[\]:\s*"([^"]+)"', data_text))
    if tags & {"pickup"}:
        return "pickup"
    if tags & {"offroad", "suv"}:
        return "suv"
    if tags & {"muscle", "sports"}:
        return "sports"
    return "sedan"


def zip_dir(src: Path, dst: Path) -> None:
    """Pack a folder as a ZIP-format .scs (ETS2 loads zip mods)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                comp = zipfile.ZIP_STORED if p.suffix in (".jpg", ".bank") else zipfile.ZIP_DEFLATED
                z.write(p, p.relative_to(src).as_posix(), compress_type=comp)
    os.replace(tmp, dst)


def rename_units(text: str, renames: dict[str, str]) -> str:
    """Rename unit names as whole tokens (camera.behind.car must not match camera.behind.car2)."""
    if not renames:
        return text
    pat = re.compile(r"(?<![A-Za-z0-9_.])(" + "|".join(map(re.escape, sorted(renames, key=len, reverse=True)))
                     + r")(?![A-Za-z0-9_.])")
    return pat.sub(lambda m: renames[m.group(1)], text)


def humanize(key: str) -> str:
    parts = key.split("_")
    if parts and parts[0] in ("tire", "disc", "rim"):
        parts = parts[2:] or parts[1:]
    return " ".join(p.upper() if any(c.isdigit() for c in p) else p.capitalize() for p in parts)


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
class Porter:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.ats = Path(a.ats) if a.ats else None
        self.ets2 = Path(a.ets2)
        self.dlc = Path(a.dlc) if a.dlc else None
        self.work = Path(a.work).resolve()
        self.lang = a.lang
        self.warnings: list[str] = []

    def w(self, msg: str) -> None:
        self.warnings.append(msg)
        warn(msg)

    # -- 0. inputs ----------------------------------------------------------
    def check_inputs(self) -> None:
        for name, p in (("ATS", self.ats), ("ETS2", self.ets2)):
            if not (p / "def.scs").is_file():
                sys.exit(f"{name} folder looks wrong (no def.scs): {p}")
        if self.dlc is None:
            cands = sorted(self.ats.glob("dlc_rt_*.scs"))
            if len(cands) != 1:
                names = ", ".join(c.name for c in cands) or "none"
                sys.exit(f"Pass --dlc. Road Trip DLCs found in ATS folder: {names}")
            self.dlc = cands[0]
        if not self.dlc.is_file():
            sys.exit(f"DLC file not found: {self.dlc}")
        self.dlc_id = self.dlc.stem
        self.mod_id = "rt2ets2_" + re.sub(r"^dlc_rt_", "", self.dlc_id)
        self.work.mkdir(parents=True, exist_ok=True)
        self.ex = Extractor.obtain(self.a.extractor, Path(self.a.tools).resolve(), self.work / "lists")

    def fresh(self, name: str) -> Path:
        p = self.work / name
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)
        return p

    # -- 1. DLC -------------------------------------------------------------
    def extract_dlc(self) -> None:
        log(f"[1/8] Extracting {self.dlc.name}")
        self.src = self.fresh("dlc")
        self.ex.extract(self.dlc, self.src)
        car = self.src / "def/vehicle/car"
        if not car.is_dir():
            sys.exit("This DLC has no /def/vehicle/car - not a Road Trip car DLC?")
        self.models = sorted(d.name for d in car.iterdir() if d.is_dir())
        if not self.models:
            sys.exit("No car models found in /def/vehicle/car")
        man = self.src / f"{self.dlc_id}.manifest.sii"
        m = re.search(r'display_name:\s*"([^"]+)"', read_text(man)) if man.is_file() else None
        self.display = (m.group(1) if m else self.dlc_id).replace("DLC - ", "")
        log(f"      models: {', '.join(self.models)}")

    # -- 2. listings --------------------------------------------------------
    def list_games(self) -> None:
        log("[2/8] Indexing ETS2 and ATS archives (cached after the first run)")
        self.ets2_all: set[str] = set()
        for f in sorted(self.ets2.glob("*.scs")):
            self.ets2_all |= self.ex.list(f)
        self.ats_lists: dict[str, set[str]] = {}
        for f in sorted(self.ats.glob("*.scs")):
            if f.resolve() == self.dlc.resolve() or f.name == self.dlc.name:
                continue
            self.ats_lists[f.stem] = self.ex.list(f)
        base = ["def", "base_vehicle", "base_share", "base", "core", "effect"]
        self.ats_order = [n for n in base if n in self.ats_lists] + \
                         sorted(n for n in self.ats_lists if n not in base)
        self.ats_all = set().union(*self.ats_lists.values())
        self.own = files_under(self.src)
        self.driver_types = sorted({p.split("/")[5] for p in self.ets2_all
                                    if p.startswith("/asset/character/human/driver/") and p.count("/") >= 6})
        # "mod" = ETS2's online Modded Trucks dealer: offers placed under the car's own
        # brand (e.g. truck_dealer/ford/), which has no physical dealer on the map.
        map_brands = sorted({p.split("/")[4] for p in self.ets2_all
                             if p.startswith("/def/vehicle/truck_dealer/") and p.count("/") >= 5})
        self.dealer_brands = []
        for b in (x.strip() for x in self.a.dealers.split(",")):
            if b == "mod":
                self.dealer_brands.append("mod")
            elif b == "all":
                self.dealer_brands += map_brands
            elif b in map_brands:
                self.dealer_brands.append(b)
            elif b:
                sys.exit(f"Unknown dealer '{b}'; use 'mod', 'all' or one of: {', '.join(map_brands)}")
        self.dealer_brands = list(dict.fromkeys(self.dealer_brands))

    def ats_where(self, p: str) -> str | None:
        for n in self.ats_order:
            if p in self.ats_lists[n]:
                return n
        return None

    # -- 3. seed ------------------------------------------------------------
    def seed(self) -> set[str]:
        log("[3/8] Working out what the DLC needs from the ATS base game")
        seed = scan_refs(self.src) - self.own - self.ets2_all
        texts = {p: read_text(p) for p in (self.src / "def").rglob("*") if p.suffix in DEF_TEXT}

        # driver animations ($driver_type$ templated)
        for t in texts.values():
            for tpl in DRIVER_ANIM_RE.findall(t):
                for dt in self.driver_types:
                    seed.add(tpl.replace("$driver_type$", dt))

        # cameras not defined in ETS2 or the DLC
        cam_ets2 = self.work / "ets2_camera"
        cam_ats = self.work / "ats_camera"
        for arc, dst in ((self.ets2 / "def.scs", cam_ets2), (self.ats / "def.scs", cam_ats)):
            if dst.exists():
                shutil.rmtree(dst)
            self.ex.extract(arc, dst, partial=["/def/camera"])
        defined = set()
        for root in (cam_ets2 / "def/camera", self.src / "def/camera"):
            if root.is_dir():
                for p in root.rglob("*"):
                    if p.suffix in DEF_TEXT:
                        defined |= set(CAMERA_DEF_RE.findall(read_text(p)))
        wanted = set()
        for t in texts.values():
            wanted |= set(CAMERA_REF_RE.findall(t))
        self.camera_units: list[str] = []
        for cam in sorted(wanted - defined):
            hit = None
            for p in sorted(cam_ats.rglob("*.sui")):
                if cam in CAMERA_DEF_RE.findall(read_text(p)):
                    hit = "/" + p.relative_to(cam_ats).as_posix()
                    break
            if hit:
                self.camera_units.append(hit)
                seed.add(hit)
            else:
                self.w(f"camera '{cam}' not found in ATS")
        self.camera_units = sorted(set(self.camera_units))

        # car brand logos
        self.brands = sorted({m.split(".")[0] for m in self.models})
        for b in self.brands:
            for ext in (".mat", ".tobj"):
                p = f"/material/ui/car_brand_logo/{b}{ext}"
                if p in self.ats_all:
                    seed.add(p)
        return seed

    # -- 4. closure ---------------------------------------------------------
    def pull_deps(self, seed: set[str]) -> None:
        log("[4/8] Pulling ATS dependencies")
        self.deps = self.fresh("deps")
        have = self.own | self.ets2_all
        done: set[str] = set()
        self.unresolved: set[str] = set()
        from_dlcs: dict[str, int] = {}
        todo = seed
        rnd = 0
        while todo:
            rnd += 1
            want = set()
            for p in todo:
                if p in have or p in done:
                    continue
                if p not in self.ats_all:
                    self.unresolved.add(p)
                    continue
                want.add(p)
                base, ext = os.path.splitext(p)
                sib = {".pmd": (".pmg", ".pmc", ".pma", ".ppd")}.get(ext, ())
                want |= {base + e for e in sib if base + e in self.ats_all}
                if ext == ".bank" and p + ".guids" in self.ats_all:
                    want.add(p + ".guids")
            want -= done
            if not want:
                break
            by_arc: dict[str, list[str]] = {}
            for p in want:
                by_arc.setdefault(self.ats_where(p), []).append(p)
            for arc, ps in by_arc.items():
                if arc.startswith("dlc_"):
                    from_dlcs[arc] = from_dlcs.get(arc, 0) + len(ps)
                self.ex.extract(self.ats / f"{arc}.scs", self.deps, paths=ps)
            done |= want
            todo = {p for p in scan_refs(self.deps) if p not in have and p not in done}
        present = files_under(self.deps)
        # .dds files are rebuilt next to their .tobj by the extractor
        self.unresolved = {p for p in self.unresolved if p not in present}
        log(f"      {len(present)} files from ATS in {rnd} round(s)")
        for arc, n in sorted(from_dlcs.items()):
            log(f"      note: {n} file(s) came from your ATS {arc}.scs")

    # -- 5. locale ----------------------------------------------------------
    def load_locale(self) -> dict[str, str]:
        log(f"[5/8] Reading ATS '{self.lang}' text strings")
        dst = self.fresh("ats_locale")
        self.ex.extract(self.ats / "locale.scs", dst, deep=True)
        vals: dict[str, str] = {}
        files = [dst / "locale/common.sui"] + sorted((dst / "locale" / self.lang).glob("*"))
        if self.lang != "en_us":
            files += sorted((dst / "locale/en_us").glob("*"))  # fallback
        for f in files:
            if f.is_file():
                for k, v in LOC_RE.findall(read_text(f)):
                    vals.setdefault(k, v)
        if not vals:
            self.w("no locale strings found - names will be shown as raw keys")
        return vals

    # -- 6. build -----------------------------------------------------------
    def build(self, loc: dict[str, str]) -> Path:
        log("[6/8] Building mod tree")
        out = self.fresh("build")
        # the car-system defs are re-created below as truck defs
        skip = re.compile(r"^(?:" + re.escape(f"{self.dlc_id}.manifest.sii") + r"$|def/vehicle/car(?:_[a-z_]+)?/)")
        for dp, _, fs in os.walk(self.src):
            for fn in fs:
                rel = os.path.relpath(os.path.join(dp, fn), self.src).replace("\\", "/")
                if skip.match(rel):
                    continue
                d = out / rel
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(os.path.join(dp, fn), d)
        shutil.copytree(self.deps, out, dirs_exist_ok=True)

        # car defs -> truck defs
        for m in self.models:
            shutil.copytree(self.src / "def/vehicle/car" / m, out / "def/vehicle/truck" / m)

        # dealers + truck browser (non-UK only: Road Trip cars are left-hand drive)
        car_dealer = self.src / "def/vehicle/car_dealer"
        dealer_files = sorted(car_dealer.rglob("*.sii"))
        for f in dealer_files:
            # car_dealer/<brand>/x.sii -> the car's own brand is the "mod dealer" folder
            rel = f.relative_to(car_dealer).parts
            own = rel[0] if len(rel) > 1 else self.brands[0]
            for b in self.dealer_brands:
                d = out / "def/vehicle/truck_dealer" / (own if b == "mod" else b)
                d.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, d / f"{self.mod_id}_{f.name}")
        desk = out / "def/vehicle/truck_desktop"
        desk.mkdir(parents=True, exist_ok=True)
        for f in sorted((self.src / "def/vehicle/car_desktop").glob("*.sii")):
            shutil.copy2(f, desk / f"{self.mod_id}_{f.name}")
        if not dealer_files:
            self.w("DLC has no car_dealer configs - cars only appear in the truck browser")

        # cameras - the ATS car cameras use generic names (camera.behind.car, ...) that
        # other car mods (e.g. Skoda Superb) also define. Unit names are global across
        # all mods, so give ours a unique suffix and a private folder.
        self.camera_renames: dict[str, str] = {}
        if self.camera_units:
            cam_dir = out / "def/camera/units" / self.mod_id
            cam_dir.mkdir(parents=True, exist_ok=True)
            includes = []
            for u in self.camera_units:
                src = out / u.lstrip("/")
                t = read_text(src)
                for name in CAMERA_DEF_RE.findall(t):
                    self.camera_renames[name] = f"{name}.{CAMERA_SUFFIX}"
                t = rename_units(t, self.camera_renames)
                (cam_dir / src.name).write_text(t, encoding="utf-8", newline="\n")
                src.unlink()
                includes.append(f"/def/camera/units/{self.mod_id}/{src.name}")
            cs = out / f"def/camera/camera_storage.{self.mod_id}.sii"
            cs.write_text("SiiNunit\n{\n" + "".join(f'@include "{u}"\n' for u in includes) + "}\n",
                          encoding="utf-8", newline="\n")

        # brand logo for the dealer / truck browser
        for b in self.brands:
            src = self.deps / f"material/ui/car_brand_logo/{b}.mat"
            if src.is_file():
                t = read_text(src).replace(f'"{b}.tobj"', f'"/material/ui/car_brand_logo/{b}.tobj"')
                for d in ("brand_logo", "brand_logo_left_bottom"):
                    p = out / f"material/ui/{d}/{b}.mat"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(t, encoding="utf-8", newline="\n")

        # rewrite paths and locale tokens
        unknown: set[str] = set()

        def tok(m: re.Match) -> str:
            k = m.group(1)
            if k in loc:
                return loc[k]
            unknown.add(k)
            return humanize(k)

        for p in out.rglob("*"):
            if p.suffix not in DEF_TEXT or not p.is_file():
                continue
            raw = p.read_bytes()
            bom = raw.startswith(b"\xef\xbb\xbf")
            t = raw.decode("utf-8-sig", errors="replace")
            n = t
            for m in self.models:
                n = n.replace(f"/def/vehicle/car/{m}/", f"/def/vehicle/truck/{m}/")
            n = rename_units(n, self.camera_renames)
            n = TOKEN_RE.sub(tok, n)
            if n != t:
                p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + n.encode("utf-8"))
        self.strip_ats_only_attrs(out)
        if unknown:
            log(f"      {len(unknown)} text key(s) not in ATS locale, used readable fallbacks: "
                + ", ".join(sorted(unknown)[:8]) + (" ..." if len(unknown) > 8 else ""))

        # icon + manifest
        icon_ok = False
        for cand in (out / f"material/ui/dlc/{self.dlc_id}.dds", out / f"material/ui/packages/{self.dlc_id}.dds"):
            if cand.is_file() and write_icon(cand, out / "mod_icon.jpg"):
                icon_ok = True
                break
        ver = self.game_version()
        compat = ".".join(ver.split(".")[:2]) + ".*" if ver else None
        (out / "manifest.sii").write_text(
            "SiiNunit\n{\nmod_package : .package_name\n{\n"
            f'\tpackage_version: "{__version__}"\n'
            f'\tdisplay_name: "{self.display} (ATS port, as trucks)"\n'
            '\tauthor: "SCS Software (ported locally with rt2ets2)"\n'
            '\tcategory[]: "truck"\n'
            + ('\ticon: "mod_icon.jpg"\n' if icon_ok else "")
            + '\tdescription_file: "mod_description.txt"\n'
            + (f'\tcompatible_versions[]: "{compat}"\n' if compat else "")
            + "}\n}\n", encoding="utf-8", newline="\n")
        cars = ", ".join(m.replace(".", " ").replace("_", " ").title() for m in self.models)
        (out / "mod_description.txt").write_text(
            f"Local port of the ATS DLC \"{self.display}\" to ETS2, built with rt2ets2 {__version__}.\n"
            f"Cars: {cars}.\nSold at: "
            + ", ".join("Modded Trucks dealer" if b == "mod" else b for b in self.dealer_brands)
            + " and in the truck browser.\n"
            "Contains SCS Software content from your own game files. Personal use only - do not redistribute.\n",
            encoding="utf-8", newline="\n")
        return out

    def _exe(self, root: Path, game: str) -> bytes | None:
        for rel in GAME_EXES[game]:
            p = root / rel
            if p.is_file():
                return p.read_bytes()
        return None

    def strip_ats_only_attrs(self, out: Path) -> None:
        """Comment out attributes that ATS has but ETS2 doesn't. ETS2 refuses to load
        a unit containing an unknown attribute (e.g. an engine with 'drivetrain_loss'),
        which leaves the vehicle without that part and crashes the dealer."""
        ets2_exe, ats_exe = self._exe(self.ets2, "ets2"), self._exe(self.ats, "ats")
        files = [p for p in out.rglob("*") if p.suffix in DEF_TEXT and p.is_file()]
        texts = {p: p.read_bytes().decode("utf-8-sig", errors="replace") for p in files}
        names = set()
        for t in texts.values():
            names |= {m.group(2) for m in ATTR_LINE_RE.finditer(t)}
        if ets2_exe and ats_exe:
            def known(blob: bytes, n: str) -> bool:
                return b"\x00" + n.encode() + b"\x00" in blob
            bad = {n for n in names if not known(ets2_exe, n) and known(ats_exe, n)}
        else:
            self.w("could not read the game executables; using built-in list of ATS-only attributes")
            bad = names & ATS_ONLY_ATTRS_FALLBACK
        if not bad:
            return
        line_re = re.compile(r"^(\s*)((?:" + "|".join(map(re.escape, sorted(bad))) + r")(?:\[\d*\])?\s*:.*)$", re.M)
        n_files = 0
        for p, t in texts.items():
            n = line_re.sub(r"\1# [rt2ets2: not supported in ETS2] \2", t)
            if n != t:
                raw = p.read_bytes()
                p.write_bytes((b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + n.encode("utf-8"))
                n_files += 1
        log(f"      removed ATS-only setting(s) {', '.join(sorted(bad))} from {n_files} file(s)")

    def game_version(self) -> str | None:
        try:
            d = self.work / "ets2_version"
            if d.exists():
                shutil.rmtree(d)
            self.ex.extract(self.ets2 / "version.scs", d)
            m = re.search(r'version:\s*"([0-9.]+)"', read_text(d / "version.sii"))
            return m.group(1) if m else None
        except Exception:
            return None

    # -- 7. validate --------------------------------------------------------
    def validate(self, out: Path) -> None:
        log("[7/8] Checking every referenced file resolves")
        have = files_under(out) | self.ets2_all
        missing = sorted(scan_refs(out) - have)
        # files SCS itself references but never shipped in ATS are harmless
        real = [p for p in missing if p in self.ats_all or p not in self.unresolved]
        harmless = [p for p in missing if p not in real]
        if harmless:
            log(f"      {len(harmless)} reference(s) also missing in ATS itself (harmless)")
        for p in real[:30]:
            self.w(f"unresolved reference: {p}")
        if len(real) > 30:
            self.w(f"... and {len(real) - 30} more")
        if not real:
            log("      all references resolve")

    # -- 8. pack ------------------------------------------------------------
    def pack(self, out: Path) -> Path:
        dst = Path(self.a.output) if self.a.output else Path("output") / f"{self.mod_id}.scs"
        dst = dst.resolve()
        log(f"[8/8] Packing {dst}")
        zip_dir(out, dst)
        log(f"      {dst.stat().st_size // (1024 * 1024)} MB")
        return dst

    # -- optional: car speed limits add-on -----------------------------------
    def build_speed_addon(self, next_to: Path) -> Path | None:
        """ETS2 always applies the *truck* speed limits to the player's vehicle; there is no
        per-vehicle setting. This separate add-on gives the truck class each country's car
        limits (and removes the truck max_limit caps). Enable it while driving cars."""
        log("Building optional car speed limits add-on")
        src = self.work / "ets2_country"
        if src.exists():
            shutil.rmtree(src)
        self.ex.extract(self.ets2 / "def.scs", src, partial=["/def/country"])
        out = self.fresh("speed_addon")
        block = lambda cls: re.compile(
            r"(country_speed_limit\s*:\s*\.speed_limit\." + cls + r"\s*\{)(.*?)(\n\s*\})", re.S)
        n = 0
        for f in sorted(src.glob("def/country/*/speed_limits*.sii")):
            t = read_text(f)
            car, truck = block("car").search(t), block("truck").search(t)
            if not car or not truck:
                continue
            body = re.sub(r"(vehicle_speed_class:\s*)car", r"\1truck", car.group(2))
            body = re.sub(r"(?m)^\s*max_limit\[\]:.*\n?", "", body)
            new = t[:truck.start(2)] + body + t[truck.end(2):]
            dst = out / f.relative_to(src)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(new, encoding="utf-8", newline="\n")
            n += 1
        if not n:
            self.w("no country speed limits found - skipping the speed limits add-on")
            return None
        (out / "manifest.sii").write_text(
            "SiiNunit\n{\nmod_package : .package_name\n{\n"
            f'\tpackage_version: "{__version__}"\n'
            '\tdisplay_name: "Car speed limits for the player (rt2ets2)"\n'
            '\tauthor: "rt2ets2"\n\tcategory[]: "physics"\n'
            '\tdescription_file: "mod_description.txt"\n}\n}\n', encoding="utf-8", newline="\n")
        (out / "mod_description.txt").write_text(
            "Makes the speed limits, speed cameras and police fines use each country's CAR limits\n"
            "for whatever you drive (e.g. 130 on French motorways, no limit on German Autobahn\n"
            "sections). ETS2 can't tell a car-as-truck mod from a real truck, so this applies to\n"
            "every vehicle while enabled: turn it off again when you drive a real truck.\n"
            f"Covers the {n} base-game countries; map mods with their own countries are not changed.\n",
            encoding="utf-8", newline="\n")
        dst = next_to.with_name("rt2ets2_car_speed_limits.scs")
        zip_dir(out, dst)
        log(f"      {n} countries -> {dst}")
        return dst

    # -- optional: conflicts with other installed mods ------------------------
    def mod_sources(self) -> list[Path]:
        roots: list[Path] = []
        docs = find_documents()
        if self.a.install_dir:
            roots.append(Path(self.a.install_dir))
        elif docs:
            roots.append(docs / "Euro Truck Simulator 2" / "mod")
        steamapps = self.ets2.resolve().parent.parent
        roots.append(steamapps / "workshop" / "content" / "227300")
        roots += [Path(p) for p in self.a.mods_dir or []]
        found: list[Path] = []
        for r in roots:
            if not r.is_dir():
                continue
            if r.name == "227300":  # workshop: one folder per item, mod inside
                for item in sorted(r.iterdir()):
                    if item.is_dir():
                        subs = [s for s in item.iterdir() if s.is_dir() or s.suffix in (".scs", ".zip")]
                        found += subs or [item]
            else:
                found += [p for p in sorted(r.iterdir()) if p.is_dir() or p.suffix in (".scs", ".zip")]
        return found

    def read_mod_defs(self, mod: Path) -> tuple[str, dict[str, bytes]]:
        """Return (display name, {path: content}) for def text files + all file paths (content b'')."""
        files: dict[str, bytes] = {}
        name = mod.name
        if mod.is_dir():
            for p in mod.rglob("*"):
                if p.is_file():
                    rel = "/" + p.relative_to(mod).as_posix()
                    files[rel] = p.read_bytes() if p.suffix in DEF_TEXT or p.name == "manifest.sii" else b""
        else:
            with open(mod, "rb") as fh:
                head = fh.read(4)
            if head[:2] == b"PK":
                with zipfile.ZipFile(mod) as z:
                    for zi in z.infolist():
                        if zi.is_dir():
                            continue
                        rel = "/" + zi.filename.lstrip("/")
                        files[rel] = z.read(zi) if rel.endswith(DEF_TEXT) else b""
            elif head == b"SCS#":
                tmp = self.work / "modscan"
                if tmp.exists():
                    shutil.rmtree(tmp)
                for p in self.ex.list(mod):
                    files[p] = b""
                self.ex.extract(mod, tmp, partial=["/def", "/manifest.sii"])
                for p in tmp.rglob("*"):
                    if p.is_file() and p.suffix in DEF_TEXT:
                        files["/" + p.relative_to(tmp).as_posix()] = p.read_bytes()
                shutil.rmtree(tmp, ignore_errors=True)
        man = files.get("/manifest.sii") or b""
        m = re.search(rb'^\s*display_name:\s*"([^"]+)"', man, re.M)
        if m:
            name = f"{m.group(1).decode('utf-8', 'replace')} ({mod.name})"
        elif mod.parent.parent.name == "227300" or mod.parent.name == "227300":
            name = f"workshop {mod.parent.name if mod.parent.name != '227300' else mod.name}/{mod.name}"
        return name, files

    @staticmethod
    def unit_names(blobs) -> set[str]:
        names = set()
        for b in blobs:
            if b:
                t = b.decode("utf-8-sig", errors="replace")
                names |= {m.group(2) for m in UNIT_DEF_RE.finditer(t)
                          if not m.group(2).startswith("_nameless.")}  # file-local, can't clash
        return names

    def check_mods(self, out: Path, our_mod: Path) -> None:
        log("Checking for conflicts with your other ETS2 mods")
        ours = {"/" + p.relative_to(out).as_posix(): p for p in out.rglob("*") if p.is_file()}
        our_units = self.unit_names(p.read_bytes() for k, p in ours.items() if k.endswith(DEF_TEXT))
        checked = clashes = 0
        for mod in self.mod_sources():
            if mod.resolve() == our_mod.resolve() or mod.name == our_mod.name:
                continue
            try:
                name, files = self.read_mod_defs(mod)
            except Exception as e:
                warn(f"could not read {mod}: {e}")
                continue
            if not files:
                continue
            if f"/def/camera/camera_storage.{self.mod_id}.sii" in files:
                continue  # an older build of this same mod
            checked += 1
            units = sorted(our_units & self.unit_names(files.values()))
            shared = [p for p in files if p in ours and not p.startswith("/automat/")
                      and p not in ("/manifest.sii", "/mod_description.txt", "/mod_icon.jpg")]
            if units or shared:
                clashes += 1
                self.w(f"conflict with {name}:")
                for u in units[:10]:
                    log(f"      same unit name: {u}")
                for p in sorted(shared)[:10]:
                    log(f"      same file:      {p}  (the mod higher in Mod Manager wins)")
                more = len(units) + len(shared) - min(len(units), 10) - min(len(shared), 10)
                if more > 0:
                    log(f"      ... and {more} more")
        log(f"      checked {checked} mod(s), {clashes} with conflicts")

    # -- optional: ATS-style handling patch for other car mods ----------------
    def ets2_index(self) -> set[str]:
        if not getattr(self, "ets2_all", None):
            self.ets2_all = set()
            for f in sorted(self.ets2.glob("*.scs")):
                self.ets2_all |= self.ex.list(f)
        return self.ets2_all

    def find_car_mods(self) -> list[dict]:
        """One entry per car chassis file: {mod, model, path, text, body}. Classification is per
        chassis, because packs like "Drivable AI Vehicles" put buses, vans and cars in one folder."""
        forced: dict[str, str | None] = {}  # "model" or "model/chassis_stem" -> body or None
        for spec in self.a.car or []:
            key, _, body = spec.partition("=")
            if body and body not in HANDLING_PROFILES:
                sys.exit(f"--car {spec}: body must be one of {', '.join(HANDLING_PROFILES)}")
            forced[key.strip()] = body or None
        excluded = {m.strip() for m in self.a.not_car or []}
        base = self.ets2_index()
        self.patch_tires: dict[str, tuple[str, str]] = {}  # path -> (mod, text)
        entries: list[dict] = []
        seen: dict[str, str] = {}
        for mod in self.mod_sources():
            try:
                name, files = self.read_mod_defs(mod)
            except Exception as e:
                warn(f"could not read {mod}: {e}")
                continue
            texts = {p: b.decode("utf-8-sig", errors="replace") for p, b in files.items() if b}
            if any(p.startswith("/def/camera/camera_storage.rt2ets2_") for p in files) \
                    or any(HANDLING_MARK in t for t in texts.values()):
                continue  # our own port (already ATS handling) or a previous patch
            for p, t in texts.items():
                m = re.match(r"^/def/vehicle/truck/([^/]+)/data\.sii$", p)
                if not m:
                    continue
                model = m.group(1)
                if model in excluded:
                    continue
                tags = set(re.findall(r'tags\[\]:\s*"([^"]+)"', t))
                is_car = model in forced or any(k.startswith(model + "/") for k in forced) or \
                    bool(CAR_CAMERA_RE.search(t)) or \
                    bool(tags & {"car", "sedan", "suv", "pickup", "offroad", "muscle"})
                if not is_car:
                    continue
                for q, s in sorted(texts.items()):
                    if not (q.startswith(f"/def/vehicle/truck/{model}/chassis/") and CHASSIS_UNIT_RE.search(s)):
                        continue
                    stem = Path(q).stem
                    key = f"{model}/{stem}"
                    if key in excluded:
                        continue
                    if key in forced or model in forced:
                        body = forced.get(key) or forced.get(model) or classify_chassis(stem, t) or "sedan"
                    else:
                        unit = CHASSIS_UNIT_RE.search(s).group(0)
                        nm = " ".join(re.findall(r'(?m)^\s*name:\s*"([^"]*)"', s))
                        # folder of the 3D model, e.g. /vehicle/ai/lowcab/ai.pmd -> "lowcab"
                        mdl = " ".join(Path(x).parent.name for x in
                                       re.findall(r'(?m)^\s*(?:detail_model|model):\s*"([^"]+)"', s))
                        body = classify_chassis(f"{stem} {unit} {nm} {mdl}", t)
                    if body is None:
                        continue  # bus, forklift, tractor ...
                    if q in seen and seen[q] != name:
                        self.w(f"{q} is in both {seen[q]} and {name}; skipped (can't tell which one wins)")
                        entries = [e for e in entries if e["path"] != q]
                        continue
                    seen[q] = name
                    entries.append({"mod": name, "model": model, "path": q, "text": s, "body": body})
                # car tires shipped by this mod (not base-game ones); skip heavy-vehicle tires
                for q, s in texts.items():
                    if re.match(r"^/def/vehicle/[fr]_tire/[^/]+\.sii$", q) and q not in base \
                            and "accessory_wheel_data" in s and classify_chassis(Path(q).stem) is not None:
                        self.patch_tires.setdefault(q, (name, s))
        for key in forced:
            if not any(e["model"] == key or f"{e['model']}/{Path(e['path']).stem}" == key for e in entries):
                self.w(f"--car {key}: no matching chassis found in your installed mods")
        return entries

    def build_handling_patch(self, next_to: Path | None) -> Path | None:
        log("Building ATS-style handling patch for your installed car mods")
        cars = self.find_car_mods()
        if not cars:
            self.w("no car mods found (use --car brand.model to add one)")
            return None
        out = self.fresh("handling")
        chassis_re = re.compile(r"accessory_chassis_data\s*:\s*[A-Za-z0-9_.]+\s*\{")
        wheel_re = re.compile(r"accessory_wheel_data\s*:\s*[A-Za-z0-9_.]+\s*\{")
        counts: dict[tuple[str, str], dict[str, int]] = {}
        for c in cars:
            prof = HANDLING_PROFILES[c["body"]]
            text = c["text"]
            # an @include'd .sui may hold the per-axle arrays; count only what's in this file
            axles = len(re.findall(r"(?m)^\s*powered_axle\[", text)) or \
                len(re.findall(r"(?m)^\s*kerb_weight\[", text))
            lines = [f"{k}: {prof[k]}" for k in HANDLING_SCALARS]
            replace = set(HANDLING_SCALARS)
            if axles == 2:  # per-axle settings only when the layout matches a car
                lines += ["axle_suspension_type[]: wishbone"] * 2
                lines += [f"suspension_damping_factor[]: {v}" for v in prof["suspension_damping_factor"]]
                replace |= set(HANDLING_ARRAYS)
            new, n = set_unit_attrs(text, chassis_re, lines, replace)
            if n:
                d = out / c["path"].lstrip("/")
                d.parent.mkdir(parents=True, exist_ok=True)
                d.write_text(new, encoding="utf-8", newline="\n")
                k = (c["mod"], c["model"])
                counts.setdefault(k, {}).setdefault(c["body"], 0)
                counts[k][c["body"]] += 1
        for path, (_, text) in self.patch_tires.items():
            new, n = set_unit_attrs(text, wheel_re, [f"grip_factor: {HANDLING_PROFILES['sedan']['grip_factor']}"],
                                    {"grip_factor"})
            if n:
                d = out / path.lstrip("/")
                d.parent.mkdir(parents=True, exist_ok=True)
                d.write_text(new, encoding="utf-8", newline="\n")
        report = []
        for (mod, model), bodies in sorted(counts.items()):
            summary = ", ".join(f"{n} {b}" for b, n in sorted(bodies.items()))
            report.append(f"{model}: {summary}  [{mod}]")
            log(f"      {model:22} {summary:40} [{mod}]")
        log(f"      tires given car grip: {len(self.patch_tires)}")
        (out / "manifest.sii").write_text(
            "SiiNunit\n{\nmod_package : .package_name\n{\n"
            f'\tpackage_version: "{__version__}"\n'
            '\tdisplay_name: "ATS-style car handling for your car mods (rt2ets2)"\n'
            '\tauthor: "rt2ets2"\n\tcategory[]: "physics"\n'
            '\tdescription_file: "mod_description.txt"\n}\n}\n', encoding="utf-8", newline="\n")
        (out / "mod_description.txt").write_text(
            "Gives your installed car mods the suspension, steering, sway bar, centre of gravity,\n"
            "drag and tire grip settings of ATS Road Trip cars. Engines and weights are untouched.\n"
            "Generated locally by rt2ets2 from the mods on this PC - it contains modified copies of\n"
            "those mods' chassis/tire files, so don't upload it. Place it ABOVE the car mods in\n"
            "Mod Manager, and re-run rt2ets2 after a car mod updates.\n\nPatched:\n"
            + "".join(f"- {r}\n" for r in report), encoding="utf-8", newline="\n")
        dst = (next_to.parent if next_to else Path("output").resolve()) / "rt2ets2_car_handling.scs"
        zip_dir(out, dst)
        log(f"      {sum(sum(b.values()) for b in counts.values())} chassis -> {dst}")
        return dst

    def install(self, mod: Path) -> None:
        target = Path(self.a.install_dir) if self.a.install_dir else None
        if target is None:
            docs = find_documents()
            target = docs / "Euro Truck Simulator 2" / "mod" if docs else None
        if target is None or not target.parent.is_dir():
            self.w("could not find the ETS2 documents folder; use --install-dir")
            return
        target.mkdir(exist_ok=True)
        shutil.copy2(mod, target / mod.name)
        log(f"Installed to {target / mod.name}")

    def run_handling_only(self) -> None:
        """Standalone mode: needs only ETS2 + the user's installed car mods (no ATS)."""
        if not (self.ets2 / "def.scs").is_file():
            sys.exit(f"ETS2 folder looks wrong (no def.scs): {self.ets2}")
        self.mod_id = "rt2ets2_handling"
        self.work.mkdir(parents=True, exist_ok=True)
        self.ex = Extractor.obtain(self.a.extractor, Path(self.a.tools).resolve(), self.work / "lists")
        out = Path(self.a.output).resolve() if self.a.output else None
        patch = self.build_handling_patch(out)
        if patch and self.a.install:
            self.install(patch)
        if not self.a.keep_work:
            shutil.rmtree(self.work / "handling", ignore_errors=True)
        log()
        if patch:
            log(f"Done: {patch}")
            log("Put it ABOVE your car mods in Mod Manager. Re-run after a car mod updates.")
            log("It contains modified copies of other authors' files: keep it for yourself, don't upload it.")

    def run(self) -> None:
        if self.a.handling_only:
            return self.run_handling_only()
        if not self.ats:
            sys.exit("--ats is required (or use --handling-only)")
        self.check_inputs()
        self.extract_dlc()
        self.list_games()
        self.pull_deps(self.seed())
        out = self.build(self.load_locale())
        self.validate(out)
        mod = self.pack(out)
        addon = None if self.a.no_speed_addon else self.build_speed_addon(mod)
        handling = self.build_handling_patch(mod) if self.a.handling_patch else None
        if handling and self.a.install:
            self.install(handling)
        if self.a.check_mods:
            self.check_mods(out, mod)
        if self.a.install:
            self.install(mod)
            if addon:
                self.install(addon)
        if not self.a.keep_work:
            for d in ("dlc", "deps", "build", "ats_locale", "ats_camera", "ets2_camera", "ets2_version",
                      "ets2_country", "speed_addon"):
                shutil.rmtree(self.work / d, ignore_errors=True)
        log()
        log(f"Done: {mod}")
        if addon:
            log(f"      {addon}  (optional: enable while driving cars, disable for trucks)")
        if self.warnings:
            log(f"{len(self.warnings)} warning(s) - see above.")
        log("Reminder: the built mod contains SCS Software content. Personal use only, do not share it.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="rt2ets2",
        description="Port an ATS Road Trip car DLC to ETS2 (cars sold as trucks) from your own game files.")
    ap.add_argument("--ats", help="American Truck Simulator install folder (contains base.scs); "
                                  "not needed with --handling-only")
    ap.add_argument("--ets2", required=True, help="Euro Truck Simulator 2 install folder (contains base.scs)")
    ap.add_argument("--dlc", help="Road Trip DLC .scs (default: the only dlc_rt_*.scs in the ATS folder)")
    ap.add_argument("-o", "--output", help="output .scs path (default: output/rt2ets2_<name>.scs)")
    ap.add_argument("--install", action="store_true", help="copy the result into Documents/Euro Truck Simulator 2/mod")
    ap.add_argument("--install-dir", help="mod folder to install into (implies --install)")
    ap.add_argument("--dealers", default="mod",
                    help="where to sell the cars: 'mod' (ETS2's Modded Trucks dealer, default), "
                         "'all' map brand dealers, or brands like 'scania,volvo'; combine with commas")
    ap.add_argument("--no-speed-addon", action="store_true",
                    help="don't build the optional 'car speed limits' add-on mod")
    ap.add_argument("--handling-patch", action="store_true",
                    help="also build an ATS-style handling patch for your installed car mods")
    ap.add_argument("--handling-only", action="store_true",
                    help="only build the handling patch (needs just --ets2, no ATS)")
    ap.add_argument("--car", action="append", metavar="MODEL[=BODY]",
                    help="treat this truck folder as a car, optionally forcing the body type "
                         "(sedan, suv, pickup, sports), e.g. --car skoda.superb=sedan")
    ap.add_argument("--not-car", action="append", metavar="MODEL",
                    help="never patch this truck folder")
    ap.add_argument("--check-mods", action="store_true",
                    help="scan your installed ETS2 mods (mod folder + Steam Workshop) for clashing "
                         "unit names or files, e.g. other car mods")
    ap.add_argument("--mods-dir", action="append",
                    help="extra folder of mods to include in --check-mods (repeatable)")
    ap.add_argument("--lang", default="en_us", help="ATS locale for part names (default: en_us)")
    ap.add_argument("--work", default="work", help="working folder (default: ./work)")
    ap.add_argument("--keep-work", action="store_true", help="keep extracted/intermediate files")
    ap.add_argument("--tools", default="tools", help="where to download the extractor (default: ./tools)")
    ap.add_argument("--extractor", help="use an existing sk-zk Extractor binary instead of downloading")
    ap.add_argument("--version", action="version", version=f"rt2ets2 {__version__}")
    a = ap.parse_args(argv)
    if a.install_dir:
        a.install = True
    Porter(a).run()


if __name__ == "__main__":
    main()
