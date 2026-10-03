/**
 * OmniFeed Frontend Application
 * Vanilla JS, 2s Polling, Zero external framework dependencies.
 * All backend API and media endpoints resolve dynamically from window.APP_CONFIG.API_BASE.
 */

const API_BASE = (window.APP_CONFIG && window.APP_CONFIG.API_BASE)
  ? window.APP_CONFIG.API_BASE.replace(/\/$/, '')
  : 'http://localhost:8000';

let currentView = 'create';
let activeJobId = null;
let jobsList = [];
let pollTimer = null;
let currentFilter = 'all';
let systemConfig = null;
let lastGlobalError = '';

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  checkSystemStatus();
  fetchJobs();
  startPolling();
});

// Global Error Banner Helpers
function showGlobalError(msg) {
  lastGlobalError = msg;
  const banner = document.getElementById('global-error-banner');
  const text = document.getElementById('global-error-text');
  if (banner && text) {
    text.textContent = msg;
    banner.classList.remove('hidden');
  }
}

function dismissGlobalError() {
  const banner = document.getElementById('global-error-banner');
  if (banner) banner.classList.add('hidden');
}

function copyGlobalError() {
  if (!lastGlobalError) return;
  navigator.clipboard.writeText(lastGlobalError);
  alert('Error details copied to clipboard.');
}

