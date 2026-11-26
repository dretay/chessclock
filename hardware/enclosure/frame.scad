// Slim picture-frame enclosure for the LicheePi Nano trip countdown frame
// (5" 800x480 resistive-touch panel + Lichee Pi Nano board).
//
// The rim is only as deep as the screen; the board lives in a small pod on
// the back. Three printed parts:
//   frame  - front bezel; print face down. The screen drops in from the back.
//   back   - back cover with the board's pod; print with its inside face down
//            (the pod's roof bridges). It sits flush in a recess in the
//            frame's back and is held by 4 M3 self-tapping screws - unscrew
//            them to reach the board and its SD card.
//   cradle - desk stand the frame rests in, tilted back. Nothing attaches,
//            so the frame lifts straight out.
//
// Export one part at a time, e.g.:
//   openscad -D 'part="frame"'  -o frame.stl  frame.scad
//   openscad -D 'part="back"'   -o back.stl   frame.scad
//   openscad -D 'part="cradle"' -o cradle.stl frame.scad
// part="assembly" shows everything in place (for checking, not printing).
//
// Coordinates: x across the screen, y up the screen (as seen from the front),
// z from the front face (z = 0) towards the back. The panel outline is
// centred on x = y = 0, and its ribbon cable leaves the bottom edge.

part = "assembly";   // [frame, back, cradle, assembly]

/* [Screen] - measure your panel and adjust */
panel_w = 120.7;     // outline width
panel_h = 75.8;      // outline height
panel_t = 4.8;       // LCD (~3.05) + resistive touch layer on top
active_w = 108.0;    // visible display area
active_h = 64.8;
active_dx = 0;       // offset of the visible area's centre from the outline's
active_dy = 0;       // centre (+x right, +y up, seen from the front)
window_margin = 1.0; // window is this much bigger than the visible area on each
                     // side, so the bezel never presses on the touch area
fit = 0.4;           // clearance around the panel
ribbon_room = 4;     // extra space below the panel for the ribbon cable's fold
// The ribbon leaves the bottom edge as a wide section carrying a few parts,
// then a narrower tail steps off to one side. The positions below are
// measured from the left edge as seen from the BACK of the panel (the side
// the ribbon is on); seen from the front, that is the right edge.
ribbon_left = 26;    // measured: wide section starts this far from that edge
ribbon_wide = 47;    // measured: width of the wide section
tail_w = 21;         // measured: width of the tail that plugs into the board
tail_left = 26;      // assumed: the tail's edge lines up with the wide section's
ribbon_w = ribbon_wide + 3;                                // gap kept clear at the bottom
// convert to front-view x (seen from the back, left is +x)
ribbon_x = panel_w / 2 - ribbon_left - ribbon_wide / 2;    // (panel rests on shelves either side)

/* [Frame] */
border = 10;         // frame width around the panel
front_t = 1.6;       // thickness of the front face
foam_gap = 2.5;      // behind the panel: room for the parts on the folded ribbon
                     // (assumed up to ~2 mm tall) and foam that presses the panel forward
back_t = 1.6;        // back cover thickness (sits flush in a recess)
rebate_wall = 2.0;   // frame wall left outside the back cover's recess
corner_r = 3;        // outer corner rounding
chamfer = 1.0;       // bevel on the window's front edge

/* [Screws: M3 self-tapping] */
pilot_d = 2.5;       // pilot hole in the frame
pilot_depth = 6.5;
clear_d = 3.4;       // clearance hole in the back cover
head_d = 6.2;        // countersunk head diameter
head_depth = 1.4;

/* [Lichee Pi Nano pod] - where the board sits, seen from the front */
nano_w = 25.4;
nano_h = 33.0;
ribbon_free = 44;    // measured: ribbon length from the panel's edge to where its
                     // copper contacts start
fold_allowance = 7;  // ribbon used up folding around the panel's bottom edge (estimate)
nano_x = panel_w / 2 - tail_left - tail_w / 2;    // board centre, left-right: under the tail
// The ribbon comes up the back and plugs into the bottom end of the board.
nano_y = -panel_h / 2 + ribbon_free - fold_allowance - 1 + nano_h / 2;
pod_depth = 9;       // room behind the panel inside the pod (board + parts)
pod_clear = 1.5;     // space around the board inside the pod
pod_slack = 6;       // extra room up and down, since the fold allowance is a guess
pod_slack_x = 4;     // extra room left-right, since the tail's position is assumed
pod_wall = 1.6;
usb_side = "top";    // [left, right, top, bottom] side of the pod facing the
                     // board's micro-USB port (seen from the front). The port is
                     // on the end opposite the ribbon connector, and the ribbon
                     // comes up from the panel's bottom edge, so it faces up.
