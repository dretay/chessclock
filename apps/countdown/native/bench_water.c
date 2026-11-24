/*
 * Speed test for the countdown's water ripple in C, on the board.
 *
 *   bench_water PLATE.rgb MASK.raw HORIZON [SECONDS]
 *
 * PLATE.rgb  800x480 raw RGB (3 bytes a pixel), e.g. the day plate
 * MASK.raw   800x480 raw bytes, nonzero = ship (the water never moves under it)
 *
 * Draws the plate, then:
 *   1. times 60 frames of the ripple as fast as it can (bilinear, and nearest for comparison)
 *   2. times blending two full plates (the time-of-day crossfade)
 *   3. animates the ripple at up to 30 fps for SECONDS (default 8) so it can be seen on the panel
 *
 * The ripple is the mockup's: two travelling sine waves, stronger toward the bottom of the
 * screen, horizontal sub-pixel shift plus a small whole-row vertical one, calm right under the
 * hull. All integer arithmetic: the ARM926 has no floating-point unit.
 */
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define W 800
#define H 480
#define LUT 1024                     /* sine table entries per turn */

static int16_t sin_lut[LUT];         /* Q14 */
static int16_t sinX[W], cosX[W], sinX2[W], cosX2[W];   /* Q14 */
static uint16_t xph1[W], xph2[W];    /* x*0.021 and x*0.013 rad, in 1/LUT turns: wave value = sin(row phase + this) */
static uint32_t *plate, *plate2, *blend_out;
static uint8_t *water, *calm;        /* calm: 0..256 scale on the wave amplitude, Q8 */
static int horizon;

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }

/* phase in 1/LUT turns */
static inline int isin(int ph) { return sin_lut[ph & (LUT - 1)]; }
static inline int icos(int ph) { return sin_lut[(ph + LUT / 4) & (LUT - 1)]; }

static void *load(const char *path, size_t n) {
    FILE *f = fopen(path, "rb"); if (!f) { perror(path); exit(1); }
    void *p = malloc(n); if (fread(p, 1, n, f) != n) { fprintf(stderr, "%s: short read\n", path); exit(1); }
    fclose(f); return p;
}

/* one frame of the ripple into the framebuffer. t_ms: time in ms. bilinear: sub-pixel or nearest */
static void ripple(uint32_t *fb, int stride_px, int t_ms, int bilinear) {
    const int hz = horizon;
    /* phases: y*0.37 + t*2.3 rad and y*0.11 - t*1.6 rad, in 1/LUT turns */
    const int k1 = (int)(0.37 / (2 * M_PI) * LUT * 256), k2 = (int)(0.11 / (2 * M_PI) * LUT * 256);   /* Q8 per row */
    const int w1 = (int)(2.3 / (2 * M_PI) * LUT * 256 / 1000), w2 = (int)(1.6 / (2 * M_PI) * LUT * 256 / 1000);  /* Q8 per ms */
    for (int y = hz + 2; y < H; y++) {
        const int depth_q8 = ((y - hz) << 8) / (H - hz);
        const int amp_q8 = 90 + ((614 * depth_q8) >> 8);           /* (0.35 + 2.4*depth) in Q8 */
        const int ph1 = (y * k1 + t_ms * w1) >> 8, ph2 = (y * k2 - t_ms * w2) >> 8;
        const int sa = isin(ph1), ca = icos(ph1), sb = isin(ph2), cb = icos(ph2);
        const uint8_t *wrow = water + y * W, *crow = calm + y * W;
        uint32_t *out = fb + y * stride_px;
        for (int x = 0; x < W; x++) {
            if (!wrow[x]) continue;                                 /* the ship: already on screen */
            const int am = (amp_q8 * crow[x]) >> 8;                 /* Q8 px */
            const int d1 = (sa * cosX[x] + ca * sinX[x]) >> 14;     /* Q14 */
            const int d2 = (sb * cosX2[x] + cb * sinX2[x]) >> 14;
            int fx = (x << 8) + ((am * d1) >> 14);                  /* Q8 */
            int yy = y + ((((am * 115) >> 8) * d2 + (1 << 21)) >> 22); /* 0.45*am, rounded to whole rows */
            if (fx < 0) fx = 0; else if (fx > (W - 2) << 8) fx = (W - 2) << 8;
            if (yy <= hz + 1) yy = hz + 2; else if (yy > H - 1) yy = H - 1;
            const int x0 = fx >> 8, j0 = yy * W + x0;
            uint32_t px;
            if (water[j0] && water[j0 + 1]) {
                const uint32_t a = plate[j0];
                if (bilinear) {
                    const uint32_t b = plate[j0 + 1], f = fx & 255, g = 256 - f;
                    const uint32_t rb = (((a & 0xff00ff) * g + (b & 0xff00ff) * f) >> 8) & 0xff00ff;
                    const uint32_t gg = (((a & 0x00ff00) * g + (b & 0x00ff00) * f) >> 8) & 0x00ff00;
                    px = rb | gg;
                } else px = a;
            } else px = plate[y * W + x];
            out[x] = px;
        }
    }
}