// Robust API fetch helper with clear error messages
async function apiFetch(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint.startsWith('/') ? '' : '/'}${endpoint}`;
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      let errText = '';
      try {
        const errJson = await res.json();
        errText = errJson.detail || errJson.message || JSON.stringify(errJson);
      } catch {
        errText = await res.text();
      }
      throw new Error(`HTTP ${res.status}: ${errText || res.statusText}`);
    }
    dismissGlobalError();
    return await res.json();
  } catch (err) {
    const msg = `API Request Failed: ${err.message || String(err)}`;
    console.error(msg);
    showGlobalError(msg);
    throw err;
  }
}

// View Navigation
function switchView(viewName) {
  currentView = viewName;

  document.querySelectorAll('.nav-tab').forEach(tab => {
    tab.className = 'nav-tab px-3 py-1.5 rounded-md text-slate-600 hover:text-slate-900 hover:bg-slate-100 border border-transparent';
  });

  const activeTab = document.getElementById(`nav-${viewName}`);
  if (activeTab) {
    activeTab.className = 'nav-tab active px-3 py-1.5 rounded-md text-teal-800 bg-teal-50 border border-teal-200';
  }

  const views = ['create', 'batch', 'library', 'status'];
  views.forEach(v => {
    const el = document.getElementById(`view-${v}`);
    if (el) {
      if (v === viewName) {
        el.classList.remove('hidden');
      } else {
        el.classList.add('hidden');
      }
    }
  });

  if (viewName === 'library') {
    fetchJobs();
  } else if (viewName === 'status') {
    checkSystemStatus();
  }
}

// System Status & Integrations Check
async function checkSystemStatus() {
  try {
    const data = await apiFetch('/api/status');
    systemConfig = data;

    // LLM badge
    const llmBadge = document.getElementById('cfg-llm-badge');
    const llmModel = document.getElementById('cfg-llm-model');
    if (llmBadge) {
      if (data.providers.llm.configured) {
        llmBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-emerald-50 text-emerald-700 border border-emerald-200';
        llmBadge.textContent = 'Configured';
        llmModel.textContent = `Model: ${data.providers.llm.model}`;
      } else {
        llmBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-rose-50 text-rose-700 border border-rose-200';
        llmBadge.textContent = 'Missing API Key';
        llmModel.textContent = 'Set LLM_API_KEY or GEMINI_API_KEY in backend/.env';
      }
    }

    // Pixabay badge (Optional / Auto-Fallback)
    const pixBadge = document.getElementById('cfg-pixabay-badge');
    if (pixBadge) {
      if (data.providers.pixabay.configured) {
        pixBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-emerald-50 text-emerald-700 border border-emerald-200';
        pixBadge.textContent = 'Active (Stock)';
      } else {
        pixBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-600 border border-slate-200';
        pixBadge.textContent = 'Fallback Scene Cards';
      }
    }

    // Image badge (Optional)
    const imgBadge = document.getElementById('cfg-image-badge');
    const imgModel = document.getElementById('cfg-image-model');
    if (imgBadge) {
      if (data.providers.image_generation.configured) {
        imgBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-emerald-50 text-emerald-700 border border-emerald-200';
        imgBadge.textContent = 'Active (Optional)';
        imgModel.textContent = `OpenAI Image: ${data.providers.image_generation.model || 'dall-e-3'}`;
      } else {
        imgBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-500';
        imgBadge.textContent = 'Optional (Unset)';
        imgModel.textContent = 'Unset (pipeline uses built-in 9:16 scene cards)';
      }
    }

    // FFmpeg badge
    const ffmpegBadge = document.getElementById('cfg-ffmpeg-badge');
    if (ffmpegBadge) {
      if (data.media_engine.ffmpeg) {
        ffmpegBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-emerald-50 text-emerald-700 border border-emerald-200';
        ffmpegBadge.textContent = 'Installed';
      } else {
        ffmpegBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-rose-50 text-rose-700 border border-rose-200';
        ffmpegBadge.textContent = 'Missing';
      }
    }

    // ffprobe badge
    const ffprobeBadge = document.getElementById('cfg-ffprobe-badge');
    if (ffprobeBadge) {
      if (data.media_engine.ffprobe) {
        ffprobeBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-emerald-50 text-emerald-700 border border-emerald-200';
        ffprobeBadge.textContent = 'Installed';
      } else {
        ffprobeBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-rose-50 text-rose-700 border border-rose-200';
        ffprobeBadge.textContent = 'Missing';
      }
    }

    // Qoneqt badge
    const qBadge = document.getElementById('cfg-qoneqt-badge');
    const qMode = document.getElementById('cfg-qoneqt-mode');
    if (qBadge) {
      if (data.providers.qoneqt_api.configured) {
        qBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-teal-50 text-teal-700 border border-teal-200';
        qBadge.textContent = 'Direct API Mode';
        qMode.textContent = `Direct upload endpoint active (${data.providers.qoneqt_api.app_url})`;
      } else {
        qBadge.className = 'text-xs px-2 py-0.5 rounded font-medium bg-slate-100 text-slate-500';
        qBadge.textContent = 'Assisted Publishing';
        qMode.textContent = 'Assisted copy & download workflow (default)';
      }
    }

  } catch (err) {
    console.error('Error fetching system status:', err);
  }
}

// Individual Diagnostic Tests
async function runTestLLM() {
  const btn = document.getElementById('btn-test-llm');
  const resEl = document.getElementById('test-llm-result');
  btn.disabled = true;
  btn.textContent = 'Testing...';
  resEl.classList.remove('hidden');
  resEl.textContent = 'Sending latency ping to LLM endpoint...';

  try {
    const data = await apiFetch('/api/status/test-llm', { method: 'POST' });
    if (data.success) {
      resEl.className = 'text-xs text-emerald-800 font-mono bg-emerald-50 p-2 rounded border border-emerald-200';
      resEl.textContent = `✓ Passed in ${data.latency_ms}ms (model: ${data.model})\n${data.message}`;
    } else {
      resEl.className = 'text-xs text-rose-800 font-mono bg-rose-50 p-2 rounded border border-rose-200';
      resEl.textContent = `✗ Failed in ${data.latency_ms}ms\n${data.message}`;
    }
  } catch (err) {
    resEl.className = 'text-xs text-rose-800 font-mono bg-rose-50 p-2 rounded border border-rose-200';
    resEl.textContent = `✗ Network Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
}

