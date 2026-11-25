# Shorts Studio build scope

Preserve AutoClip source checkpoint and production data. All implementation and generated assets stay in this sandbox. The sandbox may read explicitly imported source files but never writes to AutoClip.

- Persistent project library and reusable series identity (voice, palette, character).
- Three creation paths: source highlights, original explainers, character stories; satisfying loop template.
- Editable script/storyboard with per-scene timing, media and caption styling.
- Local narration and uploaded narration; transcript import/local transcription; word timing where available.
- MP4 render queue with progress, cancellation, retry, restart recovery, disk checks, temporary cleanup.
- Source clip selection that ends at sentence boundaries, automatic face-aware crop where available, manual crop fallback, 15/30/60 second variants.
- Original animation via deterministic local rendering, reusable character reference, uploaded illustrations and optional external AI shot generation.
- Configurable text/video provider credentials kept server-side; cost estimates and spending cap for paid video jobs.
- Batch variants and hook experiments, manual performance metrics grouped by platform and duration.
- Research/reference library with source links, dates and production recipes.
- Functional tests, actual render/media verification, browser workflow verification, launch and rollback instructions.
