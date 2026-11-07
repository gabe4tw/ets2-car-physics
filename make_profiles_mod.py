#!/usr/bin/env python3
"""Build the standalone "ETS2 Car Physics" profiles mod - ready for the Steam Workshop.

The mod contains only our own files: SII include snippets holding the handling numbers
from rt2ets2.HANDLING_PROFILES. It needs no ATS and contains no SCS or third-party content.
Car mod authors use it by adding one line inside their chassis / tire units, e.g.

    accessory_chassis_data : rwd.brand.model.chassis
    {
        ...
        @include "/def/vehicle/ets2_car_physics/sedan.sui"
    }

Output (Steam Workshop layout, as used by SCS's Workshop Uploader):
    <out>/versions.sii
    <out>/universal/manifest.sii, mod_description.txt, mod_icon.jpg
    <out>/universal/def/vehicle/ets2_car_physics/*.sui
plus <out>.scs (zip) for testing from the local mod folder.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rt2ets2 import HANDLING_PROFILES, HANDLING_SCALARS, __version__, zip_dir  # noqa: E402

MOD_NAME = "ETS2 Car Physics"
INC_DIR = "def/vehicle/ets2_car_physics"
DESCRIBE = {
    "sedan": "hatchbacks, saloons, estates, MPVs (modelled on a full-size sedan)",
    "suv": "SUVs and 4x4s (modelled on a modern off-roader)",
    "pickup": "pickups and vans (modelled on a full-size pickup)",
    "sports": "sports and muscle cars (modelled on a classic muscle car)",
}
HEADER = """# {title} - part of the "{mod}" mod ({ver})
# Include INSIDE an accessory_chassis_data unit. Remove these attributes from your own
# chassis first, otherwise they are defined twice:
#   {attrs}
"""


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def make_icon(dst: Path) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed - no icon (pip install pillow)")
        return
    im = Image.new("RGB", (276, 162), (28, 32, 40))
    d = ImageDraw.Draw(im)
    for i in range(0, 276, 23):  # road dashes
        d.rectangle((i, 118, i + 12, 122), fill=(235, 190, 60))
    d.rectangle((0, 112, 276, 113), fill=(90, 96, 110))
    d.rectangle((0, 128, 276, 129), fill=(90, 96, 110))
    try:
        big = ImageFont.truetype("arialbd.ttf", 30)
        small = ImageFont.truetype("arial.ttf", 15)
    except OSError:
        big = small = ImageFont.load_default()
    d.text((16, 22), "ETS2 CAR", font=big, fill=(245, 245, 245))
    d.text((16, 56), "PHYSICS", font=big, fill=(235, 190, 60))
    d.text((16, 138), "sedan · suv · pickup · sports", font=small, fill=(180, 186, 198))
    im.save(dst, quality=92)


def make_preview(dst: Path) -> None:
    """512x512 Steam Workshop preview image (kept outside the mod folder so it isn't uploaded as content)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed - no preview image")
        return
    W = 512
    im = Image.new("RGB", (W, W), (28, 32, 40))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 330, W, 333), fill=(90, 96, 110))
    d.rectangle((0, 381, W, 384), fill=(90, 96, 110))
    for i in range(0, W, 40):
        d.rectangle((i, 353, i + 22, 360), fill=(235, 190, 60))
    try:
        big = ImageFont.truetype("arialbd.ttf", 64)
        mid = ImageFont.truetype("arialbd.ttf", 26)
        small = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        big = mid = small = ImageFont.load_default()
    d.text((36, 60), "ETS2 CAR", font=big, fill=(245, 245, 245))
    d.text((36, 135), "PHYSICS", font=big, fill=(235, 190, 60))
    d.text((38, 230), "Realistic handling profiles", font=mid, fill=(220, 224, 232))
    d.text((38, 264), "for car mods", font=mid, fill=(220, 224, 232))
    d.text((38, 420), "sedan  ·  suv  ·  pickup  ·  sports", font=small, fill=(180, 186, 198))
    d.text((38, 455), "resource for mod authors", font=small, fill=(140, 146, 158))
    im.save(dst, quality=90)


