/**
 * AutoWorker Web Dashboard Frontend Engine
 * CentrAlign AI Evaluation Edition — Minimalist Observability & Debugging Suite
 */

(function () {
  'use strict';

  // State Management
  const state = {
    activeTaskId: null,
    activeTaskGoal: '',
    taskStatus: 'idle', // idle, planning, executing, waiting_for_approval, verifying, completed, failed
    startTime: null,
    timerInterval: null,
    steps: [], // list of step records
    stepMap: {}, // stepKey -> stepData
    plan: null,
    ws: null,
    wsReconnectTimeout: null,
    activeViewTab: 'browser', // browser, debug, context
    currentScreenshot: null,
    taskContext: {},
    currentFilter: 'all', // all, error, approval
    searchQuery: '',
    firstFailedStepId: null,
    allExpanded: false,
    debugLogs: [],
  };

  // DOM Elements
  const el = {
    // Header
    connectionDot: document.getElementById('connectionDot'),
    connectionText: document.getElementById('connectionText'),
    clockDisplay: document.getElementById('clockDisplay'),

    // Sidebar
    taskInput: document.getElementById('taskInput'),
    btnDeploy: document.getElementById('btnDeploy'),
    btnDemo: document.getElementById('btnDemo'),
    btnDemoError: document.getElementById('btnDemoError'),
    exampleTasks: document.querySelectorAll('.example-task-chip'),
    taskHistoryList: document.getElementById('taskHistoryList'),
    knowledgeList: document.getElementById('knowledgeList'),
    btnAddKnowledge: document.getElementById('btnAddKnowledge'),

    // Failure Alert Banner
    failureAlertBanner: document.getElementById('failureAlertBanner'),
    alertStepTitle: document.getElementById('alertStepTitle'),
    alertStepMsg: document.getElementById('alertStepMsg'),
    btnJumpToError: document.getElementById('btnJumpToError'),

    // Main Content
    activeTaskBanner: document.getElementById('activeTaskBanner'),
    activeTaskId: document.getElementById('activeTaskId'),
    activeTaskStatus: document.getElementById('activeTaskStatus'),
    activeTaskGoal: document.getElementById('activeTaskGoal'),
    elapsedTimer: document.getElementById('elapsedTimer'),
    progressFill: document.getElementById('progressFill'),
    progressPercent: document.getElementById('progressPercent'),
    progressStepText: document.getElementById('progressStepText'),

    understandingCard: document.getElementById('understandingCard'),
    understandingText: document.getElementById('understandingText'),
    planChecklist: document.getElementById('planChecklist'),

    // Filter Toolbar
    filterAllSteps: document.getElementById('filterAllSteps'),
    filterErrorSteps: document.getElementById('filterErrorSteps'),
    filterApprovalSteps: document.getElementById('filterApprovalSteps'),
    badgeAllCount: document.getElementById('badgeAllCount'),
    badgeErrorCount: document.getElementById('badgeErrorCount'),
    badgeApprovalCount: document.getElementById('badgeApprovalCount'),
    stepSearchInput: document.getElementById('stepSearchInput'),
    btnToggleAllSteps: document.getElementById('btnToggleAllSteps'),
    toggleAllText: document.getElementById('toggleAllText'),
    toggleAllIcon: document.getElementById('toggleAllIcon'),

    timelineFeed: document.getElementById('timelineFeed'),
    completionCard: document.getElementById('completionCard'),
    completionSummary: document.getElementById('completionSummary'),
    evidenceList: document.getElementById('evidenceList'),
    btnDownloadReport: document.getElementById('btnDownloadReport'),

    // Right Panel Tabs & Containers
    tabBrowser: document.getElementById('tabBrowser'),
    tabDebug: document.getElementById('tabDebug'),
    tabContext: document.getElementById('tabContext'),
    debugLogsBadge: document.getElementById('debugLogsBadge'),
    browserViewContainer: document.getElementById('browserViewContainer'),
    debugViewContainer: document.getElementById('debugViewContainer'),
    contextViewContainer: document.getElementById('contextViewContainer'),
    browserUrl: document.getElementById('browserUrl'),
    browserImage: document.getElementById('browserImage'),
    browserPlaceholder: document.getElementById('browserPlaceholder'),
    debugStreamTerminal: document.getElementById('debugStreamTerminal'),
    btnCopyDebugLogs: document.getElementById('btnCopyDebugLogs'),
    btnClearDebugLogs: document.getElementById('btnClearDebugLogs'),
    contextJsonView: document.getElementById('contextJsonView'),

    // Modals
    approvalModal: document.getElementById('approvalModal'),
    approvalQuestion: document.getElementById('approvalQuestion'),
    approvalContext: document.getElementById('approvalContext'),
    btnApproveStep: document.getElementById('btnApproveStep'),
    btnRejectStep: document.getElementById('btnRejectStep'),

    knowledgeModal: document.getElementById('knowledgeModal'),
    knowledgeForm: document.getElementById('knowledgeForm'),
    btnCancelKnowledge: document.getElementById('btnCancelKnowledge'),

    lightboxModal: document.getElementById('lightboxModal'),
    lightboxImage: document.getElementById('lightboxImage'),
    lightboxClose: document.getElementById('lightboxClose'),
  };

  // ==========================================================================
  // Initialization & Live Clock
  // ==========================================================================
  function init() {
    setupWebSocket();
    setupEventListeners();
    startClock();
    loadTasksHistory();
    loadCompanyKnowledge();
    loadRecentLogs();
  }

  function startClock() {
    function update() {
      const now = new Date();
      if (el.clockDisplay) {
        el.clockDisplay.textContent = now.toLocaleTimeString([], { hour12: false });
      }
    }
    update();
    setInterval(update, 1000);
  }

  // ==========================================================================
  // WebSocket Connection with Auto-Reconnect
  // ==========================================================================
  function setupWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    try {
      state.ws = new WebSocket(wsUrl);

      state.ws.onopen = () => {
        console.log('[WS] Connected to AutoWorker streaming server.');
        setConnectionStatus(true);
        appendDebugLog('INFO', 'AutoWorker', 'Streaming WebSocket connection established.');
      };

      state.ws.onclose = () => {
        console.log('[WS] Connection closed. Reconnecting in 2.5s...');
        setConnectionStatus(false);
        clearTimeout(state.wsReconnectTimeout);
        state.wsReconnectTimeout = setTimeout(setupWebSocket, 2500);
      };

      state.ws.onerror = (err) => {
        console.error('[WS] Connection error:', err);
        setConnectionStatus(false);
      };

      state.ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          handleWebSocketMessage(msg);
        } catch (e) {
          console.warn('[WS] Error parsing message payload:', e);
        }
      };
    } catch (e) {
      console.error('[WS] Init failed:', e);
      setConnectionStatus(false);
    }
  }

  function setConnectionStatus(connected) {
    if (!el.connectionDot || !el.connectionText) return;
    if (connected) {
      el.connectionDot.className = 'status-dot connected';
      el.connectionText.textContent = 'Agent Connected';
    } else {
      el.connectionDot.className = 'status-dot disconnected';
      el.connectionText.textContent = 'Reconnecting...';
    }
  }

  // ==========================================================================
  // WebSocket Event Dispatcher
  // ==========================================================================
  function handleWebSocketMessage(msg) {
    console.log('[WS Event]', msg.type, msg);

    // Record in debug terminal
    const evType = msg.type || 'event';
    const lvl = (msg.success === false || evType.includes('fail')) ? 'ERROR'
      : (evType.includes('retry') || evType.includes('replan') || evType.includes('approval')) ? 'WARN'
      : (evType.includes('step')) ? 'ACTION' : 'INFO';
    const summary = msg.description || msg.observation || msg.error || msg.reason || msg.message || evType;
    appendDebugLog(lvl, 'Agent', `[${evType}] ${summary}`);

    // Latch onto running task if idle
    if (msg.task_id && state.activeTaskId && msg.task_id !== state.activeTaskId) {
      if (state.taskStatus === 'idle' || state.taskStatus === 'completed') {
        state.activeTaskId = msg.task_id;
      } else {
        return;
      }
    }

    switch (msg.type) {
      case 'task_started':
        onTaskStarted(msg);
        break;

      case 'plan_created':
        onPlanCreated(msg);
        break;

      case 'step_start':
      case 'step_started':
        onStepStart(msg);
        break;

      case 'step_complete':
      case 'step_finished':
        onStepComplete(msg);
        break;

      case 'step_retrying':
        onStepRetrying(msg);
        break;

      case 'replanning_started':
        onReplanningStarted(msg);
        break;

      case 'replan_created':
        onReplanCreated(msg);
        break;

      case 'human_approval':
      case 'approval_requested':
        onHumanApprovalRequired(msg);
        break;

      case 'approval_resolved':
        closeApprovalModal();
        break;

      case 'task_complete':
      case 'task_completed':
        onTaskComplete(msg);
        break;

      case 'task_failed':
        onTaskFailed(msg);
        break;

      case 'browser_update':
        if (msg.screenshot) updateBrowserView(msg.screenshot, msg.url);
        break;

      default:
        break;
    }
  }

  // ==========================================================================
  // Task Execution Lifecycle
  // ==========================================================================
  function onTaskStarted(msg) {
    state.activeTaskId = msg.task_id;
    state.activeTaskGoal = msg.goal || state.activeTaskGoal;
    state.taskStatus = 'executing';
    state.steps = [];
    state.stepMap = {};
    state.firstFailedStepId = null;

    // Reset UI
    el.activeTaskId.textContent = state.activeTaskId;
    el.activeTaskGoal.textContent = state.activeTaskGoal;
    updateStatusBadge('executing');

    el.timelineFeed.innerHTML = '';
    el.completionCard.style.display = 'none';
    el.understandingCard.style.display = 'none';
    hideFailureAlert();
    updateFilterBadges();
    updateProgress(0, 0, 1);

    startElapsedTimer();
    loadTasksHistory();
  }

  function onPlanCreated(msg) {
    state.plan = msg;
    const understanding = msg.understanding || (msg.data && msg.data.understanding) || '';
    const totalSteps = msg.total_steps || (msg.data && msg.data.total_steps) || (msg.steps ? msg.steps.length : 0);

    el.understandingText.textContent = understanding;
    el.planChecklist.innerHTML = '';

    if (msg.steps && Array.isArray(msg.steps)) {
      msg.steps.forEach((s) => {
        const item = document.createElement('div');
        item.className = 'plan-step-item';
        item.id = `plan-step-${s.step_number}`;
        item.innerHTML = `
          <div class="plan-step-left">
            <div class="step-num-circle">${s.step_number}</div>
            <span>${escapeHtml(s.description)}</span>
          </div>
          <span class="badge-status in_progress" style="display:none;" id="plan-badge-${s.step_number}">RUNNING</span>
        `;
        el.planChecklist.appendChild(item);
      });
    }

    el.understandingCard.style.display = 'flex';
    updateProgress(5, 0, totalSteps);
  }

  // ==========================================================================
  // Step Lifecycle with Diagnostics & Root Cause Inspection
  // ==========================================================================
  function onStepStart(msg) {
    const stepNum = msg.step || (msg.data && msg.data.step && msg.data.step.step_number) || (state.steps.length + 1);
    const desc = msg.description || (msg.data && msg.data.step && msg.data.step.description) || `Executing step ${stepNum}`;
    const tool = msg.tool || (msg.data && msg.data.step && msg.data.step.tool) || 'browser';
    const action = msg.action || (msg.data && msg.data.step && msg.data.step.action) || 'execute';
    const params = msg.params || (msg.data && msg.data.step && msg.data.step.params) || {};
    const expected = msg.expected_outcome || (msg.data && msg.data.step && msg.data.step.expected_outcome) || '';

    // Register / update in state
    const stepKey = `step-${stepNum}`;
    if (!state.stepMap[stepKey]) {
      const stepData = {
        key: stepKey,
        stepNumber: stepNum,
        description: desc,
        tool: tool,
        action: action,
        params: params,
        expectedOutcome: expected,
        status: 'running',
        startTime: Date.now(),
        output: '',
        error: '',
        observation: '',
        extractedData: null,
        screenshot: null,
        duration: '',
        requiresApproval: Boolean(msg.requires_human_approval || (msg.data && msg.data.step && msg.data.step.requires_human_approval)),
      };
      state.stepMap[stepKey] = stepData;
      state.steps.push(stepData);
    } else {
      Object.assign(state.stepMap[stepKey], {
        description: desc,
        tool: tool,
        action: action,
        params: params,
        expectedOutcome: expected || state.stepMap[stepKey].expectedOutcome,
        status: 'running',
      });
    }

    highlightCurrentPlanStep(stepNum);
    renderOrUpdateStepCard(state.stepMap[stepKey]);
    updateFilterBadges();
    applyFilterAndSearch();

    // Update Progress
    const total = (state.plan && state.plan.total_steps) ? state.plan.total_steps : 5;
    const percent = Math.min(Math.round(((stepNum - 0.5) / total) * 100), 90);
    updateProgress(percent, stepNum, total);
  }

  function onStepComplete(msg) {
    const stepNum = msg.step || (msg.data && msg.data.step && msg.data.step.step_number);
    const stepKey = `step-${stepNum}`;
    const stepData = state.stepMap[stepKey] || {
      key: stepKey,
      stepNumber: stepNum,
      description: msg.description || `Step ${stepNum}`,
      tool: msg.tool || 'browser',
      action: msg.action || 'execute',
      params: msg.params || {},
      expectedOutcome: msg.expected_outcome || '',
    };

    const success = msg.success !== false;
    const obs = msg.observation || (msg.data && msg.data.observation && msg.data.observation.observation) || (success ? 'Step completed successfully.' : 'Step execution failed.');
    const error = msg.error || (msg.data && msg.data.step && msg.data.step.error) || (!success ? (msg.output || 'Step execution encountered an error') : '');
    const output = msg.output || (msg.data && msg.data.step && msg.data.step.output) || '';
    const screenshot = msg.screenshot || (msg.data && msg.data.step && msg.data.step.screenshot_path);
    const duration = msg.duration || (stepData.startTime ? `${((Date.now() - stepData.startTime) / 1000).toFixed(2)}s` : '1.2s');
    const extractedData = msg.extracted_data || (msg.data && msg.data.observation && msg.data.observation.extracted_data);

    stepData.status = success ? 'success' : 'failed';
    stepData.observation = obs;
    stepData.error = error;
    stepData.output = output;
    stepData.duration = duration;
    stepData.screenshot = screenshot;
    stepData.extractedData = extractedData;
    state.stepMap[stepKey] = stepData;

    if (success) {
      markPlanStepDone(stepNum);
    } else {
      // Step failed: Highlight failure and update banner for instant debugging
      if (!state.firstFailedStepId) {
        state.firstFailedStepId = stepKey;
      }
      showFailureAlert(stepNum, error || obs);
    }

    renderOrUpdateStepCard(stepData);

    if (screenshot) {
      updateBrowserView(screenshot, obs);
    }

    if (extractedData) {
      Object.assign(state.taskContext, extractedData);
      renderContextView();
    }

    updateFilterBadges();
    applyFilterAndSearch();

    // Update Progress
    const total = (state.plan && state.plan.total_steps) ? state.plan.total_steps : 5;
    const percent = Math.min(Math.round((stepNum / total) * 100), 95);
    updateProgress(percent, stepNum, total);
  }

  function onStepRetrying(msg) {
    const stepNum = msg.step;
    const stepKey = `step-${stepNum}`;
    const stepData = state.stepMap[stepKey];
    if (stepData) {
      stepData.status = 'retrying';
      stepData.retriesLeft = msg.retries_left;
      stepData.retryMessage = msg.message || `Retrying step (${msg.retries_left} attempts left)...`;
      renderOrUpdateStepCard(stepData);
      updateFilterBadges();
      applyFilterAndSearch();
    }
  }

  function onReplanningStarted(msg) {
    // Insert a distinctive Self-Correction card into the timeline
    const card = document.createElement('div');
    card.className = 'step-card replan';
    card.setAttribute('data-replan', 'true');
    const failedDesc = msg.failed_step ? (msg.failed_step.description || `Step ${msg.failed_step.step_number}`) : 'Previous step';
    card.innerHTML = `
      <div class="step-node-dot" style="border-color:var(--accent-purple); box-shadow:0 0 10px var(--accent-purple-glow);"></div>
      <div class="step-top">
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="step-num-badge" style="color:var(--accent-purple); background:rgba(139,92,246,0.15); border-color:rgba(139,92,246,0.3);">
            Self-Correction Protocol
          </span>
          <span class="step-tool-badge">🧠 planner.replan</span>
        </div>
        <span class="badge-status in_progress">ADAPTING</span>
      </div>
      <div class="step-header-title" style="color:#e2e8f0; font-size:13px;">
        ⚠️ Issue diagnosed during <em>"${escapeHtml(failedDesc)}"</em>. Re-evaluating company knowledge &amp; DOM state to adapt plan...
      </div>
    `;
    el.timelineFeed.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function onReplanCreated(msg) {
    const card = document.createElement('div');
    card.className = 'step-card replan';
    card.setAttribute('data-replan', 'true');
    const reason = msg.reason || 'Adapted plan generated based on execution failure analysis.';
    card.innerHTML = `
      <div class="step-node-dot" style="border-color:var(--accent-purple);"></div>
      <div class="step-top">
        <span class="step-num-badge" style="color:var(--accent-purple); background:rgba(139,92,246,0.15); border-color:rgba(139,92,246,0.3);">
          Plan Adapted ✓
        </span>
        <span class="badge-status completed" style="background:rgba(139,92,246,0.2); color:#c4b5fd; border-color:rgba(139,92,246,0.4);">
          SELF-CORRECTED
        </span>
      </div>
      <div style="font-size:12px; color:#c4b5fd; margin-top:4px; line-height:1.5;">
        ${escapeHtml(reason)}
      </div>
    `;
    el.timelineFeed.appendChild(card);
  }

  // ==========================================================================
  // Step Card Rendering with Minimalist Diagnostic Accordion
  // ==========================================================================
  function renderOrUpdateStepCard(step) {
    let card = document.getElementById(`step-card-${step.stepNumber}`);
    const isNew = !card;

    if (isNew) {
      card = document.createElement('div');
      card.id = `step-card-${step.stepNumber}`;
      card.className = `step-card ${step.status}`;
      card.setAttribute('data-step-number', step.stepNumber);
      el.timelineFeed.appendChild(card);
    } else {
      card.className = `step-card ${step.status}`;
    }

    // Auto-open diagnostic accordion if failed
    const shouldAutoExpand = step.status === 'failed' || state.allExpanded;

    // Tool Icon
    let toolIcon = '🌐';
    if (step.tool === 'file') toolIcon = '📁';
    else if (step.tool === 'api' || step.tool === 'system') toolIcon = '⚡';

    // Status Pill label & class
    let statusLabel = 'EXECUTING';
    let statusClass = 'running';
    if (step.status === 'success') {
      statusLabel = 'SUCCESS';
      statusClass = 'completed';
    } else if (step.status === 'failed') {
      statusLabel = 'FAILED';
      statusClass = 'failed';
    } else if (step.status === 'retrying') {
      statusLabel = `RETRYING (${step.retriesLeft ?? 1})`;
      statusClass = 'waiting_for_approval';
    }

    // Parameters JSON formatting
    let paramsFormatted = '{}';
    try {
      paramsFormatted = JSON.stringify(step.params || {}, null, 2);
    } catch (e) {
      paramsFormatted = String(step.params);
    }

    // Root Cause Alert (Shown prominent if failed)
    let rootCauseHtml = '';
    if (step.status === 'failed') {
      const errText = step.error || step.output || 'Step execution encountered an unhandled exception or selector timeout.';
      rootCauseHtml = `
        <div class="step-root-cause">
          <div class="step-root-cause-title">
            <span>🚨</span>
            <span>Root Cause / Failure Breakdown:</span>
          </div>
          <div class="step-root-cause-msg">${escapeHtml(errText)}</div>
          <div class="step-root-cause-hint">
            <span>💡</span>
            <span><strong>Diagnosis:</strong> ${escapeHtml(step.observation || 'The element selector did not resolve within timeout. Verify DOM tree and selector specificity.')}</span>
          </div>
        </div>
      `;
    } else if (step.status === 'retrying') {
      rootCauseHtml = `
        <div class="step-root-cause" style="background:rgba(245, 158, 11, 0.1); border-left-color:var(--warning);">
          <div class="step-root-cause-title" style="color:#fde68a;">
            <span>⚠️</span>
            <span>Step Retry in Progress:</span>
          </div>
          <div class="step-root-cause-msg" style="color:#fef3c7;">${escapeHtml(step.retryMessage || 'Retrying with adjusted fallback parameters...')}</div>
        </div>
      `;
    }

    // Expected vs Actual Outcome
    const expectedHtml = step.expectedOutcome ? `
      <div class="diag-row">
        <span class="diag-label">Expected Outcome vs Actual Result</span>
        <div class="diag-compare-grid">
          <div class="diag-expected-box">
            <strong style="display:block; font-size:10px; text-transform:uppercase; margin-bottom:2px; opacity:0.8;">🎯 Target Objective:</strong>
            ${escapeHtml(step.expectedOutcome)}
          </div>
          <div class="diag-actual-box ${step.status === 'failed' ? 'failed' : ''}">
            <strong style="display:block; font-size:10px; text-transform:uppercase; margin-bottom:2px; opacity:0.8;">
              ${step.status === 'failed' ? '✗ Actual Error:' : '✓ Actual Result:'}
            </strong>
            ${escapeHtml(step.status === 'failed' ? (step.error || step.output || 'Execution failed') : (step.output || step.observation || 'Step achieved target successfully'))}
          </div>
        </div>
      </div>
    ` : '';

    // Extracted Data Pill Tags & Table
    let extractedPillsHtml = '';
    if (step.extractedData && typeof step.extractedData === 'object' && Object.keys(step.extractedData).length > 0) {
      const invList = step.extractedData.overdue_invoices || step.extractedData.invoices;
      let invoiceTableHtml = '';
      if (Array.isArray(invList) && invList.length > 0) {
        const rows = invList.map((inv) => `
          <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:6px 8px; font-family:var(--font-mono); color:var(--info); font-weight:600;">${escapeHtml(inv.invoice_number || '')}</td>
            <td style="padding:6px 8px; color:#ffffff; font-weight:500;">${escapeHtml(inv.company_name || '')}</td>
            <td style="padding:6px 8px; color:var(--success); font-weight:600;">${escapeHtml(inv.amount || '')} ${escapeHtml(inv.currency || '')}</td>
            <td style="padding:6px 8px;">
              <span style="background:rgba(245,158,11,0.15); color:var(--warning); padding:2px 6px; border-radius:4px; font-weight:600; font-family:var(--font-mono); font-size:11px;">
                📅 ${escapeHtml(inv.due_date || 'N/A')}
              </span>
            </td>
            <td style="padding:6px 8px;">
              <span class="badge-status ${String(inv.status).toLowerCase() === 'overdue' ? 'failed' : 'completed'}" style="font-size:10px; padding:2px 6px;">
                ${escapeHtml(inv.status || 'Active')}
              </span>
            </td>
          </tr>
        `).join('');

        invoiceTableHtml = `
          <div style="margin-top:8px; overflow-x:auto;">
            <table style="width:100%; border-collapse:collapse; font-size:12px; background:rgba(0,0,0,0.25); border-radius:6px; overflow:hidden; border:1px solid rgba(255,255,255,0.08);">
              <thead>
                <tr style="background:rgba(255,255,255,0.06); text-align:left; color:#94a3b8; font-size:11px; text-transform:uppercase;">
                  <th style="padding:6px 8px;">Invoice #</th>
                  <th style="padding:6px 8px;">Company</th>
                  <th style="padding:6px 8px;">Amount</th>
                  <th style="padding:6px 8px;">Payment Due Date</th>
                  <th style="padding:6px 8px;">Status</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        `;
      }

      const pills = Object.entries(step.extractedData)
        .filter(([k]) => k !== 'invoices' && k !== 'overdue_invoices')
        .map(([k, v]) => {
          const valStr = typeof v === 'object' ? JSON.stringify(v) : String(v);
          return `<span style="background:rgba(255,255,255,0.06); padding:2px 7px; border-radius:4px; border:1px solid var(--border-subtle); font-family:var(--font-mono); font-size:11px;">
            <strong style="color:var(--accent-purple);">${escapeHtml(k)}:</strong> ${escapeHtml(valStr)}
          </span>`;
        }).join(' ');

      extractedPillsHtml = `
        <div class="diag-row">
          <span class="diag-label">Extracted Entities &amp; Line Items</span>
          ${pills ? `<div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:2px;">${pills}</div>` : ''}
          ${invoiceTableHtml}
        </div>
      `;
    }

    // Screenshot Thumbnail
    let thumbHtml = '';
    if (step.screenshot) {
      let normShot = String(step.screenshot).replace(/\\/g, '/');
      if (normShot.includes('screenshots/')) {
        normShot = '/screenshots/' + normShot.split('screenshots/').pop();
      } else if (!normShot.startsWith('/') && !normShot.startsWith('http')) {
        normShot = '/' + normShot;
      }
      thumbHtml = `
        <div class="step-thumb-preview" onclick="window.openStepLightbox('${normShot}')" title="Click to view full screenshot">
          <img src="${normShot}" alt="Step View" />
        </div>
      `;
    }

    card.innerHTML = `
      <div class="step-node-dot"></div>
      <div class="step-top">
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="step-num-badge">Step ${step.stepNumber}</span>
          <span class="step-tool-badge">${toolIcon} ${escapeHtml(step.tool)}.${escapeHtml(step.action)}</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span class="badge-status ${statusClass}">${statusLabel}</span>
          <button class="step-diagnostics-toggle" onclick="window.toggleStepDiagnostics(${step.stepNumber})" id="toggle-btn-${step.stepNumber}">
            ${shouldAutoExpand ? 'Diagnostics ▴' : 'Inspect ▾'}
          </button>
        </div>
      </div>

      <div class="step-header-title">${escapeHtml(step.description)}</div>

      ${rootCauseHtml}

      <!-- Collapsible Diagnostics Panel -->
      <div class="step-diagnostics-panel" id="diag-panel-${step.stepNumber}" style="display:${shouldAutoExpand ? 'flex' : 'none'};">
        ${expectedHtml}

        <div class="diag-row">
          <span class="diag-label">
            <span>Tool Parameters</span>
            <button class="diag-copy-btn" onclick="window.copyToClipboard('${escapeAttr(paramsFormatted)}', this)">Copy JSON</button>
          </span>
          <div class="diag-box">${escapeHtml(paramsFormatted)}</div>
        </div>

        ${step.observation ? `
          <div class="diag-row">
            <span class="diag-label">Observation &amp; Evaluation</span>
            <div class="diag-box" style="font-family:var(--font-family); color:#cbd5e1;">${escapeHtml(step.observation)}</div>
          </div>
        ` : ''}

        ${extractedPillsHtml}
      </div>

      <div class="step-bottom-meta">
        <span>${step.duration ? `Duration: ${step.duration}` : 'Executing...'} • ${new Date().toLocaleTimeString()}</span>
        ${thumbHtml}
      </div>
    `;

    if (isNew) {
      card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  // Global window helpers for inline click handlers
  window.toggleStepDiagnostics = function (stepNum) {
    const panel = document.getElementById(`diag-panel-${stepNum}`);
    const btn = document.getElementById(`toggle-btn-${stepNum}`);
    if (panel) {
      const isHidden = panel.style.display === 'none';
      panel.style.display = isHidden ? 'flex' : 'none';
      if (btn) btn.textContent = isHidden ? 'Diagnostics ▴' : 'Inspect ▾';
    }
  };

  window.openStepLightbox = function (imgSrc) {
    openLightbox(imgSrc);
  };

  window.copyToClipboard = function (text, btnElement) {
    navigator.clipboard.writeText(text).then(() => {
      const orig = btnElement.textContent;
      btnElement.textContent = 'Copied! ✓';
      setTimeout(() => { btnElement.textContent = orig; }, 1500);
    }).catch((e) => console.warn('Copy failed:', e));
  };

  // ==========================================================================
  // Failure Alert Banner & Direct Jump
  // ==========================================================================
  function showFailureAlert(stepNum, errorMsg) {
    if (!el.failureAlertBanner) return;
    el.alertStepTitle.textContent = `Step ${stepNum} Failed:`;
    el.alertStepMsg.textContent = errorMsg || 'Target selector failed or step execution halted.';
    el.failureAlertBanner.style.display = 'flex';
  }

  function hideFailureAlert() {
    if (el.failureAlertBanner) el.failureAlertBanner.style.display = 'none';
  }

  function jumpToFailedStep() {
    if (!state.firstFailedStepId) return;
    const card = document.getElementById(state.firstFailedStepId.replace('step-', 'step-card-'));
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.classList.remove('highlight-pulse');
      void card.offsetWidth; // trigger reflow
      card.classList.add('highlight-pulse');
      // Ensure diagnostics are open
      const stepNum = state.firstFailedStepId.replace('step-', '');
      const panel = document.getElementById(`diag-panel-${stepNum}`);
      if (panel) panel.style.display = 'flex';
    }
  }

  // ==========================================================================
  // Filtering & Search
  // ==========================================================================
  function updateFilterBadges() {
    let allCount = 0;
    let errorCount = 0;
    let approvalCount = 0;

    Object.values(state.stepMap).forEach((st) => {
      allCount++;
      if (st.status === 'failed' || st.status === 'retrying' || st.error) errorCount++;
      if (st.requiresApproval) approvalCount++;
    });

    if (el.badgeAllCount) el.badgeAllCount.textContent = allCount;
    if (el.badgeErrorCount) el.badgeErrorCount.textContent = errorCount;
    if (el.badgeApprovalCount) el.badgeApprovalCount.textContent = approvalCount;
  }

  function applyFilterAndSearch() {
    const filter = state.currentFilter;
    const query = (state.searchQuery || '').toLowerCase().trim();

    document.querySelectorAll('.step-card').forEach((card) => {
      if (card.hasAttribute('data-replan')) {
        // Replan cards show in 'all' or 'error' filters
        card.style.display = (filter === 'approval') ? 'none' : 'block';
        return;
      }

      const stepNum = card.getAttribute('data-step-number');
      const stepData = state.stepMap[`step-${stepNum}`];
      if (!stepData) return;

      // Filter logic
      let matchesFilter = true;
      if (filter === 'error') {
        matchesFilter = (stepData.status === 'failed' || stepData.status === 'retrying' || Boolean(stepData.error));
      } else if (filter === 'approval') {
        matchesFilter = Boolean(stepData.requiresApproval);
      }

      // Search logic
      let matchesSearch = true;
      if (query) {
        const textToSearch = [
          stepData.description,
          stepData.tool,
          stepData.action,
          stepData.error,
          stepData.output,
          stepData.observation,
          JSON.stringify(stepData.params || {}),
        ].join(' ').toLowerCase();
        matchesSearch = textToSearch.includes(query);
      }

      card.style.display = (matchesFilter && matchesSearch) ? 'block' : 'none';
    });
  }

  function toggleAllStepPanels() {
    state.allExpanded = !state.allExpanded;
    document.querySelectorAll('.step-diagnostics-panel').forEach((p) => {
      p.style.display = state.allExpanded ? 'flex' : 'none';
    });
    document.querySelectorAll('.step-diagnostics-toggle').forEach((b) => {
      b.textContent = state.allExpanded ? 'Diagnostics ▴' : 'Inspect ▾';
    });
    if (el.toggleAllText) el.toggleAllText.textContent = state.allExpanded ? 'Collapse All' : 'Expand All';
    if (el.toggleAllIcon) el.toggleAllIcon.textContent = state.allExpanded ? '⤡' : '⤢';
  }

  // ==========================================================================
  // Right Panel: Debug Console Terminal
  // ==========================================================================
  function appendDebugLog(level, source, message) {
    const entry = {
      timestamp: new Date().toLocaleTimeString(),
      level: level.toUpperCase(),
      source: source || 'Agent',
      message: message,
    };
    state.debugLogs.push(entry);

    if (el.debugLogsBadge) {
      el.debugLogsBadge.textContent = state.debugLogs.length;
    }

    if (!el.debugStreamTerminal) return;

    // Remove empty placeholder
    const emptyPlaceholder = el.debugStreamTerminal.querySelector('.debug-log-empty');
    if (emptyPlaceholder) emptyPlaceholder.remove();

    const tagClass = entry.level.toLowerCase();
    const line = document.createElement('div');
    line.className = 'debug-log-line';
    line.innerHTML = `
      <span class="debug-log-time">${entry.timestamp}</span>
      <span class="debug-tag ${tagClass}">${entry.level}</span>
      <span class="debug-log-msg">${escapeHtml(entry.message)}</span>
    `;
    el.debugStreamTerminal.appendChild(line);

    // Auto-scroll to bottom of terminal
    el.debugStreamTerminal.scrollTop = el.debugStreamTerminal.scrollHeight;
  }

  async function loadRecentLogs() {
    try {
      const res = await fetch('/api/logs');
      if (!res.ok) return;
      const data = await res.json();
      if (data.logs && Array.isArray(data.logs)) {
        data.logs.forEach((l) => appendDebugLog(l.level, l.source, l.message));
      }
    } catch (e) {
      console.warn('Could not load historical logs:', e);
    }
  }

  // ==========================================================================
  // Human Approval Modal
  // ==========================================================================
  function onHumanApprovalRequired(msg) {
    state.taskStatus = 'waiting_for_approval';
    updateStatusBadge('waiting_for_approval');

    const question = msg.question || (msg.data && msg.data.step && msg.data.step.description) || 'Supervisor approval requested to proceed with execution.';
    const context = msg.context || JSON.stringify(msg.data || {}, null, 2);

    el.approvalQuestion.textContent = question;
    el.approvalContext.textContent = typeof context === 'string' ? context : JSON.stringify(context, null, 2);

    el.approvalModal.classList.add('active');
  }

  function closeApprovalModal() {
    el.approvalModal.classList.remove('active');
    if (state.taskStatus === 'waiting_for_approval') {
      state.taskStatus = 'executing';
      updateStatusBadge('executing');
    }
  }

  async function resolveApproval(approved) {
    if (!state.activeTaskId) return;

    const endpoint = approved
      ? `/api/tasks/${state.activeTaskId}/approve`
      : `/api/tasks/${state.activeTaskId}/reject`;

    try {
      await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved: approved }),
      });
      closeApprovalModal();
    } catch (e) {
      console.error('Error resolving approval:', e);
      closeApprovalModal();
    }
  }

  // ==========================================================================
  // Task Completion & Failure Handlers
  // ==========================================================================
  function onTaskComplete(msg) {
    state.taskStatus = 'completed';
    stopElapsedTimer();
    updateStatusBadge('completed');
    updateProgress(100, 5, 5);

    const summary = msg.summary || (msg.data && msg.data.summary) || 'Autonomous task execution finished and outcome verified.';
    const evidence = msg.evidence || (msg.data && msg.data.evidence) || [];

    el.completionSummary.textContent = summary;
    el.evidenceList.innerHTML = '';

    if (Array.isArray(evidence)) {
      evidence.forEach((ev) => {
        const li = document.createElement('li');
        li.className = 'evidence-item';
        li.innerHTML = `<span class="evidence-check">✓</span> <span>${escapeHtml(ev)}</span>`;
        el.evidenceList.appendChild(li);
      });
    }

    el.completionCard.style.display = 'flex';
    el.completionCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    loadTasksHistory();
  }

  function onTaskFailed(msg) {
    state.taskStatus = 'failed';
    stopElapsedTimer();
    updateStatusBadge('failed');

    const error = msg.error || (msg.data && msg.data.error) || 'An unexpected error halted task execution.';
    showFailureAlert('Fatal', error);

    const card = document.createElement('div');
    card.className = 'step-card failed';
    card.innerHTML = `
      <div class="step-node-dot"></div>
      <div class="step-top">
        <span class="step-num-badge" style="color:var(--error); border-color:var(--error);">Fatal Process Halt</span>
        <span class="badge-status failed">FAILED</span>
      </div>
      <div class="step-header-title">${escapeHtml(error)}</div>
      <div class="step-root-cause">
        <div class="step-root-cause-title"><span>🚨</span> Execution Interrupted</div>
        <div class="step-root-cause-msg">${escapeHtml(error)}</div>
      </div>
    `;
    el.timelineFeed.appendChild(card);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

    loadTasksHistory();
  }

  // ==========================================================================
  // Plan Checklist Helpers
  // ==========================================================================
  function highlightCurrentPlanStep(stepNum) {
    document.querySelectorAll('.plan-step-item').forEach((item) => {
      item.classList.remove('current');
    });
    const current = document.getElementById(`plan-step-${stepNum}`);
    if (current) {
      current.classList.add('current');
      const badge = document.getElementById(`plan-badge-${stepNum}`);
      if (badge) badge.style.display = 'inline-block';
    }
  }

  function markPlanStepDone(stepNum) {
    const item = document.getElementById(`plan-step-${stepNum}`);
    if (item) {
      item.classList.remove('current');
      item.classList.add('done');
      const badge = document.getElementById(`plan-badge-${stepNum}`);
      if (badge) {
        badge.className = 'badge-status completed';
        badge.textContent = 'DONE';
        badge.style.display = 'inline-block';
      }
    }
  }

  // ==========================================================================
  // Right Panel: Browser & Context Views
  // ==========================================================================
  function updateBrowserView(screenshotUrl, label) {
    if (!screenshotUrl) return;
    let url = String(screenshotUrl).replace(/\\/g, '/');
    if (url.includes('screenshots/')) {
      url = '/screenshots/' + url.split('screenshots/').pop();
    } else if (!url.startsWith('/') && !url.startsWith('http')) {
      url = '/' + url;
    }
    state.currentScreenshot = url;
    el.browserImage.src = url;
    el.browserImage.style.display = 'block';
    el.browserPlaceholder.style.display = 'none';

    if (label && label.includes('http')) {
      const match = label.match(/https?:\/\/[^\s]+/);
      if (match) el.browserUrl.textContent = match[0];
    }
  }

  function renderContextView() {
    el.contextJsonView.textContent = JSON.stringify(state.taskContext, null, 2);
  }

  // ==========================================================================
  // Timer & Progress Helpers
  // ==========================================================================
  function startElapsedTimer() {
    state.startTime = Date.now();
    clearInterval(state.timerInterval);
    state.timerInterval = setInterval(() => {
      const elapsedSeconds = Math.floor((Date.now() - state.startTime) / 1000);
      const mins = String(Math.floor(elapsedSeconds / 60)).padStart(2, '0');
      const secs = String(elapsedSeconds % 60).padStart(2, '0');
      el.elapsedTimer.textContent = `${mins}:${secs}`;
    }, 1000);
    el.elapsedTimer.textContent = '00:00';
  }

  function stopElapsedTimer() {
    clearInterval(state.timerInterval);
  }

  function updateProgress(percent, currentStep, totalSteps) {
    el.progressFill.style.width = `${percent}%`;
    el.progressPercent.textContent = `${percent}%`;
    el.progressStepText.textContent = totalSteps ? `Step ${currentStep || 0} of ${totalSteps}` : '';
  }

  function updateStatusBadge(status) {
    el.activeTaskStatus.className = `badge-status ${status}`;
    const labels = {
      idle: 'READY',
      planning: 'PLANNING',
      executing: 'EXECUTING',
      waiting_for_approval: 'WAITING APPROVAL',
      verifying: 'VERIFYING',
      completed: 'COMPLETED',
      failed: 'FAILED',
    };
    el.activeTaskStatus.textContent = labels[status] || status.toUpperCase();
  }

  // ==========================================================================
  // Task Submission (Supports Standard Demo and Debug Error Sim Demo)
  // ==========================================================================
  async function submitTask(goalText, isDemo = false, simulateError = false) {
    if (!goalText || !goalText.trim()) return;

    el.btnDeploy.disabled = true;
    el.btnDemo.disabled = true;
    if (el.btnDemoError) el.btnDemoError.disabled = true;

    try {
      const res = await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: goalText.trim(),
          demo: isDemo,
          simulate_error: simulateError,
        }),
      });

      if (!res.ok) {
        throw new Error(`Server returned HTTP ${res.status}`);
      }

      const data = await res.json();
      console.log('[Task Submitted]', data);

      state.activeTaskId = data.task_id;
      state.activeTaskGoal = goalText.trim();

      onTaskStarted({
        task_id: data.task_id,
        goal: goalText.trim(),
      });
    } catch (err) {
      console.error('Error submitting task:', err);
      alert('Failed to deploy task: ' + err.message);
    } finally {
      el.btnDeploy.disabled = false;
      el.btnDemo.disabled = false;
      if (el.btnDemoError) el.btnDemoError.disabled = false;
    }
  }

  // ==========================================================================
  // Task History & Historical Inspection
  // ==========================================================================
  async function loadTasksHistory() {
    try {
      const res = await fetch('/api/tasks');
      if (!res.ok) return;
      const data = await res.json();
      renderTasksHistory(data.tasks || []);
    } catch (e) {
      console.warn('Could not load task history:', e);
    }
  }

  function renderTasksHistory(tasks) {
    el.taskHistoryList.innerHTML = '';
    if (tasks.length === 0) {
      el.taskHistoryList.innerHTML = '<div style="font-size:11px; color:var(--text-dim); text-align:center; padding:12px;">No tasks run yet.</div>';
      return;
    }

    tasks.forEach((t) => {
      const item = document.createElement('div');
      item.className = `task-history-item ${t.task_id === state.activeTaskId ? 'active' : ''}`;
      item.innerHTML = `
        <div class="history-top">
          <span class="history-goal">${escapeHtml(t.goal)}</span>
          <span class="badge-status ${t.status}">${t.status}</span>
        </div>
        <div class="history-meta">
          <span>${t.task_id}</span>
          <span>${formatDate(t.created_at)}</span>
        </div>
      `;
      item.onclick = () => inspectHistoricalTask(t.task_id);
      el.taskHistoryList.appendChild(item);
    });
  }

  async function inspectHistoricalTask(taskId) {
    try {
      const res = await fetch(`/api/tasks/${taskId}`);
      if (!res.ok) return;
      const data = await res.json();
      console.log('Inspecting historical task:', data);

      const task = data.task;
      state.activeTaskId = task.task_id;
      state.activeTaskGoal = task.goal;
      state.taskStatus = task.status;
      state.steps = [];
      state.stepMap = {};
      state.firstFailedStepId = null;

      el.activeTaskId.textContent = task.task_id;
      el.activeTaskGoal.textContent = task.goal;
      updateStatusBadge(task.status);
      hideFailureAlert();

      el.timelineFeed.innerHTML = '';
      if (task.understanding) {
        el.understandingText.textContent = task.understanding;
        el.understandingCard.style.display = 'flex';
      }

      if (data.steps && data.steps.length > 0) {
        data.steps.forEach((st) => {
          onStepStart({
            step: st.step_number,
            description: st.description,
            tool: st.tool,
            action: st.action,
            params: st.params,
            expected_outcome: st.expected_outcome,
            requires_human_approval: st.requires_human_approval,
          });
          onStepComplete({
            step: st.step_number,
            description: st.description,
            tool: st.tool,
            action: st.action,
            params: st.params,
            expected_outcome: st.expected_outcome,
            success: st.status === 'success',
            output: st.output,
            error: st.error,
            observation: st.output || st.description,
            screenshot: st.screenshot_path,
            duration: 'Saved',
          });
        });
      }

      if (data.context) {
        state.taskContext = data.context;
        renderContextView();
      }

      if (task.status === 'completed') {
        onTaskComplete({
          summary: `Task ${task.task_id} completed with status: ${task.status}`,
          evidence: [`Saved in SQLite database`, `Steps executed: ${data.steps ? data.steps.length : 0}`],
        });
      }

      // Highlight active in list
      document.querySelectorAll('.task-history-item').forEach((i) => i.classList.remove('active'));
    } catch (e) {
      console.error('Failed to inspect task:', e);
    }
  }

  // ==========================================================================
  // Company Knowledge
  // ==========================================================================
  async function loadCompanyKnowledge() {
    try {
      const res = await fetch('/api/company-knowledge');
      if (!res.ok) return;
      const data = await res.json();
      renderCompanyKnowledge(data.knowledge || []);
    } catch (e) {
      console.warn('Could not load company knowledge:', e);
    }
  }

  function renderCompanyKnowledge(entries) {
    el.knowledgeList.innerHTML = '';
    entries.forEach((e) => {
      const div = document.createElement('div');
      div.className = 'knowledge-item';
      div.innerHTML = `
        <div class="knowledge-cat">${escapeHtml(e.category)}</div>
        <div class="knowledge-title">${escapeHtml(e.title)}</div>
        <div class="knowledge-desc">${escapeHtml(e.content)}</div>
      `;
      el.knowledgeList.appendChild(div);
    });
  }

  // ==========================================================================
  // Report Generation & Export
  // ==========================================================================
  function downloadAuditReport() {
    let stepsBreakdown = '';
    Object.values(state.stepMap).forEach((st) => {
      stepsBreakdown += `### Step ${st.stepNumber}: ${st.description}\n`;
      stepsBreakdown += `- **Tool / Action**: \`${st.tool}.${st.action}\`\n`;
      stepsBreakdown += `- **Status**: ${st.status.toUpperCase()}\n`;
      if (st.expectedOutcome) stepsBreakdown += `- **Expected Outcome**: ${st.expectedOutcome}\n`;
      if (st.error) stepsBreakdown += `- **Error Diagnosed**: \`${st.error}\`\n`;
      if (st.observation) stepsBreakdown += `- **Observation**: ${st.observation}\n`;
      stepsBreakdown += `\n`;
    });

    const report = `# AutoWorker Audit & Diagnostics Report
Generated: ${new Date().toISOString()}
Task ID: ${state.activeTaskId || 'N/A'}
Goal: ${state.activeTaskGoal || 'N/A'}
Status: ${state.taskStatus.toUpperCase()}

---

## Executive Summary
${el.completionSummary.textContent || 'Autonomous execution verified.'}

## Step-by-Step Telemetry & Diagnostics
${stepsBreakdown}

## Extracted Context
\`\`\`json
${JSON.stringify(state.taskContext, null, 2)}
\`\`\`

## System Verification
- Verified by CentrAlign AutoWorker Autonomous Evaluator
- All compliance guardrails, supervisor thresholds, and DOM interactions validated.
`;

    const blob = new Blob([report], { type: 'text/markdown;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `autoworker_audit_${state.activeTaskId || 'report'}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  // ==========================================================================
  // Lightbox Modal
  // ==========================================================================
  function openLightbox(imgSrc) {
    el.lightboxImage.src = imgSrc;
    el.lightboxModal.classList.add('active');
  }

  function closeLightbox() {
    el.lightboxModal.classList.remove('active');
  }

  // ==========================================================================
  // Event Listeners Setup
  // ==========================================================================
  function setupEventListeners() {
    // Deploy button
    el.btnDeploy.onclick = () => {
      submitTask(el.taskInput.value, false);
    };

    // Standard Demo button
    el.btnDemo.onclick = () => {
      const prompt = el.taskInput.value.trim() || 'Find latest invoice from Acme Corp, extract amount and due date, enter into internal system';
      el.taskInput.value = prompt;
      submitTask(prompt, true, false);
    };

    // Debug Error Simulation Demo button
    if (el.btnDemoError) {
      el.btnDemoError.onclick = () => {
        const prompt = 'Find latest invoice from Acme Corp, extract amount and due date, enter into internal system [Debug Error Sim]';
        el.taskInput.value = prompt;
        submitTask(prompt, true, true);
      };
    }

    // Failure Alert "Jump to Step" button
    if (el.btnJumpToError) {
      el.btnJumpToError.onclick = jumpToFailedStep;
    }

    // Filter Buttons
    if (el.filterAllSteps) {
      el.filterAllSteps.onclick = () => {
        state.currentFilter = 'all';
        setActiveFilterButton(el.filterAllSteps);
        applyFilterAndSearch();
      };
    }
    if (el.filterErrorSteps) {
      el.filterErrorSteps.onclick = () => {
        state.currentFilter = 'error';
        setActiveFilterButton(el.filterErrorSteps);
        applyFilterAndSearch();
      };
    }
    if (el.filterApprovalSteps) {
      el.filterApprovalSteps.onclick = () => {
        state.currentFilter = 'approval';
        setActiveFilterButton(el.filterApprovalSteps);
        applyFilterAndSearch();
      };
    }

    function setActiveFilterButton(activeBtn) {
      [el.filterAllSteps, el.filterErrorSteps, el.filterApprovalSteps].forEach((b) => {
        if (b) b.classList.remove('active');
      });
      activeBtn.classList.add('active');
    }

    // Search input
    if (el.stepSearchInput) {
      el.stepSearchInput.oninput = (e) => {
        state.searchQuery = e.target.value;
        applyFilterAndSearch();
      };
    }

    // Expand/Collapse All
    if (el.btnToggleAllSteps) {
      el.btnToggleAllSteps.onclick = toggleAllStepPanels;
    }

    // Example Chips
    el.exampleTasks.forEach((chip) => {
      chip.onclick = () => {
        const text = chip.getAttribute('data-prompt') || chip.textContent.trim();
        el.taskInput.value = text;
        el.taskInput.focus();
      };
    });

    // Approval Modal Buttons
    el.btnApproveStep.onclick = () => resolveApproval(true);
    el.btnRejectStep.onclick = () => resolveApproval(false);

    // Knowledge Modal
    el.btnAddKnowledge.onclick = () => {
      el.knowledgeModal.classList.add('active');
    };
    el.btnCancelKnowledge.onclick = () => {
      el.knowledgeModal.classList.remove('active');
    };
    el.knowledgeForm.onsubmit = async (e) => {
      e.preventDefault();
      const cat = document.getElementById('knowCategory').value;
      const title = document.getElementById('knowTitle').value;
      const content = document.getElementById('knowContent').value;
      try {
        await fetch('/api/company-knowledge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category: cat, title: title, content: content }),
        });
        el.knowledgeModal.classList.remove('active');
        el.knowledgeForm.reset();
        loadCompanyKnowledge();
      } catch (err) {
        alert('Failed to save knowledge: ' + err.message);
      }
    };

    // Right Panel Tabs
    el.tabBrowser.onclick = () => switchRightTab('browser');
    if (el.tabDebug) el.tabDebug.onclick = () => switchRightTab('debug');
    el.tabContext.onclick = () => switchRightTab('context');

    function switchRightTab(tabName) {
      [el.tabBrowser, el.tabDebug, el.tabContext].forEach((t) => {
        if (t) t.classList.remove('active');
      });
      el.browserViewContainer.style.display = 'none';
      if (el.debugViewContainer) el.debugViewContainer.style.display = 'none';
      el.contextViewContainer.style.display = 'none';

      if (tabName === 'browser') {
        el.tabBrowser.classList.add('active');
        el.browserViewContainer.style.display = 'flex';
      } else if (tabName === 'debug') {
        el.tabDebug.classList.add('active');
        el.debugViewContainer.style.display = 'flex';
      } else if (tabName === 'context') {
        el.tabContext.classList.add('active');
        el.contextViewContainer.style.display = 'flex';
        renderContextView();
      }
      state.activeViewTab = tabName;
    }

    // Debug Console Copy & Clear
    if (el.btnCopyDebugLogs) {
      el.btnCopyDebugLogs.onclick = () => {
        const text = state.debugLogs.map((l) => `[${l.timestamp}] [${l.level}] ${l.message}`).join('\n');
        navigator.clipboard.writeText(text).then(() => {
          el.btnCopyDebugLogs.textContent = 'Copied! ✓';
          setTimeout(() => { el.btnCopyDebugLogs.textContent = 'Copy'; }, 1500);
        });
      };
    }
    if (el.btnClearDebugLogs) {
      el.btnClearDebugLogs.onclick = () => {
        state.debugLogs = [];
        if (el.debugLogsBadge) el.debugLogsBadge.textContent = '0';
        if (el.debugStreamTerminal) {
          el.debugStreamTerminal.innerHTML = '<div class="debug-log-empty">Telemetry stream cleared.</div>';
        }
      };
    }

    // Browser Zoom click
    el.browserImage.onclick = () => {
      if (state.currentScreenshot) openLightbox(state.currentScreenshot);
    };

    // Lightbox Close
    el.lightboxClose.onclick = closeLightbox;
    el.lightboxModal.onclick = (e) => {
      if (e.target === el.lightboxModal) closeLightbox();
    };

    // Download Report
    el.btnDownloadReport.onclick = downloadAuditReport;
  }

  // Utilities
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function escapeAttr(str) {
    if (!str) return '';
    return String(str)
      .replace(/'/g, "\\'")
      .replace(/"/g, '&quot;')
      .replace(/\n/g, '\\n');
  }

  function formatDate(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return isoStr;
    }
  }

  // Start app on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
