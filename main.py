#!/usr/bin/env python3
"""THE MONDAY WIRE - a broadsheet of Monday 23 November 2026.

news-image-20261123, first account. Pure Python standard library:
a bitmap-font text renderer, a raw-RGB still blitter, a small canvas
and a PNG encoder. No network, no clock, no randomness: two runs
write byte-identical entry.png.

Layout (1024x1024, warm paper, ink text, red rules):
  masthead with the date, 4 heroes in a 2x2 grid (each with its
  toon illustration, headline, summary and source), THE DAY IN BRIEF
  (12 medium stories in 3 columns, headline + summary + source),
  stories 17-40 as a numbered two-column list (headline + source),
  a stats strip and a footer. All 40 stories are verified and
  dated/reported 23 November 2026; every story prints its source.
"""
import hashlib
import math
import os
import struct
import zlib

W, H = 1024, 1024
MARGIN = 20
CW = W - 2 * MARGIN

PAPER = (247, 242, 230)
INK = (26, 24, 20)
GREY = (105, 99, 86)
FAINT = (233, 227, 213)
RED = (185, 28, 28)
NAVY = (31, 58, 95)
TEAL = (15, 118, 110)
GREEN = (34, 125, 50)
GOLD = (176, 128, 20)
PURPLE = (109, 40, 217)
ORANGE = (214, 96, 20)
SKY = (135, 180, 220)
YELLOW = (240, 200, 40)
WHITE = (255, 255, 255)
DARK = (18, 24, 38)

REGION = {
    "EUROPE": (24, 64, 120),
    "MIDDLE EAST": (185, 28, 28),
    "ASIA": (15, 118, 110),
    "AFRICA": (176, 128, 20),
    "AMERICAS": (109, 40, 217),
    "OCEANIA": (32, 120, 96),
    "GLOBAL": (105, 99, 86),
}


