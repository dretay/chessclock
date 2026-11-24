# Modules: the vacation countdown's trips

What the [vacation countdown](../vacation/README.md) counts down to is a **module**: a whole trip, in
a folder of its own in `vacation/modules/` (`/apps/vacation/modules/` on the board).
`vacation.conf`'s `MODULE` picks one (`cruise` by default); `vacation/modules.py` loads it.

| A module has | | |
|---|---|---|
| `module.json` | | its id, name, version, the host `api` it was made for, its scene, screens, settings and countdown wording |
| a **scene** | `scenes/NAME/` | what's behind the countdown (`THEME` picks one, else module.json's default) |
| **screens** | e.g. `map.py` | shown in turn with the countdown: a class taking the app, with `run(seconds)`; module.json names its file and class and the settings for its seconds and on/off |
| a **service** | `service` | its background job, e.g. fetching data; run in the module's folder with `MODULE_DATA` set (only on a kernel with WiFi: every service so far needs the network) |
| its **data** | `/apps/data/vacation/ID/` | whatever it fetches or saves (`MODULE_DATA`, or `app.module.data_dir` for a screen) |
| **settings** | module.json `settings` | its page in Settings > Theme (below) |
| desktop **tools** | `tools/` | helpers for the developer (e.g. sending data over USB); not installed |

The service writes, the screen reads: a dead network shows as old data, never a frozen screen.

## module.json

```json
{"id": "castle", "name": "Magic Kingdom", "version": "0.1.0", "api": 1,
 "scene": {"engine": "scene", "dir": "scenes", "default": "magic-kingdom"},
 "screens": [{"id": "waits", "file": "board.py", "class": "WaitsScreen", "enabled": "WAITS", "secs": "WAITS_SECS"}],
 "settings": [{"key": "RIDES", "label": "Rides", "note": "...", "type": "many", "options_from": "waits.json"}],
 "countdown": {"date_label": "Park day", "after": "Already there", "time": "09:00"},
 "short_names": {"Tomorrowland Transit Authority PeopleMover": "PeopleMover"}}
```

- **countdown**: Settings' label for the trip's date (`TRIP_DATE` in vacation.conf), what the header
  says once it's passed, and the time of day the last day counts down to (`TRIP_TIME` overrides).
- **settings** (Settings > Theme shows the first): `key` (the vacation.conf setting it writes),
  `label`, `note`, `type` `one` (pick one) or `many` (pick any; stored joined with `|`), and its
  options: listed (`options`; `strip` is taken off their front on the chips; `default`, `fallback`
  another setting to start from), or the `rides` names in a file the service writes
  (`options_from`; its `*_example` version beside the module until then).
- **short_names**: shorter names for long ones, on the chips and the module's screens. Text from
  data is drawn letter by letter, plain ASCII (`vacation/vacation_text.py`).

## Scenes

