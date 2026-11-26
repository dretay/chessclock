/* modinstall: check an app's signature, and install it (into /apps: see docs/apps.md).
 *
 *   modinstall [--check] [--force] [--keys FILE] [--dir DIR] APP.tar.gz [APP.tar.gz.sig]
 *
 * An app comes as a tarball (tools/apps/pack.py) and a signed statement beside it (.sig):
 *
 *   licheepi-module 1
 *   id castle
 *   name Magic Kingdom
 *   version 0.1.0
 *   api 2
 *   runtime countdown            (the runtime it runs on, if any: a folder in DIR, with an API file)
 *   provides-api 2               (a runtime: the app api it provides)
 *   size 2227697                 (the tarball's, in bytes)
 *   sha512 <128 hex>             (the tarball's)
 *   key <16 hex>                 (the signing key: the first 8 bytes of its public key)
 *   sig <128 hex>                (Ed25519, over every line above this one)
 *
 * The statement's signature is checked against the public keys in /etc/modules/trusted.keys (in the
 * base system, where a module can't change them), then the tarball's size and SHA-512 against the
 * statement; nothing in the tarball is read before both match. Then it's unpacked into a staging folder
 * (regular files and folders only, all under ID/, no "..", no links), and swapped in for the app's
 * folder in one rename; the previous one stays as .old-ID. Refused: a version older than the one
 * installed (--force allows it); an app whose runtime isn't installed, or is older than its api; a
 * runtime older than an installed app needs (--force allows it); the names DIR's other things have
 * (data, current, ...), and replacing a folder that isn't an app.
 *
 * --check: only check the signature and the tarball.
 *
 * --base --target DEV PKG.img.gz [PKG.img.gz.sig]: a base system for one of the card's two root slots
 * (tools/apps/pack.py --base; docs/system.md, "Updates"), written to DEV, the slot not running
 * (bootslot install picks it, and switches to it after). Its statement says `kind base`, the board,
 * and the unpacked image's size and SHA-512 besides the .gz's:
 *
 *   licheepi-module 1 / id base / name Base system / version 2025.02.20.1 / api 1 / kind base /
 *   board licheepi-nano / image-size 134217728 / image-sha512 <128 hex> / size / sha512 / key / sig
 *
 * The signature and the .gz are checked as for an app, before anything is written. Refused: another
 * board; a version not newer than --version-file's (default /etc/base-version; --force allows it); an
 * image bigger than DEV; DEV mounted, or the root the system is running from. The image is unpacked
 * straight onto DEV (a few KB of memory), synced, then read back from the card and checked against
 * image-size and image-sha512: "ok" only if what's on the card is what was signed.
 * --verify-installed DIR: an installed app's .signature (the statement it was installed with) is signed
 * by a trusted key, names this app, and so is its runtime's (and that runtime's, down the chain) (S99app and the app picker, when the board is
 * locked to signed apps: /apps/data/locked). It doesn't re-hash the files: that's at install. Memory: a few KB whatever the module's size
 * (the tarball is hashed and unpacked as a stream).
 */
#define _XOPEN_SOURCE 700
#define _DEFAULT_SOURCE
#define _DARWIN_C_SOURCE                /* (for testing on a Mac: O_NOFOLLOW) */
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <ftw.h>
#include <limits.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include <zlib.h>
#include "monocypher/monocypher.h"
#include "monocypher/monocypher-ed25519.h"

#define MAX_STATEMENT 4096
#define MAX_TOTAL (96LL << 20)          /* unpacked bytes: the apps partition is 128 MB */
#define MAX_FILES 10000

static char staging[600];               /* removed again if anything fails */

static int rm_one(const char *p, const struct stat *sb, int flag, struct FTW *f)
{
    (void)sb; (void)flag; (void)f;
    return remove(p);
}

static void rmtree(const char *p)
{
    struct stat st;
    if (lstat(p, &st) == 0) nftw(p, rm_one, 16, FTW_DEPTH | FTW_PHYS);
}

static void die(const char *fmt, ...)
{
    va_list ap;
    fputs("modinstall: ", stderr);
    va_start(ap, fmt); vfprintf(stderr, fmt, ap); va_end(ap);
    fputc('\n', stderr);
    if (staging[0]) rmtree(staging);
    exit(1);
}

