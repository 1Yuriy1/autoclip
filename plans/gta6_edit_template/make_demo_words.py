#!/usr/bin/env python3
"""One-off helper: build word-level timing JSON for the demo render from an
existing whisper-style SRT (used only for the sample clip in this folder,
not part of the reusable template). Real clips should get word timestamps
from AutoClip's own transcription step (backend/utils/speech_recognizer.py)
or Cutter's pipeline output, in the same [{word,start,end}] shape.
"""
import json
import re
import sys

SRT_PATH = sys.argv[1]
CLIP_START = float(sys.argv[2])  # seconds, offset into the source SRT
CLIP_END = float(sys.argv[3])
OUT_PATH = sys.argv[4]

TS_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)")


def ts_to_sec(ts):
    h, m, s, ms = TS_RE.match(ts).groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


entries = []
with open(SRT_PATH, encoding="utf-8") as f:
    block = []
    for line in f:
        line = line.rstrip("\n")
        if line.strip() == "":
            if block:
                entries.append(block)
            block = []
        else:
            block.append(line)
    if block:
        entries.append(block)

parsed = []
for block in entries:
    if len(block) < 2:
        continue
    m = re.search(r"(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)", block[1])
    if not m:
        continue
    start = ts_to_sec(m.group(1))
    end = ts_to_sec(m.group(2))
    text = " ".join(block[2:]).strip()
    if text:
        parsed.append((start, end, text))

# Keep only non-overlapping forward progress to approximate the "primary"
# caption lane (this SRT emits sliding overlapping segments).
clean = []
last_end = -1.0
for start, end, text in parsed:
    if start < CLIP_START or start > CLIP_END:
        continue
    if start < last_end - 0.05:
        continue
    clean.append((start, end, text))
    last_end = end

words = []
for start, end, text in clean:
    toks = text.split()
    if not toks:
        continue
    dur = max(end - start, 0.2)
    step = dur / len(toks)
    for i, w in enumerate(toks):
        w_start = start + i * step
        w_end = w_start + step
        words.append({
            "word": w,
            "start": round(w_start - CLIP_START, 3),
            "end": round(w_end - CLIP_START, 3),
        })

with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(words, f, indent=2)

print(f"wrote {len(words)} words to {OUT_PATH}")