A scene folder holds what the drawing library (`vacation/fx/vacfx.c`) loads: `day.rgb.gz`,
`dusk.rgb.gz`, `night.rgb.gz` (800x480 raw RGB plates, blended by the time of day), `mask.raw.gz`
(255 where it isn't sky: no water there, and fireworks go behind it), `lights.bin.gz` (the windows'
light: pixels, their light, their window, so windows switch one at a time at night), `cards.bin.gz`
(the flip-clock cards, the last day's colon and the banner for the day itself),
`settings_bg.rgb.gz` (the Settings screen's background) and `theme.json`:

- `horizon`: the sea's top (the ship), or where the fireworks go up from;
- `cards`: where the cards go (`center_x`, `top`, `gap`; `label_gap` -1: no DAYS label);
- `effects`: the library's scene effects it has (`water`, `wake`, `smoke`, `gulls`, `dolphins`,
  `raft`); without the list, all of them. Fireworks, window light and the cards are every scene's;
- the ship's own places, for those effects (`stacks`, `bow`, `stern`, `mast`, `tube`, scales), left
  out by a scene without them.

The generators are in `tools/themegen/` ([its README](../tools/themegen/README.md)): the cruise's from a
photo, the castle's from a 3D model (`tools/themegen/castle/build_castle.sh`).

## The two so far

**The cruise** (`modules/cruise/`): the Disney Dream (`scenes/dream/`; `scenes/dream-blender/` is a
Blender-rendered version, not installed), the fleet map (`map.py`, its Caribbean chart in `map/`, made
by `tools/themegen/build_map.py`), and live ship positions from AIS (`ais.py`, aisstream.io) into
`/apps/data/vacation/cruise/ships.csv`. AIS needs WiFi and an API key in
`/apps/data/vacation/cruise/ais.key`; until then the map shows `ships_example.csv`
(`modules/cruise/tools/send_ships.py` puts a file there over USB). Settings > Theme: the ship the map
follows (`MAP_SHIP`).

**The castle** (`modules/castle/`): Cinderella Castle at Magic Kingdom (`scenes/magic-kingdom/`,
rendered from a 3D model: day, dusk and night from one camera, a light AI detail pass over all but
the castle, parchment cards, the windows' light), with none of the ship's effects; the wait-times
board (`board.py`); and ride waits, park hours and show times from ThemeParks.wiki (`waits.py`, free,
no key) into `/apps/data/vacation/castle/waits.json`, else `waits_example.json`. Settings > Theme: the
rides the board shows (`RIDES`); `SHOW_NAME` the fireworks show it names (Happily Ever After); `PARK`
another park's ThemeParks.wiki id.

## Packing, signing and installing

```sh
tools/modules/keygen.sh                          # once: the signing key (~/.config/licheepi-nano/), and its
                                                 #   public half into the base system's trusted keys
tools/modules/pack.py castle --key ~/.config/licheepi-nano/module-signing.pem
                                                 # -> build/modules/castle-0.1.0.tar.gz and .tar.gz.sig
```

Over USB, in one go (pack, sign, copy, `modinstall`, restart the app):

```sh
tools/board/deploy_module.py --use castle        # --use: and switch to it; [--force] older versions; [--key KEY]
```

Or by hand, on the board, with the two files copied over (to `/apps/data/`, not RAM-backed `/tmp`):

```sh
modinstall --check castle-0.1.0.tar.gz           # only check it
modinstall castle-0.1.0.tar.gz                   # check it and install it; then /etc/init.d/S99app restart
```

**The tarball** holds exactly what `vacation/install.sh` puts on the board (`tools/test/check.py`
checks they agree), with a `MANIFEST.json` of each file's SHA-256, and is reproducible.

**The `.sig`** is a short signed statement: the module's id, name, version and api, the tarball's size
and SHA-512, the signing key's id, and an Ed25519 signature over those lines. `modinstall`
(`package/modinstall`, in the base system; Ed25519 from [Monocypher](https://monocypher.org)):

1. checks the statement's signature against the keys in `/etc/modules/trusted.keys`, which only a
   new base system changes;
2. checks the tarball's size and SHA-512 against the statement, before reading anything in it;
3. refuses an older version than the installed one (`--force` allows it) and an api newer than the
   app's (`API` in `vacation/modules.py`);
4. unpacks into `modules/.staging-ID`: regular files and folders only, all under `ID/`, no `..`,
   no links, size-limited;
5. swaps it in with one rename, keeping the previous version in `modules/.old-ID`, and records the
   statement as `ID/.signature`.

It needs a few KB of memory whatever the module's size. `tools/test/test_modinstall.py` tries a good
module and the ways to get a bad one in (changed tarball or statement, untrusted key, downgrade,
paths out of the folder, links).

**What signing doesn't do:** a module is Python running as root, inside the app (its screens) and
beside it (its service). The signature proves who made it and that it wasn't changed; it doesn't limit
what it can do. That's the right trade while every module is yours.

**Not done yet:** a catalog (a signed index of modules to download, e.g. from GitHub releases),
installing from Settings over WiFi, and refusing unsigned modules (now: `tools/board/deploy_app.py`
still copies modules straight from the repository, as the developer's way in; a module installed that
way has no `.signature`).

**Keys:** the private key never goes in the repository (`*.pem` is ignored); `trusted.keys` can hold
several, so a new key can be added in one base-system update and the old one removed in a later one.

## Generated art in the repository

A scene is generated (and reproducibly: the generators write gzip files without timestamps, so the
same pictures make the same files), and each regeneration adds megabytes to the history. So commit a
scene's files at milestones, when a version is to be kept, rather than every iteration; work in
progress stays in `tools/themegen/work/` (ignored). If the history grows too big, the scenes'
`*.gz` are what to move to Git LFS.

## Checking

`tools/test/check.py`: every module.json and its files, packing against install.sh, and renders of
each module with the device's own drawing code, compared pixel for pixel with a baseline
([tools](tools.md)).
