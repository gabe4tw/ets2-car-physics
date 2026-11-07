#!/usr/bin/env python3
"""axle_kit - give an ETS2/ATS car mod a solid (live) rear axle, the way the ATS Road
Trip cars are set up, using YOUR OWN axle model.

It edits a chassis .sii in your unpacked mod folder:
  * axle_suspension_type[]  -> wishbone (front) / solidaxle (rear)
  * solid_axle_suspension_model[] -> your axle beam model
  * one vehicle_animation_data (type: suspension) per wheel; the rear wheels get
    main_bone: axle_l / axle_r so the beam follows the wheels
and checks that every model/animation it references exists in your mod.

Your axle model needs bones named as passed with --bones (default axle_l, axle_r),
exported with SCS Blender Tools. No SCS content is included in this tool.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

MARK = "# axle_kit"
CHASSIS_RE = re.compile(r"accessory_chassis_data\s*:\s*[A-Za-z0-9_.]+\s*\{")


GAME_ROOTS = ("def", "vehicle", "model", "model2", "material", "sound", "unit", "ui", "automat")


def norm(p: str | None) -> str | None:
    """Game path as '/def/...'. Repairs paths that Git Bash/MSYS rewrote into Windows paths
    (e.g. '/def/x.sii' -> 'C:/Program Files/Git/def/x.sii')."""
    if not p:
        return p
    p = p.replace("\\", "/")
    parts = p.split("/")
    for i, part in enumerate(parts):
        if part in GAME_ROOTS and (i == 0 or ":" in p or i > 0):
            if i == 0 or parts[i - 1] == "" or ":" in p:
                return "/" + "/".join(parts[i:])
    return "/" + p.lstrip("/")


def game_path(mod: Path, p: str) -> Path:
    return mod / norm(p).lstrip("/")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="axle_kit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mod-dir", required=True, help="your unpacked mod folder (contains def/, vehicle/ ...)")
    ap.add_argument("--chassis", required=True,
                    help="chassis file inside the mod, e.g. /def/vehicle/truck/brand.model/chassis/rwd.sii")
    ap.add_argument("--axle-model", help="your axle beam .pmd (game path). Omit with --physics-only")
    ap.add_argument("--front", default="wishbone", choices=("wishbone", "solidaxle"),
                    help="front axle type (default wishbone; solidaxle for e.g. old 4x4s)")
    ap.add_argument("--bones", default="axle_l,axle_r", help="left,right bone names in the axle model")
    ap.add_argument("--susp-front", help="front wheel suspension .pmd (game path), optional")
    ap.add_argument("--susp-front-anim", help="front anim pattern with {side} = l/r, e.g. /vehicle/.../susp_0_{side}_anim.pma")
    ap.add_argument("--susp-rear", help="rear wheel suspension .pmd (game path), optional")
    ap.add_argument("--susp-rear-anim", help="rear anim pattern with {side} = l/r")
    ap.add_argument("--travel", type=float, nargs=2, default=(-15.0, 30.0), metavar=("MIN", "RANGE"),
                    help="suspension animation min and range in degrees/cm as in SCS defs (default -15 30)")
    ap.add_argument("--physics-only", action="store_true",
                    help="EXPERIMENTAL: set solidaxle without an axle model or animations (no visible beam)")
    ap.add_argument("--dry-run", action="store_true", help="print the result instead of writing it")
    a = ap.parse_args(argv)
    for k in ("chassis", "axle_model", "susp_front", "susp_rear", "susp_front_anim", "susp_rear_anim"):
        setattr(a, k, norm(getattr(a, k)))

    mod = Path(a.mod_dir)
    chassis = game_path(mod, a.chassis)
    if not chassis.is_file():
        sys.exit(f"chassis not found: {chassis}")
    if not a.physics_only and not a.axle_model:
        sys.exit("--axle-model is required (or use --physics-only)")

    # every referenced file must exist in the mod
    refs = [a.axle_model, a.susp_front, a.susp_rear]
    for pat in (a.susp_front_anim, a.susp_rear_anim):
        if pat:
            if "{side}" not in pat:
                sys.exit(f"animation pattern needs {{side}}: {pat}")
            refs += [pat.format(side="l"), pat.format(side="r")]
    missing = [r for r in refs if r and not game_path(mod, r).is_file()]
    if missing and not a.physics_only:
        for r in missing:
            print(f"missing in mod: {r}")
        return 1
    for r in refs:
        if r and r.endswith(".pmd") and not game_path(mod, r[:-4] + ".pmg").is_file():
            print(f"warning: {r} has no matching .pmg")

    text = chassis.read_text(encoding="utf-8-sig")
    m = CHASSIS_RE.search(text)
    if not m:
        sys.exit("no accessory_chassis_data unit in that file")
    end = re.compile(r"\n[ \t]*\}").search(text, m.end())
    body = text[m.end():end.start()]
    axles = len(re.findall(r"(?m)^\s*powered_axle\[", body)) or len(re.findall(r"(?m)^\s*kerb_weight\[", body))
    if axles != 2:
        sys.exit(f"this chassis has {axles} axle(s); axle_kit supports 2-axle cars")
    if MARK in text:
        sys.exit("already processed by axle_kit (restore the .bak first to redo it)")

    left, right = (b.strip() for b in a.bones.split(","))
    drop = re.compile(r"(?m)^[ \t]*(?:axle_suspension_type|solid_axle_suspension_model|animation)(?:\[\d*\])?[ \t]*:.*\r?\n?")
    old_anims = re.findall(r"(?m)^[ \t]*animation\[\]:\s*(\.\S+)", body)
    body = drop.sub("", body).rstrip()
    lines = [f"axle_suspension_type[]: {a.front}", "axle_suspension_type[]: solidaxle"]
    if a.axle_model:
        if a.front == "solidaxle":
            lines.append(f'solid_axle_suspension_model[]: "{a.axle_model}"')
        lines.append(f'solid_axle_suspension_model[]: "{a.axle_model}"')
    units = []
    if not a.physics_only:
        lines += [f"animation[]: .axk_susp_{i}" for i in range(4)]
        for i in range(4):
            front = i < 2
            side = "l" if i % 2 == 0 else "r"
            model = a.susp_front if front else a.susp_rear
            anim = (a.susp_front_anim if front else a.susp_rear_anim)
            u = [f"vehicle_animation_data: .axk_susp_{i}", "{", "\ttype: suspension", f"\twheel_index: {i}"]
            if model:
                u.append(f'\tmodel: "{model}"')
            if anim:
                u.append(f'\tanim: "{anim.format(side=side)}"')
            u += [f"\tmin: {a.travel[0]}", f"\trange: {a.travel[1]}"]
            if not front or a.front == "solidaxle":
                u.append(f"\tmain_bone: {left if side == 'l' else right}")
            u.append("}")
            units.append("\n".join(u))
        if old_anims:
            print(f"note: replaced existing suspension animation refs {old_anims}; "
                  "their old vehicle_animation_data units are left in the file unused")
    new_body = body + f"\n\n\t{MARK}\n" + "".join(f"\t{l}\n" for l in lines).rstrip("\n")
    close = text.find("}", end.start())  # the chassis unit's closing brace
    rest = text[close + 1:]
    new = text[:m.end()] + new_body + text[end.start():close + 1]
    if units:
        new += "\n\n" + "\n\n".join(units)
    new += rest

    if a.dry_run:
        print(new)
        return 0
    bak = chassis.with_suffix(chassis.suffix + ".bak")
    shutil.copy2(chassis, bak)
    chassis.write_text(new, encoding="utf-8", newline="\n")
    print(f"updated {chassis}  (backup: {bak.name})")
    print(f"axle model bones expected: {left}, {right}")
    if a.physics_only:
        print("physics-only: no beam model/animations - test in game; if the car misbehaves, restore the .bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
