### DISCLAIMER: Claude has been used to help with porting over everything to ETS2. Code written by Claude has been triple-checked and debugged. If you still encounter bugs, open an Issue.

# ets2 car physics

Tools for driving cars in **Euro Truck Simulator 2** the way they drive in ATS:

- **[`rt2ets2.py`](#usage)** ports an ATS **Road Trip** car DLC you own to ETS2, optionally with car speed limits.
- **[`rt2ets2.py --handling-only`](#ats-style-handling-for-other-car-mods)** gives any ETS2 car mod you have installed ATS-style car handling. Needs only ETS2.
- **[`axle_kit.py`](#for-car-mod-authors)** helps car mod authors add a solid rear axle using their own models.

## rt2ets2

`rt2ets2` takes a Road Trip car DLC you own (for example *Road Trip: Ford*) and builds an ETS2 mod from **your own game files**. The cars are sold at ETS2's online **Modded Trucks** dealer and in the truck browser. You can buy, customize and free-roam with them, using the original SCS models, interiors, sounds, dashboards, paint jobs and accessories.

> **This repository contains no SCS Software content.** It's only a script. Everything in the mod it builds is copied from your own installs. The built mod contains SCS content, so keep it to yourself: **don't upload or share the generated `.scs`.**

## Requirements

You need all of these on your PC:

| | |
|---|---|
| **American Truck Simulator** | Installed, including the Road Trip DLC you want to port (for example `dlc_rt_ford.scs`) |
| **Euro Truck Simulator 2** | Installed. Built and tested against **1.61**. |
| **Python 3.10+** | [python.org](https://www.python.org/downloads/) |
| **Pillow** *(optional)* | `pip install pillow`. Only used to make the mod's icon. |

The script also needs [sk-zk/Extractor](https://github.com/sk-zk/Extractor) to read SCS archives. On the first run it downloads a pinned release (2026-07-29) and checks its SHA-256. To use your own copy instead, pass `--extractor PATH`.

## Usage

```bash
python rt2ets2.py --ats "D:/SteamLibrary/steamapps/common/American Truck Simulator" --ets2 "D:/SteamLibrary/steamapps/common/Euro Truck Simulator 2" --install
```

This builds `output/rt2ets2_ford.scs` and copies it into `Documents/Euro Truck Simulator 2/mod`. Then:

1. Start ETS2 and open **Mod Manager**.
2. Enable **"Road Trip: Ford (ATS port, as trucks)"**. Put it above any truck physics mods.
3. Open the **Modded Trucks** section of the online truck dealer, or use the truck browser.

The first run takes a few minutes because it indexes both games' archives. Later runs use a cache.

### Options

| Option | Description |
|---|---|
| `--ats PATH` | ATS install folder (the one containing `base.scs`). **Required.** |
| `--ets2 PATH` | ETS2 install folder. **Required.** |
| `--dlc FILE` | The Road Trip DLC to port. Defaults to the only `dlc_rt_*.scs` in the ATS folder. |
| `-o, --output FILE` | Where to write the mod. Default: `output/rt2ets2_<name>.scs`. |
| `--install` | Copy the mod into your ETS2 `mod` folder. The Documents folder is detected automatically, including redirected ones. |
| `--install-dir PATH` | Install into a specific mod folder. |
| `--dealers LIST` | Where the cars are sold. `mod` (default) is ETS2's Modded Trucks dealer. `all` adds every brand dealer on the map, or name brands like `scania,volvo`. You can combine them, e.g. `mod,volvo`. |
| `--handling-patch` | Also build the ATS-style handling patch for your installed car mods (see below). |
| `--handling-only` | Only build the handling patch. Needs just `--ets2`, not ATS. |
| `--car SPEC` / `--not-car SPEC` | Include, exclude or re-profile a car for the handling patch, e.g. `skoda.superb/xc90=suv`. |
| `--check-mods` | After building, scan your installed ETS2 mods (the `mod` folder and Steam Workshop) for clashing unit names or files, for example other car mods. |
| `--mods-dir PATH` | Extra folder of mods to include in `--check-mods`. You can repeat it. |
| `--lang CODE` | ATS language for part names, e.g. `de_de`. Default: `en_us`. |
| `--keep-work` | Keep the extracted intermediate files in `./work` for inspection. |
| `--extractor PATH` | Use an existing Extractor binary instead of downloading one. |

## How it works

1. Extracts the Road Trip DLC.
2. Indexes every archive in both games and finds the files the DLC needs that only ATS has. That includes shared car physics, car cameras, tire/wiper/suspension sounds, dashboard fonts and templates, the phone holder and cab trinkets, and driver animations. It then follows those files' own references until nothing is left.
3. Copies the car definitions from `/def/vehicle/car/…` to `/def/vehicle/truck/…` and rewrites the paths inside them.
4. Creates entries for the Modded Trucks dealer (`/def/vehicle/truck_dealer/<car brand>/`) and the truck browser, registers the extra cameras, and adds the brand logo.
5. Replaces `@@text_keys@@` with the strings from your ATS locale files, because ETS2 doesn't have them.
6. Comments out settings that exist only in ATS, such as the engines' `drivetrain_loss`. It finds them by comparing the two games' executables. ETS2 refuses to load a part file that contains an unknown setting, and opening the dealer then crashes the game.
7. Checks that every referenced file resolves, then packs the result as a `.scs` mod.

The DLC's original car-system definitions (`car_dealer`, `car_desktop` and so on) are left out on purpose. ETS2 has no car dealers on its map, and leaving them out avoids clashing with the truck copies.

## Car speed limits (optional add-on)

ETS2 always applies the **truck** speed limits to the player: 80 on motorways, plus speed cameras and police fines. The game has no per-vehicle setting for this. ATS only switches to car limits through its Road Trip car system, which ETS2 doesn't have.

So rt2ets2 also builds a separate mod, `rt2ets2_car_speed_limits.scs`, generated from your own ETS2 files. It gives the truck class each country's **car** limits and removes the truck caps: 130 on French motorways, unlimited sections on the German Autobahn, 100 on German country roads, and so on. The limits shown in the HUD, speed cameras and police all follow it.

- **It applies to whatever you drive.** That includes other car mods such as the Skoda Superb, and real trucks. Enable it in Mod Manager for car trips and disable it when you go back to trucking.
- **Base-game countries only:** it covers all 36 base-game countries, including map DLCs. Countries added by map mods such as ProMods keep their own limits.
- **Opting out:** pass `--no-speed-addon` to skip building it.

## ATS-style handling for other car mods

Most ETS2 car mods drive like light trucks. rt2ets2 can generate a **handling patch** that gives them the chassis setup of the ATS Road Trip cars:

- suspension type and per-axle damping
- steering lock
- sway bar stiffness
- centre of gravity
- drag
- tire grip

**You only need ETS2 for this, not ATS or a Road Trip DLC:**

```bash
python rt2ets2.py --handling-only --ets2 "D:/SteamLibrary/steamapps/common/Euro Truck Simulator 2" --install
```

It scans your installed mods (the `mod` folder and Steam Workshop), finds the car mods, and classifies **each chassis** into one of four built-in profiles:

| Profile | Modelled on | Used for |
|---|---|---|
| `sedan` | Crown Victoria '06 | hatchbacks, saloons, estates, MPVs |
| `suv` | Bronco '24 | SUVs and 4×4s |
| `pickup` | F‑150 '23 | pickups and vans |
| `sports` | Mustang '67 | sports and muscle cars |

Buses, coaches, fire trucks, forklifts, tractors, lowcab trucks and similar vehicles are skipped. This matters for packs like *Drivable AI Vehicles*, which mix cars and heavy vehicles in one folder.

- **Overrides:** `--car brand.model[/chassis][=profile]` forces a body type (e.g. `--car skoda.superb/xc90=suv`), and `--not-car brand.model[/chassis]` excludes something.
- **What it leaves alone:** engines, gearboxes and weights. Many car mods use deliberately scaled "truck" values for those, and changing them would break acceleration.
- **Load order:** put `rt2ets2_car_handling.scs` **above** your car mods in Mod Manager. Re-run the tool after a car mod updates.
- **Keep it to yourself:** the patch contains modified copies of other authors' chassis files, so don't upload it.
- **Solid rear axles:** the real ATS cars have one, but the patch uses independent suspension on both axles, because a solid axle needs a 3D axle model that other mods don't have. Modders can add their own with `axle_kit.py` (below).
- **Global steering:** steering sensitivity is a single global setting shared with trucks, so it isn't changed.

### For car mod authors

**Using the profiles in your own mod:** copy the numbers from `HANDLING_PROFILES` in [`rt2ets2.py`](rt2ets2.py) into your chassis, or run the patcher on your own mod and copy the result. These are plain chassis settings that ETS2 already supports; nothing extra is required. For the most authentic result, use **real** weight, torque and RPM values like the ATS cars do. ETS2 handles real values fine, and the ported Fords prove it, so the old "multiply everything for truck physics" trick isn't needed with these chassis settings.

**Adding a solid rear axle with `axle_kit.py`:** this makes your car's rear axle a live beam, like the ATS Road Trip cars, using **your own** axle model:

```bash
python axle_kit.py --mod-dir path/to/your/unpacked/mod --chassis /def/vehicle/truck/brand.model/chassis/rwd.sii --axle-model /vehicle/truck/brand_model/axle.pmd --susp-rear-anim "/vehicle/truck/brand_model/susp_1_{side}_anim.pma"
```

It sets `axle_suspension_type` (wishbone front, solidaxle rear) and `solid_axle_suspension_model`, and adds one `vehicle_animation_data` suspension unit per wheel. The rear wheels get `main_bone: axle_l` / `axle_r`, so your axle model needs bones with those names (or pass `--bones`), exported with SCS Blender Tools. It checks that every model and animation it references exists in your mod, refuses to run twice, and keeps a `.bak` of the chassis file.

- **Old-style 4×4s:** use `--front solidaxle`.
- **`--physics-only` (experimental):** sets a solid axle without any model. It isn't confirmed whether ETS2 accepts that, so test in-game and restore the `.bak` if needed.

## Compatibility with other car mods

The mod is designed to run alongside other drivable-car mods, such as the Workshop *Skoda Superb*:

- **Cameras:** ATS's car cameras use generic names (`camera.behind.car`, `camera.bumper.car`, `camera.wheel.car` and so on), and other car mods define the same names. ETS2 shares unit names across every mod, so whichever mod loaded last would win. rt2ets2 renames its copies (for example to `camera.behind.car.rt2ets2`) and keeps them in a private folder, so neither mod changes the other's cameras.
- **Dealer:** offers go into the car's own brand folder (`truck_dealer/ford/`) with prefixed file names, so they never replace another mod's dealer entries.
- **Car parts:** everything is namespaced by model (`vehicle.ford.bronco_24`, `….ford.bronco_24.engine` and so on), and the Road Trip wheel slots (`x_tire`, `p_disc` and so on) aren't used by ETS2 or other mods.

Run with `--check-mods` to confirm against your own mod list. It reports any remaining shared unit names, and any files that are also in another mod, in which case the mod higher in Mod Manager wins.

**Towing:** the Fords can't tow caravans, such as the Skoda mod's caravan. In SCS games, where a trailer attaches is defined inside the vehicle's 3D model, and the Road Trip models don't include a hitch.

## Limitations

- **Cars as trucks:** there are no Road Trip passenger jobs and no car garage. The cars use the truck job system.
- **No UK dealers:** Road Trip cars are left-hand drive only, so UK dealers don't sell them.
- **Handling:** the original car physics are kept, but they run through ETS2's truck system, so handling may feel different from ATS. Truck-physics mods can affect them too.
- **Slightly more power:** ETS2 has no `drivetrain_loss` setting, so the cars lose no power through the drivetrain and are a little quicker than in ATS.
- **Testing:** only *Road Trip: Ford* has been tested. Other Road Trip DLCs should work but are untested.
- **Game updates:** an SCS update to either game can break the build. Rerun the script after updating.

## Troubleshooting

- **Errors or crashes in-game:** check `Documents/Euro Truck Simulator 2/game.log.txt` for `<ERROR>` lines mentioning `/def/vehicle/truck/<brand>.`. A `has no attribute named 'X'` error means a game update added another ATS-only setting. Please open an issue with that line.
- **"unresolved reference" warnings while building:** a file the DLC needs wasn't found in your ATS install. Make sure ATS is fully updated and verify its files in Steam.
- **"Pass --dlc":** you have several Road Trip DLCs. Choose one with `--dlc PATH/dlc_rt_<name>.scs`.

## Legal

Not affiliated with or endorsed by SCS Software. *American Truck Simulator*, *Euro Truck Simulator 2* and all game content are the property of SCS Software. Vehicle names and brands belong to their respective owners. This tool only rearranges files you already own on your own machine. Don't redistribute what it builds.

The script itself is MIT licensed (see [LICENSE](LICENSE)).
