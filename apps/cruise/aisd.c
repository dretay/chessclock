/*
 * aisd: live ship positions for the fleet map, from AIS (aisstream.io), into $APP_DATA/ships.csv; the
 * cruise app's service runs it. ais.py's job, in C: an always-on connection is what aisstream needs (it
 * sends reports as they come, and coverage at sea is patchy), and in C that costs a couple of MB instead
 * of Python's nine.
 *
 *   aisd            (APP_DATA: where ais.key is, and ships.csv goes; default /apps/data/cruise)
 *
 * A websocket (RFC 6455) over TLS (OpenSSL, the server's certificate checked against the CA bundle) to
 * wss://stream.aisstream.io/v0/stream, subscribed to the fleet's MMSIs: position reports and static data
 * (destination, ETA). Each ship gets a line in ships.csv when it's first heard, then at most every 10
 * minutes (or when its status changes):
 *     name,lat,lon,heading,speed,unix time,destination,ETA (MM-DD HH:MM, UTC),status,MMSI
 * trimmed hourly to each ship's last 160 lines. The fleet: the Disney ships below, or AIS_SHIPS in the
 * app's countdown.conf ("MMSI=Name,MMSI=Name"). It waits for the key and for network time, pings when the
 * link goes quiet, and reconnects (waiting longer each time) when it drops.
 */
#define _DEFAULT_SOURCE
#define _DARWIN_C_SOURCE
#include <errno.h>
#include <netdb.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#include <openssl/ssl.h>
#include <openssl/x509v3.h>

#define HOST "stream.aisstream.io"
#define PATH "/v0/stream"
#define CA_FILE "/etc/ssl/certs/ca-certificates.crt"     /* (Buildroot's ca-certificates) */
#define TRAIL_EVERY (10 * 60)                           /* seconds between a ship's lines */
#define KEEP_LINES 160                                  /* trimming keeps each ship's last this many */
#define TRIM_EVERY 3600
#define QUIET 90                                        /* no frame for this long: ping; twice: reconnect */
#define MAX_SHIPS 32
#define MAX_FRAME (256 * 1024)

static const char *FLEET[][2] = {
    {"308516000", "Disney Magic"}, {"308457000", "Disney Wonder"}, {"311042900", "Disney Dream"},
    {"311058700", "Disney Fantasy"}, {"311001098", "Disney Wish"}, {"311001221", "Disney Treasure"},
    {"311001540", "Disney Destiny"}, {"311000934", "Disney Adventure"},
};
static const char *STATUS[16] = {"under way", "at anchor", "not under command", "restricted", NULL, "moored",
                                 "aground", "fishing", "sailing"};

typedef struct {
    char mmsi[16], name[48], dest[48], eta[16], status[24];
    double lat, lon, heading, speed;
    long when, written_when;
    char written_status[24];
    int known;
} ship_t;

static ship_t ships[MAX_SHIPS];
static int nships;
static char data_dir[512], ships_file[600], key_file[600], conf_file[600];
static volatile sig_atomic_t stop;
static long trimmed;

static void say(const char *fmt, ...)
{
    va_list ap;
    fputs("ais: ", stdout);
    va_start(ap, fmt); vprintf(fmt, ap); va_end(ap);
    fputc('\n', stdout); fflush(stdout);
}

static void on_term(int s) { (void)s; stop = 1; }

/* ---------------------------------------------------------------- the fleet and the key */
static void add_ship(const char *mmsi, const char *name)
{
    if (nships >= MAX_SHIPS) return;
    ship_t *s = &ships[nships++];
    memset(s, 0, sizeof *s);
    snprintf(s->mmsi, sizeof s->mmsi, "%s", mmsi);
    snprintf(s->name, sizeof s->name, "%s", name);
}

static void load_fleet(void)
{
    char line[4096];
    FILE *f = fopen(conf_file, "r");
    nships = 0;
    while (f && fgets(line, sizeof line, f)) {              /* AIS_SHIPS=MMSI=Name,MMSI=Name */
        if (strncmp(line, "AIS_SHIPS=", 10)) continue;
        char *p = line + 10, *save = NULL;
        p[strcspn(p, "\r\n")] = 0;
        for (char *part = strtok_r(p, ",", &save); part; part = strtok_r(NULL, ",", &save)) {
            char *eq = strchr(part, '=');
            if (!eq) continue;
            *eq = 0;
            while (*part == ' ') part++;
            char *name = eq + 1;
            while (*name == ' ') name++;
            if (*part && *name) add_ship(part, name);
        }
    }
    if (f) fclose(f);
    if (!nships) for (size_t i = 0; i < sizeof FLEET / sizeof *FLEET; i++) add_ship(FLEET[i][0], FLEET[i][1]);
}

