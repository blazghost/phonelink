#!/usr/bin/env python3
"""phonelink mic -- "Phone microphone", switched on by whatever records from it.

A small resident service (phonelink-mic.service), the microphone's half of
phonelink webcam and run the same way. It makes a PipeWire source called
"Phone microphone" (a null sink, fed by scrcpy, with its monitor remapped into
a proper input) and watches who records from it. When an app starts, the
phone's microphone comes on through scrcpy, tuned for calls (echo cancelling,
gain control); when the last one stops, it goes off again.

Apart from the camera on purpose: turning the camera off in a call must not
cut the sound.

Extra scrcpy flags come from PHONELINK_MIC_ARGS.
"""

import os
import select
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PHONELINK = str(HERE.parent / "phonelink")
FEED, SOURCE = "phonelink_mic_feed", "phonelink_mic"
LABEL = "Phone microphone"
RETRY_S = 5


def log(*parts):
    print("phonelink-mic:", *parts, file=sys.stderr, flush=True)


def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout


def columns(listing):
    return [line.split("\t") for line in listing.splitlines() if "\t" in line]


def unload_ours():
    """Our two modules, including any an earlier run left behind when it died."""
    for row in columns(pactl("list", "short", "modules")):
        if len(row) > 2 and (f"sink_name={FEED}" in row[2] or f"source_name={SOURCE}" in row[2]):
            pactl("unload-module", row[0])


def setup():
    unload_ours()
    # PipeWire's pulse layer reads a description with spaces only quoted this way.
    pactl("load-module", "module-null-sink", f"sink_name={FEED}",
          "sink_properties=\"device.description='Phone mic feed'\"")
    pactl("load-module", "module-remap-source", f"master={FEED}.monitor", f"source_name={SOURCE}",
          f"source_properties=\"device.description='{LABEL}'\"")
    return next((row[0] for row in columns(pactl("list", "short", "sources")) if row[1] == SOURCE),
                None)


def recording(source):
    """Is any app recording from "Phone microphone"? (index, source, client, ...)"""
    return any(row[1] == source for row in columns(pactl("list", "short", "source-outputs")))


def status(text):
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        try:
            (Path(runtime) / "phonelink-mic").write_text(text + "\n")
        except OSError:
            pass


def microphone():
    serial = subprocess.run([PHONELINK, "adb-serial"], capture_output=True, text=True,
                            timeout=30).stdout.strip()
    if not serial:
        log("no phone over adb (phonelink wifi?): staying off")
        return None
    log("an app is recording: phone microphone on")
    subprocess.Popen(["notify-send", "-a", "phonelink", "-i", "audio-input-microphone",
                      "Phone microphone is on", "An app is recording from the phone's microphone"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # scrcpy plays what it hears through SDL; pointed at the feed, it becomes
    # the source's input instead of coming out of the speakers. SDL 3 talks to
    # PipeWire natively and ignores PULSE_SINK, so the target is PipeWire's.
    env = dict(os.environ, SDL_AUDIO_DRIVER="pipewire", PIPEWIRE_NODE=FEED)
    return subprocess.Popen(
        ["scrcpy", "-s", serial, "--no-video", "--no-window",
         "--audio-source=mic-voice-communication",
         *shlex.split(os.environ.get("PHONELINK_MIC_ARGS", ""))], env=env)


def stop(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def main():
    source = setup()
    if not source:
        log("couldn't make the PipeWire source (is pipewire-pulse running?)")
        unload_ours()
        return 1
    stopping = []
    signal.signal(signal.SIGTERM, lambda *_: stopping.append(True))
    events = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, text=True, bufsize=1)
    proc, wanted, retry_at = None, False, 0.0
    status("standby")
    log(f'ready: "{LABEL}" switches the phone microphone on when an app records from it')
    try:
        while not stopping:
            if select.select([events.stdout], [], [], RETRY_S)[0]:
                line = events.stdout.readline()
                if not line:
                    log("lost the PipeWire event stream: exiting so the service starts afresh")
                    return 1
                if "source-output" not in line:
                    continue
                wanted = recording(source)
            elif not wanted:
                continue  # quiet, and nobody listening: nothing to look after
            alive = proc is not None and proc.poll() is None
            if wanted and not alive and time.monotonic() >= retry_at:
                proc = microphone()
                retry_at = time.monotonic() + RETRY_S
                status("on" if proc else "standby")
            elif not wanted and proc:
                log("nobody is recording: phone microphone off")
                stop(proc)
                proc = None
                status("standby")
    finally:
        stop(proc)
        events.terminate()
        unload_ours()
        status("off")
    return 0


if __name__ == "__main__":
    sys.exit(main())
