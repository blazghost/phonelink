#!/usr/bin/env python3
"""phonelink webcam -- "Phone camera", switched on by whatever opens it.

A small resident service (phonelink-webcam.service). It keeps the
v4l2loopback device "Phone camera" fed with one black frame a second, which
is what keeps it listed as a camera in Meet, Zoom, OBS and browsers (they only
see a loopback device as a camera while something is writing to it), and it
asks the driver to say when an app starts or stops reading. When one starts,
the phone's camera comes on through scrcpy; when the last one stops, the phone
camera goes off again and the black frame carries on. So the phone's camera
is only in use during a call, and face unlock and Smart Stay have it the rest
of the time.

If the phone takes its camera back mid-call (face unlock, the Camera app),
scrcpy exits and is started again a few seconds later.

The camera, front or back, is read from ~/.local/state/phonelink/webcam-facing
each time it starts (`phonelink webcam front|back` writes it); extra scrcpy
flags come from PHONELINK_WEBCAM_ARGS.
"""

import fcntl
import os
import select
import shlex
import signal
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHONELINK = str(HERE.parent / "phonelink")
LABEL = "Phone camera"
WIDTH, HEIGHT = 1280, 720

# videodev2.h on x86-64: VIDIOC_SUBSCRIBE_EVENT and VIDIOC_DQEVENT, and the size
# of struct v4l2_event. v4l2loopback.c: its client-usage event, sent whenever a
# reader starts or stops streaming, whose payload (at offset 8, the union) is
# 1 while any app is reading.
SUBSCRIBE_EVENT, DEQUEUE_EVENT, EVENT_SIZE = 0x4020565A, 0x80885659, 136
CLIENT_USAGE, SEND_INITIAL = 0x10E00001, 1
RETRY_S = 3


def log(*parts):
    print("phonelink-webcam:", *parts, file=sys.stderr, flush=True)


def find_device():
    for name in sorted(Path("/sys/class/video4linux").glob("video*/name")):
        try:
            if name.read_text().strip() == LABEL:
                return "/dev/" + name.parent.name
        except OSError:
            continue
    return None


def facing():
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    try:
        value = (state / "phonelink" / "webcam-facing").read_text().strip()
    except OSError:
        value = ""
    return value if value in ("front", "back") else "front"


def status(text):
    """One line for `phonelink webcam status` to read."""
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    try:
        (runtime / "phonelink-webcam").write_text(text + "\n")
    except OSError:
        pass


def standby(device):
    """A black frame a second: the device stays a camera, and costs nothing."""
    return subprocess.Popen(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-re", "-f", "lavfi",
         "-i", f"color=black:size={WIDTH}x{HEIGHT}:rate=1", "-pix_fmt", "yuv420p",
         "-f", "v4l2", device])


def camera(device):
    serial = subprocess.run([PHONELINK, "adb-serial"], capture_output=True, text=True,
                            timeout=30).stdout.strip()
    if not serial:
        log("no phone over adb (phonelink wifi?): staying on standby")
        return None
    side = facing()
    log(f"an app is reading: phone {side} camera on")
    return subprocess.Popen(
        ["scrcpy", "-s", serial, "--video-source=camera", f"--camera-facing={side}",
         f"--camera-size={WIDTH}x{HEIGHT}", "--camera-fps=30", "--no-audio", "--no-window",
         f"--v4l2-sink={device}", *shlex.split(os.environ.get("PHONELINK_WEBCAM_ARGS", ""))])


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def readers(events):
    """Drain the driver's events; the newest says whether anything is reading."""
    reading = None
    while select.select([], [], [events], 0)[2]:
        event = bytearray(EVENT_SIZE)
        fcntl.ioctl(events, DEQUEUE_EVENT, event)
        reading = bool(struct.unpack_from("=I", event, 8)[0])
    return reading


def main():
    device = find_device()
    if not device:
        log(f'no "{LABEL}" device: run  sudo ./setup.sh  once (it installs v4l2loopback)')
        return 1
    writer = standby(device)
    phone = None
    reading = False
    retry_at = 0.0
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    status("standby")
    log(f"ready: {device} switches the phone camera on when an app reads it")
    with open(device, "rb", buffering=0) as events:
        fcntl.ioctl(events, SUBSCRIBE_EVENT, struct.pack("=8I", CLIENT_USAGE, 0, SEND_INITIAL,
                                                         0, 0, 0, 0, 0))
        try:
            while not stopping:
                select.select([], [], [events], 1.0)
                if (now := readers(events)) is not None:
                    reading = now
                if reading and phone is None and time.monotonic() >= retry_at:
                    stop(writer)
                    writer = None
                    phone = camera(device)
                    if phone is None:
                        retry_at = time.monotonic() + 10
                        writer = standby(device)
                    else:
                        status(f"streaming {facing()}")
                elif phone and phone.poll() is not None:
                    # Taken back by the phone (face unlock, the Camera app) or a
                    # dropped link: try again shortly if anyone is still watching.
                    log("the phone camera stopped")
                    phone = None
                    retry_at = time.monotonic() + RETRY_S
                    writer = standby(device)
                    status("waiting for the camera" if reading else "standby")
                elif not reading and phone:
                    log("nothing is reading: phone camera off")
                    stop(phone)
                    phone = None
                    writer = standby(device)
                    status("standby")
                if writer and writer.poll() is not None:
                    writer = standby(device)
        finally:
            stop(phone)
            stop(writer)
            status("off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
