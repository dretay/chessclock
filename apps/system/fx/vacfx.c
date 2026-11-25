/*
 * vacfx: the countdown runtime's per-frame drawing, in C (the board's ARM9 is far too slow to do
 * this in Python; see tools/themegen/bench_board*.py). Loaded by vacation.py with ctypes.
 *
 * It owns the theme's images and draws straight into the framebuffer:
 *   - the day, dusk and night plates, blended for the time of day (re-blended a few rows per frame
 *     when the light changes, so there's never a long frame)
 *   - window lights that switch on and off one window at a time, easing like real lamps
 *   - the sea's ripple (distant rows, where it moves less than a pixel, redrawn less often)
 *   - foam along the hull, the stern wake, funnel smoke, fireworks (night only, behind the ship)
 *   - the flip-clock countdown: split-flap cards that fold over when the number changes
 *
 * Only what changed is redrawn: each frame collects, per screen row, the span that needs
 * refreshing (water rows due this frame, re-blended rows, switching windows, where particles and
 * cards were or are), rebuilds those pixels from the blended base (rippled where it's water), draws
 * particles and cards over them, and copies just those spans to the screen.
 *
 * Fixed-point throughout (the ARM926 has no FPU): positions in 1/256 px, levels 0..256.
 * Theme files: see tools/themegen/scene_pack.py.
 */
#include <errno.h>
#include <fcntl.h>
#ifdef __linux__
#include <linux/fb.h>
#endif
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#ifdef VACFX_DLOPEN_ZLIB
/* built without zlib's headers (e.g. against a toolchain that doesn't have them): use the board's
   libz.so.1 at run time instead */
#include <dlfcn.h>
typedef void *gzFile;
static gzFile (*gzopen)(const char *, const char *); static int (*gzread)(gzFile, void *, unsigned); static int (*gzclose)(gzFile);
static int zlib_ready(void) {
    if (gzopen) return 1;
    void *z = dlopen("libz.so.1", RTLD_NOW); if (!z) { fprintf(stderr, "vacfx: %s\n", dlerror()); return 0; }
    gzopen = (gzFile (*)(const char *, const char *))dlsym(z, "gzopen"); gzread = (int (*)(gzFile, void *, unsigned))dlsym(z, "gzread");
    gzclose = (int (*)(gzFile))dlsym(z, "gzclose");
    return gzopen && gzread && gzclose;
}
#else
#include <zlib.h>
static int zlib_ready(void) { return 1; }
#endif

#define W 800
#define H 480
#define LUT 1024
#define MAXP 1400                      /* particles */

/* ------------------------------------------------------------------ state */
static uint8_t *plate[3];             /* day, dusk, night: RGB888; only the ones the time of day is using
                                         (one, or two while it changes): the others are loaded when needed */
static char plate_dir[512];
static const char *plate_names[3] = {"day.rgb.gz", "dusk.rgb.gz", "night.rgb.gz"};
static uint32_t *base;                /* blended plates + window light, XRGB */
static uint32_t *out;                 /* the frame being built, XRGB */
static uint32_t *fb; static size_t fb_len; static int fb_stride = W; static int fb_fd = -1;
static uint8_t *wc;                   /* water: 0 = not water, else how much it ripples (calm under the hull) */
static uint8_t *wcustom;              /* a scene's own water (water.raw.gz: how much each pixel ripples), else NULL:
                                         the sea below the horizon, off the ship (the cruise's) */
static int16_t wx0[H], wx1[H];        /* each row's water: first and last pixel (-1: none), what's redrawn */
static int water_top = H, water_amp_q8 = 256, water_speed_q8 = 256;
static uint8_t *ship;                 /* 1 = ship */
static int16_t wl[W];                 /* waterline (lowest ship pixel) per column, -1 = none */
static int horizon = 231;

static int wgt[3] = {256, 0, 0}, lights_lvl, night_lvl, dusk_lvl;
static int reblend_row = H;           /* next row to re-blend; H = done */

/* window light: pixels sorted by position, each with its added light and its window */
static int nl, ncell;
static uint32_t *lidx; static uint16_t *lcell; static uint8_t *lrgb;
static int row_start[H + 1];          /* light pixels of row y: row_start[y] .. row_start[y+1]-1 */
static uint32_t *cell_first, *cell_list;   /* light pixels of window c: cell_list[cell_first[c] .. cell_first[c+1]-1] */
static uint8_t *cell_on; static int16_t *cell_lvl;
static int toggles_per_min = 90;
static int windows_hold;               /* every window on and staying on (while windows are being painted) */

/* refresh spans for this frame and the next (particles' old footprints), per row */
static int16_t rlo[H], rhi[H], nlo[H], nhi[H];

/* scene */
static int stack_x[8], stack_y[8], smoke_q8 = 205, fw_q8 = 218;
static int smoke_n = 2, smoke_wind_q8 = -256, smoke_rate = 6, smoke_dense_q8 = 256;
static int smoke_own;                  /* a scene's own smoke (vfx_smoke: a chimney, a campfire): it rises, a plume as tall as it's big */
/* a scene's own foam (vfx_foam): white water churning at points, each with its radius: how much, which way */
static int foam_n, foam_xyr[16][3], foam_amount_q8 = 256, foam_flow, foamp_acc, foams_acc;   /* smoke: how many sources (the ship's two funnels, or a scene's
                                                                   own: vfx_smoke), the wind (-256 left .. 256 right), puffs a second */
static int bow_x, bow_y, stern_x, stern_y, hull_dx = -256, hull_dy;   /* unit vector bow -> stern, Q8 */

/* particles: kind, position and velocity in 1/256 px and 1/256 px per s */
enum { P_FOAM, P_WAKE, P_SMOKE, P_ROCKET, P_SPARK, P_GULL, P_DOLPHIN, P_SPLASH };
typedef struct { uint8_t kind; int32_t x, y, vx, vy, px, py; int32_t age, life; uint32_t col; int16_t size; int16_t ty; } part_t;
static part_t parts[MAXP]; static int np;
static int foam_acc, wake_acc, smoke_acc, toggle_acc, bow_acc, spray_acc;
static int rockets_pending, next_rocket_ms, rocket_gap_min = 300, rocket_gap_max = 550;

/* daytime touches (from the mockup): cloud shadows drifting over the sea, gulls, dolphins leaping
   ahead of the bow, a raft on the AquaDuck tube, the pennant on the mast */
typedef struct { int32_t x, y, rx, ry, v; } shadow_t;     /* 1/256 px; v in 1/256 px per s */
static shadow_t shadows[3];
static int mast_x = -1, mast_y, amb_q8 = 256, ntube; static int tube[32][2];
static int gulls_now;                  /* asked for (the previewer's Birds): whatever the scene's effects, day or night */
static int next_gulls_ms = 5000, next_pod_ms = 10000, next_raft_ms = 8000, raft_start = -1, raft_dur;
/* which of the scene's own effects run (vfx_effects): the ship has them all; a castle, none of them.
   Fireworks, window lights and the cards are every scene's. */
enum { FX_WATER = 1, FX_WAKE = 2, FX_SMOKE = 4, FX_GULLS = 8, FX_DOLPHINS = 16, FX_RAFT = 32, FX_TWINKLE = 64, FX_FOAM = 128, FX_ALL = 255 };
static int fx_on = FX_ALL;
static int hold_lvl, hold_drawn;           /* the press-and-hold bar under the cards */

/* flip clock */
static int card_w, card_h, shadow_ox, shadow_oy, shadow_w, shadow_h;
static uint8_t *card_top[10], *card_bot[10], *shadow_img, *label_img[2]; static int label_w[2], label_h[2];
static int cards_cx = 400, cards_top = 12, cards_gap = 8, label_gap = 7;
static int days = -1, ndig, dig[4], old_dig[4], old_ndig, flip_start[4];
static int split, old_split;                 /* a colon before card `split` (the last day's HH:MM), 0 = none */
static int banner_on;                        /* "Bon voyage!" instead of the cards */
static uint8_t *banner_img, *colon_img; static int banner_w, banner_h, colon_w, colon_h;
static int cards_dirty = 1, flip_ms = 650, full_redraw = 1;
static int last_t = -1, frame_no;
static double st_acc[6]; static int st_frames;     /* time per stage: base, sea+refresh, particles, cards, copy, total */

/* the panel is RGB666: the low two bits of each 8-bit channel are dropped on the way out, which bands
   smooth gradients (sky, night). Before that happens, add a 2x2 ordered-dither offset (0..3), tied to
   the screen position so still areas stay still; values are capped at 252 so nothing wraps. */
static uint8_t dlut[4][256]; static int dither_on = 1;
static const uint8_t dpat[2][2] = {{0, 2}, {3, 1}};
static int fade_lvl = 256; static uint8_t flut[256];   /* brightness of what goes to the screen (vfx_fade) */
static void copy_out(int y, int a, int b) {
    uint32_t *d = fb + y * fb_stride; const uint32_t *s = out + y * W;
    if (fade_lvl < 256) {
        const uint8_t *t0 = dither_on ? dlut[dpat[y & 1][0]] : NULL, *t1 = dither_on ? dlut[dpat[y & 1][1]] : NULL;
        for (int x = a; x <= b; x++) {
            const uint32_t p = s[x]; int r = flut[(p >> 16) & 255], g = flut[(p >> 8) & 255], bl = flut[p & 255];
            if (t0) { const uint8_t *t = (x & 1) ? t1 : t0; r = t[r]; g = t[g]; bl = t[bl]; }
            d[x] = (uint32_t)r << 16 | (uint32_t)g << 8 | (uint32_t)bl;
        }
        return;
    }
    if (!dither_on) { memcpy(d + a, s + a, (size_t)(b - a + 1) * 4); return; }
    const uint8_t *t0 = dlut[dpat[y & 1][0]], *t1 = dlut[dpat[y & 1][1]];
    for (int x = a; x <= b; x++) {
        const uint8_t *t = (x & 1) ? t1 : t0; const uint32_t p = s[x];
        d[x] = (uint32_t)t[(p >> 16) & 255] << 16 | (uint32_t)t[(p >> 8) & 255] << 8 | t[p & 255];
    }
}

static int16_t sin_lut[LUT];
static uint16_t xph1[W], xph2[W];
static uint8_t prof_soft[257], prof_puff[257], prof_lin[257];   /* falloff by distance squared, 0..256 */
static uint32_t rng = 0x9e3779b9;
static inline uint32_t rnd(void) { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }
static inline int rr(int a, int b) { return a + (int)(rnd() % (uint32_t)(b - a + 1)); }   /* a..b inclusive */
static inline int clampi(int v, int a, int b) { return v < a ? a : v > b ? b : v; }

/* ------------------------------------------------------------------ loading */
static void *gzload(const char *dir, const char *name, size_t *len) {
    if (!zlib_ready()) return NULL;
    char path[512]; snprintf(path, sizeof path, "%s/%s", dir, name);
    gzFile g = gzopen(path, "rb"); if (!g) { fprintf(stderr, "vacfx: can't open %s\n", path); return NULL; }
    size_t cap = 1 << 16, n = 0; uint8_t *buf = malloc(cap);
    for (;;) {
        if (n == cap) { cap *= 2; buf = realloc(buf, cap); }
        int k = gzread(g, buf + n, (unsigned)(cap - n)); if (k <= 0) break; n += (size_t)k;
    }
    gzclose(g); if (len) *len = n;
    uint8_t *fit = realloc(buf, n ? n : 1); return fit ? fit : buf;      /* (give back the slack) */
}
/* a gzipped file into a buffer of its own size exactly; 0 when it filled it */
static int gzload_into(const char *dir, const char *name, uint8_t *buf, size_t want) {
    if (!zlib_ready()) return -1;
    char path[512]; snprintf(path, sizeof path, "%s/%s", dir, name);
    gzFile g = gzopen(path, "rb"); if (!g) { fprintf(stderr, "vacfx: can't open %s\n", path); return -1; }
    size_t n = 0; int k;
    while (n < want && (k = gzread(g, buf + n, (unsigned)(want - n))) > 0) n += (size_t)k;
    gzclose(g); return n == want ? 0 : -1;
}

static void spans_add(int16_t *lo, int16_t *hi, int y, int x0, int x1) {
    if (y < 0 || y >= H) return;
    x0 = clampi(x0, 0, W - 1); x1 = clampi(x1, 0, W - 1); if (x0 > x1) return;
    if (lo[y] > hi[y]) { lo[y] = (int16_t)x0; hi[y] = (int16_t)x1; return; }
    if (x0 < lo[y]) lo[y] = (int16_t)x0;
    if (x1 > hi[y]) hi[y] = (int16_t)x1;
}
static void rect_add(int16_t *lo, int16_t *hi, int x0, int y0, int x1, int y1) {
    for (int y = clampi(y0, 0, H - 1); y <= clampi(y1, 0, H - 1); y++) spans_add(lo, hi, y, x0, x1);
}

/* ------------------------------------------------------------------ base: plates + window light */
static inline uint32_t blend_px(int i) {
    const int w0 = wgt[0], w1 = wgt[1], w2 = wgt[2];
    uint32_t r, g, bl;
    if (w0 == 256) { const uint8_t *a = plate[0] + i * 3; r = a[0]; g = a[1]; bl = a[2]; }
    else if (w2 == 256) { const uint8_t *c = plate[2] + i * 3; r = c[0]; g = c[1]; bl = c[2]; }
    else {                                    /* (only the plates in use: the others may not be loaded) */
        uint32_t sr = 0, sg = 0, sb = 0;
        if (w0) { const uint8_t *a = plate[0] + i * 3; sr += a[0] * w0; sg += a[1] * w0; sb += a[2] * w0; }
        if (w1) { const uint8_t *b = plate[1] + i * 3; sr += b[0] * w1; sg += b[1] * w1; sb += b[2] * w1; }
        if (w2) { const uint8_t *c = plate[2] + i * 3; sr += c[0] * w2; sg += c[1] * w2; sb += c[2] * w2; }
        r = sr >> 8; g = sg >> 8; bl = sb >> 8;
    }
    return r << 16 | g << 8 | bl;
}
/* the plates the weights use loaded, the others freed (most of the day that's one plate: 1.1 MB instead of
   3.4); a load takes a moment, at the start of each change of light. -1 if one couldn't be loaded */