static int read_key(char *key, size_t n)
{
    FILE *f = fopen(key_file, "r");
    char line[200];
    int ok = 0;
    while (f && fgets(line, sizeof line, f)) {
        line[strcspn(line, "\r\n \t")] = 0;
        if (line[0] && line[0] != '#') { snprintf(key, n, "%s", line); ok = 1; break; }
    }
    if (f) fclose(f);
    return ok;
}

static ship_t *by_mmsi(const char *m)
{
    for (int i = 0; i < nships; i++) if (!strcmp(ships[i].mmsi, m)) return &ships[i];
    return NULL;
}

/* what ships.csv already says about each ship (its destination and ETA come rarely; when it was last written) */
static void load_known(void)
{
    char line[512];
    FILE *f = fopen(ships_file, "r");
    while (f && fgets(line, sizeof line, f)) {
        if (line[0] == '#') continue;
        char *field[10] = {0}, *p = line;
        int n = 0;
        line[strcspn(line, "\r\n")] = 0;
        while (n < 10) { field[n++] = p; char *c = strchr(p, ','); if (!c) break; *c = 0; p = c + 1; }
        if (n < 10) continue;
        ship_t *s = by_mmsi(field[9]);
        if (!s) continue;
        s->lat = atof(field[1]); s->lon = atof(field[2]); s->heading = atof(field[3]); s->speed = atof(field[4]);
        s->when = s->written_when = atol(field[5]);
        snprintf(s->dest, sizeof s->dest, "%s", field[6]); snprintf(s->eta, sizeof s->eta, "%s", field[7]);
        snprintf(s->status, sizeof s->status, "%s", field[8]); snprintf(s->written_status, sizeof s->written_status, "%s", field[8]);
        s->known = 1;
    }
    if (f) fclose(f);
}

/* ---------------------------------------------------------------- ships.csv */
static void trim(void)
{
    trimmed = time(NULL);
    FILE *f = fopen(ships_file, "r");
    if (!f) return;
    static char *lines[MAX_SHIPS * KEEP_LINES * 4];
    int n = 0;
    char buf[512];
    while (fgets(buf, sizeof buf, f) && n < (int)(sizeof lines / sizeof *lines)) lines[n++] = strdup(buf);
    fclose(f);
    /* keep comments, and each ship's last KEEP_LINES lines (by its name, the first field) */
    char tmp[700];
    snprintf(tmp, sizeof tmp, "%s.tmp", ships_file);
    FILE *o = fopen(tmp, "w");
    if (o) {
        for (int i = 0; i < n; i++) {
            if (lines[i][0] == '#') { fputs(lines[i], o); continue; }
            size_t nl = strcspn(lines[i], ",");
            int later = 0;
            for (int j = i + 1; j < n && later < KEEP_LINES; j++)
                if (lines[j][0] != '#' && strcspn(lines[j], ",") == nl && !strncmp(lines[i], lines[j], nl)) later++;
            if (later < KEEP_LINES) fputs(lines[i], o);
        }
        if (fclose(o) == 0) rename(tmp, ships_file);
    }
    for (int i = 0; i < n; i++) free(lines[i]);
}

static void write_ship(ship_t *s)
{
    mkdir(data_dir, 0755);
    FILE *f = fopen(ships_file, "a");
    if (!f) return;
    fprintf(f, "%s,%.5f,%.5f,%.0f,%.1f,%ld,%s,%s,%s,%s\n", s->name, s->lat, s->lon, s->heading, s->speed, s->when,
            s->dest, s->eta, s->status, s->mmsi);
    fclose(f);
    s->written_when = s->when;
    snprintf(s->written_status, sizeof s->written_status, "%s", s->status);
    say("%s %.4f %.4f %.0fkn %s", s->name, s->lat, s->lon, s->speed, s->status);
    if (time(NULL) - trimmed > TRIM_EVERY) trim();
}

/* ---------------------------------------------------------------- just enough JSON */
/* the number after "key": in msg (the first one), or nan-ish failure */
static int num(const char *msg, const char *key, double *out)
{
    char k[64];
    snprintf(k, sizeof k, "\"%s\":", key);
    const char *p = strstr(msg, k);
    if (!p) return 0;
    p += strlen(k);
    while (*p == ' ') p++;
    char *end;
    double v = strtod(p, &end);
    if (end == p) return 0;
    *out = v;
    return 1;
}

