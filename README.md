# Budugu Bank of Fun

A tiny web app for a Raspberry Pi that prints **Indian play money** (notes ₹10 to ₹2000, coins ₹1/₹2/₹5) on an ESC/POS thermal receipt printer. A child opens the page on a phone or tablet, taps the notes and coins they want, types their name, and presses Print. Each piece comes out on its own and is cut off by the printer.

Every piece says **PLAY MONEY - NOT REAL CURRENCY**. The designs use no RBI marks, portraits or real note artwork.

```
phone / tablet  --HTTP-->  Raspberry Pi (app.py, port 8080)  --ESC/POS over TCP 9100-->  thermal printer
```

## Contents

| File | What it is |
|------|------------|
| `app.py` | The whole app: HTTP server (Python stdlib), note/coin renderer (Pillow), ESC/POS encoder and printer sender. No other dependencies. |
| `install.sh` | One-shot installer for Raspberry Pi OS: installs `python3-pil` and the DejaVu fonts, copies the app to `/opt/kidsbank`, and creates and starts the `kidsbank.service` systemd unit. |

## Hardware this was built and tested on

- Raspberry Pi 3 Model B, Raspberry Pi OS 12 (Bookworm, 32-bit), Python 3.11, Pillow 9.4.
- Everycom 80 mm ESC/POS thermal printer (self-test name `EML-GSM-190114`) with auto cutter, connected by Ethernet cable straight into the Pi's `eth0`. The Pi has a static `192.168.1.10/24` on `eth0`; the printer answers at `192.168.1.123:9100`. The Pi reaches the LAN and the phone over Wi-Fi.
- 80 mm paper, 576 printable dots (8 dots per mm).

The same Pi also runs an unrelated PrintHub agent for shop receipts. This app does not touch it.

## Install

On your PC (Windows PowerShell or any shell with `scp`):

```sh
scp -r budugu-bank-of-fun <user>@rahulkrishna.local:~/kidsbank
```

On the Pi:

```sh
cd ~/kidsbank
bash install.sh
```

Then open `http://rahulkrishna.local:8080` on a phone on the same Wi-Fi.

The installer adds your user to the `lp` group (only matters for USB printers) and enables the service at boot.

## Configuration

All settings are environment variables in `/etc/systemd/system/kidsbank.service`. Edit the file, then run `sudo systemctl daemon-reload && sudo systemctl restart kidsbank`.

| Variable | Default | Meaning |
|----------|---------|---------|
| `PRINTER` | `tcp://192.168.1.123:9100` (set by `install.sh`) | `tcp://host:port` for a LAN printer or `/dev/usb/lp0` for USB. |
| `PAPER_DOTS` | `576` | Printable width in dots: 576 for 80 mm paper, 384 for 58 mm. |
| `BANK_NAME` | `BANK OF FUN` | Printed on every piece. Values with spaces must be quoted in the unit file: `Environment="BANK_NAME=BANK OF FUN"`. |
| `PORT` | `8080` | Web port. |
| `PIECE_PAUSE` | `3.0` | Seconds between pieces, so the printer finishes one before the next job arrives. |
| `FEED_LINES` | `0` | Extra blank lines before each cut. The cut command already feeds the paper to the cutter, so 0 gives the smallest bottom margin. |
| `IMAGE_MODE` | `bitimage` | `bitimage` sends `ESC *` 24-dot bands (works on the Everycom). `raster` sends `GS v 0`, which the Everycom does not support. |

## HTTP API

- `GET /` - the page.
- `GET /preview/<value>` - PNG of a note or coin, e.g. `/preview/500`. Handy for checking the design without paper.
- `POST /print` with JSON `{"holder": "Aarav", "items": [{"value": 10, "qty": 2}, {"value": 5, "qty": 1}]}`. Returns `{"printed": 3}`. At most 20 of one value and 40 pieces per request. The first piece is sent before the reply so a dead printer returns an error; the rest print in the background.

Test from the Pi:

```sh
curl -s -X POST localhost:8080/print -H 'Content-Type: application/json' \
  -d '{"holder":"Test","items":[{"value":10,"qty":1}]}'
```

## How printing works, and why

These rules came from testing on the Everycom printer. Other ESC/POS printers may be more forgiving, but the approach is safe everywhere.

1. **Each note or coin is its own print job**: `ESC @`, the image, then `GS V 66 0` (feed to cutter and partial cut). Sending several images in one stream came out as one good piece followed by garbage.
2. **One TCP connection per job: connect, write all bytes, close.** The Everycom's network chip hangs after a few status probes, chunked or paced writes, or sockets held open, and then needs a power cycle. So the app never probes the printer and never sleeps inside a connection; the pause between pieces happens between connections.
3. **Images go as `ESC *` bit-image bands**, 24 rows per band, with line spacing set to 24 dots (`ESC 3 24`) so bands join without gaps. The newer `GS v 0` raster command is not understood by this printer and is printed as text.
4. **The rupee sign** is drawn as part of the image with DejaVu Sans Bold, so it does not depend on the printer's code page.

## Margins, and what cannot be fixed in software

- **Bottom margin** is the printer's head-to-cutter distance, about 13.5 mm on the Everycom. `FEED_LINES=0` already gives the minimum.
- **Top margin** is the same 13.5 mm of blank paper that sits between the head and the cutter after each cut.

Removing the top margin was tried and dropped. Printing the top of the next note before cutting the previous one puts the cut exactly on the boundary, but this printer shifts the paper by 3 to 4 mm during every cut (partial or full), which leaves a blank band 13.5 mm into the next note, and it has no reverse feed (`ESC K`, `ESC e`, `ESC j` are ignored). The only software fix is a two-box note design with a deliberate blank band, which was rejected. A printer with reverse feed or a "paper saving" top-margin option would solve it.

## Troubleshooting

| Symptom | Cause and fix |
|---------|---------------|
| Long run of unreadable characters instead of a note | The printer does not support the image command. Make sure `IMAGE_MODE` is `bitimage` (the default). |
| Nothing prints, page says "Could not reach" or "Oops" | Printer off, cable out, or the network chip is hung. Power-cycle the printer. `journalctl -u kidsbank -n 50` shows the error. |
| First note fine, later ones garbled | Something sent several images in one connection. The app does not do this; check for a modified `app.py`. |
| Note only says "BANK" | `BANK_NAME` with spaces is not quoted in the unit file. |
| Image clipped at the right | `PAPER_DOTS` too large for the paper; use 384 for 58 mm. |
| `Permission denied` on `/dev/usb/lp0` | USB only. Log out and in after `install.sh` (group change) or check `SupplementaryGroups=lp` in the unit. |

Useful commands on the Pi:

```sh
systemctl status kidsbank
journalctl -u kidsbank -n 50
sudo systemctl restart kidsbank
curl -s localhost:8080 | head
```

## Updating the app

```sh
scp app.py <user>@rahulkrishna.local:~/kidsbank/app.py
ssh <user>@rahulkrishna.local 'sudo cp ~/kidsbank/app.py /opt/kidsbank/app.py && sudo systemctl restart kidsbank'
```