usb_w = 12;          // opening for the plug
usb_h = 8;

/* [Desk cradle] */
tilt = 15;           // lean back from vertical
cradle_w = 84;
arm_w = 16;          // the back supports are two arms either side of the pod

$fn = 48;

// ---------------------------------------------------------------- derived

pocket_x0 = -panel_w / 2 - fit;
pocket_x1 = panel_w / 2 + fit;
pocket_y0 = -panel_h / 2 - fit - ribbon_room;
pocket_y1 = panel_h / 2 + fit;
outer_x0 = pocket_x0 - border;
outer_x1 = pocket_x1 + border;
outer_y0 = pocket_y0 - border;
outer_y1 = pocket_y1 + border;
panel_back = front_t + panel_t;               // z of the panel's back face
rim_depth = panel_back + foam_gap + back_t;   // overall thickness of the rim
cover_z = rim_depth - back_t;                 // z of the back cover's inner face
cover_x0 = outer_x0 + rebate_wall;            // the cover sits inside this
cover_x1 = outer_x1 - rebate_wall;
cover_y0 = outer_y0 + rebate_wall;
cover_y1 = outer_y1 - rebate_wall;
screws = [for (sx = [outer_x0 + border / 2 + 0.5, outer_x1 - border / 2 - 0.5])
          for (sy = [outer_y0 + border / 2 + 0.5, outer_y1 - border / 2 - 0.5]) [sx, sy]];
// pod, inside and out
pod_in = [nano_w + 2 * pod_clear + pod_slack_x, nano_h + 2 * pod_clear + pod_slack];
pod_out = pod_in + [2 * pod_wall, 2 * pod_wall];
pod_top = panel_back + pod_depth;              // z of the pod's inner roof
pod_height = pod_top + pod_wall - rim_depth;   // how far the pod stands off the back

module rounded_rect(x0, y0, x1, y1, r) {
    translate([x0 + r, y0 + r]) offset(r = r) square([x1 - x0 - 2 * r, y1 - y0 - 2 * r]);
}

module box(x0, y0, z0, x1, y1, z1) {
    translate([x0, y0, z0]) cube([x1 - x0, y1 - y0, z1 - z0]);
}

// ------------------------------------------------------------------ frame

module frame() {
    wx = active_w / 2 + window_margin;
    wy = active_h / 2 + window_margin;
    difference() {
        linear_extrude(rim_depth) rounded_rect(outer_x0, outer_y0, outer_x1, outer_y1, corner_r);
        // the panel drops in from the back
        box(pocket_x0, pocket_y0, front_t, pocket_x1, pocket_y1, rim_depth + 1);
        // recess the back cover sits flush in
        translate([0, 0, cover_z]) linear_extrude(back_t + 1)
            rounded_rect(cover_x0 - 0.2, cover_y0 - 0.2, cover_x1 + 0.2, cover_y1 + 0.2, max(0.5, corner_r - rebate_wall));
        // display window, bevelled on the front edge
        translate([active_dx, active_dy, 0]) hull() {
            box(-wx - chamfer, -wy - chamfer, -0.01, wx + chamfer, wy + chamfer, 0.01);
            box(-wx, -wy, chamfer, wx, wy, front_t + 1);
        }
        // screw pilot holes in the corners
        for (p = screws) translate([p[0], p[1], cover_z - pilot_depth]) cylinder(d = pilot_d, h = pilot_depth + 1);
    }
    // shelves the panel's bottom edge rests on, either side of the ribbon
    for (side = [[pocket_x0, ribbon_x - ribbon_w / 2], [ribbon_x + ribbon_w / 2, pocket_x1]])
        box(side[0] - 0.01, pocket_y0 - 0.01, front_t - 0.01, side[1], pocket_y0 + ribbon_room, panel_back);
}

// ------------------------------------------------------------- back cover

// Built in assembly position: the plate fills the frame's recess (inner face
// at z = cover_z) and the pod stands out behind it, around the board.
module back_cover() {
    difference() {
        union() {
            translate([0, 0, cover_z]) linear_extrude(back_t)
                rounded_rect(cover_x0, cover_y0, cover_x1, cover_y1, max(0.5, corner_r - rebate_wall));
            translate([nano_x - pod_out[0] / 2, nano_y - pod_out[1] / 2, cover_z])
                linear_extrude(pod_top + pod_wall - cover_z) offset(r = 2) offset(delta = -2) square(pod_out);
        }
        // inside of the pod, open towards the panel
        translate([nano_x - pod_in[0] / 2, nano_y - pod_in[1] / 2, cover_z - 1])
            linear_extrude(pod_top - cover_z + 1) offset(r = 1) offset(delta = -1) square(pod_in);
        // countersunk screw holes (head on the outside)
        for (p = screws) translate([p[0], p[1], cover_z - 1]) {
            cylinder(d = clear_d, h = back_t + 2);
            translate([0, 0, 1 + back_t - head_depth]) cylinder(d1 = clear_d, d2 = head_d, h = head_depth + 0.01);
        }
        // opening for the USB plug, at the board's level in the pod wall
        usb();
    }
}