static int plates_for_weights(void) {
    for (int k = 0; k < 3; k++) {
        if (wgt[k] && !plate[k]) {
            size_t n; plate[k] = gzload(plate_dir, plate_names[k], &n);
            if (!plate[k] || n != W * H * 3) { fprintf(stderr, "vacfx: bad %s\n", plate_names[k]); free(plate[k]); plate[k] = NULL; return -1; }
        } else if (!wgt[k] && plate[k]) { free(plate[k]); plate[k] = NULL; }
    }
    return 0;
}
static inline uint32_t lit_px(uint32_t p, int k) {    /* add window light k at its window's level */
    const int lv = (cell_lvl[lcell[k]] * lights_lvl) >> 8;
    if (lv <= 0) return p;
    int r = ((p >> 16) & 255) + ((lrgb[k * 3] * lv) >> 8), g = ((p >> 8) & 255) + ((lrgb[k * 3 + 1] * lv) >> 8),
        b = (p & 255) + ((lrgb[k * 3 + 2] * lv) >> 8);
    return (uint32_t)(r > 255 ? 255 : r) << 16 | (uint32_t)(g > 255 ? 255 : g) << 8 | (uint32_t)(b > 255 ? 255 : b);
}
static void reblend_rows(int count) {
    while (count-- > 0 && reblend_row < H) {
        const int y = reblend_row++;
        uint32_t *row = base + y * W;
        for (int x = 0; x < W; x++) row[x] = blend_px(y * W + x);
        for (int k = row_start[y]; k < row_start[y + 1]; k++) base[lidx[k]] = lit_px(base[lidx[k]], k);
        spans_add(rlo, rhi, y, 0, W - 1);
    }
}
static void relight_cell(int c) {
    for (uint32_t m = cell_first[c]; m < cell_first[c + 1]; m++) {
        const int k = (int)cell_list[m], i = (int)lidx[k];
        base[i] = lit_px(blend_px(i), k);
        spans_add(rlo, rhi, i / W, i % W, i % W);
    }
}

/* ------------------------------------------------------------------ the ripple */
static int k1, k2, w1, w2;
static inline uint32_t ripple_px(int x, int y, int amp_q8, int amy, int ph1, int ph2) {
    const int i = y * W + x, c = wc[i];
    const int s1 = sin_lut[(ph1 + xph1[x]) & (LUT - 1)], s2 = sin_lut[(ph2 + xph2[x]) & (LUT - 1)];
    int fx = (x << 8) + ((((amp_q8 * c) >> 8) * s1) >> 14);
    const int dy = ((((amy * c) >> 8) * s2) + (1 << 21)) >> 22;
    if (fx < 0) fx = 0; else if (fx > (W - 2) << 8) fx = (W - 2) << 8;
    int yy = y + dy; if (yy < water_top) yy = water_top; else if (yy > H - 1) yy = H - 1;
    const int j = yy * W + (fx >> 8);
    if (!(wc[j] && wc[j + 1])) return base[i];
    const uint32_t a = base[j], b = base[j + 1], f = fx & 255, g = 256 - f;
    return ((((a & 0xff00ff) * g + (b & 0xff00ff) * f) >> 8) & 0xff00ff) | ((((a & 0x00ff00) * g + (b & 0x00ff00) * f) >> 8) & 0x00ff00);
}
static int shadow_row(int y, uint8_t *sh, int *ax, int *bx);
static void refresh_row(int y, int x0, int x1, int t_ms, uint32_t *dst) {
    const uint32_t *src = base + y * W;
    if (wx0[y] < 0 || !(fx_on & FX_WATER)) { memcpy(dst + x0, src + x0, (size_t)(x1 - x0 + 1) * 4); return; }
    /* the sea grows toward the viewer; a scene's own water (a lake, a fountain) ripples evenly, as strong as it says */
    const int depth_q8 = wcustom ? 128 : ((y - horizon) << 8) / (H - horizon);
    const int amp_q8 = wcustom ? water_amp_q8 : 90 + ((614 * depth_q8) >> 8), amy = (amp_q8 * 115) >> 8;
    const int64_t tw = (int64_t)t_ms * water_speed_q8 >> 8;
    const int ph1 = (int)(((int64_t)y * k1 + tw * w1) >> 8), ph2 = (int)(((int64_t)y * k2 - tw * w2) >> 8);
    const uint8_t *wrow = wc + y * W;
    for (int x = x0; x <= x1; x++) dst[x] = wrow[x] ? ripple_px(x, y, amp_q8, amy, ph1, ph2) : src[x];
    /* cloud shadows on the water: darker, and a little bluer */
    static uint8_t sh[W]; int a, b;
    if (shadow_row(y, sh, &a, &b)) {
        a = a < x0 ? x0 : a; b = b > x1 ? x1 : b;
        for (int x = a; x <= b; x++) {
            const int s_ = sh[x] * 72 >> 8; if (!s_ || !wrow[x]) continue;      /* 0.28 at the centre */
            const uint32_t p = dst[x];
            const int R = (p >> 16) & 255, G = (p >> 8) & 255, B = p & 255;
            dst[x] = (uint32_t)(R - (R * s_ >> 8)) << 16 | (uint32_t)(G - (G * s_ * 218 >> 16)) << 8 | (uint32_t)(B - (B * s_ * 154 >> 16));
        }
    }
}

/* ------------------------------------------------------------------ drawing */
/* premultiplied RGBA sprite at (x, y), scaled by level (0..256); only into this frame's refresh spans */
static void sprite(const uint8_t *img, int w, int h, int x, int y, int level, int clip_spans) {
    for (int r = 0; r < h; r++) {
        const int yy = y + r; if (yy < 0 || yy >= H) continue;
        int a0 = x, a1 = x + w - 1;
        if (clip_spans) { if (rlo[yy] > rhi[yy]) continue; if (a0 < rlo[yy]) a0 = rlo[yy]; if (a1 > rhi[yy]) a1 = rhi[yy]; }
        a0 = clampi(a0, 0, W); a1 = clampi(a1, -1, W - 1);
        const uint8_t *s = img + ((size_t)r * w + (a0 - x)) * 4; uint32_t *d = out + yy * W;
        for (int xx = a0; xx <= a1; xx++, s += 4) {
            const int a = (s[3] * level) >> 8; if (!a) continue;
            const uint32_t p = d[xx]; const int ia = 255 - a;
            const int R = ((s[0] * level) >> 8) + ((((p >> 16) & 255) * ia) >> 8), G = ((s[1] * level) >> 8) + ((((p >> 8) & 255) * ia) >> 8),
                      B = ((s[2] * level) >> 8) + (((p & 255) * ia) >> 8);
            d[xx] = (uint32_t)(R > 255 ? 255 : R) << 16 | (uint32_t)(G > 255 ? 255 : G) << 8 | (uint32_t)(B > 255 ? 255 : B);
        }
    }
}
/* one half of a card, squashed vertically to height hh about its hinge (from_bottom: anchored at its
   bottom edge, the top flap folding down), darkened by shade (0..256) */
static void flap(const uint8_t *img, int x, int hinge_y, int hh, int from_bottom, int level) {
    const int half = card_h / 2; if (hh <= 0) return;
    for (int r = 0; r < hh; r++) {
        const int yy = from_bottom ? hinge_y - hh + r : hinge_y + r; if (yy < 0 || yy >= H) continue;
        const int sr = clampi(r * half / hh, 0, half - 1);
        const uint8_t *s = img + (size_t)sr * card_w * 4; uint32_t *d = out + yy * W;
        for (int c = 0; c < card_w; c++, s += 4) {
            const int xx = x + c; if (xx < 0 || xx >= W) continue;
            const int a = s[3]; if (!a) continue;
            const uint32_t p = d[xx]; const int ia = 255 - a;
            const int R = ((s[0] * level) >> 8) + ((((p >> 16) & 255) * ia) >> 8), G = ((s[1] * level) >> 8) + ((((p >> 8) & 255) * ia) >> 8),
                      B = ((s[2] * level) >> 8) + (((p & 255) * ia) >> 8);
            d[xx] = (uint32_t)(R > 255 ? 255 : R) << 16 | (uint32_t)(G > 255 ? 255 : G) << 8 | (uint32_t)(B > 255 ? 255 : B);
        }
    }
}
/* a soft blob at (x, y) in 1/256 px, radii in 1/256 px. mode 0 = blend, 1 = add. clip: 0 none,
   1 water only, 2 sky only (not ship, above the horizon). Records the footprint for next frame. */
static void blob(int32_t x, int32_t y, int32_t rx, int32_t ry, uint32_t col, int alpha, const uint8_t *prof, int mode, int clip) {
    if (alpha <= 0 || rx < 64 || ry < 64) return;
    const int cx = x >> 8, cy = y >> 8, Rx = (rx + 255) >> 8, Ry = (ry + 255) >> 8;
    const int x0 = cx - Rx, x1 = cx + Rx, y0 = cy - Ry, y1 = cy + Ry;
    if (x1 < 0 || x0 >= W || y1 < 0 || y0 >= H) return;
    /* q = 256 (dx^2/rx^2 + dy^2/ry^2), all 32-bit: radii in 1/16 px */
    const uint32_t r16x = (uint32_t)rx >> 4, r16y = (uint32_t)ry >> 4;
    const uint32_t irx = (1u << 26) / (r16x * r16x), iry = (1u << 26) / (r16y * r16y);
    const int cr = (col >> 16) & 255, cg = (col >> 8) & 255, cb = col & 255;
    for (int py = clampi(y0, 0, H - 1); py <= clampi(y1, 0, H - 1); py++) {
        const uint32_t dy = (uint32_t)abs(py - cy) * 16, ty = (dy * dy * iry) >> 18;
        if (ty >= 256) continue;
        uint32_t *d = out + py * W; const uint8_t *wrow = wc + py * W, *srow = ship + py * W;
        for (int px = clampi(x0, 0, W - 1); px <= clampi(x1, 0, W - 1); px++) {
            if (clip == 1 && !wrow[px]) continue;
            if (clip == 2 && (srow[px] || py >= horizon)) continue;
            const uint32_t dx = (uint32_t)abs(px - cx) * 16, q = ty + ((dx * dx * irx) >> 18);
            if (q >= 256) continue;
            const int a = (prof[q] * alpha) >> 8; if (!a) continue;
            const uint32_t p = d[px];
            int R = (p >> 16) & 255, G = (p >> 8) & 255, B = p & 255;
            if (mode) { R += (cr * a) >> 8; G += (cg * a) >> 8; B += (cb * a) >> 8; }
            else { R += ((cr - R) * a) >> 8; G += ((cg - G) * a) >> 8; B += ((cb - B) * a) >> 8; }
            d[px] = (uint32_t)(R > 255 ? 255 : R) << 16 | (uint32_t)(G > 255 ? 255 : G) << 8 | (uint32_t)(B > 255 ? 255 : B);
        }
    }
    rect_add(nlo, nhi, x0, y0, x1, y1);
}

/* ------------------------------------------------------------------ daytime touches */
static inline int day_amount(void) { return (256 - night_lvl) * (256 - (dusk_lvl * 102 >> 8)) >> 8; }    /* (1-night)(1-0.4 dusk) */
static void new_shadow(shadow_t *c, int x_px) {
    const int y = rr(horizon + 20, H - 30), depth = ((y - horizon) << 8) / (H - horizon);
    c->x = x_px << 8; c->y = y << 8;
    c->rx = rr(90, 190) * (154 + depth * 256 / 256) ;              /* (0.6 + depth) * 90..190 px, in 1/256 px */
    c->ry = rr(10, 22) * (128 + depth * 410 / 256);                /* (0.5 + 1.6 depth) */
    c->v = rr(4, 7) * 256;
}
/* how much cloud shadow falls on row y: fills sh[x0..x1] (0..256), returns 0 if none */
static int shadow_row(int y, uint8_t *sh, int *ax, int *bx) {
    const int day = day_amount(); if (day < 13) return 0;
    int any = 0, lo = W, hi = -1;
    for (int k = 0; k < 3; k++) {
        const shadow_t *c = &shadows[k];
        const int32_t dy = (y << 8) - c->y; if (dy <= -c->ry || dy >= c->ry) continue;
        const int ty = (int)((int64_t)dy * dy * 256 / ((int64_t)c->ry * c->ry));
        const int x0 = clampi((c->x - c->rx) >> 8, 0, W - 1), x1 = clampi((c->x + c->rx) >> 8, 0, W - 1);
        if (x0 > x1) continue;
        const uint32_t irx = (uint32_t)(((int64_t)256 << 16) / ((int64_t)(c->rx >> 4) * (c->rx >> 4)));
        if (!any) memset(sh + x0, 0, (size_t)(x1 - x0 + 1));
        else { if (x0 < lo) memset(sh + x0, 0, (size_t)(lo - x0)); if (x1 > hi) memset(sh + hi + 1, 0, (size_t)(x1 - hi)); }
        for (int x = x0; x <= x1; x++) {
            const uint32_t dx = (uint32_t)abs((x << 8) - c->x) >> 4, q = ty + ((dx * dx * irx) >> 16);
            if (q >= 256) continue;
            const int v = prof_lin[q] * day >> 8;
            if (v > sh[x]) sh[x] = (uint8_t)v;
        }
        any = 1; if (x0 < lo) lo = x0; if (x1 > hi) hi = x1;
    }
    *ax = lo; *bx = hi; return any;
}
/* a point on the AquaDuck tube, u 0..256 */
static void tube_at(int u, int *x, int *y) {
    if (ntube < 2) { *x = *y = -100; return; }
    int total = 0, seg[32];
    for (int k = 1; k < ntube; k++) { const int dx = tube[k][0] - tube[k-1][0], dy = tube[k][1] - tube[k-1][1]; int l = 1; while ((l + 1) * (l + 1) <= dx * dx + dy * dy) l++; seg[k] = l * 256; total += seg[k]; }
    int d = total * u / 256;
    for (int k = 1; k < ntube; k++) {
        if (d <= seg[k] || k == ntube - 1) { const int f = seg[k] ? clampi(d * 256 / seg[k], 0, 256) : 0;
            *x = (tube[k-1][0] << 8) + (tube[k][0] - tube[k-1][0]) * f; *y = (tube[k-1][1] << 8) + (tube[k][1] - tube[k-1][1]) * f; return; }
        d -= seg[k];
    }
}