/* faster version: each wave is one table lookup, sin(row phase + x phase), instead of two multiplies;
   the row is built in ordinary (cached) memory and copied to the screen in one burst */
static void ripple2(uint32_t *fb, int stride_px, int t_ms) {
    static uint32_t row[W];
    const int hz = horizon;
    const int k1 = (int)(0.37 / (2 * M_PI) * LUT * 256), k2 = (int)(0.11 / (2 * M_PI) * LUT * 256);
    const int w1 = (int)(2.3 / (2 * M_PI) * LUT * 256 / 1000), w2 = (int)(1.6 / (2 * M_PI) * LUT * 256 / 1000);
    for (int y = hz + 2; y < H; y++) {
        const int depth_q8 = ((y - hz) << 8) / (H - hz);
        const int amp_q8 = 90 + ((614 * depth_q8) >> 8);
        const int ph1 = (y * k1 + t_ms * w1) >> 8, ph2 = (y * k2 - t_ms * w2) >> 8;
        const int amy = (amp_q8 * 115) >> 8;                    /* vertical: 0.45 of it */
        const uint8_t *wrow = water + y * W, *crow = calm + y * W;
        const uint32_t *prow = plate + y * W;
        int first = -1, last = -1;
        for (int x = 0; x < W; x++) {
            if (!wrow[x]) continue;
            if (first < 0) first = x;
            last = x;
            const int c = crow[x];
            const int s1 = sin_lut[(ph1 + xph1[x]) & (LUT - 1)], s2 = sin_lut[(ph2 + xph2[x]) & (LUT - 1)];
            int fx = (x << 8) + ((((amp_q8 * c) >> 8) * s1) >> 14);
            int dy = ((((amy * c) >> 8) * s2) + (1 << 21)) >> 22;
            if (fx < 0) fx = 0; else if (fx > (W - 2) << 8) fx = (W - 2) << 8;
            int yy = y + dy;
            if (yy <= hz + 1) yy = hz + 2; else if (yy > H - 1) yy = H - 1;
            const int x0 = fx >> 8, j0 = yy * W + x0;
            if (water[j0] & water[j0 + 1]) {
                const uint32_t a = plate[j0], b = plate[j0 + 1], f = fx & 255, g = 256 - f;
                row[x] = ((((a & 0xff00ff) * g + (b & 0xff00ff) * f) >> 8) & 0xff00ff) |
                         ((((a & 0x00ff00) * g + (b & 0x00ff00) * f) >> 8) & 0x00ff00);
            } else row[x] = prow[x];
        }
        if (first < 0) continue;
        /* copy the water part of the row; the ship pixels in between get their own plate value back */
        for (int x = first; x <= last; x++) if (!wrow[x]) row[x] = prow[x];
        memcpy(fb + y * stride_px + first, row + first, (last - first + 1) * 4);
    }
}

