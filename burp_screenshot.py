# Burp Suite Auto-Screenshot - capture per-testcase Burp evidence on Windows.
# Copyright (C) 2026 AKASH HANSDA
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Burp Suite auto-screenshot utility for Windows.

What it does:
  1. Minimizes all open windows (shows the desktop).
  2. Finds the running Burp Suite window, restores + maximizes it, brings it to front.
  3. Captures just the Burp window and saves it as a PNG.

Designed to be portable across machines:
  * Depends only on pywin32 + pillow, installed explicitly from requirements.txt.
    The tool never installs packages or touches the network itself, so it is
    safe to run on locked-down / corporate hosts.
  * DPI-aware, so it works correctly at any display scaling (100% / 125% / 150% ...).
  * Captures the correct region regardless of screen resolution or which
    monitor Burp ends up on (multi-monitor safe).

Usage:
    Single screenshot of the whole Burp window (default):
        python burp_screenshot.py [output_path]

        output_path  Optional. A file (e.g. shots\\burp.png) or a directory.
                     Defaults to a timestamped PNG in the current folder.

    One screenshot per Repeater tab, when you know the tab count (recommended):
        python burp_screenshot.py -R N [output_dir]

        Captures the active tab, then presses Ctrl+= (next tab) and captures,
        N times total -- saving 01_R<timestamp>.png ... NN_R<timestamp>.png.
        Since
        'next tab' wraps around, it captures every tab no matter which one is
        selected when you start. Fully deterministic: no image comparison.

    One screenshot per Repeater tab, auto-detecting the count:
        python burp_screenshot.py --tabs [output_dir]

        Same idea, but figures out the count itself by watching the active-tab
        highlight and stopping when it wraps back to the start. Use -R instead
        if you already know the count.

    For both tab modes, output_dir defaults to a timestamped folder in the
    current directory.

    The tab modes switch Burp to the Repeater tool automatically (Ctrl+Shift+R),
    so it doesn't matter which tool tab is showing when you start.
"""

import os
import sys
import time
import datetime
import ctypes
from ctypes import wintypes


# --------------------------------------------------------------------------- #
# Third-party dependencies.
#
# These are declared in requirements.txt and must be installed explicitly, e.g.
# `pip install -r requirements.txt`. The tool deliberately does NOT install
# anything itself: silently shelling out to pip would make unsanctioned network
# calls and modify the Python environment, which many corporate / locked-down
# hosts forbid. If a dependency is missing we fail fast with clear guidance
# rather than reaching out to PyPI.
# --------------------------------------------------------------------------- #
try:
    import win32api
    import win32con
    import win32gui
    import win32com.client
    from PIL import ImageGrab, Image, ImageChops
except ImportError as exc:
    sys.stderr.write(
        f"ERROR: a required dependency is not installed ({exc.name}).\n"
        "Install the dependencies first:\n"
        "    pip install -r requirements.txt\n"
    )
    sys.exit(1)


# How much to supersample the captured image. 1 = raw native capture.
# 2 = double the pixels with smooth LANCZOS resampling, so zooming in looks
# anti-aliased instead of blocky. Override with the SCALE env var.
SUPERSAMPLE = float(os.environ.get("SCALE", "2"))

# DPI metadata written into the PNG so viewers/printers treat it as high-res.
OUTPUT_DPI = (192, 192)

# Virtual-key codes for the hotkeys we synthesize (see send_hotkey).
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_R = 0x52
VK_OEM_PLUS = 0xBB  # the '=' / '+' key


# --------------------------------------------------------------------------- #
# DPI awareness: without this, GetWindowRect and the screen grab disagree on
# machines using display scaling, producing an offset / wrong-sized crop.
# --------------------------------------------------------------------------- #
def set_dpi_awareness():
    """Make the process per-monitor DPI aware, with fallbacks for older Windows."""
    try:
        # Windows 10 1703+: per-monitor v2 (handles mixed-DPI multi-monitor best).
        ctypes.windll.user32.SetProcessDpiAwarenessContext(
            ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
    except (AttributeError, OSError):
        try:
            # Windows 8.1+: per-monitor aware.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                # Windows Vista+: system DPI aware.
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass  # very old Windows; coordinates may be slightly off


def minimize_all_windows():
    """Trigger the 'Show Desktop' shell command to minimize everything."""
    shell = win32com.client.Dispatch("Shell.Application")
    shell.MinimizeAll()
    time.sleep(1.0)  # give the desktop animation time to settle


def find_burp_window():
    """Return the hwnd of the top-level Burp Suite window, or None."""
    matches = []

    def _enum(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title and "burp suite" in title.lower():
            matches.append((hwnd, title))

    win32gui.EnumWindows(_enum, None)
    return matches[0][0] if matches else None


def find_burp_window_with_retry(attempts=5, delay=2.0):
    """Look for Burp a few times, in case it's still starting up."""
    for i in range(attempts):
        hwnd = find_burp_window()
        if hwnd is not None:
            return hwnd
        if i < attempts - 1:
            print(f"  Burp not found yet, retrying ({i + 1}/{attempts})...")
            time.sleep(delay)
    return None


