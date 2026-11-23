# Enclosure

A 3D-printable picture-frame enclosure for the clock: a slim front frame for
the 5" screen, a back cover with a pod for the Lichee Pi Nano, and a desk
cradle. Everything is in one parametric OpenSCAD file,
[`frame.scad`](frame.scad); the `.stl` files are exports of its defaults.

| Part | Size | Print |
|---|---|---|
| `frame.stl` | 141.5 x 100.6 x 10.5 mm | front face down |
| `back.stl` | 137.5 x 96.6 mm, pod 6.5 mm deep | inside face down (the pod's roof bridges ~28 mm) |
| `cradle.stl` | 84 x 62 x 43 mm | base down |

No supports needed. PLA, 0.2 mm layers, 3+ walls (so the screws bite), ~20%
infill.

## Assembly

* The screen drops into the frame from the back, against the front lip; its
  bottom edge rests on two shelves either side of a gap for the ribbon cable.
* Stick ~2.5 mm foam on the inside of the back cover (keeping it off the strip
  the ribbon runs up) so it gently presses the screen forward.
* The back cover sits flush in a recess and is held by 4 countersunk
  **M3 x 6 mm self-tapping** screws. Unscrew them to reach the board's SD card.
* The board sits in the pod, held by its ribbon cable (a dab of foam on the
  pod's roof stops it rattling). The USB power cable plugs in through the
  pod's top opening - a right-angle micro-USB plug keeps it flat against the
  back.
* The frame stands in the cradle, tilted back 15 degrees; nothing attaches,
  so it lifts straight out.

## Before printing

The screen dimensions come from the F50GLQ24E22 panel's listing (120.7 x 75.8
mm outline, 108 x 64.8 mm visible area) and the ribbon/board positions from
measurements of this build. Check them against your parts and adjust the
values at the top of `frame.scad`:

* `panel_w`, `panel_h`, `panel_t` - screen outline and thickness (with touch layer)
* `active_dx`, `active_dy` - if the visible area isn't centred on the glass
* `ribbon_left`, `ribbon_wide`, `tail_w`, `tail_left` - where the ribbon leaves
  the bottom edge (measured from the left edge as seen from the **back**)
* `ribbon_free` - ribbon length from the panel edge to the copper contacts,
  which sets where the board ends up behind the screen
* `foam_gap` - room behind the screen for the parts on the folded ribbon

Printing the frame alone first and test-fitting the screen is the cheapest
check.

If the clock will run upside down (Settings > Rotate), the pod ends up near
the bottom edge and the cradle's support arms need moving clear of it.

## Exporting

```sh
openscad -D 'part="frame"'  -o frame.stl  frame.scad
openscad -D 'part="back"'   -o back.stl   frame.scad
openscad -D 'part="cradle"' -o cradle.stl frame.scad
```

`part="assembly"` shows everything in place, for checking.