/* lean version: the plate as RGB565 (2 bytes a pixel) and one byte per pixel for "water, and how calm"
   (0 = ship): about half the memory traffic. Writes either 32-bit pixels (today's screen) or 16-bit ones
   (a 16 bpp screen, which the 18-bit panel could use with dithering) */
static uint16_t *plate565;
static uint8_t *wc;                   /* 0 = ship / sky, else wave scale 1..255 */
static inline uint32_t unpack565(uint16_t p) { return (p | ((uint32_t)p << 16)) & 0x07E0F81F; }
static void ripple3t(void *dst, int stride_px, int t_ms, int out16, int frame);
static void ripple3(void *dst, int stride_px, int t_ms, int out16) { ripple3t(dst, stride_px, t_ms, out16, -1); }
/* frame >= 0: distant rows (where the ripple is under about a pixel) are redrawn less often, a different
   subset each frame: the far third every 3rd frame, the middle third every 2nd, the near third every frame */
static void ripple3t(void *dst, int stride_px, int t_ms, int out16, int frame) {
    static uint16_t row16[W]; static uint32_t row32[W];
    const int hz = horizon;
    const int k1 = (int)(0.37 / (2 * M_PI) * LUT * 256), k2 = (int)(0.11 / (2 * M_PI) * LUT * 256);
    const int w1 = (int)(2.3 / (2 * M_PI) * LUT * 256 / 1000), w2 = (int)(1.6 / (2 * M_PI) * LUT * 256 / 1000);
    for (int y = hz + 2; y < H; y++) {
        const int depth_q8 = ((y - hz) << 8) / (H - hz);
        if (frame >= 0) {
            const int every = depth_q8 < 85 ? 3 : depth_q8 < 170 ? 2 : 1;
            if ((y + frame) % every) continue;
        }
        const int amp_q8 = 90 + ((614 * depth_q8) >> 8), amy = (amp_q8 * 115) >> 8;
        const int ph1 = (y * k1 + t_ms * w1) >> 8, ph2 = (y * k2 - t_ms * w2) >> 8;
        const uint8_t *wrow = wc + y * W; const uint16_t *prow = plate565 + y * W;
        for (int x = 0; x < W; x++) {
            const int c = wrow[x];
            uint16_t px;
            if (!c) px = prow[x];
            else {
                const int s1 = sin_lut[(ph1 + xph1[x]) & (LUT - 1)], s2 = sin_lut[(ph2 + xph2[x]) & (LUT - 1)];
                int fx = (x << 8) + ((((amp_q8 * c) >> 8) * s1) >> 14);
                const int dy = ((((amy * c) >> 8) * s2) + (1 << 21)) >> 22;
                if (fx < 0) fx = 0; else if (fx > (W - 2) << 8) fx = (W - 2) << 8;
                int yy = y + dy; if (yy <= hz + 1) yy = hz + 2; else if (yy > H - 1) yy = H - 1;
                const int j0 = yy * W + (fx >> 8);
                if (wc[j0] && wc[j0 + 1]) {
                    const uint32_t a = unpack565(plate565[j0]), b = unpack565(plate565[j0 + 1]), f = (fx & 255) >> 3;
                    uint32_t m = ((a * (32 - f) + b * f) >> 5) & 0x07E0F81F;
                    px = (uint16_t)(m | (m >> 16));
                } else px = prow[x];
            }
            if (out16) row16[x] = px;
            else row32[x] = ((px & 0xF800u) << 8) | ((px & 0x07E0u) << 5) | ((px & 0x001Fu) << 3);
        }
        if (out16) memcpy((uint16_t *)dst + y * stride_px, row16, W * 2);
        else memcpy((uint32_t *)dst + y * stride_px, row32, W * 4);
    }
}