/* ------------------------------------------------------------------ particles */
static part_t *spawn(int kind) { if (np >= MAXP) return NULL; part_t *p = &parts[np++]; memset(p, 0, sizeof *p); p->kind = (uint8_t)kind; return p; }
static inline int lerp_i(int a, int b, int t) { return a + (((b - a) * t) >> 8); }
static int wl_at(int x) {
    const int c = clampi(x, 0, W - 1); if (wl[c] >= 0) return wl[c];
    return bow_x == stern_x ? bow_y : bow_y + (stern_y - bow_y) * (x - bow_x) / (stern_x - bow_x);
}
static void cards_rect(int n, int *a, int *b, int *c, int *d);   /* (below, with the cards) */
static void step_particles(int dt) {
    const int sc = 256;
    /* hull wash: foam all along the waterline, heaviest at the bow wave, sliding aft */
    foam_acc += (fx_on & FX_WAKE) ? dt * 55 : 0;
    while (foam_acc >= 1000) {
        foam_acc -= 1000; part_t *p = spawn(P_FOAM); if (!p) break;
        const int u = (int)(((rnd() & 1023) * (rnd() & 1023)) >> 12);               /* 0..255, more near the bow */
        const int bowness = ((255 - u) * (255 - u) >> 8) * (255 - u) >> 8;
        const int x = bow_x + (stern_x - bow_x) * u / 256 + rr(-1, 1);
        p->x = x << 8; p->y = (wl_at(x) << 8) + rr(-256, 384);
        const int sp = rr(10, 18) * sc;
        p->vx = (hull_dx * sp) >> 8; p->vy = ((hull_dy * sp) >> 8) + rr(150, 560) * (128 + 2 * bowness) / 256;
        p->life = rr(900, 1800) * (179 + bowness) / 256;
        p->size = (int16_t)(rr(180, 320) * (205 + bowness * 3 / 2) / 256);   /* radius, 1/256 px */
        p->col = (uint32_t)(115 + (bowness * 64 >> 8));                    /* alpha */
    }
    /* the bow wave: white water breaking off the stem and peeling aft and outward along the hull
       (the photo's own bow foam is painted out: frozen, it looked wrong) */
    bow_acc += (fx_on & FX_WAKE) ? dt * 46 : 0;
    while (bow_acc >= 1000) {
        bow_acc -= 1000; part_t *p = spawn(P_FOAM); if (!p) break;
        const int x = bow_x + rr(-9, 3);
        p->x = x << 8; p->y = (wl_at(x) << 8) + rr(0, 640);
        const int sp = rr(14, 32) * 256;
        p->vx = (hull_dx * sp) >> 8; p->vy = ((hull_dy * sp) >> 8) + rr(900, 3000);      /* aft, and out toward us */
        p->life = rr(600, 1500); p->size = (int16_t)rr(260, 480); p->col = (uint32_t)rr(140, 210);
    }
    /* and a little spray thrown up and forward at the stem */
    spray_acc += (fx_on & FX_WAKE) ? dt * 9 : 0;
    while (spray_acc >= 1000) {
        spray_acc -= 1000; part_t *p = spawn(P_SPLASH); if (!p) break;
        p->x = (bow_x + rr(-4, 2)) << 8; p->y = (wl_at(bow_x) - 1) << 8;
        p->vx = rr(2, 9) * 256 - (hull_dx * rr(0, 4)); p->vy = -rr(5, 13) * 256; p->life = rr(300, 550);
    }
    /* a scene's own foam: at its points, within each one's radius, moving as its flow says (0 churning in
       place, 1 drifting left, 2 right, 3 falling, 4 spreading toward the viewer); it's drawn only on the
       scene's water when it has some (water.raw.gz), anywhere otherwise (p->ty 1 says so) */
    foamp_acc += (fx_on & FX_FOAM) && foam_n ? dt * 28 * foam_n * foam_amount_q8 / 256 : 0;
    while (foamp_acc >= 1000) {
        foamp_acc -= 1000; part_t *p = spawn(P_FOAM); if (!p) break;
        const int *f = foam_xyr[rnd() % (uint32_t)foam_n], r = f[2] > 0 ? f[2] : 1;
        p->x = (f[0] << 8) + (rr(-r, r) + rr(-r, r)) * 128; p->y = (f[1] << 8) + (rr(-r, r) + rr(-r, r)) * 64;   /* (flatter than wide: water seen at an angle) */
        p->vx = rr(-4, 4) * 256; p->vy = rr(-2, 2) * 256;
        if (foam_flow == 1) p->vx = -rr(8, 18) * 256;
        else if (foam_flow == 2) p->vx = rr(8, 18) * 256;
        else if (foam_flow == 3) { p->vy = rr(18, 40) * 256; p->vx = rr(-3, 3) * 256; }
        else if (foam_flow == 4) { p->vy = rr(4, 12) * 256; p->vx = rr(-10, 10) * 256; }
        p->life = rr(700, 1700); p->size = (int16_t)rr(420, 820); p->col = (uint32_t)rr(150, 235); p->ty = 1;   /* (flecks 3 to 6 px: near, not a distant ship's) */
    }
    /* and, for falling water, spray thrown up from its foot */
    foams_acc += (fx_on & FX_FOAM) && foam_n && foam_flow == 3 ? dt * 6 * foam_n * foam_amount_q8 / 256 : 0;
    while (foams_acc >= 1000) {
        foams_acc -= 1000; part_t *p = spawn(P_SPLASH); if (!p) break;
        const int *f = foam_xyr[rnd() % (uint32_t)foam_n];
        p->x = (f[0] + rr(-f[2], f[2])) << 8; p->y = (f[1] + f[2] / 2) << 8;
        p->vx = rr(-8, 8) * 256; p->vy = -rr(6, 14) * 256; p->life = rr(300, 550);
    }
    /* the stern wake: churned water streaming away behind the ship */
    wake_acc += (fx_on & FX_WAKE) ? dt * 16 : 0;
    while (wake_acc >= 1000) {
        wake_acc -= 1000; part_t *p = spawn(P_WAKE); if (!p) break;
        p->x = (stern_x + rr(-2, 4)) << 8; p->y = ((wl_at(stern_x + 3) + rr(-3, 2)) << 8);
        const int sp = rr(14, 24) * 256;
        p->vx = (hull_dx * sp) >> 8; p->vy = ((hull_dy * sp) >> 8) + rr(-640, 900);
        p->life = rr(2500, 4500); p->size = (int16_t)rr(256, 512); p->col = (uint32_t)rr(77, 128);
    }
    /* funnel smoke */
    smoke_acc += (fx_on & FX_SMOKE) ? dt * smoke_rate : 0;
    while (smoke_acc >= 1000) {
        smoke_acc -= 1000;
        for (int s = 0; s < smoke_n; s++) {
            part_t *p = spawn(P_SMOKE); if (!p) break;
            p->x = (stack_x[s] << 8) + (rr(-640, 640) * smoke_q8 >> 8); p->y = (stack_y[s] + 2) << 8;
            p->vx = (rr(9, 14) * smoke_q8) * smoke_wind_q8 / 256 + (smoke_wind_q8 == 0 ? rr(-3, 3) * smoke_q8 : 0);   /* (still air: it wavers) */
            p->vy = smoke_own ? -(rr(17, 27) * smoke_q8) : -(rr(6, 9) * smoke_q8);
            p->life = smoke_own ? rr(5500, 8000) : rr(4500, 6500); p->ty = (int16_t)rr(0, 1023);
        }
    }
    /* rockets */
    if (rockets_pending > 0 && (next_rocket_ms -= dt) <= 0) {
        rockets_pending--; next_rocket_ms = rr(rocket_gap_min, rocket_gap_max);
        part_t *p = spawn(P_ROCKET);
        /* where it bursts: a few tries for open sky (not the subject, nor behind the cards: a scene with
           little sky, like a photo filled by its subject, would hide most of them) */
        int bx = rr(60, W - 60), by = horizon * rr(46, 161) / 256;
        { int c0 = 0, c1 = -1, c2 = 0, c3 = -1; if (days >= 0) cards_rect(ndig, &c0, &c1, &c2, &c3);
          for (int k = 0; k < 24; k++) {                  /* (the usual heights first, then lower, to just above the horizon) */
              const int x = rr(60, W - 60), y = k < 12 ? horizon * rr(46, 161) / 256 : rr(horizon * 161 / 256, horizon - 24);
              const int behind_cards = x >= c0 - 30 && x <= c2 + 30 && y >= c1 - 30 && y <= c3 + 30;
              if (y > 0 && y < H && !ship[y * W + x] && !behind_cards) { bx = x; by = y; break; }
          } }
        if (p) { p->x = bx << 8; p->y = horizon << 8; p->ty = (int16_t)by;
                 p->vy = -(260 * fw_q8 + 80 * 256); static const uint32_t C[] = {0xffd278, 0xff7896, 0x8cc8ff, 0xc8ffaa, 0xfffff0, 0xdc96ff};
                 p->col = C[rnd() % 6]; p->life = 10000; }
    }
    /* daytime: cloud shadows drift with the wind */
    for (int k = 0; k < 3; k++) { shadows[k].x += shadows[k].v * dt / 1000; if ((shadows[k].x - shadows[k].rx) >> 8 > W) new_shadow(&shadows[k], -(shadows[k].rx >> 8) * 6 / 5); }
    const int sca = amb_q8;
    /* gulls: a few at a time, every minute or so, in daylight */
    if ((next_gulls_ms -= dt) < 0) {
        next_gulls_ms = rr(35000, 80000);
        if ((night_lvl < 128 && (fx_on & FX_GULLS)) || gulls_now) {
            gulls_now = 0;
            const int dir = rnd() & 1 ? 1 : -1, n = rr(1, 3), y0 = horizon * rr(64, 218) / 256;
            for (int k = 0; k < n; k++) { part_t *p = spawn(P_GULL); if (!p) break;
                p->x = (dir > 0 ? -20 - k * rr(14, 30) : W + 20 + k * rr(14, 30)) << 8; p->y = (y0 + rr(-14, 14)) << 8;
                p->vx = dir * rr(26, 40) * sca; p->size = (int16_t)(rr(45, 70) * sca / 10); p->ty = (int16_t)rr(0, LUT - 1);
                p->life = 60000; p->col = 0; }
        }
    }
    /* dolphins: now and then a small pod leaps ahead of the bow */
    if ((next_pod_ms -= dt) < 0) {
        next_pod_ms = rr(40000, 90000);
        if (night_lvl < 128 && (fx_on & FX_DOLPHINS)) {
            const int n = rr(2, 3); int delay = 0;
            for (int k = 0; k < n; k++) { part_t *p = spawn(P_DOLPHIN); if (!p) break;
                p->px = (bow_x + rr(25, 80) * sca / 256) << 8; p->py = (bow_y + rr(12, 40) * sca / 256) << 8;
                p->age = -delay; delay += rr(250, 600); p->life = rr(900, 1200);
                p->vx = rr(18, 26) * sca; p->vy = rr(9, 14) * sca; p->col = 0; }
        }
    }
    /* the AquaDuck: a raft whooshes along the tube every so often */
    if (raft_start < 0 && (next_raft_ms -= dt) < 0) { next_raft_ms = rr(25000, 55000); if (night_lvl < 154 && ntube > 1 && (fx_on & FX_RAFT)) { raft_start = last_t; raft_dur = rr(2800, 3800); } }
    if (raft_start >= 0 && last_t - raft_start > raft_dur) raft_start = -1;
    /* move */
    const int drag_foam = 256 - dt * 115 / 256, drag_spark = 256 - dt * 268 / 1000;   /* ~0.6^t, ~0.35^t */
    for (int k = 0; k < np; k++) {
        part_t *p = &parts[k]; p->age += dt;
        if (p->kind == P_SPARK || p->kind == P_ROCKET) { p->px = p->x; p->py = p->y; }   /* (others use px, py for their own state) */
        switch (p->kind) {
        case P_FOAM: case P_WAKE:
            p->x += p->vx * dt / 1000; p->y += p->vy * dt / 1000;
            if (p->ty == 1) {                               /* (a scene's foam: it keeps moving; falling water speeds up) */
                if (foam_flow == 3) p->vy += 60 * 256 * dt / 1000;
                else { p->vx = p->vx * (256 - dt / 40) >> 8; p->vy = p->vy * (256 - dt / 40) >> 8; }
                break;
            }
            p->vx = p->vx * drag_foam >> 8; p->vy = p->vy * (256 - dt * 177 / 256) >> 8; break;
        case P_SMOKE: {
            const int wob = sin_lut[((p->ty + p->age / 8) & (LUT - 1))] * 5 / 2 * smoke_q8 >> 14;   /* sideways drift */
            p->vy = p->vy * (256 - dt * 57 / 1000) >> 8;
            p->x += (p->vx + wob) * dt / 1000; p->y += p->vy * dt / 1000; break; }
        case P_ROCKET:
            p->y += p->vy * dt / 1000;
            if ((p->y >> 8) <= p->ty) {                                 /* burst */
                const int n = rr(70, 110), sp = rr(55, 100) * fw_q8;
                for (int j = 0; j < n; j++) {
                    part_t *q = spawn(P_SPARK); if (!q) break;
                    const int ang = rr(0, LUT - 1), v = sp * rr(140, 256) >> 8;
                    q->x = q->px = p->x; q->y = q->py = p->y;
                    q->vx = sin_lut[(ang + LUT / 4) & (LUT - 1)] * v >> 14; q->vy = sin_lut[ang] * v >> 14;
                    q->life = 1000 * 256 / rr(128, 218); q->col = p->col;
                }
                p->age = p->life;
            }
            break;
        case P_GULL: {
            p->x += p->vx * dt / 1000;
            p->y += (sin_lut[(p->ty + (int)((int64_t)last_t * 147 / 1000)) & (LUT - 1)] * 3 * 256 >> 14) * dt / 1000;
            /* flapping (col = until when, in ms) or gliding (py = until when) */
            if (last_t > (int)p->col && last_t > p->py) { if (rnd() & 1) p->col = (uint32_t)(last_t + rr(800, 1800)); else p->py = last_t + rr(1500, 3500); }
            if (last_t < (int)p->col) p->ty = (int16_t)((p->ty + dt * 11 * LUT / 6283) & (LUT - 1));
            if ((p->x >> 8) < -60 || (p->x >> 8) > W + 60) p->age = p->life;
            break; }
        case P_DOLPHIN:
            if (p->age >= 0 && p->col == 0) { p->col = 1; for (int j = 0; j < 7; j++) { part_t *q = spawn(P_SPLASH); if (!q) break; q->x = p->px; q->y = p->py; q->vx = rr(-10, 10) * sca; q->vy = -rr(8, 22) * sca; q->life = rr(350, 600); } }
            if (p->age >= p->life && p->col == 1) { p->col = 2; for (int j = 0; j < 7; j++) { part_t *q = spawn(P_SPLASH); if (!q) break; q->x = p->px + p->vx; q->y = p->py; q->vx = rr(-10, 10) * sca; q->vy = -rr(8, 22) * sca; q->life = rr(350, 600); } }
            break;
        case P_SPLASH:
            p->x += p->vx * dt / 1000; p->y += p->vy * dt / 1000; p->vy += 40 * 256 * dt / 1000; break;
        case P_SPARK:
            p->vx = p->vx * drag_spark >> 8; p->vy = (p->vy * drag_spark >> 8) + 38 * fw_q8 * dt / 1000;
            p->x += p->vx * dt / 1000; p->y += p->vy * dt / 1000; break;
        }
    }
    int m = 0; for (int k = 0; k < np; k++) if (parts[k].age < parts[k].life + (parts[k].kind == P_DOLPHIN ? 120 : 0)) parts[m++] = parts[k]; np = m;
}
/* the parts of the screen particles will cover this frame: refreshed first, so nothing double-draws */
static void particle_rects(void) {
    for (int k = 0; k < np; k++) {
        const part_t *p = &parts[k]; int r;
        switch (p->kind) {
        case P_FOAM: case P_WAKE: r = (p->size * (p->kind == P_WAKE ? 5 : 3) >> 8) + 2; break;
        case P_SMOKE: r = 30; break;
        case P_GULL: r = (p->size >> 8) + 3; break;
        case P_DOLPHIN: {                                   /* the whole arc */
            const int x0 = p->px >> 8, y0 = p->py >> 8, len = p->vx >> 8, ht = p->vy >> 8;
            rect_add(rlo, rhi, x0 - 8, y0 - ht - 8, x0 + len + 8, y0 + 6); continue; }
        default: r = 3;
        }
        rect_add(rlo, rhi, (p->x >> 8) - r, (p->y >> 8) - r, (p->x >> 8) + r, (p->y >> 8) + r);
        if (p->kind == P_SPARK) rect_add(rlo, rhi, p->px >> 8, p->py >> 8, p->px >> 8, p->py >> 8);
    }
}
static void draw_particles(void) {
    const int lit = lerp_i(256, 56, night_lvl) * (256 - (dusk_lvl * 51 >> 8)) >> 8;     /* how lit small effects are */
    const int fc = 245 * lit >> 8; const uint32_t foam_col = (uint32_t)fc << 16 | (uint32_t)fc << 8 | (uint32_t)clampi(fc + 6, 0, 255);
    const uint32_t wake_col = (uint32_t)(fc * 86 / 100) << 16 | (uint32_t)(fc * 95 / 100) << 8 | (uint32_t)(fc * 97 / 100);
    const int sr = lerp_i(lerp_i(128, 150, dusk_lvl), 52, night_lvl), sg = lerp_i(lerp_i(122, 118, dusk_lvl), 54, night_lvl),
              sb = lerp_i(lerp_i(116, 100, dusk_lvl), 62, night_lvl);
    const uint32_t smoke_col = (uint32_t)sr << 16 | (uint32_t)sg << 8 | (uint32_t)sb;
    const int smoke_str = clampi(lerp_i(87, 44, night_lvl) * smoke_dense_q8 >> 8, 0, 240), fw_bright = 141 + (115 * night_lvl >> 8);
    for (int k = 0; k < np; k++) {
        const part_t *p = &parts[k]; const int u = (int)((int64_t)p->age * 256 / (p->life ? p->life : 1));   /* 0..256 */
        switch (p->kind) {
        case P_FOAM: case P_WAKE: {
            const int in = u < 26 ? u * 10 : 256, a = (256 - u) * in >> 8;
            const int grow = p->kind == P_WAKE ? 256 + u * 4 : 256 + u * 2;
            const int rx = p->size * grow >> 8, ry = (p->size >> 1) * (256 + u * (p->kind == P_WAKE ? 2 : 1)) >> 8;
            blob(p->x, p->y, rx, ry, p->kind == P_WAKE ? wake_col : foam_col, (a * (int)p->col >> 8) * (p->kind == P_WAKE ? 180 : 256) >> 8,
                 prof_soft, 0, p->ty == 1 && !wcustom ? 0 : 1);    /* (a scene's foam with no water of its own: anywhere) */
            break; }
        case P_SMOKE: {
            const int f = u, inv = 256 - f;
            int a = smoke_str * (p->age < 80 ? p->age * 256 / 80 : 256) >> 8;
            const int i2 = inv * inv >> 8, i4 = i2 * i2 >> 8, i8 = i4 * i4 >> 8;
            a = a * inv >> 8; a = a * (256 + (563 * i8 >> 8)) >> 8;     /* (1-f) * (1 + 2.2 (1-f)^8): dense at the stack, then thinning */
            int sq = 0; { int lo = 0, hi = 256; while (lo < hi) { int mid = (lo + hi + 1) / 2; if (mid * mid <= f * 256) lo = mid; else hi = mid - 1; } sq = lo; }
            const int r = (5 * 256 + 19 * sq) * smoke_q8 >> 8;
            blob(p->x, p->y, r, r, smoke_col, a, prof_puff, 0, 0);
            break; }
        case P_ROCKET:
            for (int j = 0; j < 3; j++) blob(p->x, p->y + j * 3 * 256, 200, 300, 0xffdcaa, 200 - j * 50, prof_soft, 1, 2);
            break;
        case P_GULL: {                                      /* two curved wings, flapping or gliding */
            const int gl = lerp_i(48, 18, dusk_lvl) * lit >> 8; const uint32_t gc = (uint32_t)gl << 16 | (uint32_t)gl << 8 | (uint32_t)(gl + 6);
            const int z = p->size, fl = last_t < (int)p->col ? sin_lut[p->ty & (LUT - 1)] : 90 * 64;   /* Q14: flap, or 0.35 gliding */
            for (int side = -1; side <= 1; side += 2) {
                const int ax = p->x + side * z, ay = p->y - (fl * z * 7 / 10 >> 14);              /* wing tip */
                const int cx = p->x + side * z * 45 / 100, cy = p->y - z * 45 / 100 - (fl * z / 5 >> 14);   /* control point */
                for (int s2 = 0; s2 <= 8; s2++) {                   /* quadratic from the tip to the body */
                    const int t = s2 * 32, it = 256 - t;
                    const int bx = (ax * (it * it >> 8) + 2 * cx * (it * t >> 8) + p->x * (t * t >> 8)) >> 8;
                    const int by = (ay * (it * it >> 8) + 2 * cy * (it * t >> 8) + p->y * (t * t >> 8)) >> 8;
                    blob(bx, by, 150, 150, gc, 230, prof_soft, 0, 0);
                }
            }
            break; }
        case P_DOLPHIN: {                                   /* a dark curved body along the arc, nose first */
            if (p->age < 0 || p->age > p->life) break;
            const int u = p->age * 256 / p->life, len = p->vx, ht = p->vy;
            const int x = p->px + (len * u >> 8), y = p->py - (ht * 4 * u >> 8) * (256 - u) / 256;
            /* a lighter grey than the deep blue water (the mockup's slate disappears against this photo's sea),
               with a darker back */
            const uint32_t col = (uint32_t)(104 * lit >> 8) << 16 | (uint32_t)(114 * lit >> 8) << 8 | (uint32_t)(128 * lit >> 8);
            const uint32_t back = (uint32_t)(70 * lit >> 8) << 16 | (uint32_t)(80 * lit >> 8) << 8 | (uint32_t)(94 * lit >> 8);
            /* direction of travel: (len, -4 ht (1 - 2u)), normalised to 1/256 */
            const int vx = len, vy = -(ht * 4 * (256 - 2 * u) >> 8); int n = 1; { const int64_t q = (int64_t)vx * vx + (int64_t)vy * vy; while ((int64_t)(n + 1) * (n + 1) * 65536 <= q) n++; }
            const int ux = vx / n, uy = vy / n, s = amb_q8;       /* n = |v| / 256, so this is the unit vector in 1/256 */
            for (int j = -4; j <= 4; j++) {               /* body: 4.2 x 1.25 px at full size */
                const int w = 256 - (j * j * 12);
                blob(x + (ux * j * s >> 8) * 105 / 100, y + (uy * j * s >> 8) * 105 / 100, (400 * w >> 8) * s >> 8, (400 * w >> 8) * s >> 8, col, 255, prof_soft, 0, 0);
            }
            for (int j = -3; j <= 3; j++)                 /* the darker back, along the top of the body */
                blob(x + (ux * j * s >> 8) + (uy * s >> 8) * 3 / 4, y + (uy * j * s >> 8) - (ux * s >> 8) * 3 / 4, 200 * s >> 8, 150 * s >> 8, back, 200, prof_soft, 0, 0);
            blob(x - (ux * s >> 8) + (uy * 2 * s >> 8), y - (uy * s >> 8) - (ux * 2 * s >> 8), 200, 260, back, 255, prof_soft, 0, 0);   /* dorsal fin, on the back */
            blob(x - (ux * 5 * s >> 8), y - (uy * 5 * s >> 8), 260, 360, col, 255, prof_soft, 0, 0);                                         /* tail */
            break; }
        case P_SPLASH: {
            const int a = (256 - u) * 192 >> 8;
            blob(p->x, p->y, 170, 170, foam_col, a, prof_soft, 0, 0); break; }
        case P_SPARK: {
            const int life_left = 256 - u, a = (life_left * 410 >> 8 > 256 ? 256 : life_left * 410 >> 8) * fw_bright >> 8;
            blob(p->x, p->y, 230, 230, p->col, a, prof_soft, 1, 2);
            break; }
        }
    }
}

