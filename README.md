# Burp Suite Auto-Screenshot

> Automatically capture clean, per-test-case screenshots of **Burp Suite** on Windows — including one shot per Repeater tab — for pentest evidence and compliance reporting.

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.7%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011-lightgrey.svg)](#requirements)

A small, dependency-light utility that minimizes everything, brings the running
Burp Suite window to the front (maximized), and saves a crisp PNG of **just the
Burp window** — no other apps in frame. It can also walk every Repeater tab and
save one screenshot per tab, fully automatically.

## Demo

A short screen recording of the tool auto-capturing every Repeater tab (an
animated WebP, so it plays and loops on its own):

![Burp Auto-Screenshot demo](https://raw.githubusercontent.com/akash0x00/Burp-Auto-SS/refs/heads/main/Demo-Burp-SS.webp)

A single captured screenshot from a run:

![Burp Auto-Screenshot example output](https://raw.githubusercontent.com/akash0x00/Burp-Auto-SS/refs/heads/main/Demo-Burp-SS.png)

## Why I built this

During penetration testing engagements, I had to capture a screenshot for **every
single test case** I executed — it's a compliance and evidence requirement, not
an optional nicety. Doing that by hand, over and over, for dozens of Repeater
tabs per engagement, was slow, repetitive, and easy to get wrong (missed tabs,
inconsistent crops, wrong window in frame).

So I built this for myself on my own laptop to make that part of my day painless.
It isn't trying to solve some huge problem for the world — it just reliably
automates a tedious task I do constantly, so I can spend my attention on the
actual testing instead of on screenshots. It's saved me real time on every
engagement since, which is exactly why I'm sharing it: if it helps me, it might
help another tester too.

## Features

- **One shot per Repeater tab, automatically** — cycle through and capture every
  tab with a single command (`-R N` or `--tabs`).
- **No mouse clicks, no hard-coded coordinates** — it forces real keyboard focus
  and drives Burp with its own hotkeys, so it's unaffected by resolution, theme,
  window layout, or how many tabs are open.
- **DPI- and multi-monitor-aware** — crops correctly at any display scaling
  (100% / 125% / 150% …) and wherever Burp ends up across monitors.
- **High-quality output** — captured at native pixels, then supersampled (2×) and
  saved as a lossless, high-DPI PNG that stays sharp when zoomed for a report.
- **Deterministic** — with `-R N` there's no image-diff guesswork; cycling `N`
  times always visits every tab exactly once.
- **Compliance-friendly** — it **never installs packages or touches the network
  itself**, so it's safe to run on locked-down / corporate hosts.

## Requirements

- Windows 10 / 11
- Python 3.7+ (tested on **Python 3.14.5**)
- Burp Suite already running
- Python packages: `pywin32`, `pillow` (see [Setup](#setup))

## Setup

Install the dependencies first. The script **does not install anything itself** —
it never shells out to `pip` or reaches the network, so it stays safe to run on
locked-down / corporate machines.

```powershell
pip install -r requirements.txt
```

Then run it:

```powershell
python burp_screenshot.py
```

## Usage

### Single screenshot of the whole Burp window (default)

```powershell
# Save a timestamped PNG in the current folder
python burp_screenshot.py

# Save to a specific file (relative to the current folder)
python burp_screenshot.py screenshots\burp.png

# Save into a folder of your choice (created if needed; timestamped filename)
python burp_screenshot.py shots\
```

### One screenshot per Repeater tab — when you know the count (recommended)

```powershell
# You have 10 Repeater tabs open -> capture all 10
# (defaults to a timestamped folder in the current directory)
python burp_screenshot.py -R 10

# Save them into a folder of your choice (created under the current directory)
python burp_screenshot.py -R 10 repeater_shots\
```

`-R N` captures exactly `N` tabs by pressing Burp's **"next tab" hotkey
(`Ctrl+=`)** between shots. Because "next tab" wraps around, **it does not matter
which tab is selected when you start** — cycling `N` times always visits every
tab. This mode is fully deterministic: no image comparison, no guesswork.

### One screenshot per Repeater tab — auto-detecting the count

```powershell
python burp_screenshot.py --tabs
python burp_screenshot.py --tabs repeater_shots\
```

Same idea, but it works out the count itself by watching the active-tab highlight
move and stopping when it wraps back to the start (comparing only the **tab-strip
band**, so it's reliable even when several tabs hold identical requests). A safety
cap of 200 tabs guarantees it can't loop forever. Prefer `-R` if you already know
the count.

> **You don't need to be on the Repeater tab first.** Both tab modes force
> keyboard focus onto the Burp window and switch to the Repeater tool with its
> hotkey (`Ctrl+Shift+R`), so it works no matter which tool (Dashboard, Proxy,
> …) is showing when you start. With `-R`, if the tabs never change it prints a
> warning so you know something went wrong.

## Output file naming

Tab captures are saved as `NN_R<timestamp>.png`, for example:

```
01_R20260627_143015.png
02_R20260627_143018.png
03_R20260627_143021.png
```

- `NN` — two-digit **capture (cycle) order**. Because cycling starts from
  whatever tab is active, `01_…` is the first tab captured, not necessarily
  Burp's own tab #1.
- `R` — marks it as a **Repeater** capture.
- `<timestamp>` — when the shot was taken (`YYYYMMDD_HHMMSS`).

## Tips

- **Sharper / larger PNGs:** output is supersampled 2× by default. Override the
  factor with the `SCALE` environment variable (e.g. `SCALE=1` for raw native
  size, `SCALE=3` for extra-large). The PNG is also tagged at 192 DPI so viewers
  and printers treat it as high-resolution.

## Troubleshooting

- *"No running Burp Suite window found"* — make sure Burp is open (a window with
  "Burp Suite" in its title) before running the script.
- *"a required dependency is not installed"* — run
  `pip install -r requirements.txt` (the script never installs packages itself).
- *Tab captures look identical / a warning about tabs not changing* — Burp wasn't
  focused on the **Repeater** top-level tab, or only one tab is open. Re-run; the
  tool will re-focus Burp and switch to Repeater automatically.

## License

Copyright (C) 2026 AKASH HANSDA.

Licensed under the **GNU General Public License v3.0** — see [LICENSE](LICENSE)
for the full text. In short: you're free to use, study, modify, and share it,
but **any distributed version (modified or not) must keep this same license,
stay open source, and credit the original author.** Nobody can take this code and
turn it into a closed-source / proprietary product.
