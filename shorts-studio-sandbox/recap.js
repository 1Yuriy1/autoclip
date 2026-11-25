// Episode recaps have their own editor and draft; they never replace the animation canvas.
(() => {
  'use strict';
  const $r = id => document.getElementById('recap-' + id);
  const STORAGE_KEY = 'frame-lab-episode-recap-v1';
  const BEATS = ['Setup', 'Conflict', 'Main events', 'Climax', 'Resolution'];
  let recapProject = null, sourceMode = 'youtube', recapAssets = [], currentJob = null;
  let pollTimer = null, saveTimer = null, saveChain = Promise.resolve(), revision = 0;
  let busy = false, selectedBeat = null, latestResult = null;
  const copy = value => JSON.parse(JSON.stringify(value));
  const fmt = value => { const s = Math.max(0, Number(value) || 0); return `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, '0')}`; };
  const safe = fn => async (...args) => { try { return await fn(...args); } catch (error) { message(error.message, true); } };
  function message(text, error = false) { $r('status').textContent = text; $r('status').classList.toggle('error', error); }
  function remember() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({project: recapProject, jobId: currentJob?.id || null, result: latestResult})); }
    catch { message('Browser recovery is unavailable. Use Save recap to keep your project on the server.', true); }
  }
  function setBusy(value) {
    busy = value;
    for (const id of ['create', 'upload', 'source', 'youtube', 'new-title', 'duration', 'save', 'render']) $r(id).disabled = value;
    document.querySelectorAll('[data-recap-mode]').forEach(node => node.disabled = value);
    $r('create').textContent = value ? 'Working on your recap…' : 'Create episode recap ↗';
    $r('cancel').hidden = !value || !currentJob;
  }
  function chooseMode(mode) {
    sourceMode = mode;
    document.querySelectorAll('[data-recap-mode]').forEach(node => {
      const selected = node.dataset.recapMode === mode;
      node.classList.toggle('selected', selected); node.setAttribute('aria-selected', String(selected));
    });
    for (const name of ['youtube', 'upload', 'existing']) $r('input-' + name).hidden = name !== mode;
  }
  async function refreshRecapSources(selected) {
    recapAssets = await api('/assets');
    const picker = $r('source'), old = selected || picker.value;
    picker.replaceChildren(new Option('Choose a saved video…', ''));
    for (const asset of recapAssets.filter(a => a.mediaType === 'video')) {
      picker.add(new Option(`${asset.name} · ${fmt(asset.duration)}`, asset.id));
    }
    if (old && recapAssets.some(a => a.id === old)) picker.value = old;
    sourceDetails();
  }
  function sourceDetails() {
    const asset = recapAssets.find(a => a.id === $r('source').value);
    $r('source-note').textContent = asset ? `${fmt(asset.duration)} of footage · ${(asset.cues || []).length ? (asset.cues || []).length + ' transcript segments available' : 'Transcript will be generated automatically'}` : 'Videos already imported into Frame Lab appear here.';
  }
  async function uploadSource() {
    const file = $r('upload').files[0]; if (!file) return;
    setBusy(true); message('Uploading the episode. Keep this tab open until the upload finishes.');
    try {
      const asset = await uploadAsset(file);
      await refreshRecapSources(asset.id); chooseMode('existing');
      if (!$r('new-title').value) $r('new-title').value = file.name.replace(/\.[^.]+$/, '') + ' · recap';
      message('Episode uploaded. Choose a length, then create the recap.');
    } finally { setBusy(false); $r('upload').value = ''; }
  }
  function validateRecap() {
    if (!recapProject) throw Error('Create a recap first.');
    recapProject.title = $r('title').value.trim() || 'Episode recap';
    for (const [i, scene] of recapProject.scenes.entries()) {
      if (!scene.text.trim()) throw Error(`Add narration for ${BEATS[i] || 'beat ' + (i + 1)}.`);
      if (!Number.isFinite(scene.start) || !Number.isFinite(scene.end) || scene.start < 0 || scene.end <= scene.start) throw Error(`The footage end must follow the start in ${BEATS[i] || 'beat ' + (i + 1)}.`);
      if (recapProject.sourceDuration && scene.end > recapProject.sourceDuration + .05) throw Error(`The footage for ${BEATS[i]} extends past the episode.`);
      if (!Number.isFinite(scene.duration) || scene.duration < .5) throw Error(`Use at least half a second for ${BEATS[i]}.`);
    }
    if (![30, 60, 90].includes(Number(recapProject.duration))) throw Error('Choose a 30, 60 or 90 second recap.');
    return recapProject;
  }
  async function saveRecap(quiet = false) {
    clearTimeout(saveTimer); const snapshot = copy(validateRecap()), savedRevision = revision, editingProject = recapProject;
    $r('saved').textContent = 'Saving…';
    saveChain = saveChain.catch(() => {}).then(async () => {
      const saved = await api('/projects', {method: 'PUT', body: JSON.stringify(snapshot)});
      if (recapProject === editingProject) { recapProject.id = saved.id; recapProject.updated = saved.updated; }
      $r('saved').textContent = savedRevision === revision ? 'Saved ' + new Date().toLocaleTimeString() : 'New edits pending…';
      remember(); if (!quiet) message('Recap saved in your project library.'); return saved;
    }).catch(error => { $r('saved').textContent = 'Not saved: ' + error.message; throw error; });
    return saveChain;
  }
  function changed() {
    revision++; if (!recapProject.id) recapProject.id = crypto.randomUUID().replaceAll('-', '');
    $r('saved').textContent = 'Unsaved changes…';
    if (latestResult) $r('result-note').textContent = 'This export shows the previous saved edit. Render again to include your changes.';
    updateSummary(); remember(); clearTimeout(saveTimer);
    saveTimer = setTimeout(() => saveRecap(true).catch(error => message(error.message, true)), 1000);
  }
  function updateSummary() {
    if (!recapProject) return;
    const duration = Number(recapProject.duration);
    const words = recapProject.scenes.reduce((sum, s) => sum + String(s.text || '').trim().split(/\s+/).filter(Boolean).length, 0);
    $r('summary').textContent = `${recapProject.scenes.length} story beats · ${duration.toFixed(1)} seconds · ${words} narration words`;
    $r('script').textContent = recapProject.scenes.map(s => s.text).join('\n\n');
  }
  function sourceSeek(scene, autoplay = false) {
    selectedBeat = scene;
    const video = $r('source-video');
    $r('source-preview').hidden = false;
    $r('preview-label').textContent = `${scene.title || scene.beat || 'Selected footage'} · ${fmt(scene.start)}–${fmt(scene.end)}`;
    const url = '/api/assets/' + encodeURIComponent(recapProject.sourceId);
    const seek = () => { video.currentTime = scene.start; if (autoplay) video.play().catch(() => message('Press play on the source footage to preview this beat.')); };
    if (video.getAttribute('src') !== url) { video.src = url; video.addEventListener('loadedmetadata', seek, {once: true}); }
    else seek();
  }
  function normalizeProject(p) {
    const result = copy(p);
    result.scenes = (result.scenes || []).map((scene, i) => ({...scene,
      beat: scene.beat || scene.key || ['setup', 'conflict', 'key_events', 'climax', 'resolution'][i],
      title: scene.title || BEATS[i], text: scene.text || scene.narration || '',
      start: Number(scene.start ?? scene.sourceStart ?? scene.footage?.[0]?.start ?? 0),
      end: Number(scene.end ?? scene.sourceEnd ?? scene.footage?.[0]?.end ?? 0),
      duration: Number(scene.duration || result.duration / result.scenes.length), visual: 'video'
    }));
    return result;
  }
  function renderWarnings() {
    const warnings = $r('warnings'); warnings.replaceChildren();
    const mode = recapProject.analysisMode || recapProject.recap?.analysisMode;
    if (mode === 'extractive') warnings.append(el('strong', 'Transcript excerpt draft'));
    else if (mode === 'provider') warnings.append(el('strong', 'AI-written episode recap'));
    const list = recapProject.warnings || recapProject.recap?.warnings || [];
    for (const warning of (Array.isArray(list) ? list : [list])) if (warning) warnings.append(el('p', String(warning)));
    if (mode === 'extractive' && !list.length) warnings.append(el('p', 'This uses dialogue excerpts and approximate story sections. Review the beats or connect a text provider in Settings for an AI-written plot summary.'));
    warnings.hidden = !warnings.children.length;
  }
  function renderBeats() {
    const host = $r('beats'); host.replaceChildren();
    for (const [i, scene] of recapProject.scenes.entries()) {
      const card = el('article', '', 'recap-beat');
      const head = el('div', '', 'recap-beat-head'); head.append(el('span', String(i + 1).padStart(2, '0'), 'recap-beat-number'), el('h3', BEATS[i] || scene.beat));
      card.append(head);
      const titleLabel = el('label', 'Beat title'), title = el('input'); title.value = scene.title; title.maxLength = 180;
      title.oninput = () => { scene.title = title.value; changed(); }; titleLabel.append(title); card.append(titleLabel);
      const textLabel = el('label', 'Narration'), text = el('textarea'); text.rows = 3; text.value = scene.text; text.maxLength = 1800;
      text.oninput = () => { scene.text = text.value; scene.narration = text.value; changed(); }; textLabel.append(text); card.append(textLabel);
      const timing = el('div', '', 'recap-timing');
      for (const [label, key] of [['Footage start (seconds)', 'start'], ['Footage end (seconds)', 'end'], ['Screen time (seconds)', 'duration']]) {
        const wrapper = el('label', label), input = el('input');
        Object.assign(input, {type: 'number', min: key === 'duration' ? '.5' : '0', step: '.1', value: Number(scene[key]).toFixed(1)});
        input.onchange = () => {
          const value = Number(input.value);
          if (key === 'duration') {
            if (!Number.isFinite(value) || value < .5 || value > recapProject.duration - .5 * (recapProject.scenes.length - 1)) {
              input.value = Number(scene.duration).toFixed(1); message('Leave at least half a second for each of the five story beats.', true); return;
            }
            const others = recapProject.scenes.filter(s => s !== scene);
            const remaining = recapProject.duration - value - others.length * .5;
            const weights = others.map(s => Math.max(0, s.duration - .5));
            const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
            scene.duration = value;
            others.forEach((s, index) => { s.duration = .5 + remaining * (totalWeight ? weights[index] / totalWeight : 1 / others.length); });
            changed(); renderBeats();
          } else { scene[key] = value; changed(); }
        };
        wrapper.append(input); timing.append(wrapper);
      }
      card.append(timing);
      const preview = button('▶ Preview this footage', safe(() => sourceSeek(scene, true)));
      card.append(preview);
      if (scene.evidence?.length) {
        const evidence = el('details'), summary = el('summary', 'Transcript evidence'); evidence.append(summary);
        for (const cue of scene.evidence) evidence.append(el('p', `${fmt(cue.start)} — ${cue.text}`, 'hint'));
        card.append(evidence);
      }
      host.append(card);
    }
  }
  function displayProject(p) {
    clearTimeout(saveTimer); revision++; recapProject = normalizeProject(p);
    selectedBeat = null; $r('source-video').pause(); $r('source-preview').hidden = true;
    $r('editor').hidden = false; $r('title').value = recapProject.title || 'Episode recap';
    $r('captions').value = recapProject.captions || 'clean'; $r('layout').value = recapProject.layout || 'blur_pad';
    $r('voice').value = recapProject.voice || 'Samantha'; $r('saved').textContent = recapProject.id ? 'Saved in your project library' : 'Draft ready';
    renderWarnings(); renderBeats(); updateSummary(); remember();
  }
  function displayResult(job) {
    if (!job?.result?.url) return;
    latestResult = {id: job.id, updated: job.updated, result: job.result, projectId: recapProject?.id};
    $r('output').hidden = false;
    const video = $r('result-video'); video.src = job.result.url + '?v=' + (job.updated || job.id); video.load();
    $r('download').href = job.result.url;
    $r('srt').hidden = !job.result.srtUrl; if (job.result.srtUrl) $r('srt').href = job.result.srtUrl;
    $r('result-note').textContent = `${Number(job.result.duration || recapProject?.duration || 0).toFixed(1)} seconds · vertical MP4 · ready to download`;
    remember();
  }
  async function openRecapProject(p) {
    stop(); $r('result-video').pause(); latestResult = null; $r('output').hidden = true;
    displayProject(p); await showPage('recap'); message('Episode recap loaded. Edit any beat or render the saved version.');
    const jobs = await api('/jobs');
    const match = jobs.find(j => j.status === 'completed' && j.kind === 'render' && j.payload?.project?.id === p.id && j.result?.url);
    if (match) displayResult(match);
  }
  function jobUI(job) {
    currentJob = job; $r('progress-panel').hidden = false;
    $r('progress').value = Number(job.progress || 0); $r('progress-title').textContent = job.kind === 'render' ? 'Rendering the final video' : 'Building the episode recap';
    $r('progress-message').textContent = job.message || (job.status === 'queued' ? 'Queued. Your recap will start when the current job finishes.' : 'Working…');
    $r('job-state').textContent = job.status; $r('retry').hidden = !['failed', 'cancelled', 'interrupted'].includes(job.status);
    setBusy(['queued', 'running'].includes(job.status)); remember();
  }
  async function pollJob() {
    clearTimeout(pollTimer); if (!currentJob) return;
    const tracking = currentJob.id;
    try {
      const job = await api('/jobs/' + encodeURIComponent(tracking));
      if (currentJob?.id !== tracking) return;
      jobUI(job);
      if (job.status === 'completed') {
        if (job.kind === 'recap') {
          if (job.result?.project && recapProject?.id !== job.result.project.id) displayProject(job.result.project);
          if (job.result?.renderJobId) { currentJob = {id: job.result.renderJobId, kind: 'render', status: 'queued'}; remember(); await pollJob(); return; }
          message('Story beats are ready. Review the draft, then render the recap.');
        } else if (job.result?.url) { displayResult(job); message('Your episode recap is ready. Play it below or download the MP4.'); }
        setBusy(false); currentJob = null; remember(); await refreshLibrary(); return;
      }
      if (['failed', 'cancelled', 'interrupted'].includes(job.status)) { message(job.error || job.message || 'Recap stopped. You can retry this job.', job.status !== 'cancelled'); setBusy(false); return; }
      pollTimer = setTimeout(pollJob, 2400);
    } catch (error) {
      message('Unable to check progress: ' + error.message + ' Reconnecting…', true);
      pollTimer = setTimeout(pollJob, 5000);
    }
  }
  async function createRecap() {
    const payload = {duration: Number($r('duration').value), projectTitle: $r('new-title').value.trim(), autoRender: true, width: 720};
    if (sourceMode === 'youtube') {
      const input = $r('youtube').value.trim(); if (!input) throw Error('Paste the YouTube link for the episode.');
      let url; try { url = new URL(input); } catch { throw Error('Enter a valid YouTube video URL.'); }
      if (!['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(url.hostname.toLowerCase()) || !['https:', 'http:'].includes(url.protocol)) throw Error('Use a YouTube video link, or upload the episode file.');
      payload.youtubeUrl = input;
    } else {
      if (sourceMode === 'upload') throw Error('Choose a video file first. It will be selected automatically when the upload finishes.');
      payload.assetId = $r('source').value; if (!payload.assetId) throw Error('Choose an episode from your saved videos.');
    }
    if (recapProject) await saveRecap(true);
    currentJob = null; setBusy(true); message('Starting your recap. Import, transcript, story beats, narration and export will run in sequence.');
    try {
      const job = await api('/recaps', {method: 'POST', body: JSON.stringify(payload)});
      latestResult = null; $r('output').hidden = true; jobUI(job); await pollJob();
    } catch (error) { setBusy(false); throw error; }
  }
  async function renderRecap() {
    if (!recapProject) return;
    setBusy(true); message('Saving your edits and queueing the final video…');
    try {
      const saved = await saveRecap(true);
      const job = await api('/jobs', {method: 'POST', body: JSON.stringify({kind: 'render', payload: {project: saved, width: Number($r('width').value)}})});
      jobUI(job); await pollJob();
    } catch (error) { setBusy(false); throw error; }
  }
  document.querySelectorAll('[data-recap-mode]').forEach(node => node.onclick = () => chooseMode(node.dataset.recapMode));
  $r('upload').onchange = safe(uploadSource); $r('source').onchange = sourceDetails;
  $r('create').onclick = safe(createRecap); $r('save').onclick = safe(() => saveRecap()); $r('render').onclick = safe(renderRecap);
  $r('title').oninput = () => { recapProject.title = $r('title').value; changed(); };
  for (const key of ['captions', 'layout', 'voice']) $r(key).onchange = () => { recapProject[key] = $r(key).value; changed(); };
  $r('cancel').onclick = safe(async () => { if (currentJob) { const job = await api('/jobs/' + currentJob.id + '/cancel', {method: 'POST'}); jobUI(job); await pollJob(); } });
  $r('retry').onclick = safe(async () => { if (currentJob) { const job = await api('/jobs/' + currentJob.id + '/retry', {method: 'POST'}); jobUI(job); await pollJob(); } });
  $r('source-video').ontimeupdate = () => { if (selectedBeat && $r('source-video').currentTime >= selectedBeat.end) $r('source-video').pause(); };
  $r('source-video').onplay = () => { const video = $r('source-video'); if (selectedBeat && (video.currentTime >= selectedBeat.end || video.currentTime < selectedBeat.start)) video.currentTime = selectedBeat.start; };
  $r('source-video').onerror = () => message('This source could not be played. Check that the original episode file is still available.', true);
  $r('result-video').onerror = () => { if ($r('result-video').getAttribute('src')) message('The finished video could not be loaded. Try rendering the saved recap again.', true); };
  const priorOpen = openProject;
  openProject = p => p.format === 'recap' ? safe(openRecapProject)(p) : priorOpen(p);
  const priorShowPage = showPage;
  showPage = async page => {
    await priorShowPage(page);
    if (page === 'recap') {
      history.replaceState(null, '', '#recap'); await refreshRecapSources();
      const voices = studioStatus?.voices || ['Samantha']; const old = recapProject?.voice || $r('voice').value || 'Samantha';
      $r('voice').replaceChildren(...voices.map(v => new Option(v, v))); $r('voice').value = old;
      if (!$r('voice').value && voices.length) $r('voice').value = voices[0];
    } else {
      $r('source-video').pause(); $r('result-video').pause();
      if (location.hash === '#recap') history.replaceState(null, '', location.pathname + location.search);
    }
  };
  chooseMode('youtube');
  try {
    const recovered = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
    if (recovered?.project?.format === 'recap') displayProject(recovered.project);
    if (recovered?.result?.result?.url) displayResult(recovered.result);
    if (recovered?.jobId) { currentJob = {id: recovered.jobId}; safe(pollJob)(); }
  } catch { /* A damaged browser draft never prevents a new recap. */ }
  if (location.hash === '#recap') safe(() => showPage('recap'))();
})();