/* ---- twinkle: coloured lights on a scene's subject at night (EPCOT's orb), from the scene's optional
   twinkle.bin.gz: "VTW2", a count, the sphere's circle (cx, cy, r), then each light's x, y and its place
   on the sphere (how far round, 0..65535 across the whole way round; how high, -16384..16384 pole to
   pole; how far from the middle of the picture, 0..1024), worked out by scene_pack.py; or "VTW1", just
   x, y (its place then guessed from the picture). A show: a program of patterns (vfx_twinkle_program),
   each for a while, crossfading into the next; vfx_twinkle_pin holds one (the previewer's picker).
   Fading in through dusk; off by day. Only the lights' own few pixels are redrawn. */
enum { TW_WAVES, TW_RINGS, TW_BLINK, TW_SPIN, TW_RISE, TW_WASH, TW_SPARKLE, TW_SPIRAL, TW_COMET, TW_HEART, TW_PATTERNS };
static uint16_t *tw_xy, *tw_lon, *tw_d; static int16_t *tw_lat;
static int tw_n, tw_cx, tw_cy, tw_r = 1;
static int tw_prog[32] = {TW_SPIN, TW_WAVES, TW_WASH, TW_SPIRAL, TW_RINGS, TW_COMET, TW_RISE, TW_SPARKLE, TW_HEART, TW_BLINK};
static int tw_nprog = 10, tw_step_ms = 12000, tw_pin = -1;
static int isqrt(int v);                       /* (below, with the UI's drawing) */
static const uint32_t tw_pal[8] = {0xff2a3c, 0xff8a1e, 0xffd23c, 0x3cff6e, 0x28d2ff, 0x3c64ff, 0xa040ff, 0xff3cc8};
static uint32_t tw_mix(uint32_t a, uint32_t b, int t) {   /* t 0..256 */
    return (uint32_t)lerp_i((a >> 16) & 255, (b >> 16) & 255, t) << 16 | (uint32_t)lerp_i((a >> 8) & 255, (b >> 8) & 255, t) << 8 | (uint32_t)lerp_i(a & 255, b & 255, t);
}
static uint32_t tw_hue(int h) { h &= 2047; return tw_mix(tw_pal[h >> 8], tw_pal[((h >> 8) + 1) & 7], h & 255); }   /* 0..2047 round the palette */
static inline int tw_sin(int ph) { return sin_lut[ph & (LUT - 1)]; }       /* +-16384; LUT steps a turn */
static void tw_free(void) { free(tw_xy); free(tw_lon); free(tw_lat); free(tw_d); tw_xy = tw_lon = tw_d = NULL; tw_lat = NULL; tw_n = 0; }
static void tw_load(const char *theme) {
    char p[600]; snprintf(p, sizeof p, "%s/twinkle.bin.gz", theme);
    tw_free();
    if (access(p, F_OK) != 0) return;
    size_t n; uint8_t *b = gzload(theme, "twinkle.bin.gz", &n);
    const int v2 = b && n >= 16 && !memcmp(b, "VTW2", 4), v1 = b && n >= 8 && !memcmp(b, "VTW1", 4);
    if (!v1 && !v2) { free(b); fprintf(stderr, "vacfx: bad twinkle\n"); return; }
    uint32_t k; memcpy(&k, b + 4, 4);
    const size_t head = v2 ? 16 : 8, each = v2 ? 10 : 4;
    if (n < head + (size_t)k * each) { free(b); fprintf(stderr, "vacfx: twinkle file too short\n"); return; }
    tw_xy = malloc((size_t)k * 4 + 4); tw_lon = malloc((size_t)k * 2 + 2); tw_lat = malloc((size_t)k * 2 + 2); tw_d = malloc((size_t)k * 2 + 2);
    if (!tw_xy || !tw_lon || !tw_lat || !tw_d) { free(b); tw_free(); return; }
    tw_n = (int)k;
    if (v2) {
        uint16_t c[3]; memcpy(c, b + 8, 6); tw_cx = c[0]; tw_cy = c[1]; tw_r = c[2] ? c[2] : 1;
        for (int i = 0; i < tw_n; i++) {
            const uint8_t *q = b + head + (size_t)i * each;
            memcpy(&tw_xy[2 * i], q, 2); memcpy(&tw_xy[2 * i + 1], q + 2, 2); memcpy(&tw_lon[i], q + 4, 2); memcpy(&tw_lat[i], q + 6, 2); memcpy(&tw_d[i], q + 8, 2);
        }
    } else {                                    /* (only x, y: the sphere guessed from them, flat) */
        memcpy(tw_xy, b + 8, (size_t)k * 4);
        long sx = 0, sy = 0; for (int i = 0; i < tw_n; i++) { sx += tw_xy[2 * i]; sy += tw_xy[2 * i + 1]; }
        if (tw_n) { tw_cx = (int)(sx / tw_n); tw_cy = (int)(sy / tw_n); }
        tw_r = 1; for (int i = 0; i < tw_n; i++) { const int dx = tw_xy[2 * i] - tw_cx, dy = tw_xy[2 * i + 1] - tw_cy, d = isqrt(dx * dx + dy * dy); if (d > tw_r) tw_r = d; }
        for (int i = 0; i < tw_n; i++) {
            const int dx = tw_xy[2 * i] - tw_cx, dy = tw_xy[2 * i + 1] - tw_cy;
            tw_lon[i] = (uint16_t)(32768 + dx * 16384 / tw_r); tw_lat[i] = (int16_t)clampi(-dy * 16384 / tw_r, -16384, 16384);
            tw_d[i] = (uint16_t)clampi(isqrt(dx * dx + dy * dy) * 1024 / tw_r, 0, 1024);
        }
    }
    free(b);
}
/* one light in one pattern at t: its colour (palette 0..2047, or -1 for white) and brightness 0..256 */
static void tw_pattern(int pat, int i, int t, int *hue, int *br) {
    const int x = tw_xy[2 * i], lon = tw_lon[i], lat = tw_lat[i], d = tw_d[i];
    const uint32_t hsh = (uint32_t)i * 2654435761u;
    switch (pat) {
    case TW_WAVES:                              /* colour waves sweeping across */
        *hue = (x - tw_cx) * 6 - t / 6; *br = 160 + tw_sin(x * 5 - t / 3) / 200; break;
    case TW_RINGS:                              /* rings rippling out from the middle */
        *hue = d * 2 - t / 5; *br = 160 + tw_sin(d * 3 - t / 2) / 200; break;
    case TW_BLINK: {                            /* each blinking a colour of its own */
        const int period = 700 + (int)(hsh >> 22), ph = (t + (int)(hsh & 4095)) % period;
        *hue = (int)((hsh >> 8) & 7) * 256 + ((t + (int)(hsh & 4095)) / period) * 768; *br = ph < period / 2 ? 256 : 50; break; }
    case TW_SPIN:                               /* a rainbow turning round the sphere's axis */
        *hue = (lon >> 4) - t / 3; *br = 190 + tw_sin((lon >> 6) * 4 - t / 2) / 260; break;
    case TW_RISE: {                             /* bands of light rising from the bottom to the top */
        const int s = tw_sin((lat >> 4) - t / 3);
        *hue = (t / 4000) * 512 + (lat >> 6); *br = s > 4000 ? 256 : s > -2000 ? 110 : 30; break; }
    case TW_WASH:                               /* the whole sphere one colour, changing slowly, breathing */
        *hue = t / 14; *br = 170 + tw_sin(t / 4) / 220; break;
    case TW_SPARKLE: {                          /* dim, with lights flashing white here and there */
        const int slot = (t + (int)(hsh & 1023)) / 140;
        const uint32_t h2 = (hsh ^ (uint32_t)slot * 2246822519u) >> 24;
        if (h2 < 10) { *hue = -1; *br = 256; } else { *hue = 1280 + (lat >> 7); *br = 45; }
        break; }
    case TW_SPIRAL:                             /* colours spiralling round and up the sphere */
        *hue = (lon >> 4) + (lat >> 3) - t / 4; *br = 150 + tw_sin((lon >> 6) * 3 + (lat >> 4) - t / 2) / 160; break;
    case TW_COMET: {                            /* a comet racing round, a fading tail behind it */
        const int head = (t * 22) & 65535, back = (head - lon) & 65535;   /* how far behind the head */
        const int band = lat < 0 ? -lat : lat;  /* (brightest round the middle) */
        *hue = t / 25 + (back >> 7);
        *br = back < 16384 ? 256 - back / 64 : 25;
        *br = *br * (256 - clampi(band / 64, 0, 200)) >> 8; break; }
    case TW_HEART: {                            /* a heartbeat: two quick pulses, a pause, a new colour */
        const int ph = t % 1300;
        const int e = ph < 120 ? 256 - ph * 2 : ph < 260 ? 40 : ph < 380 ? 256 - (ph - 260) * 2 : 40;
        *hue = (t / 1300) * 640 + (d >> 2); *br = clampi(e, 30, 256); break; }
    default: *hue = 0; *br = 0;
    }
    *br = clampi(*br, 0, 256);
}
static void draw_twinkle(void) {
    if (!tw_n || !(fx_on & FX_TWINKLE)) return;
    const int vis = clampi(night_lvl + dusk_lvl / 3, 0, 256);
    if (vis < 8) return;
    const int t = last_t, XF = 1500;            /* (crossfade, ms) */
    int cur, prev = -1, mix = 256;
    if (tw_pin >= 0) cur = tw_pin;
    else {
        const int step = t / tw_step_ms, into = t % tw_step_ms;
        cur = tw_prog[step % tw_nprog];
        if (into < XF && tw_nprog > 1) { prev = tw_prog[(step + tw_nprog - 1) % tw_nprog]; mix = into * 256 / XF; }
    }
    for (int i = 0; i < tw_n; i++) {
        const int x = tw_xy[2 * i], y = tw_xy[2 * i + 1];
        int hue, br; tw_pattern(cur, i, t, &hue, &br);
        uint32_t col = hue < 0 ? 0xffffff : tw_hue(hue);
        if (prev >= 0 && mix < 256) {           /* (into the next pattern) */
            int h0, b0; tw_pattern(prev, i, t, &h0, &b0);
            col = tw_mix(h0 < 0 ? 0xffffff : tw_hue(h0), col, mix); br = lerp_i(b0, br, mix);
        }
        br = br * vis >> 8;
        if (br < 4) continue;
        blob(x << 8, y << 8, 560, 560, col, br * 3 / 4, prof_soft, 1, 0);                /* the glow (on the subject: no clipping) */
        blob(x << 8, y << 8, 230, 230, tw_mix(col, 0xffffff, 110), br, prof_soft, 1, 0);  /* the bulb */
        rect_add(nlo, nhi, x - 3, y - 3, x + 3, y + 3);
    }
}
/* the show: patterns (TW_*, as numbers) in turn, each step_ms long (n 0: the default) */
void vfx_twinkle_program(const int *ids, int n, int step_ms) {
    if (n > 0) { tw_nprog = 0; for (int k = 0; k < n && k < 32; k++) if (ids[k] >= 0 && ids[k] < TW_PATTERNS) tw_prog[tw_nprog++] = ids[k]; }
    if (!tw_nprog) { tw_prog[0] = TW_SPIN; tw_nprog = 1; }
    if (step_ms >= 2000) tw_step_ms = step_ms;
}
void vfx_twinkle_pin(int id) { tw_pin = id >= 0 && id < TW_PATTERNS ? id : -1; }

