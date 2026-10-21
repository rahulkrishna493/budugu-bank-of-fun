#!/usr/bin/env python3
"""Kids Play Bank - prints play rupee notes and coins on an ESC/POS printer.

Runs on the Raspberry Pi. Open http://<pi>.local:8080 on any phone/tablet.
Config via environment variables (set in kidsbank.service):
  PRINTER       /dev/usb/lp0 (USB, default)  or  tcp://192.168.1.50:9100 (network)
  PAPER_DOTS    576 for 80mm paper (default), 384 for 58mm
  BANK_NAME     name printed on the notes
  PORT          web port (default 8080)
"""
import io, json, os, random, socket, string, threading, datetime, time, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageDraw, ImageFont

PRINTER = os.environ.get("PRINTER", "/dev/usb/lp0")
DOTS = int(os.environ.get("PAPER_DOTS", "576"))
BANK = os.environ.get("BANK_NAME", "BANK OF FUN")
PORT = int(os.environ.get("PORT", "8080"))
# Everycom LAN printer rule (verified in print-server/PROTOCOL.md): one TCP
# connection per job - connect, write all bytes, close immediately. Never probe
# the printer, never hold the socket open; its network chip hangs otherwise.
# A second image sent in the same stream as the first comes out as garbage, so
# every note/coin is its own job, with a pause so the printer finishes first.
PIECE_PAUSE = float(os.environ.get("PIECE_PAUSE", "3.0"))   # seconds between pieces
FEED_LINES = int(os.environ.get("FEED_LINES", "0"))         # extra blank lines before the cut (GS V 66 already feeds to the cutter)
NOTES = [10, 20, 50, 100, 200, 500, 2000]
COINS = [1, 2, 5]
lock = threading.Lock()

FONT_DIRS = ["/usr/share/fonts/truetype/dejavu/"]
def font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in FONT_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)

WORDS = {1: "ONE", 2: "TWO", 5: "FIVE", 10: "TEN", 20: "TWENTY", 50: "FIFTY",
         100: "ONE HUNDRED", 200: "TWO HUNDRED", 500: "FIVE HUNDRED", 2000: "TWO THOUSAND"}
ANIMALS = ["TIGER", "PEACOCK", "ELEPHANT", "LOTUS", "ROCKET", "LION", "PARROT", "MANGO"]


def center(d, y, text, f, w=DOTS):
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, y), text, font=f, fill=0)


def serial():
    return "".join(random.choices(string.ascii_uppercase, k=2)) + " " + "".join(random.choices(string.digits, k=6))


def draw_star(d, cx, cy, r, fill=0):
    import math
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy - rr * math.sin(a)))
    d.polygon(pts, fill=fill)


def render_note(value, holder=""):
    W, H = DOTS, int(DOTS * 0.5)
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)
    m = 6
    d.rectangle([m, m, W - m, H - m], outline=0, width=4)
    d.rectangle([m + 10, m + 10, W - m - 10, H - m - 10], outline=0, width=1)
    # guilloche-ish pattern band on the left
    for i in range(0, 120, 8):
        d.ellipse([m + 18 + i // 3, H // 2 - 50 + i // 4, m + 108 - i // 3, H // 2 + 50 - i // 4], outline=0)
    s = W / 576
    center(d, m + 18, BANK, font(int(30 * s)))
    center(d, m + 18 + int(36 * s), "PLAY MONEY  -  NOT REAL CURRENCY", font(int(15 * s), False))
    # big value
    big = font(int(110 * s))
    txt = f"₹{value}"
    tw = d.textlength(txt, font=big)
    d.text(((W - tw) / 2 + 30 * s, H / 2 - 62 * s), txt, font=big, fill=0)
    center(d, H / 2 + 58 * s, f"{WORDS[value]} FUN RUPEES", font(int(20 * s)))
    # corner values
    cf = font(int(22 * s))
    d.text((m + 20, H - m - 20 - 26 * s), str(value), font=cf, fill=0)
    tw = d.textlength(str(value), font=cf)
    d.text((W - m - 20 - tw, H - m - 20 - 26 * s), str(value), font=cf, fill=0)
    draw_star(d, W - m - 40 * s, m + 40 * s, 18 * s)
    small = font(int(13 * s), False)
    line = f"No. {serial()}   {random.choice(ANIMALS)} SERIES"
    if holder:
        line = f"For: {holder[:18]}   " + line
    center(d, H - m - 22 - 16 * s, line, small)
    return img


def render_coin(value):
    W, H = DOTS, int(DOTS * 0.42)
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)
    r = H // 2 - 8
    cx, cy = W // 2, H // 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=0, width=5)
    d.ellipse([cx - r + 12, cy - r + 12, cx + r - 12, cy + r - 12], outline=0, width=1)
    for i in range(36):  # milled edge dots
        import math
        a = i * math.pi / 18
        x, y = cx + (r - 6) * math.cos(a), cy + (r - 6) * math.sin(a)
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=0)
    s = W / 576
    f = font(int(80 * s))
    t = f"₹{value}"
    tw = d.textlength(t, font=f)
    d.text((cx - tw / 2, cy - 52 * s), t, font=f, fill=0)
    center(d, cy + 40 * s, "PLAY COIN", font(int(16 * s)))
    center(d, cy - r + 30, BANK, font(int(13 * s), False))
    # scissor guide
    for x in range(0, W, 14):
        d.line([x, 2, x + 7, 2], fill=0)
    return img


