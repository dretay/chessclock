# F1C200s protoboard - KiCad project

KiCad 10 project for the board specified in [`../DESIGN.md`](../DESIGN.md):
118 x 72.5 mm, 4 layers: F.Cu signals + GND pour / In1 solid GND (no tracks) /
In2 signals + +3V3 pour / B.Cu signals + GND pour.

| File | |
|---|---|
| `protoboard.kicad_pro` | project, design rules (0.127 mm clearance, 0.1 mm min track for the router's neck-downs at the QFN, 0.2 mm drill) and netclasses (Default, Power, HighCurrent, USB) |
| `protoboard.kicad_sch` | root sheet, with sub-sheets `power`, `soc`, `display`, `storage`, `wifi`, `audio`, `io` |
| `protoboard.kicad_pcb` | placed and fully autorouted (0 unconnected), pours filled, ESP antenna keep-out |
| `lib/` | custom symbols (F1C200s, SY8089, PT4103, NS2009, ESP32-C3 SuperMini) and footprints (SuperMini, F1C QFN-88 with 0.22 mm pads, prototyping grid, rail strips) |
| `gen/` | the generator |

## Generated, not hand-drawn

`gen/design.py` holds the whole netlist: every part, value, footprint and
pin-to-net assignment, block by block following DESIGN.md. The rest is
derived from it:

```sh
./gen/build.sh            # libs -> schematic -> netlist -> PCB, then ERC + DRC (reports in gen/.cache/)
./gen/build.sh --sch-only # stop after the schematic
```

* `gen_sch.py` places the symbols on each sheet and connects every pin with a
  power symbol, a label or a no-connect flag. Nothing is wired, so
  connectivity comes only from net names.
* `gen_pcb.py` (run with KiCad's own Python) reads the netlist KiCad exports
  from the schematic, so the board stays in parity with it. It fixes the parts
  whose position the spec decides (FPC, USB-C, microSD, ESP, buttons,
  breakouts, rails, holes) and packs the rest as close as possible to the pads
  they connect to.

**Rerunning `build.sh` overwrites the .kicad_sch and .kicad_pcb files.** Once
you start routing or moving parts by hand, stop regenerating the PCB: make
schematic changes in KiCad and use *Update PCB from Schematic*. Or keep
editing `design.py`, but only with `--sch-only`.

## Routing

The board was autorouted with [Freerouting](https://github.com/freerouting/freerouting)
2.5 (needs Java 25+):

```sh
FREEROUTING_JAR=/path/to/freerouting.jar JAVA=/path/to/java ./gen/route.sh 40        # fresh route
FREEROUTING_JAR=... KEEP_TRACKS=1 ./gen/route.sh 40                                   # continue from the current tracks
WORK=gen/.cache/try1 ./gen/route.sh                                                   # route a copy instead
```

`route.sh` exports a Specctra DSN (`route.py export`, with pours and
stitching vias stripped), runs Freerouting with `gen/freerouting.rules`
(In1 inactive, so the GND plane gets vias but no tracks), imports the session,
then in a fresh process (`route.py post`) fixes undersized via rings, pours
+3V3 on In2 and GND on F.Cu/B.Cu, adds GND stitching vias wherever one fits
inside an outer pour, refills, and finally removes any via DRC flags as
dangling or (for GND vias) too close to something (two rounds: removing a
via can leave a neighbour dangling).

`build.sh` refuses to regenerate a routed board (`FORCE=1` overrides, which
throws the routing away). `gen_pcb.py` reproduces the routed board's
placement exactly, so a reroute is `FORCE=1 ./gen/build.sh` then
`./gen/route.sh 30`.

### What made it routable

Freerouting gets almost all of its result in the first run: continuation
passes (`KEEP_TRACKS=1`) never improved a board, and two runs of the same
placement differed by 22 vs 56 unconnected, so it pays to try several
placements in parallel (one core each) rather than run one longer. Fixes:

* **Board 118 x 72.5 mm and 0.2 mm extra spacing around every part**
  (`BOARD_W`, `BOARD_H`, `PLACE_GAP` in `gen_pcb.py`). This was the step
  from ~22 unconnected to 0. The panel is 120.7 x 75.8 mm, so this is
  about as large as the board can go.
* **Ribbon keep-out:** connectors, switches and through-hole parts stay out
  of the folded LCD ribbon's area and the space in front of the FPC.
* **QFN fan-out area:** the strip between the SoC and the FPC is kept free
  of parts for the LCD lines and their vias.
* **Placement order:** crystal and its caps first, then the SoC decoupling
  caps, each one next to a power pin of its own chip.
* **In1 stays a solid plane.** Letting the router use In1 (`gen/freerouting_in1.rules`)
  got to 7 unconnected on its own but broke the GND plane into 44 islands,
  so it isn't used.

### Finishing by hand

* One 1.5 um clearance short (SVREF track at JP1 pad 3): nudge the track.
* 174 `track_width` are the router's 0.112 mm neck-downs into the QFN pads
  (allowed by the 0.1 mm board minimum, flagged against the netclass width).
* Silkscreen overlaps.

## State

* ERC: 0 violations. DRC: 0 unconnected, 0 courtyard errors, schematic
  parity clean; the one clearance item and the warnings are listed above.
* Test points are on the bottom side.
* R/C/L designators are on F.Fab (the assembly drawing). The board is too
  dense for them on silk.
* Open items are listed at the end of DESIGN.md.
