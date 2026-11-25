# Verification report — September 4, 2026

## Passed

- `node --check app.js` and `node --check studio.js`.
- Python compile check for server and studio modules.
- 3 unit tests: SRT speaker-marker cleanup and round trip; non-overlapping sentence-complete window selection; project validation and invalid clip rejection.
- Real procedural render: 3.00-second 360×640 H.264 MP4 plus SRT and thumbnail.
- Real local narration render: 4.00-second 360×640 MP4 with H.264 video and AAC audio; character animation and bold captions visually inspected.
- Current project read-only import: 655 transcript cues found; two 15-second candidates selected at complete sentence boundaries; one rendered to a 14.97-second vertical captioned MP4.
- Browser: all primary workflow controls loaded; Source Clips listed AutoClip projects and transcript state; candidate opened in the editor with exact boundaries/framing; queue showed persisted completed and failed job states with download/watch/retry actions.
- Source checkpoint integrity: no pre-sandbox source file changed compared with `checkpoints/20260904-134216/source.tar.gz`.

## External provider result

- Text provider adapter reached the configured endpoint; it returned HTTP 401. The failed job persisted with an actionable error and retry control. No usable text provider connection can be certified until the credential is replaced.
- Runway is unconfigured. No paid generation request was submitted. Endpoint integration, task persistence, polling, credit-cap enforcement and recovered-task behavior were implemented from official API documentation; live generation requires a valid account/key and credits.

## September 5 editing improvements

- Expanded browser draft compatibility to clips, media scenes, up to 24 scenes and durations accepted by the backend.
- Added autosave, server version history, undo/redo, draggable scene timeline and preview scene timing that follows export weights.
- Offline factual drafts now use supplied source notes; missing notes produce an actionable error instead of unrelated copy.
- Short variants reduce scene count and narration at sentence boundaries, preserving the ending.
- Added local Whisper phrase alignment for narrated exports; verified a 4-second render and SRT with detected speech timestamps.
- Added music upload, configurable level, narration-triggered ducking, uploaded narration waveform and fade transitions.
- Added native Apple Vision face detection for sampled crop suggestions, retaining an explicitly labelled detail-based fallback.
- Five unit tests pass; JS syntax and Python compile checks pass. Pre-sandbox source checkpoint comparison remains unchanged.

Remaining limitations: quick canvas preview remains a sketch rather than pixel-identical export; render draft uses the actual final rendering pipeline. Crop suggestion is a stable sampled face center, not continuous speaker tracking. Offline fiction uses a reusable narrative structure; fully open-ended AI generation still requires a working text-provider key.
