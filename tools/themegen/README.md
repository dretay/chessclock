# themegen: artwork for the countdown apps

Makes the countdown apps' scenes and pictures on the Mac. The board is far too slow to render
anything, so it only blends finished images and animates small effects over them.

Every app's scene is made the same way: from one daytime photo, in the previewer's **Scene Builder**
(`tools/preview/`, see [docs/tools.md](../../docs/tools.md)), or from the command line:

| Tool | Does |
|---|---|
| `photo_scene.py` | a photo into a scene: dusk and night graded from it, the sky found (the AI model, `segment.py`, or by colour), trials to compare, kept into the app; and everything the Scene Builder does to one (lights on a sphere, windows, water, effects, layout) |
| `scene_pack.py WORK OUT` | a scene's work folder (`work/APP/`: `day.png`, `dusk.png`, `night.png`, `mask.png`, `windows.png`, `scene.json`...) into what the device loads (`apps/APP/scenes/NAME/`: raw and gzipped, so the board decodes no images): plates, mask, window light, twinkle lights, the cards, `theme.json` |
| `card_extras.py` | the cards' colon (the last day's HH:MM) and the glowing greeting text, used by `scene_pack.py` |
| `segment.py` | what each pixel is (sky, water, building...), SegFormer in the AI environment (`tools/setup.sh --ai`) |
| `app_icon.py`, `app_splash.py` | an app's icon and boot splash, from its scene |
| `build_ui.py` | the Settings pages' pre-drawn text |
| `build_map.py`, `build_sea.py` | the cruise's Caribbean chart and its sea routes (from `assets/map/`: NASA imagery, Natural Earth coastlines) |
| `make_lining_font.py` | the card font with lining figures (`tools/setup.sh` runs it) |
| `bench_board.py`, `bench_board_effects.py` | the board speed tests that showed Python and Pillow can't do the per-frame drawing |

`work/` (git-ignored) holds each app's work folder: its photo and what's been painted on it. The
apps' packed scenes are in git.

## A ship's scene (the cruise)

The cruise's work folder (`work/cruise/`) was made from its finished scene, which an earlier script
made from `assets/dream/panel_photo.jpg`: the photo lowered 52 px (more sky above the ship), the
photo's frozen bow wave painted out (the board draws a moving one), its own dusk and night grade, a
hand-drawn ship outline and its cabins' lights grouped by cabin. Its `scene.json` keeps what makes it a
ship's scene:

- `"mask_as_is": true`: the mask is the ship's outline, as it is (not "everything below the horizon"),
  so the sea round it ripples, and the wake and the bow wave know where the hull is;
- `"plates_fixed": true`: its plates and outline stay as they are when the scene is made again;
- `"stars": false`: its night plate has its own stars;
- `"lights_fixed": "lights_fixed.bin.gz"`: its cabin lights, as they were, until its windows are edited
  in the Scene Builder (`windows_base.png` holds the cabins' glass to start from);
- `"theme_extra"`: the ship's places for its effects (funnel tops for the smoke, bow, stern, mast, the
  AquaDuck's tube for the raft), passed to `theme.json` as they are;
- `"effects"`: water, wake, smoke, gulls, dolphins, raft.

## Lessons

- Choose the screen's view first, and get one sharp, high-resolution photo from close to that angle.
- Night photos show which windows really light up.
- Check every photo is the right subject (the Wonder, Magic and Fantasy look alike).