async function runTestImage() {
  const btn = document.getElementById('btn-test-image');
  const resEl = document.getElementById('test-image-result');
  btn.disabled = true;
  btn.textContent = 'Testing...';
  resEl.classList.remove('hidden');
  resEl.textContent = 'Testing AI image provider endpoint...';

  try {
    const data = await apiFetch('/api/status/test-image', { method: 'POST' });
    if (data.success) {
      resEl.className = 'text-xs text-emerald-800 font-mono bg-emerald-50 p-2 rounded border border-emerald-200';
      resEl.textContent = `✓ ${data.message} (${data.latency_ms}ms)`;
    } else {
      resEl.className = 'text-xs text-rose-800 font-mono bg-rose-50 p-2 rounded border border-rose-200';
      resEl.textContent = `✗ Failed (${data.latency_ms}ms): ${data.message}`;
    }
  } catch (err) {
    resEl.className = 'text-xs text-rose-800 font-mono bg-rose-50 p-2 rounded border border-rose-200';
    resEl.textContent = `✗ Network Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
}

async function runTestPixabay() {
  const btn = document.getElementById('btn-test-pixabay');
  const resEl = document.getElementById('test-pixabay-result');
  btn.disabled = true;
  btn.textContent = 'Testing...';
  resEl.classList.remove('hidden');
  resEl.textContent = 'Querying Pixabay API...';

  try {
    const data = await apiFetch('/api/status/test-pixabay', { method: 'POST' });
    if (data.success) {
      resEl.className = 'text-xs text-emerald-800 font-mono bg-emerald-50 p-2 rounded border border-emerald-200';
      resEl.textContent = `✓ ${data.message} (${data.latency_ms}ms)`;
    } else {
      resEl.className = 'text-xs text-rose-800 font-mono bg-rose-50 p-2 rounded border border-rose-200';
      resEl.textContent = `✗ Failed (${data.latency_ms}ms): ${data.message}`;
    }
  } catch (err) {
    resEl.className = 'text-xs text-rose-800 font-mono bg-rose-50 p-2 rounded border border-rose-200';
    resEl.textContent = `✗ Network Error: ${err.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
}

// Full Pipeline Self-Test (Requirement 9)
async function runFullSelfTest() {
  const btn = document.getElementById('btn-run-selftest');
  const card = document.getElementById('selftest-card');
  const overallBadge = document.getElementById('selftest-overall-badge');
  const grid = document.getElementById('selftest-results-grid');

  btn.disabled = true;
  btn.innerHTML = `
    <svg class="animate-spin w-4 h-4 text-white" fill="none" viewBox="0 0 24 24">
      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
    </svg>
    <span>Testing Pipeline Components...</span>
  `;

  card.classList.remove('hidden');
  overallBadge.className = 'text-xs px-2.5 py-0.5 rounded font-bold bg-teal-100 text-teal-800';
  overallBadge.textContent = 'Running Tests...';
  grid.innerHTML = '<span class="text-xs text-slate-500 italic">Executing live diagnostic suite on LLM, TTS, Pixabay, Caption Burn, and ffprobe...</span>';

  try {
    const res = await apiFetch('/api/status/self-test', { method: 'POST' });
    const tests = res.results || {};

    if (res.all_passed) {
      overallBadge.className = 'text-xs px-2.5 py-0.5 rounded font-bold bg-emerald-100 text-emerald-800';
      overallBadge.textContent = 'ALL TESTS PASSED';
    } else {
      overallBadge.className = 'text-xs px-2.5 py-0.5 rounded font-bold bg-amber-100 text-amber-800';
      overallBadge.textContent = 'SOME TESTS FAILED';
    }

    const testCards = [
      { id: 'LLM Engine', key: 'llm', label: '1. LLM Chat Completions' },
      { id: 'TTS Synthesis', key: 'tts', label: '2. TTS Voice Synthesis' },
      { id: 'Pixabay Visuals', key: 'pixabay', label: '3. Pixabay / Scene Visuals' },
      { id: 'Caption Burn', key: 'caption_burn', label: '4. FFmpeg ASS Caption Burn' },
      { id: 'ffprobe Inspector', key: 'ffprobe', label: '5. ffprobe Media Verifier' },
    ];

    grid.innerHTML = testCards.map(tc => {
      const item = tests[tc.key] || { success: false, message: 'Not executed' };
      const isOk = item.success;
      const borderClass = isOk ? 'border-emerald-200 bg-white' : 'border-rose-200 bg-rose-50/50';
      const statusClass = isOk ? 'text-emerald-700 bg-emerald-100' : 'text-rose-700 bg-rose-100';
      const mark = isOk ? '✓' : '✗';
      const latencyStr = item.latency_ms ? ` · ${item.latency_ms}ms` : '';

      return `
        <div class="border rounded-md p-3 space-y-1 ${borderClass}">
          <div class="flex items-center justify-between font-semibold">
            <span class="text-slate-800">${tc.label}</span>
            <span class="text-xxs px-1.5 py-0.5 rounded font-bold ${statusClass}">
              ${mark} ${isOk ? 'PASS' : 'FAIL'}
            </span>
          </div>
          <p class="text-xxs text-slate-600 font-mono break-words">${escapeHtml(item.message || '')}${latencyStr}</p>
        </div>
      `;
    }).join('');

  } catch (err) {
    overallBadge.className = 'text-xs px-2.5 py-0.5 rounded font-bold bg-rose-100 text-rose-800';
    overallBadge.textContent = 'SELF-TEST ERROR';
    grid.innerHTML = `<span class="text-xs text-rose-700 font-mono">Error running self-test: ${escapeHtml(err.message)}</span>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
      <span>Run Full Self-Test</span>
    `;
  }
}

// Single Job Submission
async function handleCreateJob(event) {
  event.preventDefault();
  const btn = document.getElementById('btn-submit-create');
  btn.disabled = true;
  btn.textContent = 'Queueing Pipeline...';

  const payload = {
    topic: document.getElementById('input-topic').value.trim(),
    language: document.getElementById('select-language').value,
    target_length: parseInt(document.getElementById('select-length').value, 10),
    tone: document.getElementById('select-tone').value,
    visual_style: document.getElementById('select-style').value,
    community_name: document.getElementById('input-community-name').value.trim(),
    community_description: document.getElementById('input-community-desc').value.trim(),
    add_ai_disclosure: document.getElementById('check-disclosure').checked,
  };

  try {
    const job = await apiFetch('/api/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    document.getElementById('input-topic').value = '';
    switchView('library');
    openJobModal(job.id);
    fetchJobs();

  } catch (err) {
    alert(`Submission Failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate Video Package';
  }
}

// Batch Job Submission
async function handleBatchJob(event) {
  event.preventDefault();
  const btn = document.getElementById('btn-submit-batch');
  btn.disabled = true;
  btn.textContent = 'Queueing Batch...';

  const rawTopics = document.getElementById('batch-topics').value;
  const topics = rawTopics
    .split('\n')
    .map(t => t.trim())
    .filter(t => t.length > 2);

  if (topics.length === 0) {
    alert('Please enter at least one valid topic.');
    btn.disabled = false;
    btn.textContent = 'Queue Batch Generation';
    return;
  }

  const payload = {
    topics: topics,
    language: document.getElementById('batch-language').value,
    target_length: parseInt(document.getElementById('batch-length').value, 10),
    visual_style: document.getElementById('batch-style').value,
    tone: 'Informative',
    add_ai_disclosure: true,
  };

  try {
    const data = await apiFetch('/api/jobs/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    document.getElementById('batch-topics').value = '';
    switchView('library');
    fetchJobs();

  } catch (err) {
    alert(`Batch Submission Failed: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Queue Batch Generation';
  }
}

// Real-Time 2s Polling
function startPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    await fetchJobs(true);
    if (activeJobId) {
      await refreshActiveJobModal();
    }
  }, 2000);
}

// Video Library Fetch & Render
async function fetchJobs(silent = false) {
  try {
    const url = currentFilter && currentFilter !== 'all' ? `/api/jobs?status=${currentFilter}` : '/api/jobs';
    const jobs = await apiFetch(url);
    jobsList = jobs;

    const countEl = document.getElementById('library-count');
    if (countEl) countEl.textContent = jobs.length;

    renderLibraryTable(jobs);
  } catch (err) {
    if (!silent) console.error('Error fetching jobs:', err);
  }
}

function filterLibrary(status) {
  currentFilter = status;
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.className = 'filter-btn px-2.5 py-1 rounded font-medium text-slate-600 hover:text-slate-900';
  });
  if (event && event.target) {
    event.target.className = 'filter-btn px-2.5 py-1 rounded font-medium bg-white text-slate-900 shadow-xs';
  }
  fetchJobs();
}