module usb() {
    z0 = pod_top - usb_h;                     // the board rests against the pod roof side
    hx = pod_out[0] / 2;
    hy = pod_out[1] / 2;
    if (usb_side == "right")  box(nano_x + hx - 4, nano_y - usb_w / 2, z0, nano_x + hx + 1, nano_y + usb_w / 2, pod_top);
    if (usb_side == "left")   box(nano_x - hx - 1, nano_y - usb_w / 2, z0, nano_x - hx + 4, nano_y + usb_w / 2, pod_top);
    if (usb_side == "top")    box(nano_x - usb_w / 2, nano_y + hy - 4, z0, nano_x + usb_w / 2, nano_y + hy + 1, pod_top);
    if (usb_side == "bottom") box(nano_x - usb_w / 2, nano_y - hy - 1, z0, nano_x + usb_w / 2, nano_y - hy + 4, pod_top);
}

// ----------------------------------------------------------------- cradle

gw = rim_depth + 0.6;                         // slot fits the rim
lip = 6;                                      // thickness in front of the frame
up = [sin(tilt), cos(tilt)];                  // up the face of the leaning frame
across = [cos(tilt), -sin(tilt)];             // front-to-back across its bottom edge
F = [lip, 2 + gw * sin(tilt)];                // front-bottom corner of the frame
B = F + gw * across;                          // back-bottom corner, resting lowest

// Side profiles (u = front to back, v = up), extruded across the width. The
// solid pieces are built first and the frame's slot is cut through all of
// them at once (cutting each piece separately leaves a mesh with holes).
module cradle_slot() { polygon([F, B, B + 200 * up, F + 200 * up]); }

module cradle_base() {                        // base, front lip and a low back ledge
    square([B[0] + 45, 5]);
    square([F[0] + 2, 13]);
    polygon([B + [-1, -B[1]], B + [3, -B[1]], B + 6 * up + [3, 0], B + 6 * up + [-1, 0]]);
}

module cradle_support() {                     // the tall support behind the frame
    polygon([B + [-1, -B[1]], B + [24, -B[1]], B + 42 * up + [6, 0], B + 42 * up + [-1, 0]]);
}

module cradle() {
    rotate([90, 0, 90]) difference() {
        union() {
            linear_extrude(cradle_w, center = true) cradle_base();
            for (s = [-1, 1]) translate([0, 0, s * (cradle_w - arm_w) / 2])
                linear_extrude(arm_w, center = true) cradle_support();
        }
        linear_extrude(cradle_w + 2, center = true) cradle_slot();
    }
}

// --------------------------------------------------------------- assembly

module panel_dummy() {
    color("#333") translate([-panel_w / 2, -panel_h / 2, front_t]) cube([panel_w, panel_h, panel_t]);
    color("#4a8") translate([active_dx - active_w / 2, active_dy - active_h / 2, front_t - 0.01])
        cube([active_w, active_h, 0.02]);
    color("#2a6") translate([nano_x - nano_w / 2, nano_y - nano_h / 2, pod_top - 6])
        cube([nano_w, nano_h, 1.6]);
}

if (part == "frame") {
    frame();                                                       // front face on the bed
} else if (part == "back") {
    translate([0, 0, -cover_z]) back_cover();                      // inner face on the bed
} else if (part == "cradle") {
    cradle();
} else {
    color("#c9a26b") frame();
    panel_dummy();
    color("#8b5a2b", 0.85) translate([0, 0, 20]) back_cover();     // pulled back to show inside
}

echo(str("rim thickness ", rim_depth, " mm; pod stands ", pod_height, " mm off the back; ",
          "board centre ", nano_y + panel_h / 2, " mm above the panel's bottom edge; seen from the front: ",
          "board centre ", nano_x + panel_w / 2, " mm from the left edge, ribbon gap ",
          ribbon_x - ribbon_w / 2 + panel_w / 2, "-", ribbon_x + ribbon_w / 2 + panel_w / 2, " mm from the left edge"));