def force_foreground_focus(hwnd):
    """Bring a window to the front AND give it real keyboard focus.

    A plain SetForegroundWindow often raises the window without delivering
    input focus (Windows' focus-stealing prevention), so injected keystrokes go
    nowhere. Temporarily attaching our thread's input to the current foreground
    thread and the target thread lets SetForegroundWindow + SetFocus actually
    take -- no mouse click and no screen coordinates required, so it is immune
    to resolution, DPI, theme and window-layout differences.
    """
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)

    foreground = user32.GetForegroundWindow()
    cur_tid = kernel32.GetCurrentThreadId()
    target_tid = user32.GetWindowThreadProcessId(hwnd, None)
    fg_tid = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0

    attached = [tid for tid in {fg_tid, target_tid} if tid and tid != cur_tid]
    for tid in attached:
        user32.AttachThreadInput(cur_tid, tid, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        for tid in attached:
            user32.AttachThreadInput(cur_tid, tid, False)

    time.sleep(1.0)  # allow the window to finish maximizing/repainting


def get_window_bbox(hwnd):
    """Return the true (left, top, right, bottom) of a window in physical pixels.

    Uses DWM extended frame bounds so the captured rectangle excludes the
    invisible drop-shadow borders Windows reports via GetWindowRect.
    Falls back to GetWindowRect if the DWM call is unavailable.
    """
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    rect = wintypes.RECT()
    result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
        wintypes.HWND(hwnd),
        ctypes.c_uint(DWMWA_EXTENDED_FRAME_BOUNDS),
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if result == 0:
        return (rect.left, rect.top, rect.right, rect.bottom)
    return win32gui.GetWindowRect(hwnd)


def resolve_output_path(output_arg):
    """Turn the optional CLI argument into a concrete .png file path."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"burp_screenshot_{timestamp}.png"

    if not output_arg:
        return os.path.abspath(default_name)

    # A directory (existing, or trailing slash) -> place the default name inside.
    if os.path.isdir(output_arg) or output_arg.endswith(("\\", "/")):
        os.makedirs(output_arg, exist_ok=True)
        return os.path.abspath(os.path.join(output_arg, default_name))

    # Otherwise treat it as a file path; ensure the parent dir exists.
    path = output_arg if output_arg.lower().endswith(".png") else output_arg + ".png"
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    return os.path.abspath(path)


def grab_window_image(hwnd):
    """Grab the Burp window region as a raw PIL image at native resolution.

    DPI awareness ensures this is captured at the monitor's true physical
    pixels. No resampling here -- this raw image is used both for saving and
    for the fast tab-to-tab comparison.
    """
    bbox = get_window_bbox(hwnd)
    return ImageGrab.grab(bbox=bbox, all_screens=True)


def save_image(image, output_path):
    """Supersample (for smooth zoom) and save as a lossless high-DPI PNG."""
    if SUPERSAMPLE and SUPERSAMPLE != 1:
        new_size = (
            int(image.width * SUPERSAMPLE),
            int(image.height * SUPERSAMPLE),
        )
        image = image.resize(new_size, Image.LANCZOS)

    image.save(output_path, format="PNG", optimize=True, dpi=OUTPUT_DPI)
    return output_path


def resolve_output_dir(output_arg):
    """Turn the optional CLI argument into a concrete output directory for tabs."""
    if output_arg:
        return os.path.abspath(output_arg)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.abspath(f"repeater_tabs_{timestamp}")


def take_screenshot(hwnd, output_path):
    """Capture only the Burp window region and save it to output_path."""
    return save_image(grab_window_image(hwnd), output_path)


def repeater_tab_filename(index):
    """Build a per-tab screenshot filename: NN_R<timestamp>.png.

    The two-digit index is the capture (cycle) order; the 'R' marks it as a
    Repeater capture; the timestamp records when the shot was taken and keeps
    the name unique. Example: 01_R20260627_143015.png
    """
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{index:02d}_R{timestamp}.png"


def tab_strip_box(size):
    """Bounding box of the Repeater tab strip as a fraction of the window.

    The tab strip (the row of numbered tabs) sits just below the tool tabs.
    We compare only this band to detect tab switches, because the active-tab
    highlight moving along the strip is a strong, localized signal -- and it
    works even when every tab holds an identical request (a whole-window diff
    would miss that, since only the tiny highlight changes).
    """
    w, h = size
    return (0, int(h * 0.090), w, int(h * 0.135))


def active_tab_changed(a, b, box, pixel_thresh=40, frac_thresh=0.002):
    """True if the tab-strip band differs (i.e. a different tab is active).

    Counts pixels in the band whose brightness changed by more than
    pixel_thresh (out of 255); if that exceeds frac_thresh of the band, the
    active-tab highlight has moved. Robust to faint anti-aliasing noise.
    Differing sizes always count as changed.
    """
    if a.size != b.size:
        return True
    ca = a.crop(box).convert("L")
    cb = b.crop(box).convert("L")
    diff = ImageChops.difference(ca, cb)
    mask = diff.point(lambda p: 255 if p > pixel_thresh else 0)
    changed = mask.histogram()[255]
    total = (box[2] - box[0]) * (box[3] - box[1])
    return total > 0 and (changed / total) > frac_thresh


def send_hotkey(*vk_codes):
    """Synthesize a key chord: press the given virtual-keys, then release them.

    Keys are pressed in the given order and released in reverse, mimicking a
    real chord such as Ctrl held while '=' is tapped. Uses keybd_event (Win32)
    so no PowerShell or extra dependencies are needed. The keystrokes go to the
    foreground window, so the Burp frame must already be focused.
    """
    KEYEVENTF_KEYUP = 0x0002
    for vk in vk_codes:
        win32api.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vk_codes):
        win32api.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


def press_switch_to_repeater():
    """Send Ctrl+Shift+R, Burp's hotkey to switch to the Repeater tool tab."""
    send_hotkey(VK_CONTROL, VK_SHIFT, VK_R)


def go_to_repeater(hwnd):
    """Switch Burp to the Repeater tool, ready for tab cycling.

    No mouse clicks and no screen coordinates -- it forces real keyboard focus
    on the Burp frame, then sends Ctrl+Shift+R to switch to the Repeater tool.
    Works regardless of which tool (Dashboard, Proxy, ...) is showing, and is
    unaffected by how many tabs are open or whether the tab strip is scrolled.

    Cycling then starts from whatever Repeater tab happens to be active; because
    Ctrl+= (next tab) wraps around, that still visits every tab.
    """
    force_foreground_focus(hwnd)
    press_switch_to_repeater()  # Ctrl+Shift+R -> Repeater tool tab
    time.sleep(0.7)


def press_next_repeater_tab():
    """Send Burp's 'next tab' hotkey, Ctrl+= (Ctrl + the '=' / OEM_PLUS key).

    The keystroke goes to whichever window is in the foreground, so the Burp
    window must already be foregrounded (force_foreground_focus handles that).
    """
    send_hotkey(VK_CONTROL, VK_OEM_PLUS)


def screenshot_all_repeater_tabs(hwnd, output_dir, max_tabs=200):
    """Screenshot every Repeater tab by cycling with the 'next tab' hotkey.

    Starting from whatever tab is currently active, it captures the tab, presses
    Ctrl+= to advance, and repeats. Because 'next tab' wraps around, it stops as
    soon as a capture matches the very first one (we've looped all the way back).
    A max_tabs cap guarantees it can never loop forever.

    Returns the list of saved file paths (one per tab).
    """
    os.makedirs(output_dir, exist_ok=True)
    go_to_repeater(hwnd)

    anchor = grab_window_image(hwnd)
    box = tab_strip_box(anchor.size)
    saved = [save_image(anchor, os.path.join(output_dir, repeater_tab_filename(1)))]
    print(f"  Captured tab 1 -> {os.path.basename(saved[0])}")

    previous = anchor
    for index in range(2, max_tabs + 1):
        press_next_repeater_tab()
        time.sleep(0.6)  # let Burp switch tabs and repaint
        current = grab_window_image(hwnd)

        # Hotkey had no effect (only one tab, or focus isn't in Repeater).
        if not active_tab_changed(current, previous, box):
            if index == 2:
                print("  Tab did not change -- only one tab, or Burp isn't "
                      "focused on the Repeater tab.")
            else:
                print("  Tab did not change; stopping.")
            break

        # Highlight returned to the starting tab -> we've wrapped through all.
        if not active_tab_changed(current, anchor, box):
            print("  Wrapped back to the first tab; done.")
            break

        path = os.path.join(output_dir, repeater_tab_filename(index))
        saved.append(save_image(current, path))
        print(f"  Captured tab {index} -> {os.path.basename(path)}")
        previous = current
    else:
        print(f"  Reached the safety cap of {max_tabs} tabs; stopping.")

    return saved


def screenshot_n_repeater_tabs(hwnd, output_dir, count):
    """Screenshot exactly `count` Repeater tabs by cycling the 'next tab' hotkey.

    Deterministic: it captures the currently-active tab, then presses Ctrl+=
    and captures, repeating until `count` screenshots are taken. Because
    'next tab' wraps around, it does not matter which tab is selected when you
    start -- cycling `count` times always visits every tab exactly once. No
    image comparison or wrap-detection is involved.

    The files are saved in capture order (repeater_01.png is whatever tab was
    active at start), so the numbering is the cycle order, not Burp's own tab
    labels.

    Returns the list of saved file paths.
    """
    os.makedirs(output_dir, exist_ok=True)
    go_to_repeater(hwnd)

    saved = []
    previous = None
    box = None
    changes = 0
    for index in range(1, count + 1):
        if index > 1:
            press_next_repeater_tab()
            time.sleep(0.6)  # let Burp switch tabs and repaint
        current = grab_window_image(hwnd)
        if box is None:
            box = tab_strip_box(current.size)
        if previous is not None and active_tab_changed(current, previous, box):
            changes += 1
        previous = current

        path = os.path.join(output_dir, repeater_tab_filename(index))
        saved.append(save_image(current, path))
        print(f"  Captured tab {index}/{count} -> {os.path.basename(path)}")

    if count > 1 and changes == 0:
        print("  WARNING: the active tab never changed -- the captures are "
              "likely all the same tab. Make sure Burp is on the Repeater "
              "top-level tab.", file=sys.stderr)
    return saved


def main():
    # Parse args:
    #   -R N / --repeater N : capture exactly N Repeater tabs (deterministic).
    #   --tabs              : capture all Repeater tabs, auto-detecting the count.
    #   (none)              : single screenshot of the whole Burp window.
    # An optional output path/dir may follow.
    args = sys.argv[1:]
    tab_mode = False
    explicit_count = None
    if args and args[0] in ("-R", "--repeater"):
        tab_mode = True
        if len(args) < 2 or not args[1].lstrip("+").isdigit() or int(args[1]) < 1:
            print(
                "ERROR: -R requires a positive integer tab count, "
                "e.g. 'python burp_screenshot.py -R 10'.",
                file=sys.stderr,
            )
            sys.exit(2)
        explicit_count = int(args[1])
        args = args[2:]
    elif args and args[0] in ("--tabs", "--repeater-tabs"):
        tab_mode = True
        args = args[1:]
    output_arg = args[0] if args else None

    set_dpi_awareness()

    print("Minimizing all windows...")
    minimize_all_windows()

    print("Looking for Burp Suite window...")
    hwnd = find_burp_window_with_retry()
    if hwnd is None:
        print(
            "ERROR: No running Burp Suite window found. "
            "Make sure Burp Suite is open, then run this again.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Found Burp Suite (hwnd={hwnd}). Bringing to front...")
    force_foreground_focus(hwnd)

    if tab_mode:
        output_dir = resolve_output_dir(output_arg)
        if explicit_count is not None:
            print(f"Screenshotting {explicit_count} Repeater tab(s) into: "
                  f"{output_dir}")
            saved = screenshot_n_repeater_tabs(hwnd, output_dir, explicit_count)
        else:
            print(f"Screenshotting every Repeater tab into: {output_dir}")
            saved = screenshot_all_repeater_tabs(hwnd, output_dir)
        count = len(saved)
        print(f"Done. Captured {count} Repeater tab(s) into: {output_dir}")
    else:
        output_path = resolve_output_path(output_arg)
        print("Taking screenshot...")
        saved = take_screenshot(hwnd, output_path)
        print(f"Screenshot saved to: {saved}")


if __name__ == "__main__":
    main()