static int unhex(const char *s, uint8_t *out, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        unsigned v;
        if (!isxdigit((unsigned char)s[2 * i]) || !isxdigit((unsigned char)s[2 * i + 1])) return -1;
        if (sscanf(s + 2 * i, "%2x", &v) != 1) return -1;
        out[i] = (uint8_t)v;
    }
    return isxdigit((unsigned char)s[2 * n]) ? -1 : 0;
}

static void hex(const uint8_t *b, size_t n, char *out)
{
    for (size_t i = 0; i < n; i++) sprintf(out + 2 * i, "%02x", b[i]);
}

struct statement {
    char text[MAX_STATEMENT];
    size_t signed_len;                   /* the bytes the signature covers */
    char id[33], version[33], name[80], runtime[33], kind[17], board[33];
    long api, provides_api;
    long long size, image_size;
    uint8_t sha512[64], key[8], sig[64], image_sha512[64];
    int has_image_sha512;
};

static int read_file(const char *path, char *buf, size_t cap)
{
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    ssize_t n = read(fd, buf, cap - 1);
    close(fd);
    if (n < 0 || (size_t)n >= cap - 1) return -1;
    buf[n] = 0;
    return (int)n;
}

static int good_id(const char *s)
{
    size_t n = strlen(s);
    if (n < 1 || n > 32 || s[0] == '-') return 0;
    for (; *s; s++) if (!(islower((unsigned char)*s) || isdigit((unsigned char)*s) || *s == '-' || *s == '_')) return 0;
    return 1;
}

static int good_version(const char *s)
{
    if (!*s || strlen(s) > 32 || !isdigit((unsigned char)*s)) return 0;
    for (; *s; s++) if (!isdigit((unsigned char)*s) && *s != '.') return 0;
    return 1;
}

/* parse (but don't check) a statement; 0 if it's well-formed */
static int parse(struct statement *st, const char *path, const char **why)
{
    int n = read_file(path, st->text, sizeof st->text);
    if (n < 0) { *why = "can't read it (or it's too long)"; return -1; }
    if ((int)strlen(st->text) != n) { *why = "it has a NUL byte"; return -1; }
    if (strncmp(st->text, "licheepi-module 1\n", 18)) { *why = "not a module statement (or a newer format)"; return -1; }
    char *s = strstr(st->text, "\nsig ");
    if (!s) { *why = "no sig line"; return -1; }
    st->signed_len = (size_t)(s + 1 - st->text);
    if (unhex(s + 5, st->sig, 64) || strcmp(s + 5 + 128, "\n")) { *why = "bad sig line (or something after it)"; return -1; }

    int have = 0;
    st->runtime[0] = 0; st->provides_api = -1;
    st->kind[0] = st->board[0] = 0; st->image_size = -1; st->has_image_sha512 = 0;
    for (char *line = st->text; line < st->text + st->signed_len; ) {
        char *end = strchr(line, '\n');
        *end = 0;
        if (!strncmp(line, "id ", 3) && strlen(line + 3) < sizeof st->id) { strcpy(st->id, line + 3); have |= 1; }
        else if (!strncmp(line, "version ", 8) && strlen(line + 8) < sizeof st->version) { strcpy(st->version, line + 8); have |= 2; }
        else if (!strncmp(line, "api ", 4)) { st->api = strtol(line + 4, NULL, 10); have |= 4; }
        else if (!strncmp(line, "size ", 5)) { st->size = strtoll(line + 5, NULL, 10); have |= 8; }
        else if (!strncmp(line, "sha512 ", 7) && !unhex(line + 7, st->sha512, 64)) have |= 16;
        else if (!strncmp(line, "key ", 4) && !unhex(line + 4, st->key, 8)) have |= 32;
        else if (!strncmp(line, "name ", 5)) snprintf(st->name, sizeof st->name, "%s", line + 5);
        else if (!strncmp(line, "runtime ", 8) && strlen(line + 8) < sizeof st->runtime) strcpy(st->runtime, line + 8);
        else if (!strncmp(line, "provides-api ", 13)) st->provides_api = strtol(line + 13, NULL, 10);
        else if (!strncmp(line, "kind ", 5) && strlen(line + 5) < sizeof st->kind) strcpy(st->kind, line + 5);
        else if (!strncmp(line, "board ", 6) && strlen(line + 6) < sizeof st->board) strcpy(st->board, line + 6);
        else if (!strncmp(line, "image-size ", 11)) st->image_size = strtoll(line + 11, NULL, 10);
        else if (!strncmp(line, "image-sha512 ", 13) && !unhex(line + 13, st->image_sha512, 64)) st->has_image_sha512 = 1;
        *end = '\n';                     /* (put back: the signature covers the text as it was) */
        line = end + 1;
    }
    if (have != 63) { *why = "a line is missing or bad (id, version, api, size, sha512, key)"; return -1; }
    if (!good_id(st->id)) { *why = "bad id"; return -1; }
    if (!good_version(st->version)) { *why = "bad version"; return -1; }
    if (st->runtime[0] && !good_id(st->runtime)) { *why = "bad runtime"; return -1; }
    return 0;
}

