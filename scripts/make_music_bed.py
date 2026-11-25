#!/usr/bin/env python3
"""Synthesize an original, royalty-free lo-fi music bed for Shorts (no samples, nothing to get claimed).

A four-chord loop (Am7, Fmaj7, Cmaj7, G6) of soft pads, a sine bass, a gentle kick and quiet hats, at 88 bpm.
Usage: python3 scripts/make_music_bed.py [--seconds 60] [--out data/music/bed_lofi_01.wav]
"""
import argparse
import wave
from pathlib import Path

import numpy as np

SR = 44100
BPM = 88
BEAT = 60 / BPM
BAR = 4 * BEAT
# MIDI notes per chord: bass root, then pad voicing.
CHORDS = [
    (45, [57, 60, 64, 67]),  # Am7
    (41, [57, 60, 64, 65]),  # Fmaj7
    (48, [55, 60, 64, 71]),  # Cmaj7
    (43, [55, 59, 62, 64]),  # G6
]


def hz(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def envelope(n, attack, release):
    env = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    env[:a] = np.linspace(0, 1, a)
    env[-r:] *= np.linspace(1, 0, r)
    return env


def pad(note, seconds, rng):
    t = np.arange(int(seconds * SR)) / SR
    tone = np.zeros_like(t)
    for detune in (-0.12, 0.0, 0.12):  # three slightly detuned voices for width
        f = hz(note + detune)
        for h, amp in ((1, 1.0), (2, 0.35), (3, 0.15), (4, 0.06)):  # few harmonics: a dark, soft timbre
            tone += amp * np.sin(2 * np.pi * f * h * t + rng.uniform(0, 2 * np.pi))
    wobble = 1 + 0.08 * np.sin(2 * np.pi * 0.35 * t)  # slow tape-like movement
    return tone * wobble * envelope(len(t), 0.6, 0.9)


def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    freq = 45 + 75 * np.exp(-t * 28)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 9)


def hat(rng):
    n = int(0.05 * SR)
    noise = rng.standard_normal(n)
    noise = np.diff(noise, prepend=0)  # crude high-pass
    return noise * np.exp(-np.arange(n) / SR * 90)


def build(seconds, seed=7):
    rng = np.random.default_rng(seed)
    total = int(seconds * SR)
    left, right = np.zeros(total), np.zeros(total)
    k, bar_index, start = kick(), 0, 0.0
    while start < seconds:
        root, voicing = CHORDS[bar_index % len(CHORDS)]
        s = int(start * SR)
        chord = sum(pad(note, BAR + 0.9, rng) for note in voicing) * 0.05
        bass_t = np.arange(int(BAR * SR)) / SR
        bass = np.sin(2 * np.pi * hz(root) * bass_t) * envelope(len(bass_t), 0.02, 0.4) * 0.22
        for buf, pan in ((left, 0.9), (right, 1.1)):
            e = min(total, s + len(chord))
            buf[s:e] += chord[: e - s] * pan
            e = min(total, s + len(bass))
            buf[s:e] += bass[: e - s]
        for beat in range(4):
            b = s + int(beat * BEAT * SR)
            if beat in (0, 2) and b < total:  # kick on 1 and 3
                e = min(total, b + len(k))
                left[b:e] += k[: e - b] * 0.45
                right[b:e] += k[: e - b] * 0.45
            off = s + int((beat + 0.5) * BEAT * SR)  # hats on the off-beats
            if off < total:
                h = hat(rng) * 0.05
                e = min(total, off + len(h))
                left[off:e] += h[: e - off]
                right[off:e] += h[: e - off] * 0.8
        start += BAR
        bar_index += 1
    vinyl = rng.standard_normal(total) * 0.004
    stereo = np.stack([left + vinyl, right + vinyl], axis=1)
    fade = int(1.5 * SR)
    stereo[:fade] *= np.linspace(0, 1, fade)[:, None]
    stereo[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return stereo / np.max(np.abs(stereo)) * 0.89  # about -1 dBFS peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--out", default="data/music/bed_lofi_01.wav")
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    pcm = (build(args.seconds) * 32767).astype("<i2")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print(out)


if __name__ == "__main__":
    main()