static void ambient_rects(void) {
    if (raft_start >= 0) { int x, y; for (int k = 0; k <= 4; k++) { const int u = clampi((last_t - raft_start) * 256 / raft_dur - k * 4, 0, 256); tube_at(u, &x, &y); rect_add(rlo, rhi, (x >> 8) - 4, (y >> 8) - 4, (x >> 8) + 4, (y >> 8) + 3); } }
    if (mast_x >= 0) { const int len = 9 * amb_q8 >> 8, wid = 4 * amb_q8 >> 8; rect_add(rlo, rhi, mast_x - len - 2, mast_y - 3, mast_x + 1, mast_y + wid + 4); }
}
static void draw_ambient(void) {
    const int lit = lerp_i(256, 56, night_lvl) * (256 - (dusk_lvl * 51 >> 8)) >> 8;
    /* the raft: eased along the tube, with a faint streak behind it */
    if (raft_start >= 0) {
        int u = clampi((last_t - raft_start) * 256 / raft_dur, 0, 256); u = u < 128 ? 2 * u * u / 256 : 256 - 2 * (256 - u) * (256 - u) / 256;
        int x, y; for (int k = 3; k >= 1; k--) { tube_at(clampi(u - k * 3, 0, 256), &x, &y); blob(x, y - 128, 200, 150, 0xffd65a, 60 * lit >> 8, prof_soft, 0, 0); }
        tube_at(u, &x, &y);
        blob(x, y - 128, 540, 340, (uint32_t)(255 * lit >> 8) << 16 | (uint32_t)(196 * lit >> 8) << 8 | (uint32_t)(40 * lit >> 8), 256, prof_soft, 0, 0);
    }
    /* the pennant: streaming aft from the mast top, rippling */
    if (mast_x >= 0) {
        const int len = 9 * amb_q8 >> 8, wid = 32 * amb_q8 / 10;        /* 3.2 px tall at the mast, in 1/256 px */
        const int R = 196 * lit >> 8, G = 30 * lit >> 8, B = 36 * lit >> 8;
        for (int c = 0; c <= len; c++) {
            /* ripple: sin(9 t - 5 u), growing to 1.1 px at the tip (Q14 px) */
            const int u = c * 256 / (len ? len : 1);
            const int ph = (int)((int64_t)last_t * 9 * LUT / 6283) - u * 5 * LUT / 1608;
            const int wave = sin_lut[ph & (LUT - 1)] * 11 / 10 * u >> 8;
            const int top = (mast_y << 14) + wave * amb_q8 / 256, bot = top + (wid * (256 - u * 7 / 10) >> 8 << 6);
            const int xx = mast_x - c; if (xx < 0 || xx >= W) continue;
            for (int yy = top >> 14; yy <= (bot >> 14) + 1; yy++) {
                if (yy < 0 || yy >= H) continue;
                int cov = 256; const int yt = yy << 14, yb = (yy + 1) << 14;
                if (yt < top) cov -= (top - yt) >> 6;
                if (yb > bot) cov -= (yb - bot) >> 6;
                if (cov <= 0) continue;
                if (cov > 256) cov = 256;
                const uint32_t p = out[yy * W + xx]; const int r0 = (p >> 16) & 255, g0 = (p >> 8) & 255, b0 = p & 255;
                out[yy * W + xx] = (uint32_t)(r0 + ((R - r0) * cov >> 8)) << 16 | (uint32_t)(g0 + ((G - g0) * cov >> 8)) << 8 | (uint32_t)(b0 + ((B - b0) * cov >> 8));
            }
        }
        rect_add(nlo, nhi, mast_x - len - 2, mast_y - 3, mast_x + 1, mast_y + (wid >> 8) + 4);
    }
}

/* ------------------------------------------------------------------ the flip clock */
static int split_w(int sp) { return sp && colon_img ? colon_w + cards_gap : sp ? cards_gap * 2 : 0; }
/* where a row wtot wide is centred: the scene's centre (cards_cx), moved just enough to keep the row on
   the screen (a scene with the cards to one side, like the castle's, and three digits) */
#define CARDS_MARGIN 14
static int cards_center(int wtot) {
    int c = cards_cx;
    if (c - wtot / 2 < CARDS_MARGIN) c = CARDS_MARGIN + wtot / 2;
    if (c - wtot / 2 + wtot > W - CARDS_MARGIN) c = W - CARDS_MARGIN - wtot + wtot / 2;
    return c;
}
static void cards_layout_s(int n, int sp, int *x0, int *wtot) { *wtot = n * card_w + (n - 1) * cards_gap + split_w(sp); *x0 = cards_center(*wtot) - *wtot / 2; }
static void cards_layout(int n, int *x0, int *wtot) { cards_layout_s(n, split, x0, wtot); }
static int card_x(int x0, int k) { return x0 + k * (card_w + cards_gap) + (split && k >= split ? split_w(split) : 0); }
static void cards_rect_s(int n, int sp, int *a, int *b, int *c, int *d);
static void cards_rect(int n, int *a, int *b, int *c, int *d) { cards_rect_s(n, split, a, b, c, d); }
static void cards_rect_s(int n, int sp, int *a, int *b, int *c, int *d) {
    int x0, wt; cards_layout_s(n, sp, &x0, &wt);
    const int cx = x0 + wt / 2;                            /* (the row's centre, on the screen) */
    if (banner_img && (banner_on || n == 0)) {             /* (the banner's footprint too: it may be showing) */
        const int bx0 = cards_center(banner_w) - banner_w / 2;
        if (x0 > bx0) { wt += x0 - bx0; x0 = bx0; }
        if (x0 + wt < bx0 + banner_w) wt = bx0 + banner_w - x0;
    }
    *a = x0 + shadow_ox; *b = cards_top + shadow_oy; *c = x0 + wt - 1 - shadow_ox;
    *d = cards_top + card_h + (label_gap >= 0 ? label_gap + label_h[0] : 0) + 14;      /* (label_gap < 0: no label) */
    if (*a > cx - 62) *a = cx - 62;                      /* wide enough for the hold bar */
    if (*c < cx + 62) *c = cx + 62;
    if (*d < cards_top + shadow_oy + shadow_h) *d = cards_top + shadow_oy + shadow_h;
}
static void draw_cards(int t_ms, int clip) {
    if (days < 0) return;
    const int level = lerp_i(256, 205, night_lvl), half = card_h / 2;
    if (banner_on && banner_img) {
        sprite(banner_img, banner_w, banner_h, cards_center(banner_w) - banner_w / 2, cards_top + (card_h - banner_h) / 2, level, clip);
        return;
    }
    int x0, wt; cards_layout(ndig, &x0, &wt);
    const int cx = x0 + wt / 2;                            /* (the label and the hold bar go under the row) */
    for (int k = 0; k < ndig; k++) sprite(shadow_img, shadow_w, shadow_h, card_x(x0, k) + shadow_ox, cards_top + shadow_oy, level, clip);
    if (split && colon_img) sprite(colon_img, colon_w, colon_h, card_x(x0, split) - cards_gap - colon_w,
                                   cards_top + (card_h - colon_h) / 2, level, clip);
    for (int k = 0; k < ndig; k++) {
        const int x = card_x(x0, k), hinge = cards_top + half, d = dig[k];
        const int el = flip_start[k] < 0 ? flip_ms : t_ms - flip_start[k];
        if (el >= flip_ms || el < 0) {
            sprite(card_top[d], card_w, half, x, cards_top, level, clip); sprite(card_bot[d], card_w, half, x, hinge, level, clip);
            continue;
        }
        const int od = old_dig[k], ph = el * (LUT / 2) / flip_ms;                 /* 0..half a turn */
        sprite(card_top[d], card_w, half, x, cards_top, level, 0);                 /* behind: the new top */
        sprite(card_bot[od], card_w, half, x, hinge, level, 0);                    /* and the old bottom */
        const int c = sin_lut[(ph + LUT / 4) & (LUT - 1)];                         /* cos: 1 .. -1 (Q14) */
        if (c > 0) flap(card_top[od], x, hinge, half * c >> 14, 1, level * (160 + (96 * c >> 14)) >> 8);   /* old top folding down */
        else flap(card_bot[d], x, hinge, half * -c >> 14, 0, level * (160 + (96 * -c >> 14)) >> 8);        /* new bottom falling */
    }
    const int lab = days == 1 ? 1 : 0;
    if (label_gap >= 0) sprite(label_img[lab], label_w[lab], label_h[lab], cx - label_w[lab] / 2, cards_top + card_h + label_gap, level, clip);
    /* press and hold: a thin bar fills under the label, and Settings opens when it's full */
    if (hold_lvl > 0) {
        const int bw = 120, by = cards_top + card_h + (label_gap >= 0 ? label_gap + label_h[lab] : 0) + 7, bx = cx - bw / 2, fill = bw * hold_lvl >> 8;
        for (int yy = by; yy < by + 3; yy++) for (int xx = bx; xx < bx + bw; xx++) {
            const uint32_t p = out[yy * W + xx]; const int on = xx < bx + fill;
            const int R = (p >> 16) & 255, G = (p >> 8) & 255, B = p & 255;
            out[yy * W + xx] = on ? 0xf4eede : (uint32_t)(R * 140 >> 8) << 16 | (uint32_t)(G * 140 >> 8) << 8 | (uint32_t)(B * 150 >> 8);
        }
        hold_drawn = 1;
    }
}