/* the statement's signature, by one of the trusted keys */
static void check_signature(const struct statement *st, const char *keys_path)
{
    char keys[16384];
    if (read_file(keys_path, keys, sizeof keys) < 0) die("no trusted keys (%s)", keys_path);
    int tried = 0;
    for (char *line = strtok(keys, "\n"); line; line = strtok(NULL, "\n")) {
        while (isspace((unsigned char)*line)) line++;
        uint8_t pub[32];
        if (*line == '#' || !*line || unhex(line, pub, 32)) continue;
        if (memcmp(pub, st->key, 8)) continue;
        tried++;
        if (crypto_ed25519_check(st->sig, pub, (const uint8_t *)st->text, st->signed_len) == 0) return;
    }
    char k[17]; hex(st->key, 8, k);
    if (!tried) die("signed by key %s, which isn't trusted here (%s)", k, keys_path);
    die("the signature doesn't match: the statement was changed, or isn't from key %s", k);
}

/* the tarball's size and SHA-512 against the statement's */
static void check_tarball(int fd, const struct statement *st)
{
    struct stat sb;
    if (fstat(fd, &sb) || !S_ISREG(sb.st_mode)) die("the app isn't a regular file");
    if (sb.st_size != st->size) die("the app is %lld bytes, the statement says %lld", (long long)sb.st_size, st->size);
    crypto_sha512_ctx ctx;
    crypto_sha512_init(&ctx);
    static uint8_t buf[16384];
    ssize_t n;
    long long total = 0;
    while ((n = read(fd, buf, sizeof buf)) > 0) { crypto_sha512_update(&ctx, buf, (size_t)n); total += n; }
    if (n < 0 || total != st->size) die("couldn't read the app");
    uint8_t h[64];
    crypto_sha512_final(&ctx, h);
    if (crypto_verify64(h, st->sha512)) die("the app doesn't match its statement (changed, or the wrong file)");
}

static int vcmp(const char *a, const char *b)
{
    while (*a || *b) {
        long x = strtol(a, (char **)&a, 10), y = strtol(b, (char **)&b, 10);
        if (x != y) return x < y ? -1 : 1;
        if (*a == '.') a++;
        if (*b == '.') b++;
    }
    return 0;
}

/* a runtime's app api (DIR/RUNTIME/API, a number), or -1 if it isn't installed */
static long runtime_api(const char *dir, const char *runtime)
{
    char path[600], buf[32];
    snprintf(path, sizeof path, "%s/%s/API", dir, runtime);
    if (read_file(path, buf, sizeof buf) < 0) return -1;
    return strtol(buf, NULL, 10);
}

/* the names in DIR that aren't apps */
static int reserved(const char *id)
{
    static const char *names[] = {"data", "current", "swapfile", "base", NULL};      /* (lost+found: not a possible id) */
    for (int i = 0; names[i]; i++) if (!strcmp(id, names[i])) return 1;
    return 0;
}

static int is_app_folder(const char *path)
{
    char p[700];
    struct stat sb;
    if (lstat(path, &sb) || !S_ISDIR(sb.st_mode)) return 0;
    snprintf(p, sizeof p, "%s/app.json", path);
    if (access(p, F_OK) == 0) return 1;
    snprintf(p, sizeof p, "%s/module.json", path);
    return access(p, F_OK) == 0;
}

