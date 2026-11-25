# GTA 6 Cutter Readiness — AutoClip findings

Owner: Cutter · Tested: 2026-11-12 · Machine: this Mac (Apple Silicon, CPU-only inference)

## 1. Source ingestion: Twitch / Kick / YouTube / Bilibili / local

**AutoClip's own API only accepts YouTube and Bilibili URLs.** `backend/api/v1/youtube.py:101-102`
hard-rejects any URL that doesn't contain `youtube.com` or `youtu.be` ("无效的YouTube视频链接"). There is
no Twitch or Kick code anywhere in the backend or frontend (`grep` for `twitch|kick` across
`backend/` and `frontend/src` returns nothing).

**But the underlying dependency already supports both.** AutoClip's YouTube downloader is a thin
wrapper around `yt-dlp` (already installed, v2026.08.19), and yt-dlp ships native `twitch:vod` and
`kick:vod` extractors. I confirmed this directly:
```
$ yt-dlp "https://www.twitch.tv/videos/1111111111" --dump-json --skip-download
ERROR: [twitch:vod] 1111111111: Video 1111111111 does not exist   # extractor matched, just a fake ID
$ yt-dlp "https://kick.com/.../videos/00000000-..." --dump-json --skip-download
ERROR: [kick:vod] ...: HTTP Error 404: Not Found                   # extractor matched, just a fake ID
```
Both correctly matched their platform-specific extractor; they only failed because I used placeholder
IDs. A real Twitch or Kick VOD URL will download today with the CLI already on this machine.