def build(out: Path) -> Path:
    if out.exists():
        shutil.rmtree(out)
    u = out / "universal"
    arrays = ("axle_suspension_type", "suspension_damping_factor")
    for name, p in HANDLING_PROFILES.items():
        scal = "".join(f"\t{k}: {p[k]}\n" for k in HANDLING_SCALARS)
        axle = ("\taxle_suspension_type[]: wishbone\n\taxle_suspension_type[]: wishbone\n"
                + "".join(f"\tsuspension_damping_factor[]: {v}\n" for v in p["suspension_damping_factor"]))
        # full profile: 2-axle cars
        write(u / INC_DIR / f"{name}.sui",
              HEADER.format(title=f"{name} profile, 2-axle car: {DESCRIBE[name]}", mod=MOD_NAME, ver=__version__,
                            attrs=", ".join(HANDLING_SCALARS + arrays)) + scal + axle)
        # core profile: everything except the per-axle arrays (other axle counts / own suspension)
        write(u / INC_DIR / f"{name}_core.sui",
              HEADER.format(title=f"{name} profile without per-axle settings", mod=MOD_NAME, ver=__version__,
                            attrs=", ".join(HANDLING_SCALARS)) + scal)
    grip = HANDLING_PROFILES["sedan"]["grip_factor"]
    write(u / INC_DIR / "tire.sui",
          f"# car tire grip - part of the \"{MOD_NAME}\" mod ({__version__})\n"
          "# Include INSIDE an accessory_wheel_data unit (your f_tire / r_tire defs).\n"
          "# Remove grip_factor from your own tire def first.\n"
          f"\tgrip_factor: {grip}\n")
    write(u / "manifest.sii",
          "SiiNunit\n{\nmod_package : .package_name\n{\n"
          f'\tpackage_version: "{__version__}"\n'
          f'\tdisplay_name: "{MOD_NAME}"\n'
          '\tauthor: "gabe4tw"\n'
          '\tcategory[]: "physics"\n'
          '\ticon: "mod_icon.jpg"\n'
          '\tdescription_file: "mod_description.txt"\n}\n}\n')
    write(u / "mod_description.txt",
          f"{MOD_NAME} - realistic car handling profiles for ETS2 car mods.\n\n"
          "This is a resource for car mod authors. On its own it changes nothing: car mods\n"
          "that support it include one of its profiles in their chassis, and list this mod\n"
          "as a required item.\n\n"
          "Profiles (suspension, steering lock, sway bar, centre of gravity, drag):\n"
          + "".join(f"  {k:7} {v}\n" for k, v in DESCRIBE.items())
          + "Plus tire.sui for car tire grip.\n\n"
          "Usage inside accessory_chassis_data:\n"
          '  @include "/def/vehicle/ets2_car_physics/sedan.sui"\n'
          "Use <profile>_core.sui if your chassis is not a 2-axle car or you set your own suspension.\n\n"
          "Source, docs and a patcher for existing car mods: https://github.com/gabe4tw/ets2-car-physics\n")
    write(out / "versions.sii",
          "SiiNunit\n{\npackage_version_info : .universal\n{\n\tpackage_name: \"universal\"\n}\n}\n")
    make_icon(u / "mod_icon.jpg")
    make_preview(out.parent / f"{out.name}_preview.jpg")
    scs = out.with_suffix(".scs")
    zip_dir(u, scs)
    return scs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", default="workshop/ets2_car_physics",
                    help="output folder (default: workshop/ets2_car_physics)")
    a = ap.parse_args(argv)
    scs = build(Path(a.out))
    print(f"Workshop folder: {Path(a.out).resolve()}")
    print(f"Test build:      {scs.resolve()}  (copy into Documents/Euro Truck Simulator 2/mod)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