function renderLibraryTable(jobs) {
  const tbody = document.getElementById('library-tbody');
  const empty = document.getElementById('library-empty');
  if (!tbody) return;

  if (!jobs || jobs.length === 0) {
    tbody.innerHTML = '';
    empty.classList.remove('hidden');
    return;
  }

  empty.classList.add('hidden');

  tbody.innerHTML = jobs.map(job => {
    // Status Badge Style
    let statusClass = 'bg-slate-100 text-slate-700';
    if (job.status === 'completed') statusClass = 'bg-emerald-50 text-emerald-700 border border-emerald-200';
    else if (job.status === 'processing') statusClass = 'bg-teal-50 text-teal-700 border border-teal-200 animate-pulse';
    else if (job.status === 'flagged') statusClass = 'bg-amber-50 text-amber-800 border border-amber-200';
    else if (job.status === 'failed') statusClass = 'bg-rose-50 text-rose-700 border border-rose-200';

    // Format created date
    const d = new Date(job.created_at);
    const dateStr = d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const totalTimeStr = job.total_duration_s ? `${job.total_duration_s}s` : '—';
    const displayTitle = job.title || job.topic;

    return `
      <tr class="hover:bg-slate-50/80 transition cursor-pointer" onclick="openJobModal('${job.id}')">
        <td class="py-3 px-4 font-medium text-slate-900 max-w-xs truncate">
          ${escapeHtml(displayTitle)}
        </td>
        <td class="py-3 px-4 uppercase text-xs font-mono text-slate-500">
          ${escapeHtml(job.language || 'en')}
        </td>
        <td class="py-3 px-4">
          <span class="text-xs px-2 py-0.5 rounded font-medium ${statusClass}">
            ${escapeHtml(job.status)}
          </span>
        </td>
        <td class="py-3 px-4 text-xs font-mono text-slate-600">
          ${escapeHtml(job.current_stage || 'input')}
        </td>
        <td class="py-3 px-4 text-xs font-mono text-slate-600">
          ${totalTimeStr}
        </td>
        <td class="py-3 px-4 text-xs text-slate-500 whitespace-nowrap">
          ${dateStr}
        </td>
        <td class="py-3 px-4 text-right space-x-2 whitespace-nowrap" onclick="event.stopPropagation()">
          <button onclick="openJobModal('${job.id}')" class="text-teal-700 hover:text-teal-900 text-xs font-medium">Inspect</button>
          <button onclick="deleteJobDirect('${job.id}')" class="text-rose-600 hover:text-rose-800 text-xs font-medium">Delete</button>
        </td>
      </tr>
    `;
  }).join('');
}

