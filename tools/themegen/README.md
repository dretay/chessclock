# themegen: artwork for the countdown apps

Builds a theme's plates for the countdown display on a desktop machine. The board is
far too slow to render anything, so it only blends these finished images and animates
small effects over them.

A theme is a set of 800x480 images rendered from the same camera:

| Plate | Use on the device |
|---|---|
| `day.png`, `dusk.png`, `night_dark.png` | blended by time of day |
| `night_lit.png` | the night plate with every window lit; (lit − dark) per window cell is added to switch lights on and off |
| `mask.png` | where the subject is (white): water ripples and fireworks stay off it |
| `scene.json` | screen positions the effects need: the horizon, funnel tops (smoke), bow and stern (foam and wake), mast, the AquaDuck path |

## Disney Dream

```
tools/themegen/build_dream.sh            # full quality, ~15 min on an M2
tools/themegen/build_dream.sh --quick    # a quick look, ~3 min
```

Writes the plates to `apps/cruise/scenes/dream/`, and to `tools/themegen/work/dream/`
(git-ignored): the intermediate files plus `mockup/cruise-mockups.html`, an interactive
page that animates the plates the way the device will (time-of-day slider, fireworks,
horn), and `mockup/preview.png`.

Needs Blender 4.2 or later (Cycles; set `BLENDER=` if it isn't at the macOS default
path), Python 3 with Pillow, and the source files in `assets/`, listed in
`apps/cruise/scenes/dream/SOURCES.md`.

### How it works

1. `cruise/build_livery.py`: the side-profile photo is warped onto a side elevation of the
   model (metres along the ship by metres up), using a few matched stations: bow,
   funnels, stern. This gives the real paint, windows and balconies. On top of that:
   - the bow scrollwork and anchor ornament come from the high-resolution bow photo
   - the photo's flat lifeboats are painted out, leaving a dark recess for 3D boats
   - a stray porthole is removed
   - `windows.png` marks the glass that lights at night: cabin decks only, no funnels,
     nothing forward of the round porthole cluster
2. `cruise/scene.py` (run by Blender):
   - imports the STL and projects the elevation onto its side faces
   - paints the rest by position: navy hull, gold stripe, red boot band, funnels, front
     window strips and bridge glass, aft glass
   - moves the 3D lifeboats and davits to where the photo has them
   - renders over a Blender ocean under a photographed sky (day, dusk) or a moonlit night
   - the `mask` look renders the ship alone
3. `mockup/photo_windows.py` and `mockup/build_page.py`: the 800x480 plates (with a
   light contrast and colour lift), the mockup page and the preview sheet.

Useful options for `scene.py` while adjusting things (after `--`): `--preview`
(400x240), `--samples N`, `--az/--el/--dist/--lens/--shift/--target x,y,z` for the
camera, `--info` (positions only, no render), `--no-livery`.

### The device theme (photo version)

The countdown on the board uses the photograph (the mockup's approach 1), not the Blender renders:
`cruise/photo_theme.py` turns it into `apps/cruise/scenes/dream/`:
- day, dusk and night plates (graded from the photo; the night one has stars)
- the ship mask
- the window light: built from the photo's glass, with its glow baked in, grouped into windows
  that switch as a whole
- the flip-clock cards

All of it is in raw or gzipped formats, so the board does no image decoding. The card digits need
`assets/fonts/CormorantGaramond-SemiBold-Lining.ttf`, made once by `make_lining_font.py` (needs
`pip install fonttools`) from Google Fonts' Cormorant Garamond (OFL).

`bench_board.py` and `bench_board_effects.py` are the board speed tests that showed Python and
Pillow can't do the per-frame drawing.

### Lessons for the next theme

- Choose the screen's view first, and get one sharp, high-resolution photo from close to
  that angle. Projecting a photo from a matching camera is much simpler than warping a
  side view.
- A model with separate parts and colours (OBJ, glTF) saves guessing where paint goes. A
  print STL is a single fused shell.
- Night photos show which windows really light up.
- Check every photo is the right subject (the Wonder, Magic and Fantasy look alike).