/* the string after "key": (plain ASCII; escapes dropped) */
static int str(const char *msg, const char *key, char *out, size_t n)
{
    char k[64];
    snprintf(k, sizeof k, "\"%s\":", key);
    const char *p = strstr(msg, k);
    if (!p) return 0;
    p += strlen(k);
    while (*p == ' ') p++;
    if (*p != '"') return 0;
    p++;
    size_t i = 0;
    while (*p && *p != '"' && i + 1 < n) {
        if (*p == '\\' && p[1]) p++;
        out[i++] = (*p >= 0x20 && *p < 0x7f && *p != ',') ? *p : ' ';
        p++;
    }
    out[i] = 0;
    while (i && out[i - 1] == ' ') out[--i] = 0;    /* (AIS pads with spaces) */
    return 1;
}

/* MetaData's time_utc ("2026-11-24 06:53:10.123 +0000 UTC") as unix time; now if it's not that */
static long utc_time(const char *msg)
{
    char t[64];
    struct tm tm;
    if (!str(msg, "time_utc", t, sizeof t)) return time(NULL);
    memset(&tm, 0, sizeof tm);
    if (sscanf(t, "%d-%d-%d %d:%d:%d", &tm.tm_year, &tm.tm_mon, &tm.tm_mday, &tm.tm_hour, &tm.tm_min, &tm.tm_sec) != 6) return time(NULL);
    tm.tm_year -= 1900; tm.tm_mon -= 1;
    return (long)timegm(&tm);
}

static void message(const char *msg)
{
    char type[32], mmsi_s[24];
    double v;
    if (strstr(msg, "\"error\"")) { char e[200] = ""; str(msg, "error", e, sizeof e); say("aisstream: %s", e); return; }
    if (!str(msg, "MessageType", type, sizeof type)) return;
    const char *meta = strstr(msg, "\"MetaData\"");
    if (!meta || !num(meta, "MMSI", &v)) return;
    snprintf(mmsi_s, sizeof mmsi_s, "%.0f", v);
    ship_t *s = by_mmsi(mmsi_s);
    if (!s) return;
    const char *body = strstr(msg, "\"Message\"");
    if (!body) return;
    if (!strcmp(type, "PositionReport")) {
        double lat, lon, sog = 0, cog = 360, hd = 511, st = 15;
        if (!num(body, "Latitude", &lat) || !num(body, "Longitude", &lon)) return;
        if (lat < -90 || lat > 90 || lon < -180 || lon > 180 || (lat == 0 && lon == 0)) return;
        num(body, "Sog", &sog); num(body, "Cog", &cog); num(body, "TrueHeading", &hd); num(body, "NavigationalStatus", &st);
        s->lat = lat; s->lon = lon;
        s->speed = sog < 102.3 ? sog : 0;
        s->heading = hd < 360 ? hd : cog < 360 ? cog : s->heading;
        int si = (int)st;
        if (si >= 0 && si < 16 && STATUS[si]) snprintf(s->status, sizeof s->status, "%s", STATUS[si]);
        s->when = utc_time(meta);
        s->known = 1;
        if (!s->written_when || s->when - s->written_when >= TRAIL_EVERY || strcmp(s->written_status, s->status)) write_ship(s);
    } else if (!strcmp(type, "ShipStaticData")) {
        char dest[48];
        if (str(body, "Destination", dest, sizeof dest)) {
            for (char *c = dest; *c; c++) if (*c == '@') *c = ' ';
            snprintf(s->dest, sizeof s->dest, "%s", dest);
        }
        const char *eta = strstr(body, "\"Eta\"");
        double mo, d, h = 24, mi = 60;
        if (eta && num(eta, "Month", &mo) && num(eta, "Day", &d) && mo > 0 && d > 0) {   /* (month 0: not given) */
            num(eta, "Hour", &h); num(eta, "Minute", &mi);
            snprintf(s->eta, sizeof s->eta, "%02d-%02d %02d:%02d", (int)mo, (int)d, h < 24 ? (int)h : 0, mi < 60 ? (int)mi : 0);
        }
    }
}

/* ---------------------------------------------------------------- the websocket over TLS */
static SSL_CTX *ctx;
static SSL *ssl;
static int sock = -1;