// Job Detail Modal Logic
function openJobModal(jobId) {
  activeJobId = jobId;
  const modal = document.getElementById('job-detail-modal');
  modal.classList.remove('hidden');
  refreshActiveJobModal();
}

function closeJobModal() {
  activeJobId = null;
  const modal = document.getElementById('job-detail-modal');
  modal.classList.add('hidden');
  const player = document.getElementById('modal-video-player');
  if (player) {
    player.pause();
    player.src = '';
  }
}

async function refreshActiveJobModal() {
  if (!activeJobId) return;

  try {
    const job = await apiFetch(`/api/jobs/${activeJobId}`);

    document.getElementById('modal-title').textContent = job.title || job.topic;
    document.getElementById('modal-topic').textContent = `Prompt: "${job.topic}" · ${job.language.toUpperCase()} · ${job.target_length}s · ${job.visual_style}`;
    document.getElementById('modal-job-id').textContent = `ID: ${job.id}`;

    // Status Badge
    const statusBadge = document.getElementById('modal-status-badge');
    let badgeClass = 'bg-slate-100 text-slate-700';
    if (job.status === 'completed') badgeClass = 'bg-emerald-50 text-emerald-700 border border-emerald-200';
    else if (job.status === 'processing') badgeClass = 'bg-teal-50 text-teal-700 border border-teal-200';
    else if (job.status === 'flagged') badgeClass = 'bg-amber-50 text-amber-800 border border-amber-200';
    else if (job.status === 'failed') badgeClass = 'bg-rose-50 text-rose-700 border border-rose-200';
    statusBadge.className = `text-xs px-2 py-0.5 rounded font-medium ${badgeClass}`;
    statusBadge.textContent = job.status;

    // Total Time
    document.getElementById('modal-total-time').textContent = job.total_duration_s ? `Total: ${job.total_duration_s}s` : '';

    // Render Stage Grid
    renderStagesGrid(job);

    // Video Player & Downloads
    const player = document.getElementById('modal-video-player');
    const placeholder = document.getElementById('modal-video-placeholder');
    const mediaActions = document.getElementById('modal-media-actions');
    const btnMp4 = document.getElementById('btn-download-mp4');
    const btnThumb = document.getElementById('btn-download-thumb');

    if (job.video_path && (job.status === 'completed' || job.status === 'flagged')) {
      const videoUrl = `${API_BASE}/media/${job.id}/video.mp4`;
      if (player.src !== videoUrl) {
        player.src = videoUrl;
        player.crossOrigin = "anonymous";
      }
      player.classList.remove('hidden');
      placeholder.classList.add('hidden');
      mediaActions.classList.remove('hidden');
      btnMp4.href = videoUrl;
      btnThumb.href = `${API_BASE}/media/${job.id}/thumbnail.jpg`;
    } else {
      player.classList.add('hidden');
      placeholder.classList.remove('hidden');
      mediaActions.classList.add('hidden');
    }

    // Quality Report Card
    renderQualityCard(job);

    // Content Safety Card
    renderSafetyCard(job);

    // Publishing Card
    renderPublishingCard(job);

    // Hooks
    renderHooks(job);

    // Script & Scenes
    document.getElementById('modal-script').textContent = job.script_text || 'Narration script generating...';
    renderScenes(job);

    // Caption
    const captionEl = document.getElementById('modal-caption');
    let fullCaptionText = job.post_caption || '';
    if (job.hashtags && job.hashtags.length > 0) {
      fullCaptionText += `\n\n${job.hashtags.join(' ')}`;
    }
    captionEl.value = fullCaptionText;

    // Error box with failing stage & copy button
    const errorBox = document.getElementById('modal-error-box');
    const errorMsg = document.getElementById('modal-error-msg');
    const errorStage = document.getElementById('modal-error-stage');
    if (job.status === 'failed' && job.error_message) {
      errorBox.classList.remove('hidden');
      errorStage.textContent = `stage: ${job.current_stage || 'unknown'}`;
      errorMsg.textContent = job.error_message;
    } else {
      errorBox.classList.add('hidden');
    }

  } catch (err) {
    console.error('Error refreshing active modal:', err);
  }
}