# ------------------------------------------------------------------ fonts
# FNT1 bitmap fonts: magic, cell height (1 byte), glyph count (big-endian
# uint16), then per glyph: codepoint (uint16 BE), width (1 byte), height
# (uint16 BE), packed bits, most-significant-bit first, row major.
class BitmapFont:
    def __init__(self, path):
        with open(path, "rb") as fh:
            data = fh.read()
        assert data[:4] == b"FNT1"
        self.cell = data[4]
        count = struct.unpack(">H", data[5:7])[0]
        self.glyphs = {}
        off = 7
        for _ in range(count):
            cp, gw, gh = struct.unpack(">HBH", data[off:off + 5])
            off += 5
            nbytes = (gw * gh + 7) // 8
            self.glyphs[cp] = (gw, gh, data[off:off + nbytes])
            off += nbytes
        self.fallback = self.glyphs[ord("?")]

    def glyph(self, ch):
        return self.glyphs.get(ord(ch), self.fallback)

    def width(self, s, scale=1):
        return sum((self.glyph(c)[0] + 1) * scale for c in s)

    def draw(self, img, x, y, s, scale, color):
        cx = x
        for ch in s:
            gw, gh, bits = self.glyph(ch)
            for yy in range(gh):
                base = yy * gw
                for xx in range(gw):
                    if (bits[(base + xx) // 8] >> (7 - (base + xx) % 8)) & 1:
                        img.box(cx + xx * scale, y + yy * scale,
                                scale, scale, color)
            cx += (gw + 1) * scale
        return cx - x

    def centred(self, img, cx, y, s, scale, color):
        self.draw(img, cx - self.width(s, scale) // 2, y, s, scale, color)

    def wrap(self, s, scale, maxw):
        """Greedy word wrap; returns a list of lines."""
        out = []
        for chunk in s.split("\n"):
            words = chunk.split(" ")
            cur = ""
            for wd in words:
                trial = wd if not cur else cur + " " + wd
                if self.width(trial, scale) <= maxw or not cur:
                    cur = trial
                else:
                    out.append(cur)
                    cur = wd
            if cur:
                out.append(cur)
        return out

    def shorten(self, s, scale, maxw):
        if self.width(s, scale) <= maxw:
            return s
        while s and self.width(s + "..", scale) > maxw:
            s = s[:-1]
        return s + ".."


BASE = os.path.dirname(os.path.abspath(__file__))
F8 = BitmapFont(os.path.join(BASE, "fonts", "font8.bin"))
F11 = BitmapFont(os.path.join(BASE, "fonts", "font11.bin"))
F16 = BitmapFont(os.path.join(BASE, "fonts", "font16.bin"))
F24 = BitmapFont(os.path.join(BASE, "fonts", "font24.bin"))


# ------------------------------------------------------------------ canvas
class Canvas:
    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(w * h * 3)
        self.box(0, 0, w, h, bg)

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = c[0]
            self.px[i + 1] = c[1]
            self.px[i + 2] = c[2]

    def box(self, x, y, w, h, c):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        row = bytes(c) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def frame(self, x, y, w, h, c, t=1):
        self.box(x, y, w, t, c)
        self.box(x, y + h - t, w, t, c)
        self.box(x, y, t, h, c)
        self.box(x + w - t, y, t, h, c)

    def hline(self, x, y, w, c, t=1):
        self.box(x, y, w, t, c)

    def vline(self, x, y, h, c, t=1):
        self.box(x, y, t, h, c)

    def line(self, x0, y0, x1, y1, c, t=1):
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.box(x0, y0, t, t, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def disc(self, cx, cy, r, c):
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r:
                    self.set(xx, yy, c)

    def triangle(self, x0, y0, x1, y1, x2, y2, c):
        pts = [(x0, y0), (x1, y1), (x2, y2)]
        for y in range(min(y0, y1, y2), max(y0, y1, y2) + 1):
            xs = []
            for i in range(3):
                ax, ay = pts[i]
                bx, by = pts[(i + 1) % 3]
                if (ay <= y < by) or (by <= y < ay):
                    xs.append(ax + (y - ay) * (bx - ax) / (by - ay))
            xs.sort()
            for j in range(0, len(xs) - 1, 2):
                self.box(int(xs[j]), y, int(xs[j + 1]) - int(xs[j]), 1, c)

    def blit_rgb(self, raw, sw, sh, dx, dy, dw, dh):
        """Nearest-neighbour scale of a raw RGB buffer onto the canvas."""
        for yy in range(dh):
            sy = yy * sh // dh
            srow = sy * sw * 3
            drow = (dy + yy) * self.w * 3 + dx * 3
            for xx in range(dw):
                sx = xx * sw // dw
                si = srow + sx * 3
                di = drow + xx * 3
                self.px[di] = raw[si]
                self.px[di + 1] = raw[si + 1]
                self.px[di + 2] = raw[si + 2]


def text(img, x, y, s, font, scale, color, align="l"):
    if align == "c":
        font.centred(img, x, y, s, scale, color)
    elif align == "r":
        font.draw(img, x - font.width(s, scale), y, s, scale, color)
    else:
        font.draw(img, x, y, s, scale, color)


def para(img, x, y, s, font, scale, color, maxw, lh):
    lines = font.wrap(s, scale, maxw)
    for i, ln in enumerate(lines):
        font.draw(img, x, y + i * lh, ln, scale, color)
    return len(lines)


def write_png(img, path):
    raw = bytearray()
    for y in range(img.h):
        raw.append(0)
        raw.extend(img.px[y * img.w * 3:(y + 1) * img.w * 3])
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        out = struct.pack(">I", len(data)) + typ + data
        return out + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", img.w, img.h, 8, 2, 0, 0, 0)
    blob = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp) + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(blob)
    return len(blob)


# ------------------------------------------------------------------ stills
STILLS = {}


def still(name):
    if name not in STILLS:
        with open(os.path.join(BASE, "stills", name + ".rgb"), "rb") as fh:
            STILLS[name] = fh.read()
    return STILLS[name]


# ------------------------------------------------------------------ stories
# (tag, headline, summary, source, region, still-or-None)
HEROES = [
    ("SANTA CLARA, USA - MARKETS",
     "NVIDIA: HUANG IS BACK - SHARES +31.5%",
     "Huang reinstated as CEO. Shares +31.5%, best day since 2003.",
     "Reuters, BBC, CNN", "AMERICAS", "nvidia"),
    ("ANTALYA, TURKIYE - CLIMATE",
     "COP31 COLLAPSES: NO DEAL AFTER RECORD OVERTIME",
     "No deal after 44+ hours of overtime, the longest COP ever.",
     "Reuters", "GLOBAL", "cop31"),
    ("DYMER, UKRAINE - WAR",
     "DRONE HITS KYIV FLATS; 11 DEAD",
     "Drone hits a block in Dymer; 11 dead, including an 11-year-old girl.",
     "Reuters, AP, AFP", "EUROPE", None),
    ("WASHINGTON, USA - POLITICS",
     "TRUMP BACKS 10% CARD-RATE CAP - WITH THE DEMOCRATS",
     "Trump will work with Democrats to cap card interest at 10% for a year.",
     "AP, Fox News", "AMERICAS", "trump10"),
]

# (tag, headline, summary, source, region, still-or-icon)
MEDIUMS = [
    ("CIKANDE, INDONESIA - DISASTER",
     "FACTORY FIRE: 24 DEAD, ~30 STILL MISSING",
     "Candy factory fire; 24 dead, ~30 missing.",
     "Reuters", "ASIA", "flame"),
    ("NEW YORK, USA - TECH",
     "CROWDSTRIKE BUYS ZSCALER FOR $44BN",
     "Biggest cybersecurity deal ever, all stock.",
     "Reuters", "AMERICAS", "crowdstrike"),
    ("SINALOA, MEXICO - CRIME",
     "MEXICO CAPTURES FBI MOST-WANTED 'CHAPO ISIDRO'",
     "FBI most-wanted capo seized; 11 killed.",
     "AP", "AMERICAS", "shield"),
    ("BRUSSELS, BELGIUM - SECURITY",
     "NATO MEETS ON MISSILES OVER POLAND",
     "NATO meets after missiles cross Poland.",
     "Reuters", "EUROPE", "globe"),
    ("WASHINGTON, USA - TECH",
     "STATES SUE MUSK OVER GROK SEXUALIZED IMAGES",
     "States sue over sexualized AI images.",
     "AP", "AMERICAS", "scale"),
    ("LIVERPOOL, ENGLAND - SPORT",
     "LIVERPOOL ROUT UNITED 4-0 IN POCHETTINO DEBUT",
     "Pochettino's debut as United boss ends 4-0.",
     "ESPN, BBC", "EUROPE", "liverpool"),
    ("LAS VEGAS, USA - SPORT",
     "VERSTAPPEN WINS CHAOTIC VEGAS GRAND PRIX",
     "35 lead changes; Ferraris collide.",
     "ESPN, Sky Sports", "AMERICAS", "verstappen"),
    ("WELLINGTON, NEW ZEALAND - SPORT",
     "INDIA POST RECORD 720/9 IN WELLINGTON TEST",
     "Record Test innings on day 4 in Wellington.",
     "ESPNcricinfo", "OCEANIA", "india720"),
    ("WASHINGTON, USA - POLITICS",
     "DEMOCRATS CLINCH 258-SEAT HOUSE MAJORITY",
     "Largest House majority since 1992.",
     "AP", "AMERICAS", "flag"),
    ("MEXICO CITY, MEXICO - SPORT",
     "49ERS ROUT VIKINGS 35-10 IN MEXICO CITY",
     "Purdy throws three TD passes.",
     "AP", "AMERICAS", "ball"),
    ("WASHINGTON, USA - FOREIGN POLICY",
     "TRUMP 'INCLINED' TO RESUME IRAN CONFLICT",
     "Trump 'inclined' to resume conflict if no deal.",
     "Economic Times, AP", "MIDDLE EAST", "bolt"),
    ("SAN FRANCISCO, USA - TECH",
     "OPENAI RELEASES GPT-6.2 ASTRA AND SOL",
     "Astra and Sol out; Astra 20% cheaper.",
     "Reuters", "GLOBAL", "gpt62"),
]

# (number, headline, source)
REST = [
    (17, "LAVROV CALLS KYIV 'ANCESTRAL RUSSIAN LANDS'", "Independent"),
    (18, "UKRAINE SINKS RUSSIAN CORVETTE AT BENGHAZI", "Reuters"),
    (19, "ODESA SCHOOLS GO REMOTE 23-27 NOV", "Washington Post"),
    (20, "EU PROPOSES SMALLER BUDGET, 100BN EURO FOR UKRAINE", "EU"),
    (21, "THOUSANDS MARCH IN LISBON OVER LIVING COSTS", "Reuters"),
    (22, "THOUSANDS PROTEST MEDIA CLOSURES IN ISTANBUL", "AP"),
    (23, "UN TALKS ON LETHAL AI WEAPONS TO CONTINUE", "UN"),
    (24, "TWO TANKERS HIT IN STRAIT OF HORMUZ", "UKMTO"),
    (25, "EISENKOT: SETTLER VIOLENCE IS 'JEWISH TERRORISM'", "Al Jazeera"),
    (26, "SAUDI COALITION INTERCEPTS HOUTHI MISSILE", "Arab News"),
    (27, "PAKISTAN FM HOPEFUL ON US-IRAN DEAL", "Arab News"),
    (28, "FIGHTING NEAR CONGO EBOLA AREA DISRUPTS RESPONSE", "WHO"),
    (29, "PHILIPPINES LEADS ASIA-PACIFIC FARM TALKS", "DA / FAO"),
    (30, "SHIP FIRE AT CHINESE PORT KILLS 25", "AP"),
    (31, "NEPAL PM HOLDS TALKS WITH MODI", "PTI"),
    (32, "S KOREA MINISTER QUITS OVER AI EXAM-CHEATING SCANDAL", "Reuters"),
    (33, "FBI PROBES BREACH OF ITS CRIME DATABASE", "AP"),
    (34, "WASHINGTON GOVERNOR: ICE 'OUT OF CONTROL'", "AP"),
    (35, "THREE KILLED AT OHIO BABY SHOWER", "AP"),
    (36, "'SUNRISE ON THE REAPING' OPENS AT $120M", "Exhibitor Relations"),
    (37, "MILEY CYRUS MARRIES MAXX MORANDO", "AP"),
    (38, "FRANCE ROUT ARGENTINA 45-17", "AFP"),
    (39, "BOWEN: COP31 OUTCOME 'VERY DISAPPOINTING'", "Reuters"),
    (40, "DELTA DELAYS TOP 1,000 FLIGHTS AT ATLANTA HUB", "Xinhua"),
]

STATS = [
    ("+31.5%", "NVIDIA SHARES"),
    ("0", "COP31 DEAL"),
    ("24", "DEAD IN JAVA FIRE"),
    ("258", "DEM HOUSE SEATS"),
    ("153", "DRONES OVERNIGHT"),
    ("$44BN", "CYBER DEAL"),
]


# ------------------------------------------------------- drawn art + icons
def draw_dymer(img, x, y, w, h):
    """Night scene for the Dymer drone strike (no still exists for H3)."""
    img.box(x, y, w, h, DARK)
    for i in range(18):
        sx = x + 8 + (i * 47) % (w - 16)
        sy = y + 6 + (i * 23) % 34
        img.disc(sx, sy, 1, (200, 210, 224))
    # drone, top right
    dx, dy = x + w - 46, y + 22
    img.box(dx - 12, dy - 3, 24, 6, (180, 190, 205))
    img.box(dx - 2, dy - 9, 4, 18, (180, 190, 205))
    img.box(dx - 22, dy - 10, 16, 3, (180, 190, 205))
    img.box(dx + 6, dy - 10, 16, 3, (180, 190, 205))
    img.box(dx - 22, dy + 7, 16, 3, (180, 190, 205))
    img.box(dx + 6, dy + 7, 16, 3, (180, 190, 205))
    # explosion burst
    ex, ey = x + w - 96, y + 56
    img.disc(ex, ey, 15, ORANGE)
    img.disc(ex, ey, 8, YELLOW)
    for k in range(8):
        a = k * math.pi / 4
        img.line(ex, ey, int(ex + 26 * math.cos(a)),
                 int(ey + 26 * math.sin(a)), ORANGE, 2)
    # buildings, bottom
    img.box(x + 10, y + h - 58, 48, 58, (60, 66, 80))
    img.box(x + 66, y + h - 78, 42, 78, (70, 76, 92))
    img.box(x + 116, y + h - 46, 38, 46, (60, 66, 80))
    for bx in (x + 18, x + 32, x + 46):
        for by in range(y + h - 52, y + h - 6, 12):
            img.box(bx, by, 6, 7, YELLOW)
    for bx in (x + 74, x + 90):
        for by in range(y + h - 72, y + h - 6, 12):
            img.box(bx, by, 6, 7, YELLOW)
    img.box(x + 78, y + h - 40, 16, 11, ORANGE)
    text(img, x + 12, y + h - 26, "11 DEAD", F24, 1, WHITE)


def draw_icon(img, x, y, s, kind, color):
    """Small white pictogram on a coloured tile."""
    cx, cy = x + s // 2, y + s // 2
    if kind == "flame":
        img.disc(cx, y + s // 2, s // 4, WHITE)
        img.triangle(cx - s // 4, y + s // 2, cx + s // 4, y + s // 2,
                     cx, y + 3, WHITE)
        img.disc(cx, y + s * 2 // 3, s // 8, YELLOW)
    elif kind == "shield":
        img.triangle(cx, y + 2, cx + s // 2 - 2, y + s // 4,
                     cx, y + s - 2, WHITE)
        img.triangle(cx, y + 2, cx - s // 2 + 2, y + s // 4,
                     cx, y + s - 2, WHITE)
        img.box(cx - 2, y + s // 3, 4, s // 3, color)
    elif kind == "globe":
        img.disc(cx, cy, s // 2 - 2, WHITE)
        img.disc(cx - s // 6, cy - s // 6, s // 6, color)
        img.disc(cx + s // 6, cy + s // 6, s // 7, color)
    elif kind == "scale":
        img.box(cx - 1, y + 3, 3, s - 8, WHITE)
        img.box(x + 3, y + 5, s - 6, 3, WHITE)
        img.triangle(x + 3, y + 9, x + s // 2 - 3, y + 9,
                     x + s // 4, y + s // 2 + 2, WHITE)
        img.triangle(x + s // 2 + 3, y + 9, x + s - 3, y + 9,
                     x + s * 3 // 4, y + s // 2 + 2, WHITE)
        img.box(x + s // 4, y + s - 6, s // 2, 4, WHITE)
    elif kind == "flag":
        img.box(x + 5, y + 3, 3, s - 6, WHITE)
        img.triangle(x + 8, y + 3, x + s - 3, y + s // 5, x + 8,
                     y + s // 3, WHITE)
    elif kind == "ball":
        img.disc(cx, cy, s // 2 - 2, WHITE)
        img.disc(cx, cy, s // 6, color)
    elif kind == "bolt":
        img.triangle(cx + s // 4, y + 2, cx - s // 5, cy,
                     cx + s // 10, cy, WHITE)
        img.triangle(cx - s // 4, y + s - 2, cx + s // 5, cy,
                     cx - s // 10, cy, WHITE)


# ------------------------------------------------------------------ layout
def hero_card(img, x, y, w, h, tag, headline, deck, source, region, art):
    img.frame(x, y, w, h, INK, 1)
    img.box(x + 1, y + 1, w - 2, 4, REGION[region])
    iw = 213
    if art is None:
        draw_dymer(img, x + 1, y + 5, iw, h - 6)
    else:
        img.blit_rgb(still(art), 600, 450, x + 1, y + 5, iw, h - 6)
    img.frame(x + 1, y + 5, iw, h - 6, INK, 1)
    tx = x + iw + 12
    tw = w - iw - 20
    ty = y + 10
    text(img, tx, ty, tag, F8, 1, REGION[region])
    ty += 13
    n = para(img, tx, ty, headline, F16, 1, INK, tw, 20)
    ty += n * 20 + 4
    n = para(img, tx, ty, deck, F11, 1, GREY, tw, 13)
    ty += n * 13 + 5
    text(img, tx, ty, "Source: " + source, F8, 1, GREY)


def medium_card(img, x, y, w, h, tag, headline, deck, source, region, art):
    img.frame(x, y, w, h, INK, 1)
    img.box(x + 1, y + 1, w - 2, 3, REGION[region])
    tw, th = 64, 48
    tx0, ty0 = x + 8, y + 13
    if art in ("crowdstrike", "liverpool", "verstappen", "india720",
               "gpt62"):
        img.blit_rgb(still(art), 600, 450, tx0, ty0, tw, th)
    else:
        img.box(tx0, ty0, tw, th, REGION[region])
        draw_icon(img, tx0 + 8, ty0 + 4, 40, art, REGION[region])
    img.frame(tx0, ty0, tw, th, INK, 1)
    tx = x + 80
    twd = w - 88
    ty = y + 6
    text(img, tx, ty, tag, F8, 1, REGION[region])
    ty += 12
    n = para(img, tx, ty, headline, F11, 1, INK, twd, 13)
    ty += n * 13 + 2
    text(img, tx, ty, F8.shorten(deck, 1, twd), F8, 1, INK)
    ty += 12
    text(img, tx, ty, "Source: " + source, F8, 1, GREY)


def build():
    img = Canvas(W, H, PAPER)
    # --- masthead ---
    text(img, W // 2, 8, "THE MONDAY WIRE", F24, 2, INK, align="c")
    text(img, W // 2, 74, "Monday, 23 November 2026", F16, 1, RED, align="c")
    img.hline(MARGIN, 98, CW, RED, 3)
    img.hline(MARGIN, 103, CW, INK, 1)

    # --- heroes, 2x2 grid ---
    hw = (CW - 8) // 2
    hh = 160
    hy = 110
    for i, hero in enumerate(HEROES):
        hx = MARGIN + (i % 2) * (hw + 8)
        hyy = hy + (i // 2) * (hh + 8)
        hero_card(img, hx, hyy, hw, hh, *hero)
    y = hy + 2 * hh + 8  # 438

    # --- the day in brief: 12 mediums, 3 columns x 4 rows ---
    y += 8
    text(img, MARGIN, y, "THE DAY IN BRIEF", F11, 1, RED)
    text(img, W - MARGIN, y, "12 MORE STORIES", F8, 1, GREY, align="r")
    y += 16
    img.hline(MARGIN, y, CW, INK, 1)
    y += 6
    mw = (CW - 12) // 3
    mh = 74
    for i, med in enumerate(MEDIUMS):
        mx = MARGIN + (i % 3) * (mw + 6)
        my = y + (i // 3) * (mh + 6)
        medium_card(img, mx, my, mw, mh, *med)
    y += 4 * mh + 3 * 6  # 470 + 314 = 784

    # --- stories 17-40, numbered, 2 columns ---
    y += 8
    text(img, MARGIN, y, "MORE OF THE DAY - STORIES 17 TO 40", F11, 1, RED)
    y += 16
    img.hline(MARGIN, y, CW, INK, 1)
    y += 6
    colw = (CW - 16) // 2
    per = (len(REST) + 1) // 2
    for i, (n, head, src) in enumerate(REST):
        col = i // per
        row = i % per
        x = MARGIN + col * (colw + 16)
        yy = y + row * 12
        num = str(n) + "."
        text(img, x, yy, num, F8, 1, RED)
        sw = F8.width(src, 1)
        head = F8.shorten(head, 1, colw - 26 - sw - 8)
        text(img, x + 26, yy, head, F8, 1, INK)
        text(img, x + colw - sw, yy, src, F8, 1, GREY)
    y += per * 12  # 12 rows

    # --- stats strip ---
    y += 6
    img.hline(MARGIN, y, CW, INK, 1)
    y += 8
    seg = CW // len(STATS)
    for i, (num, lab) in enumerate(STATS):
        x = MARGIN + i * seg
        text(img, x, y, num, F16, 1, RED)
        text(img, x, y + 22, lab, F8, 1, GREY)
        if i:
            img.vline(x - 8, y + 2, 30, FAINT, 1)
    y += 34
    img.hline(MARGIN, y, CW, INK, 1)
    y += 7
    text(img, W // 2, y,
         "40 stories, all reported Monday 23 November 2026 - sources beside every story.",
         F8, 1, GREY, align="c")
    assert y + 12 <= H, y
    return img


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    img = build()
    path = os.path.join(out_dir, "entry.png")
    n = write_png(img, path)
    digest = hashlib.sha256(open(path, "rb").read()).hexdigest()
    print("wrote", path, n, "bytes", "sha256", digest)


if __name__ == "__main__":
    main()