/* a runtime about to be installed: the installed (signed) apps on it it would be too old for */
static void check_dependents(const char *dir, const struct statement *st, int force)
{
    DIR *d = opendir(dir);
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d))) {
        if (e->d_name[0] == '.') continue;
        static struct statement other;
        char p[700];
        const char *why;
        snprintf(p, sizeof p, "%s/%s/.signature", dir, e->d_name);
        if (access(p, F_OK) || parse(&other, p, &why)) continue;
        if (strcmp(other.runtime, st->id) || other.api <= st->provides_api) continue;
        if (!force) { closedir(d); die("%s %s provides api %ld, and %s %s needs %ld (--force installs it anyway)",
                                       st->id, st->version, st->provides_api, other.id, other.version, other.api); }
        fprintf(stderr, "modinstall: %s %s needs api %ld; it won't run until it's updated\n", other.id, other.version, other.api);
    }
    closedir(d);
}

/* a path inside the tarball: ID/ then plain names */
static const char *checked_path(const char *path, const char *id)
{
    size_t n = strlen(id);
    if (strncmp(path, id, n) || path[n] != '/') return NULL;
    const char *rel = path + n + 1;
    int depth = 0;
    for (const char *c = rel; *c; ) {
        const char *e = strchr(c, '/');
        size_t len = e ? (size_t)(e - c) : strlen(c);
        if (len == 0 && !e) break;                       /* (a folder's trailing /) */
        if (len == 0 || (len == 1 && c[0] == '.') || (len == 2 && c[0] == '.' && c[1] == '.')) return NULL;
        for (size_t i = 0; i < len; i++) {
            unsigned char ch = (unsigned char)c[i];
            if (ch < 0x20 || ch >= 0x7f || ch == '\\') return NULL;
        }
        if (++depth > 12) return NULL;
        c += len + (e ? 1 : 0);
    }
    return rel;
}

static long long octal(const char *f, size_t n)
{
    long long v = 0;
    for (size_t i = 0; i < n && f[i]; i++) {
        if (f[i] == ' ') continue;
        if (f[i] < '0' || f[i] > '7') return -1;
        v = v * 8 + (f[i] - '0');
    }
    return v;
}

static void make_parents(char *path)
{
    for (char *p = path + strlen(staging) + 1; (p = strchr(p, '/')); p++) {
        *p = 0;
        if (mkdir(path, 0755) && errno != EEXIST) die("mkdir %s: %s", path, strerror(errno));
        *p = '/';
    }
}

static void unpack(int fd, const char *id)
{
    if (lseek(fd, 0, SEEK_SET)) die("couldn't reread the app");
    gzFile gz = gzdopen(dup(fd), "rb");
    if (!gz) die("not a gzip file");
    if (mkdir(staging, 0755)) die("mkdir %s: %s", staging, strerror(errno));
    static char h[512], buf[16384];
    long long total = 0;
    int files = 0, has_meta = 0;
    for (;;) {
        if (gzread(gz, h, 512) != 512) die("the tarball ends early");
        int zero = 1;
        for (int i = 0; i < 512; i++) if (h[i]) { zero = 0; break; }
        if (zero) break;
        unsigned sum = 0;
        for (int i = 0; i < 512; i++) sum += (i >= 148 && i < 156) ? ' ' : (unsigned char)h[i];
        if (octal(h + 148, 8) != sum || memcmp(h + 257, "ustar", 5)) die("a bad tar header");
        char name[101], prefix[156], path[260];
        memcpy(name, h, 100); name[100] = 0;
        memcpy(prefix, h + 345, 155); prefix[155] = 0;
        snprintf(path, sizeof path, prefix[0] ? "%s/%s" : "%s%s", prefix, name);
        const char *rel = checked_path(path, id);
        if (!rel) die("a file outside the app, or a bad name: %s", path);
        long long size = octal(h + 124, 12), mode = octal(h + 100, 8);
        char type = h[156];
        if (size < 0 || mode < 0) die("a bad tar header: %s", path);
        if ((total += size) > MAX_TOTAL || ++files > MAX_FILES) die("too big unpacked");

        char out[900];
        snprintf(out, sizeof out, "%s/%s", staging, rel);
        if (type == '5') {
            if (!*rel) continue;
            make_parents(out);
            if (mkdir(out, 0755) && errno != EEXIST) die("mkdir %s: %s", out, strerror(errno));
            continue;
        }
        if (type != '0' && type != 0) die("not a plain file (a link, or a device): %s", path);
        if (!*rel) die("a bad name: %s", path);
        make_parents(out);
        int o = open(out, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, (mode & 0111) ? 0755 : 0644);
        if (o < 0) die("%s: %s", out, strerror(errno));
        for (long long left = size; left > 0; ) {
            int want = left > (long long)sizeof buf ? (int)sizeof buf : (int)left;
            if (gzread(gz, buf, (unsigned)want) != want) die("the tarball ends early");
            if (write(o, buf, (size_t)want) != want) die("writing %s: %s", out, strerror(errno));
            left -= want;
        }
        if (fsync(o) || close(o)) die("writing %s: %s", out, strerror(errno));
        long long pad = (512 - size % 512) % 512;
        if (pad && gzread(gz, buf, (unsigned)pad) != pad) die("the tarball ends early");
        if (!strcmp(rel, "app.json") || !strcmp(rel, "module.json")) has_meta = 1;
    }
    gzclose(gz);
    if (!has_meta) die("no app.json in the app");
}