**Simplest working path for Twitch/Kick (no code change needed):**
1. `yt-dlp -f 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' <twitch_or_kick_vod_url>`
   (same format spec AutoClip's own YouTube downloader uses, so output is equivalent)
2. Import the resulting local .mp4 via AutoClip's existing local-upload endpoint
   (`POST /api/v1/projects/upload`, `video_file` + optional `srt_file`) — this path has no domain
   restriction, only handles a file.
3. Proceed with AutoClip's normal project processing.

This is a 2-step manual (or easily scriptable) workaround, not a code change, and it's available
right now. If we want one-click Twitch/Kick URL import inside the app later, the fix is small
(loosen the domain check in `youtube.py` and point it at the same yt-dlp download function — but
I did **not** make this change since it's optional and out of this brief's scope).

YouTube and Bilibili: work as documented, native URL import.

## 2. Processing time on a long VOD — measured, not guessed

**Content used for the timing test:** I could not find a verifiably rights-clear 6+ hour
Twitch/Kick facecam+commentary VOD to download in full within this session (bandwidth/time), and
GTA 6 hasn't launched yet, so there is no post-launch stream to test against. To get real numbers
without touching anything leak- or rights-adjacent, I benchmarked against a public, standard-license
YouTube gaming VOD, **"8 HOURS of ZEN Rocket League Gameplay (SSL 2v2)"** (8.77h, confirmed via
`yt-dlp --dump-json`), for **internal engineering timing only** — nothing was published, kept, or
clipped from it; all downloaded files were deleted after the test. Treat the rates below as a
reasonable estimate for the gaming-VOD workload shape, re-validate once we have a real approved
GTA6 streamer VOD.

**Measured, real numbers from this machine:**
| Stage | Measured | Rate |
|---|---|---|
| yt-dlp audio-only download (worst audio, 183.55MB for 8.77h) | 63s | ~2.9 MB/s this network |
| faster-whisper `base` model load (int8, CPU, `device=auto`) | 40.1s | one-time per run |
| faster-whisper transcription, 15-min real audio sample, `vad_filter=False` (forces full decode — the realistic case for a stream with near-continuous talking/yelling, which VAD won't skip over) | 67.3s | **13.4× realtime** |
| Same 15-min sample with `vad_filter=True` (production default) | 2.8s, 0 segments | VAD decided this specific 15-min window had no speech (it's a quiet stretch of this particular video) — not a representative number, excluded from extrapolation |

**Extrapolated whisper transcription time** (13.4× realtime, model load is a fixed ~40s add-on):
- 6-hour VOD: ~40s + (21,600s ÷ 13.4) ≈ **27–28 minutes**
- 12-hour VOD: ~40s + (43,200s ÷ 13.4) ≈ **54–55 minutes**

These are CPU/int8 numbers on this Mac for the `base` model (the current default,
`SPEECH_RECOGNITION_MODEL=base` in `shared_config.py`). A larger model (e.g. `small`/`medium`) would
be more accurate on yelling/overlapping speech but slower — worth a tradeoff test once AI scoring is
unblocked (see below), since transcript quality feeds directly into the outline/scoring steps.

**AI analysis steps (outline → timeline → scoring → title → clustering) — BLOCKED, not measured.**
I tested the actual configured LLM key used by `LLMClient`/`llm_manager` with a trivial live call:
```
OpenAI调用失败: Error code: 429 - insufficient_quota / "You have no credits remaining"
```
This is a **different failure than the known 401** noted in my standing instructions — the key
now authenticates but the account has **no credits left**. Every pipeline step from `step1_outline`
onward calls this same client, so the whole AI-analysis portion of the pipeline (topic extraction,
timeline, scoring, titling, clustering) fails immediately regardless of video length. I did not
attempt to paste, find, or guess a replacement key, per standing instructions.

**What this means for the done_when "measured processing time for a long VOD":** download +
transcription (the non-AI half of the pipeline) is measured and reported above. The AI-analysis
half cannot be timed until a funded/working API key is restored — **this needs Yuriy or Showrunner
to top up/replace the OpenAI key before Nov 18 night**, or nothing past transcription will run for
launch-night VODs.

## 3. Highlight scoring on reaction/gameplay content — prompt tweaks made (untested live)

Read all three LLM-facing prompts that drive topic extraction, moment timing, and scoring for the
closest existing category to a gaming livestream (`entertainment`, selected via each project's
`video_category` field — there is no dedicated "gaming" category in `VideoCategory`
(`backend/core/shared_config.py:16-24`), so these are the entertainment-category files, which is
what Scout/Editor should set `video_category` to for GTA6 projects):
- `prompt/entertainment/大纲.txt` (step1 outline — which topics get extracted)
- `prompt/entertainment/时间点.txt` (step2 timeline — exact start/end of each topic)
- `prompt/entertainment/推荐理由.txt` (step3 scoring — this file doubles as the actual scoring
  prompt in code; `ClipScorer` in `backend/pipeline/step3_scoring.py` loads it as
  `self.recommendation_prompt` and uses it for the numeric `final_score`, not just the reason text)

**Before edits**, all three were written entirely for celebrity variety shows / interviews: "star
charm," "healing," "guest chemistry," game-show rules-and-results framing. Nothing in any of them
referenced streamer facecam reactions, fails, deaths, or chases — a scoring run would likely have
under-valued exactly the moment types the plan wants ("fails/chaos/police chases with strong
reaction") because the prompt's own quality rubric and examples only reward celebrity-variety
beats.

**Changes made** (additive sections, existing variety-show content untouched so non-gaming
projects using `entertainment` still work as before):
- `prompt/entertainment/大纲.txt` — added a "游戏直播特别场景" section instructing the model to
  treat strong emotional reactions (yelling/screaming/laughing), deaths/fails, chase/escape
  sequences, surprise reveals, and chat-driven bits as top-priority topics, and to not force them
  into the 3–8 min standard length if the full beat is shorter.
- `prompt/entertainment/时间点.txt` — added timing rules for these same moment types: start
  3–5s before the triggering event (keep the setup), end 2–4s after the reaction fully plays out
  (keep the reaction tail), and explicitly allow 20s–2min durations instead of the 3–8 min
  standard.
- `prompt/entertainment/推荐理由.txt` — added explicit scoring guidance so `final_score` treats
  streamer reactions/fails/chases/surprises as high-value signals on their own merits (not
  penalized for lacking a "celebrity" or "variety guest").

**Not verified against a live run** — the API quota block above (section 2) means I could not run
these prompts against the real Rocket League transcript or any gaming transcript to confirm the
scoring actually shifts as intended. This needs a real pass once the API key is restored:
feed a transcript with clear reaction/fail/chase moments through steps 1–3 with
`video_category=entertainment` and check the scored output picks them up and ranks them highly.

## 4. Can the app even start on this Mac right now? Two non-AI blockers found

While checking whether the local-upload workaround could be verified end-to-end, I found the app
can't currently be started on this Mac with the standard script, for two reasons unrelated to the
OpenAI key:

- **`start_autoclip.sh` looks for a `venv` directory** (`source venv/bin/activate`,
  `start_autoclip.sh:201-264`), but this machine's actual Python environment is `.venv` (uv-managed,
  Python 3.13). The script would fail its own venv-exists check before doing anything else.
- **Redis is not installed** (`redis-cli`/`redis-server` not found, no Homebrew keg) and no
  Celery/uvicorn/Redis processes are running. `backend/core/celery_app.py:29-30` defaults the
  Celery broker/result backend to `redis://localhost:6379/0`, and `status_autoclip.sh` treats Redis
  + Celery as required services.
- **However, the codebase already has a Redis-free path for exactly this**:
  `backend/utils/task_submission_utils.py` checks `AUTOCLIP_MODE=desktop` (or
  `AUTOCLIP_DESKTOP_MODE=1`) and, if set, runs the full pipeline synchronously in a local background
  thread instead of submitting to Celery/Redis — this is meant for "desktop installs with no Redis"
  per the code's own comment. **This is not set in `.env` on this machine today.**

I did not change `start_autoclip.sh`, `.env`, or any code for this — it's a config/environment gap,
not something my brief asked me to fix, and I don't want to collide with whatever setup Yuriy/Editor
are already running elsewhere. Flagging it because if launch night runs on this same Mac with the
scripts as-is, it won't start at all, independent of the OpenAI credits issue.

## Summary / what's needed from Yuriy

1. **OpenAI API key has no credits** (429, not the earlier 401) — nothing past transcription runs
   until this is funded or swapped. This blocks outline/timeline/scoring/title/clustering for
   every project, not just GTA6. Needs a working key before Nov 18 night.
2. Twitch/Kick ingestion works via a yt-dlp download + local-upload workaround today; no code
   change made or needed unless we want one-click URL import in the UI later (optional, small
   change, didn't do it since it wasn't asked for).
3. Whisper transcription on this Mac: ~13.4× realtime (base model, CPU/int8) → ~28 min for a 6h
   VOD, ~55 min for 12h. Model-load overhead ~40s per run.
4. Entertainment-category prompts updated to bias toward reactions/fails/chases (3 files, listed
   above) — logic-level change only, unverified against a live scoring run because of blocker #1.
5. **The standard start script won't run on this Mac as-is** (`venv` vs actual `.venv`, and no
   Redis installed) — see section 4. Easy fixes exist (point the script at `.venv`, set
   `AUTOCLIP_MODE=desktop` in `.env` to use the existing Redis-free code path) but I didn't apply
   them since it's a config change outside this brief's scope — flagging so it doesn't surprise
   anyone on launch night.

NEEDS INPUT: the OpenAI key needs credits added (or a replacement working key) before launch night,
since nothing AI-driven runs without it. Default: I'm treating this as the single hard blocker and
flagging it rather than guessing a fix, per standing instructions never to hunt for or invent keys.
Separately, NEEDS A DECISION (not urgent, not a key): should I apply the two small startup fixes in
section 4 (point the start script at `.venv`, set `AUTOCLIP_MODE=desktop`) so the app actually boots
on this machine? Default: I'll leave the script/config untouched until told to change it, since it's
outside this brief and I don't know what else depends on the current setup.
