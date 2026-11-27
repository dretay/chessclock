# F1C200s protoboard - KiCad project

KiCad 10 project for the board specified in [`../DESIGN.md`](../DESIGN.md):
118 x 72.5 mm, 4 layers: F.Cu signals + GND pour / In1 solid GND (no tracks) /
In2 signals + +3V3 pour / B.Cu signals + GND pour.

| File | |
|---|---|
| `protoboard.kicad_pro` | project, design rules (0.127 mm clearance, 0.1 mm min track for the router's neck-downs at the QFN, 0.2 mm drill) and netclasses (Default, Power, HighCurrent, USB) |
| `protoboard.kicad_sch` | root sheet, with sub-sheets `power`, `soc`, `display`, `storage`, `wifi`, `audio`, `io` |
| `protoboard.kicad_pcb` | placed for the desk stand (LCD connector front-right, USB-C/microSD/5V IN on the back edge) and autorouted, 5 connections left by hand (see below), pours filled, ESP antenna keep-out |
| `lib/` | custom symbols (F1C200s, SY8089, PT4103, NS2009, ESP32-C3 SuperMini) and footprints (SuperMini for headers or flat soldering, F1C QFN-88 with 0.22 mm pads, prototyping grid, rail strips) |
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

* **Board 118 x 72.5 mm and 0.25 mm extra spacing around every part**
  (`BOARD_W`, `BOARD_H`, `PLACE_GAP` in `gen_pcb.py`). On the stand layout
  0.25 gave 5 unconnected where 0.15/0.2 gave 14-57.
* **SoC rotated 180 degrees** (`SOC_ROT`): the LCD connector is right of the
  chip, and 180 lets the power pins escape far better than 90 (13 vs 28+).
* **Buck order** (`BUCK_X`): the three SY8089 bucks along the front edge.
* **microSD on the back edge.** `SD_SIDE=1` puts it on the right edge instead
  (and gives the protogrid back its full 38 columns, rails 32 holes), but the
  best of six routes was 19 unconnected against 5, so it isn't the default.
* **+1V1 area on In2** (added by `route.py post`, priority over the +3V3
  pour) from the core buck to under the SoC, plus `gen/viafix.py`, which
  drops a via into it from any +1V1 pad or track end the router left.
* **0.5 mm no-track strip** along the board edges (the router hugged them).
* **Ribbon keep-out:** connectors, switches and through-hole parts stay out
  of the area the LCD ribbon lies over between the front edge and the FPC.
* **QFN fan-out area:** the strip between the SoC and the FPC is kept free
  of parts for the LCD lines and their vias.
* **Placement order:** crystal and its caps first, then the SoC decoupling
  caps, each one next to a power pin of its own chip.
* **In1 stays a solid plane.** Letting the router use In1 (`gen/freerouting_in1.rules`)
  got to 7 unconnected on its own but broke the GND plane into 44 islands,
  so it isn't used.

### Finishing by hand

* **+2V5, SoC pin 36:** a 0.8 mm gap to its own track end; the straight line
  passes +1V1 pin 35, so come in from outside the pin row.
* **RESET (2):** SoC pin 70 to its pull-up R16, and R16 to the RESET button's
  track on B.Cu (stub at x 47.5, y 31).
* **GND (2):** two pour islands; KiCad's ratsnest shows them - a via each.
* 199 `track_width` are the router's 0.112 mm neck-downs into the QFN pads
  (allowed by the 0.1 mm board minimum, flagged against the netclass width).
* Silkscreen overlaps.

## State

* ERC: 0 violations. DRC: 0 clearance, short or courtyard errors, schematic
  parity clean; 5 unconnected, listed above.
* Test points are on the bottom side.
* R/C/L designators are on F.Fab (the assembly drawing). The board is too
  dense for them on silk.
* Open items are listed at the end of DESIGN.md.