/* an installed app's signature, and its runtime's; exits (die) if either isn't good */
static void verify_installed(const char *appdir, const char *keys, int depth)
{
    char p[700];
    const char *why;
    struct statement st;
    snprintf(p, sizeof p, "%s/.signature", appdir);
    if (parse(&st, p, &why)) die("%s isn't signed (%s)", appdir, why);
    check_signature(&st, keys);
    const char *name = strrchr(appdir, '/');
    name = name ? name + 1 : appdir;
    if (*name == 0 || strcmp(st.id, name)) die("%s's signature is for %s", appdir, st.id);
    if (st.runtime[0] && depth < 4) {                    /* (its runtime's, and that one's: castle, countdown, system) */
        char rt[700], parent[600];
        snprintf(parent, sizeof parent, "%s", appdir);
        char *slash = strrchr(parent, '/');
        if (slash) *slash = 0; else snprintf(parent, sizeof parent, ".");
        snprintf(rt, sizeof rt, "%s/%s", parent, st.runtime);
        verify_installed(rt, keys, 1);
    }
    if (depth == 0) printf("signed: %s %s\n", st.id, st.version);
}

#ifndef BOARD
#define BOARD "licheepi-nano"
#endif

/* is DEV the running root (root= on the kernel's command line) or mounted? */
static void check_not_in_use(const char *dev)
{
    char buf[4096], real[PATH_MAX], other[PATH_MAX];      /* (realpath needs PATH_MAX: less aborts, with glibc's checks) */
    if (!realpath(dev, real)) snprintf(real, sizeof real, "%s", dev);
    if (read_file("/proc/cmdline", buf, sizeof buf) >= 0) {
        char *r = strstr(buf, "root=");
        if (r) {
            r += 5; r[strcspn(r, " \n")] = 0;
            if (!strcmp(r, dev) || !strcmp(r, real) || (realpath(r, other) && !strcmp(other, real)))
                die("%s is the root this system is running from", dev);
        }
    }
    FILE *m = fopen("/proc/mounts", "r");
    if (!m) return;
    while (fgets(buf, sizeof buf, m)) {
        buf[strcspn(buf, " ")] = 0;
        if (!strcmp(buf, dev) || !strcmp(buf, real)) { fclose(m); die("%s is mounted", dev); }
    }
    fclose(m);
}

static void drop_cache(int fd)
{
#ifdef POSIX_FADV_DONTNEED
    posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);      /* (so the check reads the card, not memory) */
#else
    (void)fd;
#endif
}

