# Frame Lab — isolated Shorts Studio

Frame Lab is a complete local-first experimental production area. It does not call AutoClip APIs or write to AutoClip projects. Referenced AutoClip source videos are read-only; projects, uploaded assets, transcripts, render jobs, metrics, provider settings and outputs live under `workspace-user/` here. Verification artifacts are retained separately under `workspace/`.

## Run

```sh
cd /Users/yuriy/autoclip/shorts-studio-sandbox
./run.sh
```

Visit http://127.0.0.1:8317. AutoClip remains at http://localhost:3001.

## Creation workflows

- **Existing footage:** Upload a video or reference an existing AutoClip source; import SRT or transcribe locally with the bundled Whisper model; generate 15/30/60-second non-overlapping sentence-complete candidates; adjust exact boundaries; choose blur padding or crop; request a local subject-center suggestion; render synchronized captions and normalized source audio.
- **Animated explainers:** Enter an idea; use the finished local template or an optional configured text model; edit scenes, timing, animation, media, captions, voice and brand; render an MP4.
- **Character stories:** Save a reusable series identity and character reference, generate editable stories, create local character animation, or attach uploaded/generated media to individual scenes.
- **Satisfying loops:** Create a short procedural loop or attach an original visual and optional AI motion shot.
- **Experiments:** Queue 15/30/60 variants and two hook variants. Record YouTube/TikTok/Instagram metrics, compared by platform and duration band.

## Rendering

The persistent single-worker queue survives server restarts, limits peak memory, checks free disk space, cleans temporary files and supports cancel/retry. Exports are H.264/AAC MP4 plus SRT and a thumbnail, at 360p draft, 720p, or 1080p. Source files are never overwritten. Uploaded narration overrides generated local narration.

## Providers and cost controls

Local templates, procedural animation, system narration, FFmpeg, source clipping, captions and Whisper transcription have no API charge. Optional text generation uses a configurable HTTPS OpenAI-compatible chat-completions endpoint. Optional Runway image-to-video uses its documented task API and requires a reference image, 5/10-second duration and per-job maximum-credit cap. Credentials are stored server-side in `workspace/providers.env` with mode 0600 and are excluded from project JSON and API responses. Estimates use the configurable credit rate; verify current provider pricing before running paid jobs. A recovered Runway job with an existing task ID polls that task rather than submitting another paid generation.

The inherited Qwen credentials were rejected with HTTP 401 during verification on September 4, 2026. Replace the key in Settings to use AI drafting. Runway has not been configured, so no paid video request was made. These external features fail with explicit errors while all local workflows remain available.

## Known boundaries

- Local animation provides polished reusable 2D motion and a recurring character, rather than pretending to be photorealistic generative video.
- Local template copy is a coherent starting draft; factual claims still need human review. AI factual drafts are marked as needing review unless source notes are supplied.
- Uploaded narration is not automatically word-aligned. Scene captions are paced within each scene. Imported and Whisper-generated source transcripts retain timestamp alignment.
- Automatic crop uses sampled frame detail to suggest a stable horizontal center. Review a draft; it is not semantic face tracking.
- Performance metrics are manual because no social analytics account is connected. Comparisons are directional and grouped to avoid treating unlike platforms and durations as equivalent.

## Verification

See `TEST_REPORT.md`. Tests cover transcript cleanup, sentence-boundary selection, project validation, real H.264 MP4 rendering, local narration/audio mixing, current AutoClip source import, captioned vertical clip rendering, browser navigation, candidate review and persistent queue visibility.

## Remove or restore

Stop this server, then remove only `/Users/yuriy/autoclip/shorts-studio-sandbox`. AutoClip continues to use its existing files and data. The pre-experiment source checkpoint is `/Users/yuriy/autoclip/checkpoints/20260904-134216/source.tar.gz`, with a binary working-tree patch and status record alongside it. Restore that archive into a new directory when inspecting or recovering; do not extract it over active work blindly.