function copyModalError() {
  const errorMsg = document.getElementById('modal-error-msg');
  const errorStage = document.getElementById('modal-error-stage');
  const btnText = document.getElementById('copy-error-btn-text');

  const textToCopy = `[Failed Stage: ${errorStage ? errorStage.textContent : 'unknown'}]\n\n${errorMsg ? errorMsg.textContent : ''}`;
  navigator.clipboard.writeText(textToCopy);

  if (btnText) {
    const prev = btnText.textContent;
    btnText.textContent = 'Copied!';
    setTimeout(() => { btnText.textContent = prev; }, 2000);
  }
}

// Stage progress with real measured seconds
const PIPELINE_STAGES = [
  { key: 'input', label: '1. Ingestion' },
  { key: 'llm_script', label: '2. Script & Plan' },
  { key: 'content_check', label: '3. Safety Check' },
  { key: 'tts_voice', label: '4. Voice Synthesis' },
  { key: 'visuals', label: '5. Scene Visuals' },
  { key: 'captions', label: '6. Kinetic Captions' },
  { key: 'ffmpeg_render', label: '7. FFmpeg Assembly' },
  { key: 'quality_check', label: '8. ffprobe Quality' },
];

function renderStagesGrid(job) {
  const container = document.getElementById('modal-stages-grid');
  const timings = job.stage_timings || {};

  container.innerHTML = PIPELINE_STAGES.map(stage => {
    const st = timings[stage.key];
    let statusText = 'pending';
    let durationText = '—';
    let boxClass = 'bg-slate-50 border-slate-200 text-slate-400';

    if (st) {
      if (st.status === 'completed') {
        statusText = 'completed';
        boxClass = 'bg-white border-emerald-200 text-slate-800 shadow-xs';
        durationText = `${st.duration_s}s`;
      } else if (st.status === 'processing') {
        statusText = 'active...';
        boxClass = 'bg-teal-50 border-teal-300 text-teal-900 animate-pulse';
        durationText = 'running';
      } else if (st.status === 'failed') {
        statusText = 'failed';
        boxClass = 'bg-rose-50 border-rose-300 text-rose-800';
        durationText = 'error';
      }
    }

    return `
      <div class="border rounded p-2 text-xs flex flex-col justify-between ${boxClass}">
        <span class="font-medium truncate">${stage.label}</span>
        <div class="flex items-center justify-between mt-1 text-xxs font-mono">
          <span class="uppercase">${statusText}</span>
          <span class="font-bold">${durationText}</span>
        </div>
      </div>
    `;
  }).join('');
}

function renderQualityCard(job) {
  const badge = document.getElementById('quality-overall-badge');
  const list = document.getElementById('quality-checks-list');
  const q = job.quality_report;

  if (!q || !q.checks || q.checks.length === 0) {
    badge.className = 'px-1.5 py-0.5 rounded text-slate-500 bg-slate-100';
    badge.textContent = 'Pending';
    list.innerHTML = '<span class="text-slate-400 italic">ffprobe checks will execute upon video assembly.</span>';
    return;
  }

  if (q.passed) {
    badge.className = 'px-1.5 py-0.5 rounded text-emerald-800 bg-emerald-100 font-medium';
    badge.textContent = 'All Checks Passed';
  } else {
    badge.className = 'px-1.5 py-0.5 rounded text-rose-800 bg-rose-100 font-medium';
    badge.textContent = 'Quality Issue';
  }

  list.innerHTML = q.checks.map(c => `
    <div class="flex items-center justify-between text-xs py-0.5">
      <div class="flex items-center space-x-1.5">
        <span class="${c.passed ? 'text-emerald-600' : 'text-rose-600'} font-bold">
          ${c.passed ? '✓' : '✗'}
        </span>
        <span class="text-slate-700">${escapeHtml(c.name)}</span>
      </div>
      <span class="font-mono text-slate-600 text-xxs">${escapeHtml(c.measured)}</span>
    </div>
  `).join('');
}