static int install_base(int fd, const struct statement *st, const char *target, const char *version_file, int force)
{
    if (strcmp(st->kind, "base")) die("not a base system package (an app: modinstall without --base)");
    if (strcmp(st->board, BOARD)) die("a base system for %s, not this board (%s)", st->board[0] ? st->board : "no board", BOARD);
    if (st->image_size <= 0 || !st->has_image_sha512) die("the statement has no image-size or image-sha512");
    char cur[64] = "";
    if (read_file(version_file, cur, sizeof cur) >= 0) {
        cur[strcspn(cur, " \n")] = 0;
        if (*cur && vcmp(st->version, cur) <= 0 && !force)
            die("base %s isn't newer than the running %s (--force installs it anyway)", st->version, cur);
    }
    check_not_in_use(target);
    int out = open(target, O_RDWR);
    if (out < 0) die("%s: %s", target, strerror(errno));
    off_t room = lseek(out, 0, SEEK_END);
    if (room < st->image_size) die("the image is %lld bytes, %s only %lld", st->image_size, target, (long long)room);
    if (lseek(out, 0, SEEK_SET) || lseek(fd, 0, SEEK_SET)) die("couldn't seek");

    printf("writing base %s (%lld bytes) to %s\n", st->version, st->image_size, target); fflush(stdout);
    gzFile gz = gzdopen(dup(fd), "rb");
    if (!gz) die("not a gzip file");
    static uint8_t buf[65536];
    crypto_sha512_ctx ctx;
    crypto_sha512_init(&ctx);
    long long done = 0;
    for (;;) {
        int n = gzread(gz, buf, sizeof buf);
        if (n < 0) die("the image doesn't unpack (a bad gzip)");
        if (n == 0) break;
        if ((done += n) > st->image_size) die("the image unpacks bigger than its statement says");
        crypto_sha512_update(&ctx, buf, (size_t)n);
        for (int w = 0; w < n; ) {
            ssize_t k = write(out, buf + w, (size_t)(n - w));
            if (k <= 0) die("writing %s: %s", target, strerror(errno));
            w += (int)k;
        }
    }
    gzclose(gz);
    uint8_t h[64];
    crypto_sha512_final(&ctx, h);
    if (done != st->image_size || crypto_verify64(h, st->image_sha512)) die("the unpacked image doesn't match its statement");
    if (fsync(out)) die("syncing %s: %s", target, strerror(errno));
    drop_cache(out);
    close(out);

    printf("checking what's on %s\n", target); fflush(stdout);
    int in = open(target, O_RDONLY);
    if (in < 0) die("%s: %s", target, strerror(errno));
    drop_cache(in);
    crypto_sha512_init(&ctx);
    for (long long left = st->image_size; left > 0; ) {
        ssize_t n = read(in, buf, left > (long long)sizeof buf ? sizeof buf : (size_t)left);
        if (n <= 0) die("reading %s back: %s", target, n ? strerror(errno) : "it ends early");
        crypto_sha512_update(&ctx, buf, (size_t)n);
        left -= n;
    }
    close(in);
    crypto_sha512_final(&ctx, h);
    if (crypto_verify64(h, st->image_sha512)) die("what's on %s isn't what was written (a card problem?): not using it", target);
    printf("ok: base %s is on %s\n", st->version, target);
    return 0;
}

static const char *usage =
    "usage: modinstall [--check] [--force] [--keys FILE] [--dir DIR] APP.tar.gz [APP.tar.gz.sig]\n"
    "       modinstall [--keys FILE] --verify-installed DIR\n"
    "       modinstall [--keys FILE] [--force] [--version-file FILE] --base --target DEV PKG.img.gz [PKG.img.gz.sig]\n"
    "  check an app's signature (--check: only that), then install it into DIR\n"
    "  (default /apps; keys: /etc/modules/trusted.keys)\n";