IMAGE_MODE = os.environ.get("IMAGE_MODE", "bitimage")  # "bitimage" (ESC *) or "raster" (GS v 0)


def to_raster(img):
    """GS v 0 raster, in bands of <=200 rows (some printers ignore the high height byte).
    NOT supported by the Everycom printer - it prints the data as text."""
    img = img.convert("1")
    w, h = img.size
    wb = (w + 7) // 8
    px = img.load()
    out = bytearray()
    for y0 in range(0, h, 200):
        rows = min(200, h - y0)
        data = bytearray()
        for y in range(y0, y0 + rows):
            for xb in range(wb):
                b = 0
                for bit in range(8):
                    x = xb * 8 + bit
                    if x < w and px[x, y] == 0:
                        b |= 0x80 >> bit
                data.append(b)
        out += b"\x1dv0\x00" + bytes([wb & 255, wb >> 8, rows & 255, rows >> 8]) + bytes(data)
    return bytes(out)


def to_bitimage(img):
    """ESC * 33 (24-dot double density) column bit-image, 24 rows per band.
    Line spacing is set to 24 dots so the bands join without gaps."""
    img = img.convert("1")
    w, h = img.size
    px = img.load()
    out = bytearray(b"\x1b3\x18")  # ESC 3 24: line spacing 24 dots
    for y0 in range(0, h, 24):
        out += b"\x1b*\x21" + bytes([w & 255, w >> 8])
        for x in range(w):
            for k in range(3):
                b = 0
                for bit in range(8):
                    y = y0 + k * 8 + bit
                    if y < h and px[x, y] == 0:
                        b |= 0x80 >> bit
                out.append(b)
        out += b"\n"
    out += b"\x1b2"  # ESC 2: default line spacing
    return bytes(out)


def to_escpos(img):
    return to_raster(img) if IMAGE_MODE == "raster" else to_bitimage(img)


CUT_FEED = b"\x1dV\x42\x00"  # GS V 66 0: feed to the cutter, then partial cut


def send(raw):
    """One job: connect, write everything in one go, close at once (escpos-php style)."""
    if PRINTER.startswith("tcp://"):
        host, port = PRINTER[6:].rsplit(":", 1)
        s = socket.create_connection((host, int(port)), timeout=10)
        try:
            s.sendall(raw)
        finally:
            s.close()
    else:
        with open(PRINTER, "wb") as f:
            f.write(raw)


def build_pieces(items, holder):
    pieces = []
    for it in items:
        v, q = int(it["value"]), max(0, min(20, int(it["qty"])))
        if v not in NOTES + COINS:
            continue
        for _ in range(q):
            img = render_note(v, holder) if v in NOTES else render_coin(v)
            # init, image, plain LF feed, partial cut - one cut per piece
            pieces.append(b"\x1b@" + to_escpos(img) + b"\n" * FEED_LINES + CUT_FEED)
    return pieces


def print_rest(pieces, start):
    """Background: remaining pieces, one job each, with a pause between jobs."""
    with lock:
        for i in range(start, len(pieces)):
            time.sleep(PIECE_PAUSE)
            try:
                send(pieces[i])
            except Exception as e:
                print(f"print failed on piece {i + 1}/{len(pieces)}: {e}", file=sys.stderr, flush=True)
                return
        print(f"printed {len(pieces)} pieces", flush=True)


def print_items(items, holder):
    pieces = build_pieces(items, holder)
    if not pieces:
        return 0
    with lock:
        send(pieces[0])  # first piece now, so a dead printer shows as an error
    if len(pieces) > 1:
        threading.Thread(target=print_rest, args=(pieces, 1), daemon=True).start()
    return len(pieces)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kids Play Bank</title>
