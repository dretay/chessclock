/* modinstall: check a vacation-countdown module's signature, and install it.
 *
 *   modinstall [--check] [--force] [--keys FILE] [--dir DIR] MODULE.tar.gz [MODULE.tar.gz.sig]
 *
 * A module comes as a tarball (tools/modules/pack.py) and a signed statement beside it (.sig):
 *
 *   licheepi-module 1
 *   id castle
 *   name Magic Kingdom
 *   version 0.1.0
 *   api 1
 *   size 2227697                 (the tarball's, in bytes)
 *   sha512 <128 hex>             (the tarball's)
 *   key <16 hex>                 (the signing key: the first 8 bytes of its public key)
 *   sig <128 hex>                (Ed25519, over every line above this one)
 *
 * The statement's signature is checked against the public keys in /etc/modules/trusted.keys (in the
 * base system, where a module can't change them), then the tarball's size and SHA-512 against the
 * statement; nothing in the tarball is read before both match. Then it's unpacked into a staging folder
 * (regular files and folders only, all under ID/, no "..", no links), and swapped in for the module's
 * folder in one rename; the previous one stays as .old-ID. Refused: a version older than the one
 * installed (--force allows it), or an api newer than the host's (modules.py's API).
 *
 * --check: only check the signature and the tarball. Memory: a few KB whatever the module's size
 * (the tarball is hashed and unpacked as a stream).
 */
#define _XOPEN_SOURCE 700
#define _DEFAULT_SOURCE
#define _DARWIN_C_SOURCE                /* (for testing on a Mac: O_NOFOLLOW) */
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <ftw.h>
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
    char id[33], version[33], name[80];
    long api;
    long long size;
    uint8_t sha512[64], key[8], sig[64];
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
        *end = '\n';                     /* (put back: the signature covers the text as it was) */
        line = end + 1;
    }
    if (have != 63) { *why = "a line is missing or bad (id, version, api, size, sha512, key)"; return -1; }
    if (!good_id(st->id)) { *why = "bad id"; return -1; }
    if (!good_version(st->version)) { *why = "bad version"; return -1; }
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
    if (fstat(fd, &sb) || !S_ISREG(sb.st_mode)) die("the module isn't a regular file");
    if (sb.st_size != st->size) die("the module is %lld bytes, the statement says %lld", (long long)sb.st_size, st->size);
    crypto_sha512_ctx ctx;
    crypto_sha512_init(&ctx);
    static uint8_t buf[16384];
    ssize_t n;
    long long total = 0;
    while ((n = read(fd, buf, sizeof buf)) > 0) { crypto_sha512_update(&ctx, buf, (size_t)n); total += n; }
    if (n < 0 || total != st->size) die("couldn't read the module");
    uint8_t h[64];
    crypto_sha512_final(&ctx, h);
    if (crypto_verify64(h, st->sha512)) die("the module doesn't match its statement (changed, or the wrong file)");
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

/* the host's module API (modules.py: "API = N"), or -1 if it can't tell */
static long host_api(const char *dir)
{
    char path[600], buf[16384];
    snprintf(path, sizeof path, "%s/../modules.py", dir);
    if (read_file(path, buf, sizeof buf) < 0) return -1;
    char *p = strstr(buf, "\nAPI = ");
    return p ? strtol(p + 7, NULL, 10) : -1;
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
    if (lseek(fd, 0, SEEK_SET)) die("couldn't reread the module");
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
        if (!rel) die("a file outside the module, or a bad name: %s", path);
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
        if (!strcmp(rel, "module.json")) has_meta = 1;
    }
    gzclose(gz);
    if (!has_meta) die("no module.json in the module");
}

static const char *usage =
    "usage: modinstall [--check] [--force] [--keys FILE] [--dir DIR] MODULE.tar.gz [MODULE.tar.gz.sig]\n"
    "  check a module's signature (--check: only that), then install it into DIR\n"
    "  (default /apps/vacation/modules; keys: /etc/modules/trusted.keys)\n";

int main(int argc, char **argv)
{
    const char *keys = "/etc/modules/trusted.keys", *dir = "/apps/vacation/modules", *tar = NULL, *sig = NULL;
    int check_only = 0, force = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--check")) check_only = 1;
        else if (!strcmp(argv[i], "--force")) force = 1;
        else if (!strcmp(argv[i], "--keys") && i + 1 < argc) keys = argv[++i];
        else if (!strcmp(argv[i], "--dir") && i + 1 < argc) dir = argv[++i];
        else if (argv[i][0] == '-') { fputs(usage, stderr); return 2; }
        else if (!tar) tar = argv[i];
        else if (!sig) sig = argv[i];
        else { fputs(usage, stderr); return 2; }
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

    long api = host_api(dir);
    if (api >= 0 && st.api > api) die("%s %s needs a newer app (module api %ld; this one is %ld)", st.id, st.version, st.api, api);
    char cur[600], old[600], was[80] = "new";
    snprintf(cur, sizeof cur, "%s/%s", dir, st.id);
    snprintf(old, sizeof old, "%s/.old-%s", dir, st.id);
    struct stat sb;
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