static void hang_up(void)
{
    if (ssl) { SSL_shutdown(ssl); SSL_free(ssl); ssl = NULL; }
    if (sock >= 0) { close(sock); sock = -1; }
}

static int send_all(const void *buf, int n)
{
    const char *p = buf;
    while (n > 0) {
        int w = SSL_write(ssl, p, n);
        if (w <= 0) return -1;
        p += w; n -= w;
    }
    return 0;
}

/* read exactly n bytes, waiting at most secs for the first of them; 1 ok, 0 timeout, -1 closed/error */
static int read_n(void *buf, int n, int secs)
{
    char *p = buf;
    while (n > 0) {
        if (!SSL_pending(ssl)) {
            struct pollfd pf = {sock, POLLIN, 0};
            int r = poll(&pf, 1, secs * 1000);
            if (r == 0) return p == (char *)buf ? 0 : -1;
            if (r < 0) return errno == EINTR && !stop ? 0 : -1;
        }
        int got = SSL_read(ssl, p, n);
        if (got <= 0) {
            int e = SSL_get_error(ssl, got);
            if (e == SSL_ERROR_WANT_READ) continue;
            return -1;
        }
        p += got; n -= got; secs = 30;                  /* (the rest of a frame comes promptly) */
    }
    return 1;
}

static int send_frame(int op, const void *data, size_t n)
{
    unsigned char h[14], mask[4];
    size_t hn = 0;
    h[hn++] = 0x80 | (op & 15);
    if (n < 126) h[hn++] = 0x80 | n;
    else if (n < 65536) { h[hn++] = 0x80 | 126; h[hn++] = n >> 8; h[hn++] = n & 255; }
    else { h[hn++] = 0x80 | 127; for (int i = 7; i >= 0; i--) h[hn++] = (unsigned char)(((uint64_t)n >> (8 * i)) & 255); }
    RAND_bytes(mask, 4);
    memcpy(h + hn, mask, 4); hn += 4;
    unsigned char *m = malloc(n + 1);
    if (!m) return -1;
    for (size_t i = 0; i < n; i++) m[i] = ((const unsigned char *)data)[i] ^ mask[i & 3];
    int r = send_all(h, (int)hn) || send_all(m, (int)n) ? -1 : 0;
    free(m);
    return r;
}

static int connect_tls(void)
{
    struct addrinfo hints = {0}, *ai;
    hints.ai_socktype = SOCK_STREAM;
    if (getaddrinfo(HOST, "443", &hints, &ai)) { say("link down: can't find %s", HOST); return -1; }
    for (struct addrinfo *a = ai; a; a = a->ai_next) {
        sock = socket(a->ai_family, a->ai_socktype, a->ai_protocol);
        if (sock < 0) continue;
        if (connect(sock, a->ai_addr, a->ai_addrlen) == 0) break;
        close(sock); sock = -1;
    }
    freeaddrinfo(ai);
    if (sock < 0) { say("link down: can't connect to %s", HOST); return -1; }
    ssl = SSL_new(ctx);
    SSL_set_fd(ssl, sock);
    SSL_set_tlsext_host_name(ssl, HOST);
    SSL_set1_host(ssl, HOST);                           /* (the certificate must be for this name) */
    if (SSL_connect(ssl) != 1) {
        say("link down: TLS: %s", ERR_reason_error_string(ERR_get_error()) ?: "handshake failed");
        hang_up(); return -1;
    }
    /* the websocket handshake */
    unsigned char nonce[16];
    char key64[32], req[512], resp[2048];
    RAND_bytes(nonce, sizeof nonce);
    EVP_EncodeBlock((unsigned char *)key64, nonce, sizeof nonce);
    snprintf(req, sizeof req, "GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n", PATH, HOST, key64);
    if (send_all(req, (int)strlen(req))) { hang_up(); return -1; }
    size_t n = 0;
    while (n + 1 < sizeof resp) {                       /* up to the blank line */
        if (read_n(resp + n, 1, 15) != 1) { say("link down: no answer to the handshake"); hang_up(); return -1; }
        n++; resp[n] = 0;
        if (n >= 4 && !memcmp(resp + n - 4, "\r\n\r\n", 4)) break;
    }
    if (!strstr(resp, " 101")) { say("link down: refused (%.40s)", resp); hang_up(); return -1; }
    return 0;
}