function renderSafetyCard(job) {
  const badge = document.getElementById('safety-status-badge');
  const reason = document.getElementById('safety-reason');
  const approveAction = document.getElementById('safety-approval-action');
  const sc = job.content_check;

  if (!sc || typeof sc.passed === 'undefined') {
    badge.className = 'px-1.5 py-0.5 rounded text-slate-500 bg-slate-100';
    badge.textContent = 'Pending';
    reason.textContent = 'Automated policy check executing...';
    approveAction.classList.add('hidden');
    return;
  }

  if (sc.flagged && !job.content_approved_by_user) {
    badge.className = 'px-1.5 py-0.5 rounded text-amber-800 bg-amber-100 font-medium';
    badge.textContent = 'Flagged for Review';
    reason.textContent = `Warning: ${sc.reason || 'Flagged by content check'}`;
    approveAction.classList.remove('hidden');
  } else if (sc.flagged && job.content_approved_by_user) {
    badge.className = 'px-1.5 py-0.5 rounded text-teal-800 bg-teal-100 font-medium';
    badge.textContent = 'Approved by Creator';
    reason.textContent = `Flag acknowledged: ${sc.reason}`;
    approveAction.classList.add('hidden');
  } else {
    badge.className = 'px-1.5 py-0.5 rounded text-emerald-800 bg-emerald-100 font-medium';
    badge.textContent = 'Passed';
    reason.textContent = sc.reason || 'Content passed all safety checks.';
    approveAction.classList.add('hidden');
  }
}

function renderPublishingCard(job) {
  const publishedBadge = document.getElementById('published-badge');
  const assistedSteps = document.getElementById('assisted-publish-steps');
  const apiSection = document.getElementById('api-publish-section');
  const confirmedInfo = document.getElementById('confirmed-publish-info');
  const postLink = document.getElementById('published-post-link');

  if (job.published_url) {
    publishedBadge.classList.remove('hidden');
    confirmedInfo.classList.remove('hidden');
    postLink.href = job.published_url;
    postLink.textContent = job.published_url;
    assistedSteps.classList.add('hidden');
    apiSection.classList.add('hidden');
    return;
  }

  publishedBadge.classList.add('hidden');
  confirmedInfo.classList.add('hidden');
  assistedSteps.classList.remove('hidden');

  if (systemConfig?.providers?.qoneqt_api?.configured) {
    apiSection.classList.remove('hidden');
  } else {
    apiSection.classList.add('hidden');
  }
}

function renderHooks(job) {
  const container = document.getElementById('hooks-list');
  const reasonEl = document.getElementById('chosen-hook-reason');
  const hooks = job.hooks || [];
  const chosenIdx = job.chosen_hook_index || 0;

  if (reasonEl) {
    reasonEl.textContent = job.hook_selection_reason ? `Decision: ${job.hook_selection_reason}` : '';
  }

  if (hooks.length === 0) {
    container.innerHTML = '<span class="text-xs text-slate-400 italic">Hooks generating...</span>';
    return;
  }

  container.innerHTML = hooks.map((h, idx) => {
    const isSelected = idx === chosenIdx;
    return `
      <div class="border rounded p-2.5 text-xs flex flex-col justify-between ${isSelected ? 'border-teal-600 bg-teal-50/50' : 'border-slate-200 bg-white'}">
        <div class="space-y-1">
          <div class="flex items-center justify-between text-xxs">
            <span class="font-semibold uppercase tracking-wider text-slate-500">${escapeHtml(h.type || `Candidate 0${idx+1}`)}</span>
            ${isSelected ? '<span class="text-teal-800 font-bold">Selected Hook</span>' : ''}
          </div>
          <p class="font-medium text-slate-900 leading-snug">"${escapeHtml(h.hook || '')}"</p>
        </div>
        ${!isSelected ? `
          <button onclick="selectHook(${idx})" class="mt-2 text-xxs text-teal-700 hover:text-teal-900 font-medium text-left">
            Select this hook
          </button>
        ` : ''}
      </div>
    `;
  }).join('');
}