int main(int argc, char **argv)
{
    const char *keys = "/etc/modules/trusted.keys", *dir = "/apps", *tar = NULL, *sig = NULL;
    int check_only = 0, force = 0;
    const char *installed = NULL, *target = NULL, *version_file = "/etc/base-version";
    int base = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--check")) check_only = 1;
        else if (!strcmp(argv[i], "--verify-installed") && i + 1 < argc) installed = argv[++i];
        else if (!strcmp(argv[i], "--force")) force = 1;
        else if (!strcmp(argv[i], "--base")) base = 1;
        else if (!strcmp(argv[i], "--target") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "--version-file") && i + 1 < argc) version_file = argv[++i];
        else if (!strcmp(argv[i], "--keys") && i + 1 < argc) keys = argv[++i];
        else if (!strcmp(argv[i], "--dir") && i + 1 < argc) dir = argv[++i];
        else if (argv[i][0] == '-') { fputs(usage, stderr); return 2; }
        else if (!tar) tar = argv[i];
        else if (!sig) sig = argv[i];
        else { fputs(usage, stderr); return 2; }
    }
    if (installed) {
        char d[600];
        snprintf(d, sizeof d, "%s", installed);
        size_t n = strlen(d);
        while (n > 1 && d[n - 1] == '/') d[--n] = 0;     /* (no trailing /) */
        verify_installed(d, keys, 0);
        return 0;
    }
    if (!tar) { fputs(usage, stderr); return 2; }
    char sig_buf[600];
    if (!sig) { snprintf(sig_buf, sizeof sig_buf, "%s.sig", tar); sig = sig_buf; }

    static struct statement st;
    const char *why;
    if (parse(&st, sig, &why)) die("%s: %s", sig, why);
    check_signature(&st, keys);
    int fd = open(tar, O_RDONLY);
    if (fd < 0) die("%s: %s", tar, strerror(errno));
    check_tarball(fd, &st);
    char k[17]; hex(st.key, 8, k);
    if (check_only) {
        printf("ok: %s %s (api %ld), signed by key %s\n", st.id, st.version, st.api, k);
        return 0;
    }
    if (base) {
        if (!target) die("--base needs --target DEV (the slot to write: bootslot install picks it)");
        return install_base(fd, &st, target, version_file, force);
    }
    if (st.kind[0]) die("a %s package, not an app (modinstall --base)", st.kind);

    if (reserved(st.id)) die("%s isn't a name an app can have here", st.id);
    if (st.runtime[0]) {
        long api = runtime_api(dir, st.runtime);
        if (api < 0) die("%s %s runs on the %s runtime, which isn't installed: install it first", st.id, st.version, st.runtime);
        if (st.api > api) die("%s %s needs a newer %s runtime (app api %ld; the installed one has %ld)", st.id, st.version, st.runtime, st.api, api);
    }
    if (st.provides_api >= 0) check_dependents(dir, &st, force);
    char cur[600], old[600], was[80] = "new";
    snprintf(cur, sizeof cur, "%s/%s", dir, st.id);
    snprintf(old, sizeof old, "%s/.old-%s", dir, st.id);
    struct stat sb;
    if (lstat(cur, &sb) == 0 && !is_app_folder(cur)) die("%s is there and isn't an app: not replacing it", cur);
    if (lstat(cur, &sb) == 0) {
        static struct statement in;
        char p[700];
        snprintf(p, sizeof p, "%s/.signature", cur);
        if (parse(&in, p, &why) == 0) {
            if (vcmp(st.version, in.version) < 0 && !force)
                die("%s %s is older than the installed %s (--force installs it anyway)", st.id, st.version, in.version);
            snprintf(was, sizeof was, "was %s", in.version);
        } else snprintf(was, sizeof was, "was an unsigned copy");
    }

    snprintf(staging, sizeof staging, "%s/.staging-%s", dir, st.id);
    rmtree(staging);
    unpack(fd, st.id);
    close(fd);
    char p[700];
    snprintf(p, sizeof p, "%s/.signature", staging);
    int o = open(p, O_WRONLY | O_CREAT | O_EXCL, 0644);
    size_t len = strlen(st.text);
    if (o < 0 || write(o, st.text, len) != (ssize_t)len || fsync(o) || close(o)) die("writing %s", p);

    rmtree(old);
    int moved = lstat(cur, &sb) == 0;
    if (moved && rename(cur, old)) die("rename %s: %s", cur, strerror(errno));
    if (rename(staging, cur)) {
        int e = errno;
        if (moved) rename(old, cur);
        die("rename %s: %s", staging, strerror(e));
    }
    staging[0] = 0;
    sync();
    printf("installed %s %s (%s)\n", st.id, st.version, was);
    if (moved) printf("the previous one is kept in %s\n", old);
    return 0;
}