/* one frame: 1 a message (into *out, NUL-ended), 0 nothing for QUIET seconds, -1 closed/error */
static int recv_frame(char **out, size_t *outn)
{
    unsigned char h[2];
    *outn = 0;
    for (;;) {
        int r = read_n(h, 2, QUIET);
        if (r <= 0) return r;
        int fin = h[0] & 0x80, op = h[0] & 15;
        uint64_t n = h[1] & 127;
        if (n == 126) { unsigned char e[2]; if (read_n(e, 2, 30) != 1) return -1; n = (e[0] << 8) | e[1]; }
        else if (n == 127) { unsigned char e[8]; if (read_n(e, 8, 30) != 1) return -1; n = 0; for (int i = 0; i < 8; i++) n = (n << 8) | e[i]; }
        if (h[1] & 0x80) { unsigned char m[4]; if (read_n(m, 4, 30) != 1) return -1; }   /* (servers don't mask) */
        if (*outn + n > MAX_FRAME) return -1;
        char *buf = realloc(*out, *outn + n + 1);
        if (!buf) return -1;
        *out = buf;
        if (n && read_n(buf + *outn, (int)n, 30) != 1) return -1;
        if (op == 8) return -1;                                             /* close */
        if (op == 9) { send_frame(10, buf + *outn, n); continue; }          /* ping: pong */
        if (op == 10) { continue; }                                         /* pong */
        *outn += n; buf[*outn] = 0;
        if (fin) return 1;
    }
}

static int stream(const char *key)
{
    if (connect_tls()) return -1;
    /* (within 3 s of connecting, or the server hangs up: the whole world, filtered to the fleet) */
    char sub[2048];
    int k = snprintf(sub, sizeof sub, "{\"APIKey\":\"%s\",\"BoundingBoxes\":[[[-90,-180],[90,180]]],\"FiltersShipMMSI\":[", key);
    for (int i = 0; i < nships && k < (int)sizeof sub - 64; i++) k += snprintf(sub + k, sizeof sub - k, "%s\"%s\"", i ? "," : "", ships[i].mmsi);
    snprintf(sub + k, sizeof sub - k, "],\"FilterMessageTypes\":[\"PositionReport\",\"ShipStaticData\"]}");
    if (send_frame(1, sub, strlen(sub))) { hang_up(); return -1; }
    say("connected; following %d ships", nships);
    char *msg = NULL;
    size_t n;
    int quiet = 0;
    while (!stop) {
        int r = recv_frame(&msg, &n);
        if (r < 0) { say("link down: closed"); break; }
        if (r == 0) {
            if (++quiet >= 2) { say("link down: nothing from the server for %d s", QUIET * quiet); break; }
            send_frame(9, "", 0);                                           /* are you there? */
            continue;
        }
        quiet = 0;
        message(msg);
    }
    free(msg);
    hang_up();
    return 0;
}

int main(void)
{
    const char *d = getenv("APP_DATA");
    snprintf(data_dir, sizeof data_dir, "%s", d && *d ? d : "/apps/data/cruise");
    snprintf(ships_file, sizeof ships_file, "%s/ships.csv", data_dir);
    snprintf(key_file, sizeof key_file, "%s/ais.key", data_dir);
    snprintf(conf_file, sizeof conf_file, "%s/countdown.conf", data_dir);
    signal(SIGTERM, on_term); signal(SIGINT, on_term); signal(SIGPIPE, SIG_IGN);
    load_fleet(); load_known(); trim();

    SSL_library_init(); SSL_load_error_strings();
    ctx = SSL_CTX_new(TLS_client_method());
    SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, NULL);
    if (access(CA_FILE, R_OK) == 0) SSL_CTX_load_verify_locations(ctx, CA_FILE, NULL);
    else SSL_CTX_set_default_verify_paths(ctx);

    char key[200];
    int wait = 5, said = 0;
    while (!stop) {
        if (!read_key(key, sizeof key)) {
            if (said != 1) say("no API key yet: put an aisstream.io key in %s", key_file), said = 1;
            sleep(30); continue;
        }
        if (time(NULL) < 1700000000L) {                 /* before 2023: no network time yet (TLS needs it) */
            if (said != 2) say("waiting for the clock (network time)"), said = 2;
            sleep(10); continue;
        }
        said = 0;
        time_t started = time(NULL);
        stream(key);
        if (stop) break;
        if (time(NULL) - started > 300) wait = 5;       /* it had been working: retry soon */
        sleep((unsigned)(wait + rand() % (wait / 2 + 1)));
        wait = wait * 2 > 600 ? 600 : wait * 2;
    }
    SSL_CTX_free(ctx);
    return 0;
}