/* ------------------------------------------------------------------ API */
int vfx_open(const char *fbdev, const char *theme) {
    for (int i = 0; i < LUT; i++) {           /* sine table without libm: rotate a vector */
        static double s, c; if (i == 0) { s = 0; c = 1; }
        sin_lut[i] = (int16_t)(s * 16384 + (s >= 0 ? 0.5 : -0.5));
        const double a = 6.283185307179586 / LUT, ns = s + a * c - a * a / 2 * s, nc = c - a * s - a * a / 2 * c;
        const double n2 = ns * ns + nc * nc, f = (3 - n2) / 2; s = ns * f; c = nc * f;
    }
    for (int x = 0; x < W; x++) { xph1[x] = (uint16_t)(x * 21 * LUT / 6283); xph2[x] = (uint16_t)(x * 13 * LUT / 6283); }
    for (int t = 0; t < 4; t++) for (int v = 0; v < 256; v++) dlut[t][v] = (uint8_t)(((v > 252 ? 252 : v) + t) & 0xFC);
    k1 = (int)(0.37 / 6.283185 * LUT * 256); k2 = (int)(0.11 / 6.283185 * LUT * 256);
    w1 = (int)(2.3 / 6.283185 * LUT * 256 / 1000); w2 = (int)(1.6 / 6.283185 * LUT * 256 / 1000);
    for (int q = 0; q <= 256; q++) {
        prof_soft[q] = (uint8_t)(q >= 256 ? 0 : 255 - q * 200 / 256 - (q > 192 ? (q - 192) * 55 / 64 : 0));
        int r = 0; while ((r + 1) * (r + 1) <= q * 256) r++;            /* r = sqrt(q/256) in 0..256 */
        prof_puff[q] = (uint8_t)(r < 115 ? 255 - (255 - 140) * r / 115 : r < 256 ? 140 * (256 - r) / 141 : 0);
        prof_lin[q] = (uint8_t)(r >= 256 ? 0 : (256 - r) * 255 / 256);
    }
    /* images */
    snprintf(plate_dir, sizeof plate_dir, "%s", theme);
    for (int k = 0; k < 3; k++) {                       /* (each must be there and whole: checked now, kept if in use) */
        size_t n; uint8_t *p = gzload(theme, plate_names[k], &n);
        if (!p || n != W * H * 3) { fprintf(stderr, "vacfx: bad %s\n", plate_names[k]); free(p); return -1; }
        if (wgt[k]) plate[k] = p; else free(p);
    }
    /* the scene's mask: 1 where it isn't sky (the ship, the castle, trees...): no water there, and fireworks
       go behind it (mask.raw.gz; ship.raw.gz in scenes made before the castle) */
    char mp[600]; snprintf(mp, sizeof mp, "%s/mask.raw.gz", theme);
    size_t n; uint8_t *m = gzload(theme, access(mp, F_OK) == 0 ? "mask.raw.gz" : "ship.raw.gz", &n);
    if (!m || n != W * H) return -1;
    ship = m; for (int i = 0; i < W * H; i++) ship[i] = ship[i] > 127;
    uint8_t *lb = gzload(theme, "lights.bin.gz", &n);
    if (!lb || memcmp(lb, "VLT1", 4)) { fprintf(stderr, "vacfx: bad lights\n"); return -1; }
    memcpy(&nl, lb + 4, 4); memcpy(&ncell, lb + 8, 4);
    lidx = malloc((size_t)nl * 4); lcell = malloc((size_t)nl * 2); lrgb = malloc((size_t)nl * 3);
    memcpy(lidx, lb + 12, (size_t)nl * 4); memcpy(lcell, lb + 12 + (size_t)nl * 4, (size_t)nl * 2); memcpy(lrgb, lb + 12 + (size_t)nl * 6, (size_t)nl * 3);
    free(lb);
    { int k = 0; for (int y = 0; y <= H; y++) { while (k < nl && (int)(lidx[k] / W) < y) k++; row_start[y] = k; } }
    cell_first = calloc((size_t)ncell + 1, 4); cell_list = malloc((size_t)nl * 4);
    for (int k = 0; k < nl; k++) cell_first[lcell[k] + 1]++;
    for (int c = 0; c < ncell; c++) cell_first[c + 1] += cell_first[c];
    { uint32_t *fill = calloc((size_t)ncell, 4); for (int k = 0; k < nl; k++) cell_list[cell_first[lcell[k]] + fill[lcell[k]]++] = (uint32_t)k; free(fill); }
    cell_on = malloc((size_t)ncell); cell_lvl = malloc((size_t)ncell * 2);
    for (int c = 0; c < ncell; c++) { cell_on[c] = (rnd() % 100) < 62; cell_lvl[c] = cell_on[c] ? 256 : 0; }
    tw_load(theme);
    free(wcustom); wcustom = NULL;
    { char wp[600]; snprintf(wp, sizeof wp, "%s/water.raw.gz", theme);
      if (access(wp, F_OK) == 0) { size_t wn; uint8_t *w = gzload(theme, "water.raw.gz", &wn);
          if (w && wn == (size_t)W * H) wcustom = w; else { free(w); fprintf(stderr, "vacfx: bad water\n"); } } }
    uint8_t *cb = gzload(theme, "cards.bin.gz", &n);
    if (!cb || memcmp(cb, "VFC1", 4)) { fprintf(stderr, "vacfx: bad cards\n"); return -1; }
    { uint16_t v; memcpy(&v, cb + 4, 2); card_w = v; memcpy(&v, cb + 6, 2); card_h = v; }
    size_t o = 9; int16_t s16[2]; uint16_t u16[2];
    memcpy(s16, cb + o, 4); memcpy(u16, cb + o + 4, 4); o += 8;
    shadow_ox = s16[0]; shadow_oy = s16[1]; shadow_w = u16[0]; shadow_h = u16[1];
    shadow_img = cb + o; o += (size_t)shadow_w * shadow_h * 4;
    const size_t halfsz = (size_t)card_w * (card_h / 2) * 4;
    for (int d = 0; d < 10; d++) { card_top[d] = cb + o; o += halfsz; card_bot[d] = cb + o; o += halfsz; }
    for (int l = 0; l < 2; l++) { memcpy(u16, cb + o, 4); o += 4; label_w[l] = u16[0]; label_h[l] = u16[1]; label_img[l] = cb + o; o += (size_t)label_w[l] * label_h[l] * 4; }
    if (o > n) { fprintf(stderr, "vacfx: cards file too short\n"); return -1; }
    /* newer themes: the "Bon voyage!" banner and the last day's colon */
    if (o + 4 <= n) { memcpy(u16, cb + o, 4); o += 4; banner_w = u16[0]; banner_h = u16[1]; banner_img = cb + o; o += (size_t)banner_w * banner_h * 4; }
    if (o + 4 <= n) { memcpy(u16, cb + o, 4); o += 4; colon_w = u16[0]; colon_h = u16[1]; colon_img = cb + o; o += (size_t)colon_w * colon_h * 4; }
    if (o > n) { banner_img = colon_img = NULL; }
    /* the screen */
    fb_fd = open(fbdev, O_RDWR | O_CREAT, 0644); if (fb_fd < 0) { perror(fbdev); return -1; }
    struct stat st; fstat(fb_fd, &st);
#ifdef __linux__
    if (S_ISCHR(st.st_mode)) {
        struct fb_var_screeninfo v; struct fb_fix_screeninfo f;
        if (ioctl(fb_fd, FBIOGET_VSCREENINFO, &v) || ioctl(fb_fd, FBIOGET_FSCREENINFO, &f)) { perror("fb ioctl"); return -1; }
        if (v.xres != W || v.yres != H || v.bits_per_pixel != 32) { fprintf(stderr, "vacfx: need %dx%d at 32 bpp, have %ux%u at %u\n", W, H, v.xres, v.yres, v.bits_per_pixel); return -1; }
        fb_stride = (int)(f.line_length / 4); fb_len = f.line_length * H;
    } else
#endif
    { fb_len = W * H * 4; if (ftruncate(fb_fd, (off_t)fb_len)) { perror("ftruncate"); return -1; } }   /* a plain file: for testing on a desktop */
    fb = mmap(NULL, fb_len, PROT_READ | PROT_WRITE, MAP_SHARED, fb_fd, 0); if (fb == MAP_FAILED) { perror("mmap"); return -1; }
    base = malloc(W * H * 4); out = malloc(W * H * 4); wc = calloc(W * H, 1);
    if (!base || !out || !wc) { fprintf(stderr, "vacfx: out of memory\n"); return -1; }
    for (int y = 0; y < H; y++) { rlo[y] = nlo[y] = 1; rhi[y] = nhi[y] = 0; }
    memset(flip_start, 0xff, sizeof flip_start);
    return 0;
}

/* where the effects go (from theme.json); call after vfx_open */
void vfx_scene(int hz, int s1x, int s1y, int s2x, int s2y, int smoke_scale_q8, int fw_scale_q8, int bx, int by, int sx, int sy,
               int ccx, int ctop, int cgap, int lgap) {
    smoke_own = 0;
    horizon = hz; stack_x[0] = s1x; stack_y[0] = s1y; stack_x[1] = s2x; stack_y[1] = s2y; smoke_q8 = smoke_scale_q8; fw_q8 = fw_scale_q8;
    bow_x = bx; bow_y = by; stern_x = sx; stern_y = sy; cards_cx = ccx; cards_top = ctop; cards_gap = cgap; label_gap = lgap;
    int dx = sx - bx, dy = sy - by, len = 1; while ((len + 1) * (len + 1) <= dx * dx + dy * dy) len++;
    hull_dx = dx * 256 / len; hull_dy = dy * 256 / len;
    /* water below the horizon and off the ship; calm for 16 px under the waterline */
    memset(wc, 0, W * H);
    for (int x = 0; x < W; x++) {
        wl[x] = -1; for (int y = H - 1; y > horizon; y--) if (ship[y * W + x]) { wl[x] = (int16_t)y; break; }
        for (int y = horizon + 2; y < H && (fx_on & FX_WATER); y++) {
            if (ship[y * W + x]) continue;
            int v = 255;
            if (wl[x] >= 0 && y > wl[x] && y < wl[x] + 20) {
                const int d = y - wl[x]; v = d <= 2 ? 0 : d >= 16 ? 256 : ((d - 2) << 8) / 14;
                v = (v * v * (768 - 2 * v)) >> 16; v = clampi(v, 1, 255);
            }
            wc[y * W + x] = (uint8_t)v;
        }
    }
    if (wcustom) memcpy(wc, wcustom, W * H);                  /* (a scene's own water instead) */
    water_top = H;
    for (int y = 0; y < H; y++) {
        wx0[y] = wx1[y] = -1;
        for (int x = 0; x < W; x++) if (wc[y * W + x]) { if (wx0[y] < 0) wx0[y] = (int16_t)x; wx1[y] = (int16_t)x; }
        if (wx0[y] >= 0 && y < water_top) water_top = y;
    }
    reblend_row = 0; while (reblend_row < H) reblend_rows(H);
    memcpy(out, base, W * H * 4);
    full_redraw = 1; cards_dirty = 1;
}
/* a scene's own water: how strongly it ripples (256: about a pixel) and how fast (256: the sea's pace) */
void vfx_water(int strength_q8, int speed_q8) { water_amp_q8 = clampi(strength_q8, 0, 1024); water_speed_q8 = clampi(speed_q8, 16, 1024); }

/* time of day: plate weights (0..256 each, summing to 256), window lights, night and dusk amounts */
void vfx_light(int wday, int wdusk, int wnight, int lights, int night, int dusk) {
    lights = clampi(lights, 0, 256);
    if (wday == wgt[0] && wdusk == wgt[1] && wnight == wgt[2] && lights == lights_lvl && night == night_lvl && dusk == dusk_lvl) return;
    const int relight = wday != wgt[0] || wdusk != wgt[1] || wnight != wgt[2] || lights != lights_lvl;
    const int old[3] = {wgt[0], wgt[1], wgt[2]};
    wgt[0] = wday; wgt[1] = wdusk; wgt[2] = wnight; lights_lvl = lights; night_lvl = night; dusk_lvl = dusk;
    if (plates_for_weights()) { wgt[0] = old[0]; wgt[1] = old[1]; wgt[2] = old[2]; plates_for_weights(); }   /* (keep the light as it was) */
    if (relight) reblend_row = 0;              /* spread over the next frames */
    cards_dirty = 1;
}
void vfx_lights_rate(int per_minute) { toggles_per_min = per_minute; }
/* every window lit and holding still (1), or switching on and off again (0) */
void vfx_windows_hold(int on) {
    windows_hold = on;
    if (on && cell_on) for (int c = 1; c < ncell; c++) cell_on[c] = 1;
}
void vfx_redraw(void) { full_redraw = 1; }
/* the daytime touches' places: mast top, a size scale, and the AquaDuck tube as x,y pairs */
void vfx_ambient(int mx, int my, int scale_q8, int n, const int *xy) {
    mast_x = mx; mast_y = my; amb_q8 = scale_q8; ntube = n > 32 ? 32 : n;
    for (int k = 0; k < ntube; k++) { tube[k][0] = xy[2 * k]; tube[k][1] = xy[2 * k + 1]; }
    for (int k = 0; k < 3; k++) new_shadow(&shadows[k], rr(-100, W));
}
void vfx_hold(int level) { hold_lvl = clampi(level, 0, 256); }
/* which of the scene's own effects run: bits 1 sea, 2 wake and foam, 4 smoke, 8 gulls, 16 dolphins,
   32 the raft (all of them by default: the ship). Call before vfx_scene (the sea is set up there). */
void vfx_effects(int mask) { fx_on = mask & FX_ALL; }
/* darken what's on the screen (an instant "opening Settings": the Settings screen takes a few seconds) */
void vfx_dim(void) {
    for (int y = 0; y < H; y++) { uint32_t *r = fb + y * fb_stride; for (int x = 0; x < W; x++) r[x] = (r[x] >> 2) & 0x3f3f3f; }
}
/* for previews: 1 gulls, 2 dolphins, 3 the raft, now */
void vfx_demo(int what) { if (what == 1) { next_gulls_ms = 0; gulls_now = 1; } if (what == 2) next_pod_ms = 0; if (what == 3) { raft_start = -1; next_raft_ms = 0; } }

/* three digits on a scene that asks for it (theme.json cards.scale3; the castle's cards sit to one side
   and three of them would reach it): a smaller copy of the cards, made the first time it's needed */