<style>
:root{--bg:#fff7e6;--ink:#2b2118;--note:#2e7d4f;--coin:#c98a12;--card:#fff}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:20px 16px 8px;text-align:center}h1{margin:0;font-size:28px}
p.sub{margin:4px 0 0;opacity:.7}
main{max-width:720px;margin:0 auto;padding:16px}
h2{font-size:16px;text-transform:uppercase;letter-spacing:.08em;opacity:.7;margin:20px 0 8px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.item{background:var(--card);border-radius:14px;padding:12px;border:3px solid var(--note);text-align:center}
.item.coin{border-color:var(--coin);border-radius:60px}
.val{font-size:30px;font-weight:800}
.q{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:8px}
.q button{width:40px;height:40px;border-radius:50%;border:0;font-size:22px;background:#eee;cursor:pointer}
.q span{min-width:24px;font-size:20px;font-weight:700}
input{width:100%;padding:12px;font-size:18px;border-radius:10px;border:2px solid #ccc}
.bar{position:sticky;bottom:0;background:var(--bg);padding:12px 0;display:flex;gap:10px;align-items:center}
.total{flex:1;font-size:20px;font-weight:700}
#go{padding:14px 22px;font-size:20px;border:0;border-radius:12px;background:var(--note);color:#fff;font-weight:700}
#go:disabled{opacity:.5}#msg{text-align:center;min-height:24px;font-weight:600}
</style></head><body>
<header><h1>🏦 Kids Play Bank</h1><p class="sub">Pick your money, then press Print!</p></header>
<main>
<h2>Your name</h2><input id="holder" maxlength="18" placeholder="e.g. Aarav">
<h2>Notes</h2><div class="grid" id="notes"></div>
<h2>Coins</h2><div class="grid" id="coins"></div>
<div class="bar"><div class="total">Total: ₹<span id="tot">0</span></div><button id="go" disabled>Print 🖨️</button></div>
<div id="msg"></div></main>
<script>
const NOTES=__NOTES__,COINS=__COINS__,q={};
function card(v,el,coin){q[v]=0;const d=document.createElement('div');d.className='item'+(coin?' coin':'');
d.innerHTML=`<div class=val>₹${v}</div><div class=q><button>−</button><span>0</span><button>+</button></div>`;
const [m,p]=d.querySelectorAll('button'),s=d.querySelector('span');
m.onclick=()=>{q[v]=Math.max(0,q[v]-1);s.textContent=q[v];upd()};
p.onclick=()=>{q[v]=Math.min(20,q[v]+1);s.textContent=q[v];upd()};el.appendChild(d)}
NOTES.forEach(v=>card(v,notes,0));COINS.forEach(v=>card(v,coins,1));
function upd(){let t=0,n=0;for(const v in q){t+=v*q[v];n+=q[v]}tot.textContent=t.toLocaleString('en-IN');go.disabled=n==0}
go.onclick=async()=>{go.disabled=true;msg.textContent='Printing…';
try{const r=await fetch('/print',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({holder:holder.value,items:Object.entries(q).filter(e=>e[1]>0).map(([value,qty])=>({value:+value,qty}))})});
const j=await r.json();msg.textContent=r.ok?`Printing ${j.printed} pieces… 🎉 (about ${Math.ceil(j.printed*4)} seconds)`:'Oops: '+j.error}
catch(e){msg.textContent='Could not reach the printer box'}upd()}
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/preview/"):
            try:
                v = int(self.path.split("/")[-1])
                img = render_note(v) if v in NOTES else render_coin(v)
                buf = io.BytesIO(); img.save(buf, "PNG")
                return self._send(200, buf.getvalue(), "image/png")
            except Exception:
                return self._send(404, "not found", "text/plain")
        page = PAGE.replace("__NOTES__", json.dumps(NOTES)).replace("__COINS__", json.dumps(COINS))
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self):
        if self.path != "/print":
            return self._send(404, "{}", "application/json")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0))
            items = body.get("items", [])
            if sum(int(i["qty"]) for i in items) > 40:
                return self._send(400, json.dumps({"error": "max 40 pieces at a time"}), "application/json")
            n = print_items(items, str(body.get("holder", "")).strip())
            self._send(200, json.dumps({"printed": n}), "application/json")
        except Exception as e:
            self._send(500, json.dumps({"error": str(e)}), "application/json")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"Kids Play Bank on http://0.0.0.0:{PORT}  printer={PRINTER} width={DOTS}")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