function renderScenes(job) {
  const container = document.getElementById('modal-scenes-grid');
  const scenes = job.scenes || [];

  if (scenes.length === 0) {
    container.innerHTML = '<span class="text-xs text-slate-400 italic">Scene breakdown generating...</span>';
    return;
  }

  container.innerHTML = scenes.map(s => {
    const imgUrl = `${API_BASE}/media/${job.id}/scene_${s.scene_id}.jpg`;
    return `
      <div class="border border-slate-200 rounded overflow-hidden bg-white text-xs flex flex-col">
        <div class="w-full aspect-[9/16] bg-slate-900 relative">
          <img src="${imgUrl}" alt="Scene ${s.scene_id}" class="w-full h-full object-cover" onerror="this.style.display='none'" />
          <div class="absolute top-2 left-2 bg-slate-900/80 text-white font-mono text-xxs px-1.5 py-0.5 rounded">
            Scene 0${s.scene_id} (${s.duration_s || '4.0'}s)
          </div>
          ${s.emphasis ? `
            <div class="absolute bottom-2 left-2 right-2 bg-slate-900/85 text-teal-300 font-bold text-xxs px-2 py-1 rounded truncate">
              ${escapeHtml(s.emphasis)}
            </div>
          ` : ''}
        </div>
        <div class="p-2 space-y-1 flex-1 flex flex-col justify-between">
          <p class="text-slate-800 leading-tight">${escapeHtml(s.narration || '')}</p>
          <div class="text-xxs text-slate-400 pt-1 border-t border-slate-100 truncate">
            Provider: ${escapeHtml(s.visual_provider || 'generating')}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

// Action Handlers
async function approveJobContent() {
  if (!activeJobId) return;
  try {
    await apiFetch(`/api/jobs/${activeJobId}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    await refreshActiveJobModal();
    fetchJobs();
  } catch (err) {
    alert(err.message);
  }
}

async function selectHook(hookIndex) {
  if (!activeJobId) return;
  try {
    await apiFetch(`/api/jobs/${activeJobId}/select-hook`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ hook_index: hookIndex }),
    });
    await refreshActiveJobModal();
  } catch (err) {
    alert(err.message);
  }
}

async function retryCurrentJob() {
  if (!activeJobId) return;
  try {
    await apiFetch(`/api/jobs/${activeJobId}/retry`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    await refreshActiveJobModal();
    fetchJobs();
  } catch (err) {
    alert(err.message);
  }
}

async function deleteCurrentJob() {
  if (!activeJobId) return;
  if (!confirm('Are you sure you want to delete this video job and all its media files?')) return;
  try {
    await apiFetch(`/api/jobs/${activeJobId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
    closeJobModal();
    fetchJobs();
  } catch (err) {
    alert(err.message);
  }
}

async function deleteJobDirect(jobId) {
  if (!confirm('Delete this video job?')) return;
  try {
    await apiFetch(`/api/jobs/${jobId}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
    });
    fetchJobs();
  } catch (err) {
    alert(err.message);
  }
}

// Publishing Handlers
async function confirmAssistedPublish() {
  if (!activeJobId) return;
  const input = document.getElementById('input-confirm-url');
  const url = input.value.trim();
  if (!url) {
    alert('Please enter your published post URL on Qoneqt');
    return;
  }

  try {
    await apiFetch(`/api/jobs/${activeJobId}/confirm-published`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ post_url: url }),
    });
    await refreshActiveJobModal();
    fetchJobs();
  } catch (err) {
    alert(err.message);
  }
}

async function publishViaAPI() {
  if (!activeJobId) return;
  const btn = document.getElementById('btn-api-publish');
  const respEl = document.getElementById('api-publish-response');
  btn.disabled = true;
  btn.textContent = 'Publishing...';
  respEl.classList.add('hidden');

  try {
    const data = await apiFetch(`/api/jobs/${activeJobId}/publish`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    respEl.classList.remove('hidden');
    respEl.textContent = JSON.stringify(data, null, 2);

    await refreshActiveJobModal();
    fetchJobs();
  } catch (err) {
    alert(`Publishing Error: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Publish via API';
  }
}

function copyPostCaption() {
  const captionEl = document.getElementById('modal-caption');
  captionEl.select();
  navigator.clipboard.writeText(captionEl.value);

  const textEl = document.getElementById('copy-caption-text');
  const prev = textEl.textContent;
  textEl.textContent = 'Copied!';
  setTimeout(() => {
    textEl.textContent = prev;
  }, 2000);
}

// Helper: Escape HTML
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
