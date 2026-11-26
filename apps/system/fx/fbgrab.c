/* fbgrab: the screen, small, as text, for the Mac's Remote mirror (tools/preview/remote.py) over the USB console.
 *
 *   fbgrab [FILE]      (default /dev/fb0; FILE: a raw 800x480 BGRX file, for testing on a desktop)
 *
 * The screen at half size (400x240, each pixel the average of a 2x2 square: text stays legible), as RGB565
 * little-endian, zlib-compressed (level 1: quick on the ARM9), base64, between two lines:
 *
 *   FBGRAB 400 240 <compressed bytes>
 *   <base64, 76 a line>
 *   FBEND
 *
 * or just "FBSAME" when it's the same picture as last time (/tmp/fbgrab.last keeps its hash), so a screen
 * that isn't moving (Settings, the app picker) costs a line, not a picture. Memory: about 400 KB.
 *
 * Built with -DWITH_JPEG -ljpeg (fbgrab-jpeg, when the base system has libjpeg): the same picture as a
 * JPEG instead ("FBJPEG 400 240 <bytes>"), about a fifth the size of the zlib one for a moving scene, so
 * the mirror keeps up (the USB console carries about 200 KB/s).
 */
#define _DEFAULT_SOURCE
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <zlib.h>
#ifdef WITH_JPEG
#include <jpeglib.h>
#endif
#ifdef __linux__
#include <linux/fb.h>
#include <sys/ioctl.h>
#endif

#define W 800
#define H 480
#define OW (W / 2)
#define OH (H / 2)
#define LAST "/tmp/fbgrab.last"

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "/dev/fb0";
    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror(path); return 1; }
    size_t stride = W * 4, len = stride * H;
#ifdef __linux__
    struct stat st;
    if (!fstat(fd, &st) && S_ISCHR(st.st_mode)) {
        struct fb_var_screeninfo v; struct fb_fix_screeninfo f;
        if (ioctl(fd, FBIOGET_VSCREENINFO, &v) || ioctl(fd, FBIOGET_FSCREENINFO, &f)) { perror("fb ioctl"); return 1; }
        if (v.xres != W || v.yres != H || v.bits_per_pixel != 32) { fprintf(stderr, "fbgrab: need %dx%d at 32 bpp\n", W, H); return 1; }
        stride = f.line_length; len = stride * H;
    }
#endif
    const uint8_t *fb = mmap(NULL, len, PROT_READ, MAP_SHARED, fd, 0);
    if (fb == MAP_FAILED) { perror("mmap"); return 1; }

    static uint16_t px[OW * OH];
    static uint8_t rgb[OW * OH * 3];
    uint32_t hash = 2166136261u;                         /* FNV-1a over the small picture */
    for (int y = 0; y < OH; y++) {
        const uint8_t *r0 = fb + (size_t)(2 * y) * stride, *r1 = r0 + stride;
        for (int x = 0; x < OW; x++) {
            const uint8_t *a = r0 + 8 * x, *b = r1 + 8 * x;  /* B, G, R, X */
            unsigned bl = (a[0] + a[4] + b[0] + b[4]) >> 2, g = (a[1] + a[5] + b[1] + b[5]) >> 2, r = (a[2] + a[6] + b[2] + b[6]) >> 2;
            uint16_t v = (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (bl >> 3));
            px[y * OW + x] = v;
            uint8_t *o = rgb + 3 * (y * OW + x); o[0] = (uint8_t)r; o[1] = (uint8_t)g; o[2] = (uint8_t)bl;
            hash = (hash ^ (v & 0xff)) * 16777619u; hash = (hash ^ (v >> 8)) * 16777619u;
        }
    }
    munmap((void *)fb, len); close(fd);

    uint32_t last = 0;
    FILE *lf = fopen(LAST, "r");
    if (lf) { if (fscanf(lf, "%u", &last) != 1) last = 0; fclose(lf); }
    if (last == hash) { puts("FBSAME"); return 0; }

#ifdef WITH_JPEG
    struct jpeg_compress_struct c; struct jpeg_error_mgr e;
    unsigned char *z = NULL;
#if JPEG_LIB_VERSION >= 90
    size_t zlen = 0;                                      /* (libjpeg 9's jpeg_mem_dest; jpeg-turbo's is unsigned long) */
#else
    unsigned long zlen = 0;
#endif
    c.err = jpeg_std_error(&e); jpeg_create_compress(&c);
    jpeg_mem_dest(&c, &z, &zlen);
    c.image_width = OW; c.image_height = OH; c.input_components = 3; c.in_color_space = JCS_RGB;
    jpeg_set_defaults(&c); jpeg_set_quality(&c, 72, TRUE);
    c.dct_method = JDCT_IFAST;                            /* (integer, the quickest: no FPU here) */
    jpeg_start_compress(&c, TRUE);
    while (c.next_scanline < c.image_height) { JSAMPROW row = rgb + c.next_scanline * OW * 3; jpeg_write_scanlines(&c, &row, 1); }
    jpeg_finish_compress(&c); jpeg_destroy_compress(&c);
    printf("FBJPEG %d %d %lu\n", OW, OH, (unsigned long)zlen);
#else
    uLongf zlen = compressBound(sizeof px);
    uint8_t *z = malloc(zlen);
    if (!z || compress2(z, &zlen, (const Bytef *)px, sizeof px, 1) != Z_OK) { fprintf(stderr, "fbgrab: compress failed\n"); return 1; }
    printf("FBGRAB %d %d %lu\n", OW, OH, (unsigned long)zlen);
#endif
    char line[80]; int n = 0;
    for (uLongf i = 0; i < zlen; i += 3) {
        uint32_t v = (uint32_t)z[i] << 16 | (i + 1 < zlen ? (uint32_t)z[i + 1] << 8 : 0) | (i + 2 < zlen ? z[i + 2] : 0);
        line[n++] = B64[v >> 18 & 63]; line[n++] = B64[v >> 12 & 63];
        line[n++] = i + 1 < zlen ? B64[v >> 6 & 63] : '=';
        line[n++] = i + 2 < zlen ? B64[v & 63] : '=';
        if (n >= 76) { line[n] = 0; puts(line); n = 0; }
    }
    if (n) { line[n] = 0; puts(line); }
    puts("FBEND");
    free(z);
    lf = fopen(LAST, "w");                               /* (only once it's all out) */
    if (lf) { fprintf(lf, "%u\n", hash); fclose(lf); }
    return 0;
}
