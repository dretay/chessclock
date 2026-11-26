/*
 * splashanim: three dots pulsing in turn after "Starting" on a splash already on the screen (the
 * boot splash a countdown app's splash.sh puts up; the app picker's "Starting <app>" note), so the
 * wait for an app to start doesn't look like a hang.
 *
 *   splashanim X Y [SECS]      the first dot's centre at (X, Y); stop after SECS (default 90)
 *
 * It draws only its own little patch (blended over what was there when it started), about 20 times a
 * second, so it costs almost nothing while the board boots. It writes its pid to
 * /var/run/splashanim.pid: an app stops it (SIGTERM) just before its first frame (the countdown's
 * vacation.py), and it stops by itself after SECS anyway. 32-bit screens only (the
 * board's); on a desktop SPLASH_FB names a plain 800x480x32 file instead of /dev/fb0, SPLASH_PID the pid file.
 */
#define _DEFAULT_SOURCE
#include <fcntl.h>
#ifdef __linux__
#include <linux/fb.h>
#endif
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define DOTS 3
#define GAP 13                      /* between dot centres */
#define R 3.4                       /* dot radius */
#define PERIOD_MS 1200              /* one round of the three */
#define PID_FILE "/var/run/splashanim.pid"
#define FRAME_MS 50

static volatile sig_atomic_t stop;
static void on_term(int sig) { (void)sig; stop = 1; }

static long now_ms(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000L + ts.tv_nsec / 1000000L;
}

/* the pid in the pid file, or 0 */
static int pid_in(const char *path)
{
    int pid = 0;
    FILE *f = fopen(path, "r");
    if (f) { if (fscanf(f, "%d", &pid) != 1) pid = 0; fclose(f); }
    return pid;
}

/* A set of dots already running (the app picker's "Starting...", then the new app's own splash: two in a
 * row) is stopped first: the app stops the dots the pid file names, so an earlier set it didn't name would
 * pulse on over the app until its SECS ran out. Only a process that is a splashanim (/proc/PID/comm). */
static void stop_other(const char *pid_file)
{
    int pid = pid_in(pid_file);
    if (pid <= 0 || pid == (int)getpid()) return;
    char path[64], comm[32] = "";
    snprintf(path, sizeof path, "/proc/%d/comm", pid);
    FILE *f = fopen(path, "r");
    if (!f) return;
    if (!fgets(comm, sizeof comm, f)) comm[0] = 0;
    fclose(f);
    if (strncmp(comm, "splashanim", 10)) return;
    kill(pid, SIGTERM);
    for (int i = 0; i < 50 && kill(pid, 0) == 0; i++) usleep(10000);   /* (its last frame done before ours) */
}

int main(int argc, char **argv) {
    if (argc < 3) { fprintf(stderr, "usage: splashanim X Y [SECS]\n"); return 2; }
    const int cx = atoi(argv[1]), cy = atoi(argv[2]);
    const long secs = argc > 3 ? atol(argv[3]) : 90;
    const char *dev = getenv("SPLASH_FB") ? getenv("SPLASH_FB") : "/dev/fb0";
    int fd = open(dev, O_RDWR);
    if (fd < 0) return 1;
    int w = 800, h = 480, bpp = 32, stride = 800 * 4;
#ifdef __linux__
    struct fb_var_screeninfo var; struct fb_fix_screeninfo fix;
    if (ioctl(fd, FBIOGET_VSCREENINFO, &var) == 0 && ioctl(fd, FBIOGET_FSCREENINFO, &fix) == 0) {
        w = (int)var.xres; h = (int)var.yres; bpp = (int)var.bits_per_pixel; stride = (int)fix.line_length;
    }
#endif
    if (bpp != 32) return 1;
    size_t len = (size_t)stride * h;
    uint8_t *fb = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (fb == MAP_FAILED) return 1;

    /* the patch: the dots and a pixel around them, clipped; what's under it, kept */
    int x0 = cx - (int)R - 2, x1 = cx + (DOTS - 1) * GAP + (int)R + 3, y0 = cy - (int)R - 2, y1 = cy + (int)R + 3;
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > w) x1 = w;
    if (y1 > h) y1 = h;
    if (x1 <= x0 || y1 <= y0) return 1;
    const int pw = x1 - x0, ph = y1 - y0;
    uint8_t *under = malloc((size_t)pw * ph * 4);
    if (!under) return 1;
    for (int y = 0; y < ph; y++) memcpy(under + (size_t)y * pw * 4, fb + (size_t)(y0 + y) * stride + x0 * 4, (size_t)pw * 4);

    /* how much of each pixel each dot covers (anti-aliased): worked out once */
    float *cover = calloc((size_t)pw * ph * DOTS, sizeof *cover);
    if (!cover) return 1;
    for (int y = 0; y < ph; y++) for (int x = 0; x < pw; x++) for (int i = 0; i < DOTS; i++) {
        const double dx = x0 + x + 0.5 - (cx + i * GAP), dy = y0 + y + 0.5 - cy;
        double c = R + 0.5 - sqrt(dx * dx + dy * dy);
        cover[((size_t)y * pw + x) * DOTS + i] = (float)(c < 0 ? 0 : c > 1 ? 1 : c);
    }

    const char *pid_file = getenv("SPLASH_PID") ? getenv("SPLASH_PID") : PID_FILE;
    stop_other(pid_file);                                 /* (one set of dots at a time: see stop_other) */
    FILE *pf = fopen(pid_file, "w");
    if (pf) { fprintf(pf, "%d\n", (int)getpid()); fclose(pf); }
    signal(SIGTERM, on_term); signal(SIGINT, on_term);

    const long start = now_ms();
    while (!stop && now_ms() - start < secs * 1000L) {
        const double t = (double)((now_ms() - start) % PERIOD_MS) / PERIOD_MS;
        double level[DOTS];
        for (int i = 0; i < DOTS; i++) {                  /* each dot brightens and fades in turn */
            double p = t - i * 0.18; p -= floor(p);       /* this dot's place in the round, 0..1 */
            level[i] = 0.22 + (p < 0.5 ? 0.78 * sin(p * 2 * M_PI) : 0);   /* up and down in the first half */
        }
        for (int y = 0; y < ph; y++) {
            uint8_t *row = fb + (size_t)(y0 + y) * stride + x0 * 4;
            const uint8_t *bg = under + (size_t)y * pw * 4;
            for (int x = 0; x < pw; x++) {
                const float *cv = cover + ((size_t)y * pw + x) * DOTS;
                double a = 0;
                for (int i = 0; i < DOTS; i++) if (cv[i] * level[i] > a) a = cv[i] * level[i];
                if (a == 0) continue;                     /* (between the dots: as it was) */
                /* gold (226, 190, 120), BGRX */
                row[x * 4 + 0] = (uint8_t)(bg[x * 4 + 0] + (120 - bg[x * 4 + 0]) * a);
                row[x * 4 + 1] = (uint8_t)(bg[x * 4 + 1] + (190 - bg[x * 4 + 1]) * a);
                row[x * 4 + 2] = (uint8_t)(bg[x * 4 + 2] + (226 - bg[x * 4 + 2]) * a);
            }
        }
        usleep(FRAME_MS * 1000);
    }
    if (pid_in(pid_file) == (int)getpid()) unlink(pid_file);   /* (not a newer one's) */
    return 0;
}