static int scale3_q8, small_ready, using_small;
typedef struct { int w, h, sox, soy, sw, sh; uint8_t *top[10], *bot[10], *shadow; } cardset_t;
static cardset_t big_set, small_set;
static void save_set(cardset_t *c) {
    c->w = card_w; c->h = card_h; c->sox = shadow_ox; c->soy = shadow_oy; c->sw = shadow_w; c->sh = shadow_h; c->shadow = shadow_img;
    for (int d = 0; d < 10; d++) { c->top[d] = card_top[d]; c->bot[d] = card_bot[d]; }
}
static void load_set(const cardset_t *c) {
    card_w = c->w; card_h = c->h; shadow_ox = c->sox; shadow_oy = c->soy; shadow_w = c->sw; shadow_h = c->sh; shadow_img = c->shadow;
    for (int d = 0; d < 10; d++) { card_top[d] = c->top[d]; card_bot[d] = c->bot[d]; }
}
/* a premultiplied RGBA image, scaled (bilinear: fine for the gentle shrink this is) */
static uint8_t *scaled(const uint8_t *s, int sw, int sh, int dw, int dh) {
    uint8_t *d = malloc((size_t)dw * dh * 4); if (!d) return NULL;
    for (int y = 0; y < dh; y++) {
        double fy = (y + 0.5) * sh / dh - 0.5; if (fy < 0) fy = 0;
        int y0 = (int)fy; if (y0 > sh - 1) y0 = sh - 1; const int y1 = y0 + 1 < sh ? y0 + 1 : y0; const double ty = fy - y0;
        for (int x = 0; x < dw; x++) {
            double fx = (x + 0.5) * sw / dw - 0.5; if (fx < 0) fx = 0;
            int x0 = (int)fx; if (x0 > sw - 1) x0 = sw - 1; const int x1 = x0 + 1 < sw ? x0 + 1 : x0; const double tx = fx - x0;
            for (int ch = 0; ch < 4; ch++) {
                const double a = s[((size_t)y0 * sw + x0) * 4 + ch] * (1 - tx) + s[((size_t)y0 * sw + x1) * 4 + ch] * tx;
                const double b = s[((size_t)y1 * sw + x0) * 4 + ch] * (1 - tx) + s[((size_t)y1 * sw + x1) * 4 + ch] * tx;
                d[((size_t)y * dw + x) * 4 + ch] = (uint8_t)(a * (1 - ty) + b * ty + 0.5);
            }
        }
    }
    return d;
}
static void use_small_cards(int on) {
    if (!scale3_q8 || on == using_small) return;
    if (on && !small_ready) {
        save_set(&big_set);
        cardset_t *c = &small_set; const int q = scale3_q8, half = big_set.h / 2;
        c->w = big_set.w * q / 256; const int nh = half * q / 256; c->h = nh * 2;
        c->sox = big_set.sox * q / 256; c->soy = big_set.soy * q / 256; c->sw = big_set.sw * q / 256; c->sh = big_set.sh * q / 256;
        int ok = c->w > 8 && nh > 4 && (c->shadow = scaled(big_set.shadow, big_set.sw, big_set.sh, c->sw, c->sh)) != NULL;
        for (int d = 0; ok && d < 10; d++)
            ok = (c->top[d] = scaled(big_set.top[d], big_set.w, half, c->w, nh)) && (c->bot[d] = scaled(big_set.bot[d], big_set.w, half, c->w, nh));
        if (!ok) { fprintf(stderr, "vacfx: no memory for the smaller cards\n"); scale3_q8 = 0; return; }   /* (the big ones, then) */
        small_ready = 1;
    }
    load_set(on ? &small_set : &big_set); using_small = on;
}
void vfx_cards_scale3(int q8) { scale3_q8 = clampi(q8, 0, 256); }

/* a scene's own foam: n points (x, y, radius triples, up to 16), how much (amount_q8: 256 normal), which way
   (flow: 0 churning in place, 1 drifting left, 2 right, 3 falling, with spray, 4 spreading toward the viewer) */
void vfx_foam(int n, const int *xyr, int amount_q8, int flow) {
    foam_n = clampi(n, 0, 16);
    for (int k = 0; k < foam_n; k++) { foam_xyr[k][0] = xyr[3 * k]; foam_xyr[k][1] = xyr[3 * k + 1]; foam_xyr[k][2] = clampi(xyr[3 * k + 2], 1, 80); }
    foam_amount_q8 = clampi(amount_q8, 32, 1024); foam_flow = clampi(flow, 0, 4);
}

/* a scene's own smoke (instead of the ship's two funnels, which vfx_scene sets): n sources at xy (x, y
   pairs, up to 8), how big (scale_q8: 256 the funnels' size), the wind (-256 blowing left, 0 still: it
   rises, wavering, 256 right), puffs a second from each (the funnels: 6), how dense (256: the funnels', faint
   at their distance). After vfx_scene. */
void vfx_smoke(int n, const int *xy, int scale_q8, int wind_q8, int rate, int density_q8) {
    smoke_dense_q8 = clampi(density_q8, 64, 1024);           /* (how opaque: the funnels' 256; a campfire close by, more) */
    smoke_n = clampi(n, 0, 8); smoke_own = 1;
    for (int k = 0; k < smoke_n; k++) { stack_x[k] = xy[2 * k]; stack_y[k] = xy[2 * k + 1]; }
    smoke_q8 = clampi(scale_q8, 40, 768); smoke_wind_q8 = clampi(wind_q8, -256, 256); smoke_rate = clampi(rate, 1, 30);
}

/* the countdown's size (theme.json cards.scale, 0.4 to 1.3 of the cards as drawn): the cards, their shadow
   and the last day's colon, scaled once (the three-digit size, scale3, then applies to these). Called
   after vfx_open; again with another size, the earlier copies are freed and made afresh. */
static int scale_q8 = 256, orig_saved, colon_ow, colon_oh, big_owned;
static cardset_t orig_set; static uint8_t *colon_orig;
static void free_set(cardset_t *c) { free(c->shadow); c->shadow = NULL; for (int d = 0; d < 10; d++) { free(c->top[d]); free(c->bot[d]); c->top[d] = c->bot[d] = NULL; } }
void vfx_cards_scale(int q8) {
    q8 = clampi(q8, 102, 333);
    if (q8 == scale_q8) return;                                         /* (that size already) */
    if (!orig_saved) { if (using_small) load_set(&big_set); save_set(&orig_set); colon_orig = colon_img; colon_ow = colon_w; colon_oh = colon_h; orig_saved = 1; }
    if (small_ready) { free_set(&small_set); small_ready = 0; }      /* (the three-digit copy: made again from the new size) */
    if (using_small) using_small = 0;
    if (big_owned) { free_set(&big_set); if (colon_img != colon_orig) free(colon_img); big_owned = 0; }
    if (q8 == 256) { big_set = orig_set; colon_img = colon_orig; colon_w = colon_ow; colon_h = colon_oh; }
    else {
        cardset_t *c = &big_set; const int half = orig_set.h / 2, nh = half * q8 / 256;
        c->w = orig_set.w * q8 / 256; c->h = nh * 2;
        c->sox = orig_set.sox * q8 / 256; c->soy = orig_set.soy * q8 / 256; c->sw = orig_set.sw * q8 / 256; c->sh = orig_set.sh * q8 / 256;
        int ok = c->w > 8 && nh > 4 && (c->shadow = scaled(orig_set.shadow, orig_set.sw, orig_set.sh, c->sw, c->sh)) != NULL;
        for (int d = 0; ok && d < 10; d++)
            ok = (c->top[d] = scaled(orig_set.top[d], orig_set.w, half, c->w, nh)) && (c->bot[d] = scaled(orig_set.bot[d], orig_set.w, half, c->w, nh));
        if (ok && colon_orig) {
            colon_w = colon_ow * q8 / 256; colon_h = colon_oh * q8 / 256;
            colon_img = colon_w > 0 && colon_h > 0 ? scaled(colon_orig, colon_ow, colon_oh, colon_w, colon_h) : NULL;
            ok = colon_img != NULL;
        }
        if (!ok) {                                                     /* (no memory: the cards as drawn) */
            fprintf(stderr, "vacfx: no memory for the countdown at that size\n");
            free_set(c); big_set = orig_set; colon_img = colon_orig; colon_w = colon_ow; colon_h = colon_oh; q8 = 256;
        } else big_owned = 1;
    }
    load_set(&big_set); scale_q8 = q8; cards_dirty = 1; full_redraw = 1;
}

/* the cards show value as n digits (with a colon before digit sp, if sp); flip: animate the ones that change */
static void set_cards(int value, int n, int sp, int flip, int t_ms) {
    int nd[4]; for (int k = n - 1, v = value; k >= 0; k--, v /= 10) nd[k] = v % 10;
    if (days >= 0) { int a, b, c, e; cards_rect_s(ndig, split, &a, &b, &c, &e); rect_add(rlo, rhi, a, b, c, e); }   /* old footprint */
    use_small_cards(n == 3 && !sp);
    const int same_shape = n == ndig && sp == split;
    old_ndig = ndig; old_split = split; memcpy(old_dig, dig, sizeof dig);
    for (int k = 0; k < n; k++) {
        const int ok = same_shape ? k : sp ? -1 : k - (n - old_ndig);   /* the same place value before */
        const int od = (days >= 0 && ok >= 0 && ok < old_ndig) ? old_dig[ok] : (nd[k] + 1) % 10;
        old_dig[k] = od;
        flip_start[k] = (flip && od != nd[k]) ? t_ms + (n - 1 - k) * 90 : -1;
    }
    memcpy(dig, nd, sizeof nd); ndig = n; split = sp; days = value; banner_on = 0; cards_dirty = 1;
}
/* the countdown in days */
void vfx_days(int d, int flip, int t_ms) {
    d = clampi(d, 0, 9999);
    if (d == days && !flip && !split && !banner_on) return;
    set_cards(d, d >= 1000 ? 4 : d >= 100 ? 3 : 2, 0, flip, t_ms);
}
/* the last day: hours and minutes, HH:MM */
void vfx_clock(int hh, int mm, int flip, int t_ms) {
    hh = clampi(hh, 0, 99); mm = clampi(mm, 0, 59);
    if (split && hh * 100 + mm == days && !flip && !banner_on) return;
    set_cards(hh * 100 + mm, 4, 2, flip, t_ms);
}
/* sailing: "Bon voyage!" in place of the cards (if the theme has it) */
void vfx_banner(int on) {
    if (!banner_img || (on != 0) == banner_on) return;
    int a, b, c, e; cards_rect(ndig, &a, &b, &c, &e); rect_add(rlo, rhi, a, b, c, e);
    banner_on = on != 0; if (days < 0) days = 0; cards_dirty = 1;
}
void vfx_fireworks(int rockets) { rocket_gap_min = 300; rocket_gap_max = 550; rockets_pending += rockets; if (next_rocket_ms > 200) next_rocket_ms = 0; }

/* one frame; returns the time spent, in microseconds */
static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }
int vfx_frame(int t_ms) {
    const double t0 = now_s();
    int dt = last_t < 0 ? 40 : t_ms - last_t; dt = clampi(dt, 0, 200); last_t = t_ms; frame_no++;
    /* last frame's particle footprints become this frame's refresh */
    for (int y = 0; y < H; y++) { rlo[y] = nlo[y]; rhi[y] = nhi[y]; nlo[y] = 1; nhi[y] = 0; }
    if (full_redraw) { for (int y = 0; y < H; y++) { rlo[y] = 0; rhi[y] = W - 1; } full_redraw = 0; }
    /* time of day: a few rows of re-blending per frame */
    double ts = now_s();
    reblend_rows(40);
    /* windows switching on and off, easing */
    toggle_acc = ncell > 1 && !windows_hold ? toggle_acc + dt * toggles_per_min : 0;              /* (a scene with no windows: none to switch) */
    while (toggle_acc >= 60000) { toggle_acc -= 60000; const int c = 1 + (int)(rnd() % (uint32_t)(ncell - 1)); cell_on[c] ^= 1; }
    const int rate = clampi(dt * 8 * 256 / 1000, 1, 256);
    for (int c = 1; c < ncell; c++) {
        const int tg = cell_on[c] ? 256 : 0, lv = cell_lvl[c];
        if (lv == tg) continue;
        int nv = lv + (tg - lv) * rate / 256; if (nv == lv) nv += tg > lv ? 1 : -1;
        if ((tg - nv) * (tg - lv) <= 0 || (nv - tg < 3 && tg - nv < 3)) nv = tg;
        cell_lvl[c] = (int16_t)nv;
        if (lights_lvl) relight_cell(c);
    }
    /* the sea, staggered: near rows every 2nd frame, the middle third every 3rd, the far third every 4th
       (the ripple moves well under a pixel in that time) */
    for (int y = water_top; y < H && (fx_on & FX_WATER); y++) {
        if (wx0[y] < 0) continue;
        const int depth_q8 = wcustom ? 255 : ((y - horizon) << 8) / (H - horizon), every = depth_q8 < 85 ? 4 : depth_q8 < 170 ? 3 : 2;
        if ((y + frame_no) % every == 0) spans_add(rlo, rhi, y, wx0[y], wx1[y]);
    }
    /* cards: while flipping (or after a change), their whole area */
    int flipping = 0; for (int k = 0; k < ndig; k++) if (flip_start[k] >= 0 && t_ms - flip_start[k] < flip_ms + 40) flipping = 1;
    if (hold_lvl > 0 || hold_drawn) { cards_dirty = 1; if (!hold_lvl) hold_drawn = 0; }
    if ((cards_dirty || flipping) && days >= 0) { int a, b, c, e; cards_rect(ndig, &a, &b, &c, &e); rect_add(rlo, rhi, a, b, c, e); cards_dirty = 0; }
    st_acc[0] += now_s() - ts; ts = now_s();
    /* particles: move, then claim where they'll be drawn */
    step_particles(dt);
    particle_rects();
    ambient_rects();
    /* rebuild, draw, show */
    for (int y = 0; y < H; y++) if (rlo[y] <= rhi[y]) refresh_row(y, rlo[y], rhi[y], t_ms, out + y * W);
    st_acc[1] += now_s() - ts; ts = now_s();
    draw_twinkle();
    draw_particles();
    draw_ambient();
    st_acc[2] += now_s() - ts; ts = now_s();
    draw_cards(t_ms, 1);
    st_acc[3] += now_s() - ts; ts = now_s();
    for (int y = 0; y < H; y++) {
        int a = rlo[y], b = rhi[y];
        if (nlo[y] <= nhi[y]) { if (a > b || nlo[y] < a) a = nlo[y]; if (a > b || nhi[y] > b) b = nhi[y]; }
        if (a <= b) copy_out(y, a, b);
    }
    st_acc[4] += now_s() - ts; st_acc[5] += now_s() - t0; st_frames++;
    return (int)((now_s() - t0) * 1e6);
}
/* ------------------------------------------------------------------ Settings pages
   Text and arrows come pre-drawn (tools/themegen/build_ui.py: alpha images with offsets and advances);
   panels and buttons are rounded rectangles drawn here. Everything goes into `out` (the countdown is
   paused meanwhile) and vfx_ui_flush() sends what changed to the screen. */