int main(int argc, char **argv) {
    if (argc < 4) { fprintf(stderr, "usage: %s PLATE.rgb MASK.raw HORIZON [SECONDS]\n", argv[0]); return 1; }
    horizon = atoi(argv[3]);
    const int seconds = argc > 4 ? atoi(argv[4]) : 8;
    for (int i = 0; i < LUT; i++) sin_lut[i] = (int16_t)lrint(sin(i * 2 * M_PI / LUT) * 16384);
    for (int x = 0; x < W; x++) {
        sinX[x] = (int16_t)lrint(sin(x * 0.021) * 16384); cosX[x] = (int16_t)lrint(cos(x * 0.021) * 16384);
        sinX2[x] = (int16_t)lrint(sin(x * 0.013) * 16384); cosX2[x] = (int16_t)lrint(cos(x * 0.013) * 16384);
        xph1[x] = (uint16_t)lrint(x * 0.021 / (2 * M_PI) * LUT); xph2[x] = (uint16_t)lrint(x * 0.013 / (2 * M_PI) * LUT);
    }
    uint8_t *rgb = load(argv[1], W * H * 3), *mask = load(argv[2], W * H);
    plate = malloc(W * H * 4); plate2 = malloc(W * H * 4); blend_out = malloc(W * H * 4);
    for (int i = 0; i < W * H; i++) {
        plate[i] = (uint32_t)rgb[i * 3] << 16 | (uint32_t)rgb[i * 3 + 1] << 8 | rgb[i * 3 + 2];
        plate2[i] = (plate[i] >> 2) & 0x3f3f3f;               /* a dark stand-in for the night plate */
    }
    free(rgb);
    /* water below the horizon, off the ship; calm ramps up over 16 px under the waterline */
    water = calloc(W * H, 1); calm = malloc(W * H); memset(calm, 255, W * H);
    for (int y = horizon + 2; y < H; y++) for (int x = 0; x < W; x++) water[y * W + x] = !mask[y * W + x];
    for (int x = 0; x < W; x++) {
        int wl = -1;
        for (int y = H - 1; y > horizon; y--) if (mask[y * W + x]) { wl = y; break; }
        if (wl < 0) continue;
        for (int y = wl + 1; y < H && y < wl + 20; y++) {
            int d = y - wl, v = d <= 2 ? 0 : d >= 16 ? 256 : ((d - 2) << 8) / 14;
            v = (v * v * (768 - 2 * v)) >> 16;                   /* smoothstep */
            calm[y * W + x] = v > 255 ? 255 : v;
        }
    }
    free(mask);
    plate565 = malloc(W * H * 2); wc = malloc(W * H);
    for (int i = 0; i < W * H; i++) {
        const uint32_t p = plate[i];
        plate565[i] = (uint16_t)(((p >> 8) & 0xF800) | ((p >> 5) & 0x07E0) | ((p >> 3) & 0x1F));
        wc[i] = water[i] ? (calm[i] ? calm[i] : 1) : 0;
    }

    int fd = open("/dev/fb0", O_RDWR); if (fd < 0) { perror("/dev/fb0"); return 1; }
    const size_t fbsize = W * H * 4;
    uint32_t *fb = mmap(NULL, fbsize, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (fb == MAP_FAILED) { perror("mmap"); return 1; }
    memcpy(fb, plate, fbsize);

    double t0 = now();
    for (int k = 0; k < 60; k++) ripple(fb, W, k * 33, 1);
    double ms_bil = (now() - t0) / 60 * 1000;
    t0 = now();
    for (int k = 0; k < 60; k++) ripple(fb, W, k * 33, 0);
    double ms_near = (now() - t0) / 60 * 1000;
    t0 = now();
    for (int k = 0; k < 60; k++) ripple2(fb, W, k * 33);
    double ms_fast = (now() - t0) / 60 * 1000;
    t0 = now();
    for (int k = 0; k < 60; k++) ripple3(fb, W, k * 33, 0);
    double ms_lean32 = (now() - t0) / 60 * 1000;
    t0 = now();
    for (int k = 0; k < 60; k++) ripple3t(fb, W, k * 33, 0, k);
    double ms_tier = (now() - t0) / 60 * 1000;
    uint16_t *fb16 = malloc(W * H * 2);          /* stand-in for a 16 bpp screen (same kind of memory) */
    t0 = now();
    for (int k = 0; k < 60; k++) ripple3(fb16, W, k * 33, 1);
    double ms_lean16 = (now() - t0) / 60 * 1000;
    printf("ripple, bilinear (sub-pixel)   %6.1f ms/frame  (%5.1f fps)\n", ms_bil, 1000 / ms_bil);
    printf("ripple, lean, 32-bit screen    %6.1f ms/frame  (%5.1f fps)\n", ms_lean32, 1000 / ms_lean32);
    printf("ripple, lean, 16-bit buffer    %6.1f ms/frame  (%5.1f fps)\n", ms_lean16, 1000 / ms_lean16);
    printf("ripple, lean 32-bit, tiered    %6.1f ms/frame  (%5.1f fps)\n", ms_tier, 1000 / ms_tier);
    printf("ripple, faster version         %6.1f ms/frame  (%5.1f fps)\n", ms_fast, 1000 / ms_fast);
    printf("ripple, nearest                %6.1f ms/frame  (%5.1f fps)\n", ms_near, 1000 / ms_near);

    t0 = now();
    for (int k = 0; k < 10; k++) {
        const uint32_t g = 64 + k * 8, f = 256 - g;
        for (int i = 0; i < W * H; i++) {
            const uint32_t a = plate[i], b = plate2[i];
            blend_out[i] = ((((a & 0xff00ff) * f + (b & 0xff00ff) * g) >> 8) & 0xff00ff) |
                           ((((a & 0x00ff00) * f + (b & 0x00ff00) * g) >> 8) & 0x00ff00);
        }
    }
    double ms_blend = (now() - t0) / 10 * 1000;
    printf("blend two full plates          %6.1f ms\n", ms_blend);
    t0 = now();
    for (int k = 0; k < 20; k++) memcpy(fb, plate, fbsize);
    printf("copy a full frame to the screen %5.1f ms\n", (now() - t0) / 20 * 1000);
    fflush(stdout);

    /* show it: 30 fps cap */
    memcpy(fb, plate, fbsize);
    /* a reference frame rendered off screen: the same checksum every minute, or the CPU is making mistakes */
    uint32_t *ref = malloc(W * H * 4);
    uint32_t ref_sum = 0;
    #define CHECKSUM(out) do { memset(ref, 0, W * H * 4); ripple3(ref, W, 12345, 0); out = 0; \
        for (int i = 0; i < W * H; i++) out = out * 31 + ref[i]; } while (0)
    CHECKSUM(ref_sum);
    const double start = now(); int frames = 0; double busy = 0, next_report = 60; int errors = 0;
    while (now() - start < seconds) {
        const double f0 = now();
        if (f0 - start >= next_report) {
            uint32_t sum; CHECKSUM(sum); if (sum != ref_sum) errors++;
            printf("%4.0f min: %d frames (%.1f fps), checksum %s, errors %d\n", (f0 - start) / 60, frames,
                   frames / (f0 - start), sum == ref_sum ? "ok" : "WRONG", errors);
            fflush(stdout); next_report += 60;
        }
        ripple3t(fb, W, (int)((f0 - start) * 1000), 0, frames);
        const double spent = now() - f0; busy += spent; frames++;
        if (spent < 1.0 / 25) usleep((useconds_t)((1.0 / 25 - spent) * 1e6));      /* 25 fps cap */
    }
    printf("animated %d frames in %d s (%.1f fps), CPU busy %.0f%%\n", frames, seconds, frames / (double)seconds,
           busy / seconds * 100);
    return 0;
}