typedef struct { char name[64]; int w, h, ox, oy, adv; const uint8_t *a; } uiimg_t;
static uiimg_t *ui; static int nui; static uint8_t *ui_blob, *ui_bg;
static int16_t ulo[H], uhi[H];
int vfx_ui_open_bg(const char *ui_dir, const char *bg_dir, const char *bg_name);
void vfx_ui_close(void);
int vfx_ui_open(const char *ui_dir, const char *theme_dir) { return vfx_ui_open_bg(ui_dir, theme_dir, "settings_bg.rgb.gz"); }
/* with another 800x480 RGB background (the fleet map's chart) */
static int ui_load(const char *ui_dir) {
    size_t n; ui_blob = gzload(ui_dir, "ui.bin.gz", &n);
    if (!ui_blob || memcmp(ui_blob, "VUI1", 4)) { fprintf(stderr, "vacfx: bad ui.bin.gz\n"); return -1; }
    uint16_t cnt; memcpy(&cnt, ui_blob + 4, 2); nui = cnt; ui = calloc((size_t)nui, sizeof *ui);
    size_t o = 6;
    for (int k = 0; k < nui; k++) {
        memcpy(ui[k].name, ui_blob + o, 63); o += 64;
        uint16_t wh[2]; int16_t m[3]; memcpy(wh, ui_blob + o, 4); memcpy(m, ui_blob + o + 4, 6); o += 10;
        ui[k].w = wh[0]; ui[k].h = wh[1]; ui[k].ox = m[0]; ui[k].oy = m[1]; ui[k].adv = m[2]; ui[k].a = ui_blob + o;
        o += (size_t)wh[0] * wh[1];
        if (o > n) { fprintf(stderr, "vacfx: ui.bin.gz too short\n"); return -1; }
    }
    for (int y = 0; y < H; y++) { ulo[y] = 1; uhi[y] = 0; }
    return 0;
}
/* The background lives in the countdown's blended picture (base: W*H*4 bytes, more than the W*H*3
   needed), which isn't used meanwhile and is blended again when the page closes: memory is tight. */
int vfx_ui_open_bg(const char *ui_dir, const char *bg_dir, const char *bg_name) {
    if (ui_load(ui_dir)) return -1;
    ui_bg = (uint8_t *)base;
    if (gzload_into(bg_dir, bg_name, ui_bg, W * H * 3)) {
        fprintf(stderr, "vacfx: bad %s\n", bg_name); vfx_ui_close(); return -1;
    }
    return 0;
}
/* with a background put together from pieces (the fleet map's tiles): starts black */
int vfx_ui_open_blank(const char *ui_dir) {
    if (ui_load(ui_dir)) return -1;
    ui_bg = (uint8_t *)base; memset(ui_bg, 0, W * H * 3); return 0;
}
/* fill part of the background with one colour */
void vfx_ui_bg_fill(int x0, int y0, int x1, int y1, int rgb) {
    if (!ui_bg) return;
    x0 = clampi(x0, 0, W); x1 = clampi(x1, 0, W); y0 = clampi(y0, 0, H); y1 = clampi(y1, 0, H);
    for (int y = y0; y < y1; y++) for (int x = x0; x < x1; x++) {
        uint8_t *p = ui_bg + (y * W + x) * 3; p[0] = (uint8_t)(rgb >> 16); p[1] = (uint8_t)(rgb >> 8); p[2] = (uint8_t)rgb;
    }
}
/* a gzipped tw x th RGB image (dir/name) into the background at (x, y), clipped; 0 when done */
int vfx_ui_bg_tile(const char *dir, const char *name, int x, int y, int tw, int th) {
    if (!ui_bg) return -1;
    uint8_t *t = malloc((size_t)tw * th * 3);
    if (!t || gzload_into(dir, name, t, (size_t)tw * th * 3)) { free(t); return -1; }
    for (int r = 0; r < th; r++) {
        const int yy = y + r; if (yy < 0 || yy >= H) continue;
        const int c0 = x < 0 ? -x : 0, c1 = x + tw > W ? W - x : tw; if (c1 <= c0) continue;
        memcpy(ui_bg + (yy * W + x + c0) * 3, t + (r * tw + c0) * 3, (size_t)(c1 - c0) * 3);
    }
    free(t); return 0;
}
/* what's been drawn so far becomes part of the background (things vfx_ui_bg restores: the map's
   trail and route, under the ships) */
void vfx_ui_bake(void) {
    if (!ui_bg) return;
    for (int i = 0; i < W * H; i++) { const uint32_t p = out[i]; uint8_t *b = ui_bg + i * 3; b[0] = (uint8_t)(p >> 16); b[1] = (uint8_t)(p >> 8); b[2] = (uint8_t)p; }
}
/* darken (blend toward rgb) rows y0..y1 of the background, alpha a0 at y0 fading to a1 at y1 */
void vfx_ui_bg_band(int y0, int y1, int rgb, int a0, int a1) {
    if (!ui_bg || y1 <= y0) return;
    const int R = (rgb >> 16) & 255, G = (rgb >> 8) & 255, B = rgb & 255;
    for (int y = clampi(y0, 0, H); y < clampi(y1, 0, H); y++) {
        const int a = a0 + (a1 - a0) * (y - y0) / (y1 - y0);
        for (int x = 0; x < W; x++) {
            uint8_t *p = ui_bg + (y * W + x) * 3;
            p[0] = (uint8_t)(p[0] + ((R - p[0]) * a >> 8)); p[1] = (uint8_t)(p[1] + ((G - p[1]) * a >> 8)); p[2] = (uint8_t)(p[2] + ((B - p[2]) * a >> 8));
        }
    }
}
int vfx_ui_find(const char *name) { for (int k = 0; k < nui; k++) if (!strcmp(ui[k].name, name)) return k; return -1; }
int vfx_ui_metric(int id, int what) {
    if (id < 0 || id >= nui) return 0;
    const uiimg_t *u = &ui[id]; return what == 0 ? u->w : what == 1 ? u->h : what == 2 ? u->ox : what == 3 ? u->oy : u->adv;
}
static void ui_dirty(int x0, int y0, int x1, int y1) { rect_add(ulo, uhi, x0, y0, x1 - 1, y1 - 1); }
/* the blurred photo behind Settings, scaled by shade (256 = as it is) */
void vfx_ui_bg(int x0, int y0, int x1, int y1, int shade) {
    x0 = clampi(x0, 0, W); x1 = clampi(x1, 0, W); y0 = clampi(y0, 0, H); y1 = clampi(y1, 0, H);
    for (int y = y0; y < y1; y++) for (int x = x0; x < x1; x++) {
        const uint8_t *p = ui_bg + (y * W + x) * 3;
        out[y * W + x] = (uint32_t)(p[0] * shade >> 8) << 16 | (uint32_t)(p[1] * shade >> 8) << 8 | (uint32_t)(p[2] * shade >> 8);
    }
    ui_dirty(x0, y0, x1, y1);
}
static int isqrt(int v) { int r = 0, b = 1 << 30;      /* (any non-negative int) */ while (b > v) b >>= 2; while (b) { if (v >= r + b) { v -= r + b; r = (r >> 1) + b; } else r >>= 1; b >>= 2; } return r; }
/* how much of pixel (x, y) is inside the rounded rectangle, 0..256 (antialiased corners) */
static int rr_cover(int x, int y, int x0, int y0, int x1, int y1, int r) {
    if (x < x0 || x >= x1 || y < y0 || y >= y1) return 0;
    const int cx = x < x0 + r ? x0 + r : x >= x1 - r ? x1 - r : -1, cy = y < y0 + r ? y0 + r : y >= y1 - r ? y1 - r : -1;
    if (cx < 0 || cy < 0 || r <= 0) return 256;
    const int dx = (x * 16 + 8) - cx * 16, dy = (y * 16 + 8) - cy * 16, d = isqrt(dx * dx + dy * dy);   /* 1/16 px */
    return clampi((r * 16 - d + 8) * 16, 0, 256);
}
static inline void ui_blend(uint32_t *d, int rgb, int a) {
    const uint32_t p = *d; const int R = (p >> 16) & 255, G = (p >> 8) & 255, B = p & 255;
    *d = (uint32_t)(R + ((((rgb >> 16) & 255) - R) * a >> 8)) << 16 | (uint32_t)(G + ((((rgb >> 8) & 255) - G) * a >> 8)) << 8 | (uint32_t)(B + (((rgb & 255) - B) * a >> 8));
}
/* a rounded rectangle: fill (alpha 0..255) and a 1-px outline (line_alpha 0 = none); x1, y1 exclusive */
void vfx_ui_round(int x0, int y0, int x1, int y1, int r, int rgb, int alpha, int line_rgb, int line_alpha) {
    for (int y = clampi(y0, 0, H); y < clampi(y1, 0, H); y++) for (int x = clampi(x0, 0, W); x < clampi(x1, 0, W); x++) {
        const int outer = rr_cover(x, y, x0, y0, x1, y1, r), inner = line_alpha ? rr_cover(x, y, x0 + 1, y0 + 1, x1 - 1, y1 - 1, r - 1) : outer;
        if (inner && alpha) ui_blend(out + y * W + x, rgb, inner * alpha >> 8);
        if (outer > inner) ui_blend(out + y * W + x, line_rgb, (outer - inner) * line_alpha >> 8);
    }
    ui_dirty(x0, y0, x1, y1);
}
/* a pre-drawn image in a colour: text at a pen position on the baseline (its offsets apply), alpha 0..255 */
void vfx_ui_text(int id, int pen_x, int base_y, int rgb, int alpha) {
    if (id < 0 || id >= nui) return;
    const uiimg_t *u = &ui[id]; const int x0 = pen_x + u->ox, y0 = base_y + u->oy;
    for (int r = 0; r < u->h; r++) {
        const int y = y0 + r; if (y < 0 || y >= H) continue;
        for (int c = 0; c < u->w; c++) {
            const int x = x0 + c; if (x < 0 || x >= W) continue;
            const int a = u->a[r * u->w + c] * alpha / 255; if (a) ui_blend(out + y * W + x, rgb, a);
        }
    }
    ui_dirty(x0, y0, x0 + u->w, y0 + u->h);
}
/* a smooth line of width w with round ends (w = 0..: a dot), coordinates in 1/16 px; alpha 0..255 */
void vfx_ui_line(int ax, int ay, int bx, int by, int w, int rgb, int alpha) {
    const int r = w / 2, x0 = (ax < bx ? ax : bx) - r - 16, x1 = (ax > bx ? ax : bx) + r + 16, y0 = (ay < by ? ay : by) - r - 16, y1 = (ay > by ? ay : by) + r + 16;
    const int64_t dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    for (int py = clampi(y0 >> 4, 0, H - 1); py <= clampi(y1 >> 4, 0, H - 1); py++)
        for (int px = clampi(x0 >> 4, 0, W - 1); px <= clampi(x1 >> 4, 0, W - 1); px++) {
            const int64_t qx = px * 16 + 8 - ax, qy = py * 16 + 8 - ay;
            int64_t t = len2 ? (qx * dx + qy * dy) * 256 / len2 : 0; if (t < 0) t = 0; if (t > 256) t = 256;
            const int64_t ex = qx - dx * t / 256, ey = qy - dy * t / 256;
            const int d = isqrt((int)(ex * ex + ey * ey)), cov = clampi((r - d + 8) * 16, 0, 256);
            if (cov) ui_blend(out + py * W + px, rgb, cov * alpha >> 8);
        }
    ui_dirty(x0 >> 4, y0 >> 4, (x1 >> 4) + 1, (y1 >> 4) + 1);
}
/* a ring: radius r and width w, in 1/16 px */
void vfx_ui_ring(int cx, int cy, int r, int w, int rgb, int alpha) {
    const int x0 = (cx - r - w) >> 4, x1 = (cx + r + w) >> 4, y0 = (cy - r - w) >> 4, y1 = (cy + r + w) >> 4;
    for (int py = clampi(y0, 0, H - 1); py <= clampi(y1, 0, H - 1); py++)
        for (int px = clampi(x0, 0, W - 1); px <= clampi(x1, 0, W - 1); px++) {
            const int qx = px * 16 + 8 - cx, qy = py * 16 + 8 - cy, d = isqrt(qx * qx + qy * qy);
            const int cov = clampi((w / 2 - abs(d - r) + 8) * 16, 0, 256);
            if (cov) ui_blend(out + py * W + px, rgb, cov * alpha >> 8);
        }
    ui_dirty(x0, y0, x1 + 1, y1 + 1);
}
void vfx_ui_flush(void) {
    for (int y = 0; y < H; y++) if (ulo[y] <= uhi[y]) { copy_out(y, ulo[y], uhi[y]); ulo[y] = 1; uhi[y] = 0; }
}
void vfx_ui_close(void) {
    free(ui); free(ui_blob); ui = NULL; ui_blob = ui_bg = NULL; nui = 0;
    reblend_row = 0; reblend_rows(H);                      /* the picture back where the page was */
    full_redraw = 1; cards_dirty = 1;
}
void vfx_dither(int on) { dither_on = on; full_redraw = 1; }
/* fade the whole screen: 0 black .. 256 as it is; resends everything at that brightness (anything
   drawn meanwhile goes out at it too, so a page can be drawn in the dark and faded in) */
void vfx_fade(int level) {
    fade_lvl = clampi(level, 0, 256);
    for (int v = 0; v < 256; v++) flut[v] = (uint8_t)(v * fade_lvl >> 8);
    for (int y = 0; y < H; y++) copy_out(y, 0, W - 1);
}
/* fireworks: n rockets, launched gap_min..gap_max ms apart (the nightly show's finale is quick) */
void vfx_fireworks_gap(int n, int gap_min, int gap_max) { rocket_gap_min = gap_min; rocket_gap_max = gap_max; rockets_pending += n; if (next_rocket_ms > gap_max) next_rocket_ms = 0; }

/* average ms per stage since the last call: "base sea particles cards copy total (n particles)" */
const char *vfx_stats(void) {
    static char buf[160]; const double n = st_frames ? st_frames : 1;
    snprintf(buf, sizeof buf, "base %.1f, sea %.1f, particles %.1f, cards %.1f, copy %.1f, total %.1f ms (%d particles)",
             st_acc[0] / n * 1e3, st_acc[1] / n * 1e3, st_acc[2] / n * 1e3, st_acc[3] / n * 1e3, st_acc[4] / n * 1e3, st_acc[5] / n * 1e3, np);
    memset(st_acc, 0, sizeof st_acc); st_frames = 0; return buf;
}

/* a fixed piece of work whose result never changes: a different answer means the CPU is making
   mistakes (for checking an overclock while the app runs) */
unsigned vfx_selftest(void) {
    uint32_t sum = 0;
    for (int i = 0; i < W * H; i += 7) {
        const uint8_t p[3] = {(uint8_t)(i * 7), (uint8_t)(i >> 3), (uint8_t)(i * 13 >> 2)};   /* (fixed data: the plates come and go) */
        const uint32_t v = (uint32_t)(p[0] * sin_lut[(i + p[1]) & (LUT - 1)] + p[2] * prof_puff[p[1]]) ^ (uint32_t)(i * 2654435761u);
        sum = (sum * 31 + v) ^ (sum >> 7);
    }
    return sum;
}
int vfx_particles(void) { return np; }

void vfx_close(void) {
    tw_free(); free(wcustom); wcustom = NULL;
    if (fb && fb != MAP_FAILED) munmap(fb, fb_len);
    if (fb_fd >= 0) close(fb_fd);
    fb = NULL; fb_fd = -1;
}
