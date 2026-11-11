
/*
=========================================================
MULASTREAM VENTUREOS
COMPLETE APPLICATION JAVASCRIPT
=========================================================

Two account types:
1. Entrepreneur / Founder
2. Investor / Observer

Investors have read-only access to business tools.
Authorised Investors can review submissions.

Existing FastAPI routes and SQLite data are preserved.
=========================================================
*/

'use strict';

// =======================================================
// APPLICATION STATE
// =======================================================

let csrf = '';
let account = null;
let ventures = [];
let chats = [];
let selected = null;
let chatId = null;
let view = 'readiness';
let canReview = false;
let signingUp = false;
let loginRole = 'founder';
let loginBusy = false;

const $ = id => document.getElementById(id);

const ROLE_NAMES = {
  founder: 'Entrepreneur',
  investor: 'Investor'
};

const DECISION_NAMES = {
  invest: 'Interested in investing',
  collaborate: 'Interested in collaborating',
  more_information: 'Request more information',
  decline: 'Not interested'
};

const BUSINESS_PAGES = [
  'overview',
  'venture',
  'evidence',
  'finance',
  'incubator',
  'readiness'
];

// =======================================================
// HELPER FUNCTIONS
// =======================================================

function esc(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    character => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[character]
  );
}

function err(error) {
  alert(error?.message || String(error));
}

function notice(message) {
  alert(message);
}

function money(value) {
  return Number(value || 0).toLocaleString(
    'en-NA',
    {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }
  );
}

function showError(message) {
  $('content').innerHTML = `
    <div class="card">
      <h3>Unable to load this section</h3>
      <p>${esc(message)}</p>
    </div>
  `;
}

function emptyCard(message) {
  return `
    <div class="card">
      <p>${esc(message)}</p>
    </div>
  `;
}

function fromForm(form) {
  return Object.fromEntries(new FormData(form));
}

function isFounder() {
  return account?.role === 'founder';
}

function isInvestor() {
  return account?.role === 'investor';
}

// =======================================================
// BACKEND API
// =======================================================

async function api(path, method = 'GET', body) {
  const options = {
    method,
    credentials: 'same-origin',
    headers: {
      'x-csrf-token': csrf
    }
  };

  if (body !== undefined) {
    options.headers['content-type'] =
      'application/json';

    options.body = JSON.stringify(body);
  }

  let response;

  try {
    response = await fetch('/api' + path, options);
  } catch (error) {
    throw new Error(
      'Cannot connect to the VentureOS server. ' +
      'Check that the server is running on port 8501.'
    );
  }

  const result = await response.json()
    .catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      typeof result.detail === 'string'
        ? result.detail
        : `Request failed (${response.status})`
    );
  }

  return result;
}

// =======================================================
// AUTHENTICATION
// =======================================================

function authMessage(message, success = false) {
  const element = $('authError');

  if (!element) return;

  element.textContent = message || '';
  element.style.color =
    success ? '#16a34a' : '#c34141';
}

function displayLogin() {
  $('regFields').hidden = !signingUp;
  $('name').required = signingUp;

  const options = $('loginOptions');

  if (options) {
    options.hidden = signingUp;
  }

  $('password').autocomplete =
    signingUp ? 'new-password' : 'current-password';

  $('authAction').disabled = loginBusy;

  $('authAction').textContent = loginBusy
    ? 'Please wait...'
    : signingUp
      ? 'Create account'
      : 'Sign in as ' + ROLE_NAMES[loginRole];

  $('switchAuth').textContent = signingUp
    ? 'Sign in instead'
    : 'Create an account';

  $('switchText').textContent = signingUp
    ? 'Already have an account?'
    : 'New to MulaStream?';

  const description = $('loginModeDescription');

  if (description) {
    description.textContent = signingUp
      ? 'Register as an Entrepreneur or Investor.'
      : `Sign in to your ${ROLE_NAMES[loginRole].toLowerCase()} account.`;
  }

  for (const role of Object.keys(ROLE_NAMES)) {
    const button = $(role + 'Login');

    if (button) {
      button.classList.toggle(
        'active',
        role === loginRole
      );
    }
  }
}

function chooseLoginRole(role) {
  if (!ROLE_NAMES[role]) return;

  loginRole = role;
  signingUp = false;

  authMessage('');
  displayLogin();
}

for (const role of Object.keys(ROLE_NAMES)) {
  const button = $(role + 'Login');

  if (button) {
    button.onclick = () => chooseLoginRole(role);
  }
}

$('switchAuth').onclick = () => {
  signingUp = !signingUp;
  authMessage('');
  displayLogin();
};

$('authForm').onsubmit = async event => {
  event.preventDefault();

  if (loginBusy) return;

  loginBusy = true;
  authMessage('');
  displayLogin();

  try {
    const email = $('email').value.trim().toLowerCase();
    const password = $('password').value;

    if (signingUp) {
      const name = $('name').value.trim();
      const role = $('role').value;

      if (!name) {
        throw new Error('Enter your full name.');
      }

      if (!['founder', 'investor'].includes(role)) {
        throw new Error('Choose a valid account type.');
      }

      await api('/register', 'POST', {
        name,
        email,
        password,
        role
      });

      signingUp = false;
      loginRole = role;
      $('password').value = '';

      authMessage(
        'Account created. Enter your password to sign in.',
        true
      );

    } else {
      const result = await api('/login', 'POST', {
        email,
        password,
        role: loginRole
      });

      csrf = result.csrf;

      const user = await api('/me');

      await boot(user);
    }

  } catch (error) {
    authMessage(error.message);
  } finally {
    loginBusy = false;
    displayLogin();
  }
};

// =======================================================
// ACCOUNT INITIALISATION
// =======================================================

function resetVisibleAccount() {
  ventures = [];
  chats = [];
  selected = null;
  chatId = null;
  view = 'readiness';
  canReview = false;

  $('chatList').replaceChildren();
  $('ventureSelect').replaceChildren();
  $('content').replaceChildren();

  $('modal').hidden = true;
  if ($('aiMentorWidget')) $('aiMentorWidget').hidden = true;
  if ($('aiChatBox')) $('aiChatBox').hidden = true;
  if ($('landingNavWorkspaceBtn')) $('landingNavWorkspaceBtn').hidden = true;
  closeAllDropdowns();

}

async function boot(existingUser = null) {
  let user = existingUser;

  if (!user) {
    try {
      user = await api('/me');
    } catch (error) {
      account = null;
      csrf = '';

      resetVisibleAccount();

      $('auth').hidden = false;
      $('shell').hidden = true;

      return;
    }
  }

  resetVisibleAccount();

  account = user;
  csrf = user.csrf;

  $('auth').hidden = true;
  $('shell').hidden = false;
  if ($('aiMentorWidget')) $('aiMentorWidget').hidden = false;
  if ($('userPopupName')) $('userPopupName').textContent = user.name || 'Account';
  if ($('avatarPopup')) $('avatarPopup').textContent = (user.name || 'U').charAt(0).toUpperCase();
  if ($('landingNavWorkspaceBtn')) $('landingNavWorkspaceBtn').hidden = false;

  $('userLabel').textContent =
    user.name || 'Account';

  $('roleLabel').textContent =
    ROLE_NAMES[user.role] || user.role;

  $('avatar').textContent =
    (user.name || 'U').charAt(0).toUpperCase();

  await loadAccountData();

  await updateRoleNavigation();

  api('/health')
    .then(data => {
      $('aiPill').textContent =
        `AI: ${data.ai} · ${data.model}`;
    })
    .catch(() => {
      $('aiPill').textContent =
        'AI connection unavailable';
    });
}

async function loadAccountData() {
  const venturePath = isInvestor()
    ? '/investor/business-list'
    : '/ventures';

  const results = await Promise.allSettled([
    api(venturePath),
    api('/chats')
  ]);

  if (results[0].status === 'fulfilled') {
    const value = results[0].value;

    ventures = isInvestor()
      ? value.ventures || []
      : value || [];
  } else {
    ventures = [];
  }

  chats = results[1].status === 'fulfilled'
    ? results[1].value
    : [];

  if (!ventures.some(item => item.id === selected)) {
    selected = ventures[0]?.id || null;
  }

  updateVentureSelect();
  renderChats();
}

async function refreshAll() {
  await loadAccountData();
  await render();
}

async function logout() {
  try {
    await api('/logout', 'POST');
  } catch (error) {
    err(error);
    return;
  }

  account = null;
  csrf = '';

  resetVisibleAccount();

  $('authForm').reset();

  signingUp = false;
  loginRole = 'founder';

  $('shell').hidden = true;
  $('auth').hidden = false;

  authMessage('');
  displayLogin();
}

// =======================================================
// VENTURE SELECTION
// =======================================================

function updateVentureSelect() {
  const select = $('ventureSelect');

  select.innerHTML = ventures.map(item => `
    <option value="${Number(item.id)}">
      ${esc(item.name)}
    </option>
  `).join('') ||
    '<option value="">No available venture</option>';

  select.value = selected || '';
}

$('ventureSelect').onchange = event => {
  selected = Number(event.target.value) || null;
  render();
};

// =======================================================
// SIDEBAR NAVIGATION
// =======================================================

document.querySelectorAll('.nav').forEach(button => {
  button.onclick = () =>
    navigate(button.dataset.view);
});

function navigate(page) {
  if (typeof closeAllDropdowns === 'function') closeAllDropdowns();
  if (!account) return;

  if (
    BUSINESS_PAGES.includes(page) &&
    !['founder', 'investor'].includes(account.role)
  ) {
    return;
  }

  if (page === 'admin') return;

  if (page === 'investors' && !isInvestor()) return;

  if (page === 'activation' && !isInvestor()) return;

  if (page === 'review' && !canReview) return;

  view = page;

  document.querySelectorAll('.nav').forEach(button => {
    button.classList.toggle(
      'active',
      button.dataset.view === page
    );
  });

  render().catch(err);
}

async function updateRoleNavigation() {
  canReview = false;

  if (isInvestor()) {
    try {
      const result = await api('/review/status');
      canReview = Boolean(result.allowed);
    } catch (error) {
      canReview = false;
    }
  }

  document.querySelectorAll('.nav').forEach(button => {
    const page = button.dataset.view;

    let visible = false;

    if (BUSINESS_PAGES.includes(page)) {
      visible = isFounder() || isInvestor();
    } else if (page === 'investors') {
      visible = isInvestor();
    } else if (page === 'activation') {
      visible = isInvestor();
    } else if (page === 'review') {
      visible = canReview;
    } else if (page === 'chat') {
      visible = true;
    }

    button.hidden = !visible;
    button.style.display = visible ? '' : 'none';
  });

  $('ventureSelect').hidden = false;

  const newVentureButton =
    document.querySelector('.top-right button');

  if (newVentureButton) {
    newVentureButton.hidden = !isFounder();
    newVentureButton.style.display =
      isFounder() ? '' : 'none';
  }

  navigate('readiness');
}

// =======================================================
// MAIN VIEW CONTROLLER
// =======================================================

async function render() {
  const titles = {
    overview: 'Venture mission control',
    venture: 'Venture Genome',
    evidence: 'Evidence ledger',
    finance: 'Financial laboratory',
    incubator: '90-day incubator',
    readiness: 'Readiness & rewards',
    investors: 'Investor opportunities',
    activation: 'Reviewer activation',
    review: 'Submission reviews',
    chat: 'AI mentor & chats'
  };

  $('pageTitle').textContent =
    titles[view] || 'MulaStream VentureOS';

  if (view === 'chat') {
    return renderChat();
  }

  if (view === 'investors') {
    return renderInvestors();
  }

  if (view === 'activation') {
    return renderReviewerActivation();
  }

  if (view === 'review') {
    return renderReviews();
  }

  if (isInvestor()) {
    return renderInvestorBusinessView();
  }

  if (view === 'incubator') {
    return renderIncubator();
  }

  if (view === 'readiness') {
    return renderReadiness();
  }

  if (!selected) {
    return renderStartPage();
  }

  try {
    const data = await api(
      `/ventures/${selected}/dashboard`
    );

    if (view === 'overview') return overview(data);
    if (view === 'venture') return genome(data);
    if (view === 'evidence') return evidence(data);
    if (view === 'finance') return finance(data);

  } catch (error) {
    showError(error.message);
  }
}

// =======================================================
// CREATE VENTURE
// =======================================================

function renderStartPage() {
  $('content').innerHTML = `
    <div class="hero">
      <span class="eyebrow">ENTREPRENEUR WORKSPACE</span>

      <h1>Start your venture journey</h1>

      <p>
        Create a business workspace and begin
        your three-month incubation programme.
      </p>

      <button class="primary" onclick="openModal()">
        + Create your first venture
      </button>
    </div>

    <div class="card">
      <h3>Eight-stage incubation programme</h3>

      <p>
        Complete each stage, submit evidence and
        receive independent Investor review.
      </p>
    </div>
  `;
}

function openModal() {
  if (!isFounder()) return;
  $('modal').hidden = false;
}

function closeModal() {
  $('modal').hidden = true;
}

$('ventureForm').onsubmit = async event => {
  event.preventDefault();

  try {
    const result = await api(
      '/ventures',
      'POST',
      fromForm(event.target)
    );

    selected = result.id;

    closeModal();
    event.target.reset();

    await refreshAll();
    navigate('overview');

  } catch (error) {
    err(error);
  }
};

// =======================================================
// ENTREPRENEUR MISSION CONTROL
// =======================================================

function overview(data) {
  const v = data.venture;
  const missions = data.missions || [];
  const evidenceRecords = data.evidence || [];
  const f = data.financials || {};

  const completed = missions.filter(
    item => item.state === 'done'
  ).length;

  $('content').innerHTML = `
    <div class="hero">
      <span class="eyebrow">ACTIVE VENTURE</span>

      <h1>${esc(v.name)}</h1>

      <p>
        ${esc(v.problem || 'Define your business problem.')}
      </p>

      <button class="primary" onclick="navigate('venture')">
        Edit Venture Genome
      </button>
    </div>

    <div class="grid">
      <div class="card">
        <span class="eyebrow">COMPLETED MISSIONS</span>
        <div class="metric">
          ${completed}/${missions.length}
        </div>
      </div>

      <div class="card">
        <span class="eyebrow">EVIDENCE RECORDS</span>
        <div class="metric">
          ${evidenceRecords.length}
        </div>
      </div>

      <div class="card">
        <span class="eyebrow">ESTIMATED MONTHLY PROFIT</span>
        <div class="metric">
          N$ ${money(f.estimated_profit)}
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Business missions</h3>

      ${missions.map(mission => `
        <label class="mission">
          <input
            type="checkbox"
            ${mission.state === 'done' ? 'checked' : ''}
            onchange="toggleMission(${Number(mission.id)})">

          <strong>${esc(mission.title)}</strong>
        </label>
      `).join('')}

      <div class="toolbar">
        <button class="primary"
                onclick="navigate('incubator')">
          Open incubator
        </button>

        <button class="ghost"
                onclick="navigate('evidence')">
          View evidence
        </button>
      </div>
    </div>
  `;
}

async function toggleMission(id) {
  try {
    await api(`/missions/${id}/toggle`, 'POST');
    await render();
  } catch (error) {
    err(error);
  }
}

// =======================================================
// VENTURE GENOME
// =======================================================

function genome(data) {
  const v = data.venture;

  $('content').innerHTML = `
    <div class="card">
      <h3>Your business model</h3>

      <form id="genomeForm">
        <label>
          Business name
          <input name="name" value="${esc(v.name)}" required>
        </label>

        <label>
          Location
          <input name="location" value="${esc(v.location)}">
        </label>

        <label>
          Industry
          <input name="industry" value="${esc(v.industry)}">
        </label>

        <label>
          Problem being solved
          <textarea name="problem" rows="3">${esc(v.problem)}</textarea>
        </label>

        <label>
          Target customers
          <textarea name="customers" rows="3">${esc(v.customers)}</textarea>
        </label>

        <label>
          Value proposition
          <textarea name="proposition" rows="3">${esc(v.proposition)}</textarea>
        </label>

        <button class="primary">
          Save business model
        </button>
      </form>
    </div>
  `;

  $('genomeForm').onsubmit = async event => {
    event.preventDefault();

    try {
      await api(
        `/ventures/${selected}`,
        'PATCH',
        fromForm(event.target)
      );

      await refreshAll();
      notice('Venture updated.');

    } catch (error) {
      err(error);
    }
  };
}

// =======================================================
// EVIDENCE LEDGER
// =======================================================

function evidence(data) {
  const records = data.evidence || [];

  $('content').innerHTML = `
    <div class="card">
      <h3>Add evidence</h3>

      <form id="evidenceForm">
        <label>
          Claim or observation
          <textarea
            name="claim"
            rows="4"
            maxlength="1000"
            required></textarea>
        </label>

        <label>
          Source description
          <input name="source" maxlength="500">
        </label>

        <button class="primary">
          Save evidence
        </button>
      </form>
    </div>

    <div class="card">
      <h3>Evidence records (${records.length})</h3>

      <label>
        Search
        <input id="evidenceSearch" placeholder="Search evidence">
      </label>

      <label>
        Filter status
        <select id="evidenceFilter">
          <option value="all">All</option>
          <option value="unreviewed">Unreviewed</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </label>

      <div id="evidenceRecords"></div>
    </div>
  `;

  $('evidenceForm').onsubmit = async event => {
    event.preventDefault();

    try {
      await api(
        `/ventures/${selected}/evidence`,
        'POST',
        fromForm(event.target)
      );

      await render();

    } catch (error) {
      err(error);
    }
  };

  function draw() {
    const term = $('evidenceSearch').value.toLowerCase();
    const status = $('evidenceFilter').value;

    const filtered = records.filter(item => {
      const matchesTerm =
        `${item.claim} ${item.source}`
          .toLowerCase()
          .includes(term);

      const matchesStatus =
        status === 'all' || item.status === status;

      return matchesTerm && matchesStatus;
    });

    $('evidenceRecords').innerHTML =
      filtered.map(item => `
        <div class="record">
          <strong>${esc(item.claim)}</strong>

          <span class="tag">${esc(item.status)}</span>

          <p>
            Source:
            ${esc(item.source || 'Not specified')}
          </p>

          ${item.status === 'unreviewed' ? `
            <button class="ghost"
              onclick="editLedgerEntry(${Number(item.id)})">
              Edit
            </button>

            <button class="ghost"
              onclick="deleteLedgerEntry(${Number(item.id)})">
              Delete
            </button>
          ` : ''}
        </div>
      `).join('') || '<p>No matching evidence.</p>';
  }

  $('evidenceSearch').oninput = draw;
  $('evidenceFilter').onchange = draw;

  draw();
}

async function editLedgerEntry(id) {
  try {
    const data = await api(
      `/ventures/${selected}/dashboard`
    );

    const item = data.evidence.find(
      record => record.id === id
    );

    if (!item) return;

    const claim = prompt('Edit claim', item.claim);

    if (claim === null) return;

    const source = prompt(
      'Edit source',
      item.source || ''
    );

    if (source === null) return;

    await api(
      `/ventures/${selected}/evidence/${id}`,
      'PATCH',
      { claim, source }
    );

    await render();

  } catch (error) {
    err(error);
  }
}

async function deleteLedgerEntry(id) {
  if (!confirm('Delete this evidence record?')) {
    return;
  }

  try {
    await api(
      `/ventures/${selected}/evidence/${id}`,
      'DELETE'
    );

    await render();

  } catch (error) {
    err(error);
  }
}

// =======================================================
// FINANCIAL LAB
// =======================================================

function finance(data) {
  const v = data.venture;
  const f = data.financials || {};

  $('content').innerHTML = `
    <div class="hero">
      <h1>Financial Laboratory</h1>

      <p>
        Estimate income, business costs and
        operating profit.
      </p>
    </div>

    <div class="grid">
      <div class="card">
        <span class="eyebrow">REVENUE</span>
        <div class="metric">N$ ${money(f.revenue)}</div>
      </div>

      <div class="card">
        <span class="eyebrow">COSTS</span>
        <div class="metric">
          N$ ${money(
            Number(f.variable_cost || 0) +
            Number(f.fixed_cost || 0)
          )}
        </div>
      </div>

      <div class="card">
        <span class="eyebrow">ESTIMATED PROFIT</span>
        <div class="metric">
          N$ ${money(f.estimated_profit)}
        </div>
      </div>
    </div>

    <div class="card">
      <h3>Financial assumptions</h3>

      <form id="financeForm">
        ${[
          ['price', 'Price per unit'],
          ['unit_cost', 'Direct cost per unit'],
          ['monthly_units', 'Monthly units sold'],
          ['fixed_cost', 'Monthly fixed costs']
        ].map(([key, label]) => `
          <label>
            ${label}

            <input
              name="${key}"
              type="number"
              min="0"
              step="${key === 'monthly_units' ? '1' : '0.01'}"
              value="${Number(v[key] || 0)}">
          </label>
        `).join('')}

        <button class="primary">
          Save and recalculate
        </button>
      </form>

      <p class="hint">
        Estimates are illustrative, not verified forecasts.
      </p>
    </div>
  `;

  $('financeForm').onsubmit = async event => {
    event.preventDefault();

    try {
      await api(
        `/ventures/${selected}`,
        'PATCH',
        fromForm(event.target)
      );

      await render();

    } catch (error) {
      err(error);
    }
  };
}

// =======================================================
// PRIVATE CHAT HISTORY
// =======================================================

function renderChats() {
  const searchInput = $('chatSearchInput');
  const term = searchInput ? searchInput.value : '';
  filterChatHistory(term);
}

function filterChatHistory(query) {
  const term = (query || '').toLowerCase().trim();
  const filtered = term
    ? chats.filter(c => (c.title || '').toLowerCase().includes(term))
    : chats;
  renderFilteredChats(filtered);
}

function clearChatSearch() {
  const searchInput = $('chatSearchInput');
  if (searchInput) {
    searchInput.value = '';
    searchInput.focus();
  }
  renderFilteredChats(chats);
}

function renderFilteredChats(list) {
  const container = $('chatList');
  if (!container) return;
  if (!list.length) {
    container.innerHTML = '<div class="mini" style="padding:15px; text-align:center; color:#94a3b8;">No matching conversations.</div>';
    return;
  }
  container.innerHTML = list.map(chat => `
    <div class="chat-item">
      <button
        class="chat-title-btn ${chat.id === chatId ? 'active-chat' : ''}"
        title="${esc(chat.title)}"
        onclick="openChat(${Number(chat.id)})">
        💬 &nbsp;${esc(chat.title)}
      </button>

      <button class="chat-tools"
        title="Rename conversation"
        onclick="renameChat(${Number(chat.id)})">
        ✎
      </button>

      <button class="chat-tools"
        title="Delete conversation"
        onclick="deleteChat(${Number(chat.id)})">
        ×
      </button>
    </div>
  `).join('');
}

async function newChat() {
  try {
    const result = await api('/chats', 'POST', {
      venture_id: isFounder()
        ? selected || null
        : null
    });

    chatId = result.id;
    chats = await api('/chats');
    renderChats();

    const searchPanel = $('aiChatSearchPanel');
    if (searchPanel) searchPanel.hidden = true;

    openAiChat();
    await loadCurrentChatMessages();

    const field = $('messageText');
    if (field) field.focus();
  } catch (error) {
    err(error);
  }
}

function openChat(id) {
  chatId = id;
  const searchPanel = $('aiChatSearchPanel');
  if (searchPanel) searchPanel.hidden = true;
  openAiChat();
  loadCurrentChatMessages();
}

async function renameChat(id) {
  const chat = chats.find(item => item.id === id);
  const title = prompt(
    'Rename conversation',
    chat?.title || ''
  );

  if (!title) return;

  try {
    await api(`/chats/${id}`, 'PATCH', { title });
    chats = await api('/chats');
    renderChats();
    if (chatId === id) await loadCurrentChatMessages();
  } catch (error) {
    err(error);
  }
}

async function deleteChat(id) {
  if (!confirm('Delete this conversation?')) {
    return;
  }

  try {
    await api(`/chats/${id}`, 'DELETE');
    if (chatId === id) chatId = null;
    chats = await api('/chats');
    renderChats();
    await loadCurrentChatMessages();
  } catch (error) {
    err(error);
  }
}

function openAiChat() {
  const box = $('aiChatBox');
  if (box) {
    box.hidden = false;
    loadCurrentChatMessages();
  }
}

function toggleAiChat(forceOpen) {
  const box = $('aiChatBox');
  if (!box) return;
  if (typeof forceOpen === 'boolean') {
    box.hidden = !forceOpen;
  } else {
    box.hidden = !box.hidden;
  }
  if (!box.hidden) {
    loadCurrentChatMessages();
  }
}

function toggleChatHistorySearch() {
  const searchPanel = $('aiChatSearchPanel');
  if (!searchPanel) return;
  searchPanel.hidden = !searchPanel.hidden;
  if (!searchPanel.hidden) {
    const searchInput = $('chatSearchInput');
    if (searchInput) {
      searchInput.value = '';
      searchInput.focus();
    }
    renderChats();
  }
}

async function loadCurrentChatMessages() {
  const container = $('messages');
  if (!container) return;

  if (!chatId && chats.length) {
    chatId = chats[0].id;
  }

  if (chatId) {
    try {
      const result = await api(`/chats/${chatId}`);
      container.innerHTML = (result.messages || []).map(message => `
        <div class="bubble ${message.role === 'user' ? 'user' : ''}">
          ${esc(message.body)}
        </div>
      `).join('') || '<div class="empty">Ask your first question to the AI mentor.</div>';
    } catch (error) {
      container.textContent = error.message;
    }
  } else {
    container.innerHTML = `
      <div class="empty">
        <div style="font-size:36px; margin-bottom:10px;">🤖</div>
        <h3>Start an AI conversation</h3>
        <p>Your AI mentor conversations are saved privately to your account.</p>
        <button class="primary" style="margin-top:10px;" onclick="newChat()">+ Start New Chat</button>
      </div>
    `;
  }
  container.scrollTop = container.scrollHeight;
}

async function renderChat() {
  openAiChat();
  await loadCurrentChatMessages();
}

function goToHomePage() {
  closeAllDropdowns();
  $('auth').hidden = false;
  $('shell').hidden = true;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function goToWorkspace() {
  if (!account) {
    const portal = document.getElementById('portal');
    if (portal) portal.scrollIntoView({ behavior: 'smooth' });
    return;
  }
  closeAllDropdowns();
  $('auth').hidden = true;
  $('shell').hidden = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function closeAllDropdowns() {
  const menu = $('taskbarMenuDropdown');
  if (menu) {
    menu.style.display = 'none';
    menu.hidden = true;
  }
  const userPopup = $('userDropdownPopup');
  if (userPopup) {
    userPopup.style.display = 'none';
    userPopup.hidden = true;
  }
}

function toggleTaskbarMenu(event) {
  if (event) {
    if (event.stopPropagation) event.stopPropagation();
    if (event.preventDefault) event.preventDefault();
  }
  const menu = $('taskbarMenuDropdown');
  const userPopup = $('userDropdownPopup');
  if (userPopup) {
    userPopup.style.display = 'none';
    userPopup.hidden = true;
  }
  if (menu) {
    const isShown = (menu.style.display === 'flex' || (!menu.hidden && menu.style.display !== 'none'));
    if (isShown) {
      menu.style.display = 'none';
      menu.hidden = true;
    } else {
      menu.hidden = false;
      menu.style.display = 'flex';
    }
  }
}

function toggleUserDropdown(event) {
  if (event) {
    if (event.stopPropagation) event.stopPropagation();
    if (event.preventDefault) event.preventDefault();
  }
  const userPopup = $('userDropdownPopup');
  const menu = $('taskbarMenuDropdown');
  if (menu) {
    menu.style.display = 'none';
    menu.hidden = true;
  }
  if (userPopup) {
    const isShown = (userPopup.style.display === 'flex' || (!userPopup.hidden && userPopup.style.display !== 'none'));
    if (isShown) {
      userPopup.style.display = 'none';
      userPopup.hidden = true;
    } else {
      userPopup.hidden = false;
      userPopup.style.display = 'flex';
    }
  }
}

function menuNavigate(page) {
  closeAllDropdowns();
  navigate(page);
}

function aiWidgetNewChat() {
  return newChat();
}

window.toggleTaskbarMenu = toggleTaskbarMenu;
window.toggleUserDropdown = toggleUserDropdown;
window.closeAllDropdowns = closeAllDropdowns;
window.menuNavigate = menuNavigate;
window.goToHomePage = goToHomePage;
window.goToWorkspace = goToWorkspace;
window.toggleAiChat = toggleAiChat;
window.openAiChat = openAiChat;
window.aiWidgetNewChat = aiWidgetNewChat;
window.toggleChatHistorySearch = toggleChatHistorySearch;
window.filterChatHistory = filterChatHistory;
window.clearChatSearch = clearChatSearch;

document.addEventListener('click', function(event) {
  const menuBtn = $('taskbarMenuBtn');
  const menu = $('taskbarMenuDropdown');
  if (menu && (menu.style.display === 'flex' || !menu.hidden)) {
    if (menuBtn && !menuBtn.contains(event.target) && !menu.contains(event.target)) {
      menu.style.display = 'none';
      menu.hidden = true;
    }
  }

  const userBtn = $('userProfileBtn');
  const userPopup = $('userDropdownPopup');
  if (userPopup && (userPopup.style.display === 'flex' || !userPopup.hidden)) {
    if (userBtn && !userBtn.contains(event.target) && !userPopup.contains(event.target)) {
      userPopup.style.display = 'none';
      userPopup.hidden = true;
    }
  }
});

// Setup compose submit and enter key handling
function setupChatForm() {
  const composeForm = $('compose');
  if (composeForm) {
    composeForm.onsubmit = async event => {
      event.preventDefault();
      const field = $('messageText');
      const message = field ? field.value.trim() : '';
      if (!message) return;

      const button = event.target.querySelector('button');
      if (button) button.disabled = true;
      if (field) field.value = '';

      try {
        if (!chatId) {
          const result = await api('/chats', 'POST', {
            venture_id: isFounder() ? selected || null : null
          });
          chatId = result.id;
        }

        const msgBox = $('messages');
        if (msgBox) {
          const userDiv = document.createElement('div');
          userDiv.className = 'bubble user';
          userDiv.textContent = message;
          msgBox.appendChild(userDiv);

          const thinkingDiv = document.createElement('div');
          thinkingDiv.className = 'bubble';
          thinkingDiv.id = 'aiThinkingBubble';
          thinkingDiv.innerHTML = '<small style="color:#64748b">AI Mentor is thinking…</small>';
          msgBox.appendChild(thinkingDiv);
          msgBox.scrollTop = msgBox.scrollHeight;
        }

        await api(`/chats/${chatId}/send`, 'POST', { message });

        chats = await api('/chats');
        renderChats();
        await loadCurrentChatMessages();

      } catch (error) {
        if (field) field.value = message;
        err(error);
        await loadCurrentChatMessages();
      } finally {
        if (button) button.disabled = false;
      }
    };
  }

  const msgText = $('messageText');
  if (msgText) {
    msgText.onkeydown = event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        const form = $('compose');
        if (form) {
          if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
          } else {
            form.dispatchEvent(new Event('submit', { cancelable: true }));
          }
        }
      }
    };
  }
}

setupChatForm();
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', setupChatForm);
}



// =======================================================
// EIGHT-STAGE INCUBATOR
// =======================================================

async function renderIncubator() {
  if (!selected) {
    renderStartPage();
    return;
  }

  try {
    const data = await api(
      `/ventures/${selected}/incubator`
    );

    $('content').innerHTML = `
      <div class="hero">
        <span class="eyebrow">
          THREE-MONTH INCUBATION PROGRAMME
        </span>

        <h1>90-Day Incubator</h1>

        <p>
          Complete the eight stages, submit your
          work and receive Investor review.
        </p>

        <div class="metric">
          ${Number(data.readiness_score || 0)}%
        </div>

        <small>
          ${Number(data.reviewed_stages || 0)}
          of 8 approved stages
        </small>
      </div>

      <div class="card">
        <h3>Startup Capital Planner</h3>

        <form id="budgetForm">
          <label>
            Starting capital (N$)

            <input
              name="amount"
              type="number"
              min="100"
              max="1000000"
              value="10000"
              required>
          </label>

          <label>
            Business type

            <select name="kind">
              <option value="retail">Retail</option>
              <option value="service">Service</option>
              <option value="food">Food</option>
            </select>
          </label>

          <button class="ghost">
            Calculate allocation
          </button>
        </form>

        <div id="budgetOutput"></div>
      </div>

      <div class="grid">
        ${(data.roadmap || []).map(month => `
          <div class="card">
            <span class="eyebrow">
              MONTH ${Number(month.month)}
            </span>

            <h3>${esc(month.name)}</h3>
            <p>${esc(month.goal)}</p>
          </div>
        `).join('')}
      </div>

      ${(data.stages || []).map(stage => `
        <div class="card" style="margin-top:18px">
          <div class="row-between">
            <div>
              <span class="eyebrow">
                MONTH ${Number(stage.month)}
                · STAGE ${Number(stage.number)}
              </span>

              <h3>${esc(stage.title)}</h3>
            </div>

            <span class="tag">
              ${esc(stage.status)}
            </span>
          </div>

          <p>${esc(stage.goal)}</p>

          <h4>Activities</h4>

          <p>
            ${(stage.activities || []).map(esc).join(' · ')}
          </p>

          <h4>Deliverables</h4>

          ${(stage.deliverables || []).map(deliverable => {
            const submission =
              (stage.submissions || []).find(
                item => item.deliverable === deliverable
              );

            const approved =
              submission?.reviewer_status === 'approved';

            const writable =
              stage.unlocked && !approved;

            return `
              <details class="record">
                <summary style="cursor:pointer">
                  <strong>${esc(deliverable)}</strong>

                  <span class="tag">
                    ${esc(
                      submission?.reviewer_status ||
                      'Not submitted'
                    )}
                  </span>
                </summary>

                <form
                  onsubmit="submitIncubator(event, ${Number(stage.number)})">

                  <input
                    type="hidden"
                    name="deliverable"
                    value="${esc(deliverable)}">

                  <label>
                    Your work

                    <textarea
                      name="narrative"
                      rows="6"
                      minlength="40"
                      maxlength="12000"
                      required
                      ${writable ? '' : 'readonly'}
                    >${esc(submission?.narrative || '')}</textarea>
                  </label>

                  <label>
                    Evidence reference

                    <input
                      name="evidence_ref"
                      maxlength="500"
                      value="${esc(
                        submission?.evidence_ref || ''
                      )}"
                      ${writable ? '' : 'readonly'}>
                  </label>

                  ${submission?.ai_feedback ? `
                    <p class="hint">
                      AI feedback:
                      ${esc(submission.ai_feedback)}
                    </p>
                  ` : ''}

                  ${!stage.unlocked ? `
                    <p class="hint">
                      Complete earlier stages first.
                    </p>
                  ` : ''}

                  ${writable ? `
                    <button class="primary">
                      Submit for review
                    </button>
                  ` : ''}
                </form>
              </details>
            `;
          }).join('')}
        </div>
      `).join('')}

      <div class="card">
        <h3>Investor Dossier</h3>

        <p>
          Export your venture information and
          incubation progress.
        </p>

        <button class="ghost"
                onclick="downloadDossier()">
          Export dossier
        </button>
      </div>
    `;

    $('budgetForm').onsubmit = showBudget;

  } catch (error) {
    showError(error.message);
  }
}

async function submitIncubator(event, stage) {
  event.preventDefault();

  try {
    const result = await api(
      `/ventures/${selected}/incubator/${stage}/submit`,
      'POST',
      fromForm(event.target)
    );

    notice(
      `Provisional score: ${result.score}/100\n\n` +
      `${result.feedback}\n\n` +
      'Authorised Investor reviewer approval is required.'
    );

    await renderIncubator();

  } catch (error) {
    err(error);
  }
}

async function showBudget(event) {
  event.preventDefault();

  const form = event.target;
  const amount = form.elements.amount.value;
  const kind = form.elements.kind.value;

  try {
    const data = await api(
      `/business-budget?amount=${encodeURIComponent(amount)}` +
      `&kind=${encodeURIComponent(kind)}`
    );

    $('budgetOutput').innerHTML = `
      <h3>
        Suggested allocation:
        N$ ${money(data.starting_capital_nad)}
      </h3>

      ${(data.allocations || []).map(item => `
        <div class="record">
          <strong>${esc(item.category)}</strong>

          ${Number(item.percentage)}%
          · N$ ${money(item.amount_nad)}
        </div>
      `).join('')}

      <p>Total: N$ ${money(data.total_nad)}</p>

      <p class="hint">${esc(data.caution)}</p>
    `;

  } catch (error) {
    err(error);
  }
}

async function downloadDossier() {
  try {
    const result = await api(
      `/ventures/${selected}/investor-package`
    );

    const blob = new Blob(
      [JSON.stringify(result, null, 2)],
      { type: 'application/json' }
    );

    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');

    link.href = url;
    link.download = 'venture_due_diligence_draft.json';

    link.click();
    URL.revokeObjectURL(url);

  } catch (error) {
    err(error);
  }
}

// =======================================================
// READINESS AND REWARDS
// =======================================================

async function renderReadiness() {
  if (!selected) {
    renderStartPage();
    return;
  }

  try {
    const [
      assessment,
      rewards,
      uploads,
      interest
    ] = await Promise.all([
      api(`/ventures/${selected}/assessment`),
      api(`/ventures/${selected}/rewards`),
      api(`/ventures/${selected}/uploads`),
      api(`/ventures/${selected}/investor-interest`)
    ]);

    $('content').innerHTML = `
      <div class="hero">
        <h1>Investment Readiness</h1>

        <div class="metric">
          ${Number(assessment.overall)}/100
        </div>

        <p>${esc(assessment.interpretation)}</p>

        <button class="primary"
                onclick="saveReadiness()">
          Save assessment
        </button>
      </div>

      <div class="grid two">
        <div class="card">
          <h3>Assessment Criteria</h3>

          ${(assessment.criteria || []).map(item => `
            <div class="record">
              <strong>${esc(item.criterion)}</strong>

              ${Number(item.score)}/100

              <small>
                ${esc(item.confidence)} confidence
              </small>
            </div>
          `).join('')}
        </div>

        <div class="card">
          <h3>Progress Rewards</h3>

          <div class="metric">
            ${Number(rewards.points || 0)} points
          </div>

          ${(rewards.badges || []).map(badge => `
            <div class="record">
              Stage ${Number(badge.stage)}:
              ${esc(badge.name)}
            </div>
          `).join('')}

          <h3>Investor Enquiries</h3>

          ${(interest || []).map(item => `
            <div class="record">
              ${esc(item.note)}
            </div>
          `).join('') || '<p>No enquiries yet.</p>'}
        </div>
      </div>

      <div class="card">
        <h3>Upload Supporting Evidence</h3>

        <form id="evidenceUpload">
          <label>
            Stage

            <select name="stage">
              ${Array.from(
                { length: 8 },
                (_, index) => `
                  <option value="${index + 1}">
                    Stage ${index + 1}
                  </option>
                `
              ).join('')}
            </select>
          </label>

          <label>
            Deliverable description
            <input name="deliverable" required>
          </label>

          <input
            type="file"
            name="file"
            required>

          <button class="primary">
            Upload evidence
          </button>
        </form>

        <h3>Saved Files</h3>

        ${(uploads || []).map(file => `
          <div class="record">
            ${esc(file.filename)}

            <small>
              Stage ${Number(file.stage)}
            </small>
          </div>
        `).join('') || '<p>No files uploaded.</p>'}
      </div>

      <div class="card" id="investorFeedback">
        <h3>Investor Feedback</h3>
        <p>Loading...</p>
      </div>
    `;

    $('evidenceUpload').onsubmit =
      uploadSupportingEvidence;

    await loadFounderFeedback();

  } catch (error) {
    showError(error.message);
  }
}

async function uploadSupportingEvidence(event) {
  event.preventDefault();

  try {
    const response = await fetch(
      `/api/ventures/${selected}/upload`,
      {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'x-csrf-token': csrf
        },
        body: new FormData(event.target)
      }
    );

    const data = await response.json();

    if (!response.ok) {
      throw new Error(
        data.detail || 'Upload failed.'
      );
    }

    notice(data.notice || 'Evidence uploaded.');
    await renderReadiness();

  } catch (error) {
    err(error);
  }
}

async function saveReadiness() {
  try {
    await api(
      `/ventures/${selected}/assessment`,
      'POST',
      {}
    );

    notice('Readiness assessment saved.');
    await renderReadiness();

  } catch (error) {
    err(error);
  }
}

async function loadFounderFeedback() {
  const container = $('investorFeedback');

  if (!container || !selected) return;

  try {
    const data = await api(
      `/ventures/${selected}/investor-feedback`
    );

    container.innerHTML = `
      <h3>Investor Feedback</h3>

      <h4>Investor Decisions</h4>

      ${(data.decisions || []).map(item => `
        <div class="record">
          <strong>${esc(item.investor_name)}</strong>

          <p>
            ${esc(
              DECISION_NAMES[item.decision] ||
              item.decision
            )}
          </p>

          <p>${esc(item.reason)}</p>
        </div>
      `).join('') || '<p>No decisions yet.</p>'}

      <h4>Investor Comments</h4>

      ${(data.comments || []).map(item => `
        <div class="record">
          <strong>${esc(item.investor_name)}</strong>
          <p>${esc(item.body)}</p>
        </div>
      `).join('') || '<p>No comments yet.</p>'}
    `;

  } catch (error) {
    container.innerHTML = `
      <h3>Investor Feedback</h3>
      <p>${esc(error.message)}</p>
    `;
  }
}

// =======================================================
// INVESTOR REVIEWER ACTIVATION
// =======================================================

async function renderReviewerActivation() {
  if (!isInvestor()) {
    showError('Investor account required.');
    return;
  }

  $('content').innerHTML = `
    <div class="card reviewer-access">
      <h2>Reviewer Activation</h2>

      <p>
        Enter the private reviewer token to read
        Entrepreneur submissions, provide feedback,
        approve work or request corrections.
      </p>

      <form id="reviewerTokenForm">
        <label>
          Authorised reviewer token

          <input
            type="password"
            name="token"
            required
            autocomplete="off">
        </label>

        <button class="primary">
          Activate review access
        </button>
      </form>

      <p id="reviewerTokenMessage" role="alert"></p>
    </div>
  `;

  $('reviewerTokenForm').onsubmit = async event => {
    event.preventDefault();

    const token = String(
      new FormData(event.target).get('token') || ''
    );

    try {
      await api(
        '/reviewer/activate',
        'POST',
        { token }
      );

      const status = await api('/review/status');

      canReview = Boolean(status.allowed);

      await loadAccountData();

      const reviewButton = document.querySelector(
        '[data-view="review"]'
      );

      if (reviewButton) {
        reviewButton.hidden = !canReview;
        reviewButton.style.display =
          canReview ? '' : 'none';
      }

      if (canReview) {
        navigate('review');
      } else {
        $('reviewerTokenMessage').textContent =
          'Reviewer activation could not be confirmed.';
      }

    } catch (error) {
      $('reviewerTokenMessage').textContent =
        error.message;
    }
  };
}

// =======================================================
// INVESTOR READ-ONLY BUSINESS TOOLS
// =======================================================

async function renderInvestorBusinessView() {
  if (!selected) {
    $('content').innerHTML = `
      <div class="card">
        <h3>No ventures currently available</h3>

        <p>
          Published ventures appear here.
          Reviewer activation allows authorised
          Investors to inspect unpublished submissions.
        </p>

        <button class="primary"
                onclick="navigate('activation')">
          Activate reviewer access
        </button>
      </div>
    `;

    return;
  }

  try {
    const result = await api(
      `/investor/business-view/${selected}`
    );

    const v = result.venture;
    const evidenceRecords = result.evidence || [];
    const submissions = result.submissions || [];
    const missions = result.missions || [];
    const f = result.financials || {};

    const header = `
      <div class="hero">
        <span class="eyebrow">
          INVESTOR READ-ONLY WORKSPACE
        </span>

        <h1>${esc(v.name)}</h1>

        <p>
          ${esc(v.industry)} · ${esc(v.location)}
        </p>

        <p>
          View venture information without changing
          the Entrepreneur's original work.
        </p>
      </div>
    `;

    let content = '';

    if (view === 'overview') {
      content = `
        <div class="grid">
          <div class="card">
            <h3>Completed missions</h3>

            <div class="metric">
              ${missions.filter(
                item => item.state === 'done'
              ).length}/${missions.length}
            </div>
          </div>

          <div class="card">
            <h3>Evidence records</h3>

            <div class="metric">
              ${evidenceRecords.length}
            </div>
          </div>

          <div class="card">
            <h3>Estimated monthly profit</h3>

            <div class="metric">
              N$ ${money(f.estimated_profit)}
            </div>
          </div>
        </div>

        <div class="card">
          <h3>Business overview</h3>

          <p><strong>Problem:</strong> ${esc(v.problem)}</p>
          <p><strong>Customers:</strong> ${esc(v.customers)}</p>
          <p><strong>Solution:</strong> ${esc(v.proposition)}</p>
        </div>
      `;

    } else if (view === 'venture') {
      content = `
        <div class="card">
          <h3>Venture Genome</h3>

          <p><strong>Business:</strong> ${esc(v.name)}</p>
          <p><strong>Industry:</strong> ${esc(v.industry)}</p>
          <p><strong>Location:</strong> ${esc(v.location)}</p>
          <p><strong>Problem:</strong> ${esc(v.problem)}</p>
          <p><strong>Customers:</strong> ${esc(v.customers)}</p>
          <p><strong>Value proposition:</strong> ${esc(v.proposition)}</p>
        </div>
      `;

    } else if (view === 'evidence') {
      content = `
        <div class="card">
          <h3>Evidence Ledger</h3>

          ${evidenceRecords.map(item => `
            <div class="record">
              <strong>${esc(item.claim)}</strong>
              <p>${esc(item.source)}</p>

              <span class="tag">
                ${esc(item.status)}
              </span>
            </div>
          `).join('') || '<p>No visible evidence records.</p>'}
        </div>
      `;

    } else if (view === 'finance') {
      content = `
        <div class="card">
          <h3>Financial Laboratory</h3>

          <p>
            <strong>Price per unit:</strong>
            N$ ${money(v.price)}
          </p>

          <p>
            <strong>Unit cost:</strong>
            N$ ${money(v.unit_cost)}
          </p>

          <p>
            <strong>Monthly units:</strong>
            ${Number(v.monthly_units || 0)}
          </p>

          <p>
            <strong>Fixed costs:</strong>
            N$ ${money(v.fixed_cost)}
          </p>

          <p>
            <strong>Revenue:</strong>
            N$ ${money(f.revenue)}
          </p>

          <p>
            <strong>Estimated profit:</strong>
            N$ ${money(f.estimated_profit)}
          </p>
        </div>
      `;

    } else if (view === 'incubator') {
      const stages = Array.from(
        { length: 8 },
        (_, index) => index + 1
      );

      content = `
        <div class="hero">
          <h2>90-Day Incubation Programme</h2>

          <p>
            View the Entrepreneur's submitted work.
            Use Submission Reviews to provide decisions.
          </p>
        </div>

        ${stages.map(stage => {
          const items = submissions.filter(
            item => Number(item.stage) === stage
          );

          return `
            <div class="card">
              <h3>Stage ${stage}</h3>

              ${items.map(item => `
                <div class="record">
                  <strong>${esc(item.deliverable)}</strong>

                  <p>${esc(item.narrative)}</p>

                  <p>
                    <strong>Evidence reference:</strong>
                    ${esc(item.evidence_ref)}
                  </p>

                  <span class="tag">
                    ${esc(item.reviewer_status)}
                  </span>
                </div>
              `).join('') ||
              '<p>No visible submissions for this stage.</p>'}
            </div>
          `;
        }).join('')}
      `;

    } else if (view === 'readiness') {
      content = `
        <div class="card">
          <h3>Readiness & Rewards</h3>

          <p>
            <strong>Submitted deliverables:</strong>
            ${submissions.length}
          </p>

          <p>
            <strong>Approved deliverables:</strong>
            ${Number(result.approved_count || 0)}
          </p>

          <p>
            Reviewer decisions are made through
            the Submission Reviews section.
          </p>
        </div>
      `;
    }

    $('content').innerHTML = header + content;

  } catch (error) {
    showError(error.message);
  }
}

// =======================================================
// INVESTOR OPPORTUNITIES
// =======================================================

async function renderInvestors() {
  if (!isInvestor()) {
    showError('Investor account required.');
    return;
  }

  try {
    const data = await api('/investor/opportunities');

    $('content').innerHTML = `
      <div class="hero">
        <span class="eyebrow">INVESTOR PORTAL</span>

        <h1>Investment Opportunities</h1>

        <p>${esc(data.notice || '')}</p>

        <p>
          Browse published businesses, leave comments
          and record investment interest.
        </p>
      </div>

      ${(data.opportunities || []).map(venture => `
        <div class="card" style="margin-top:16px">
          <h3>${esc(venture.name)}</h3>

          <p>
            ${esc(venture.industry)}
            · ${esc(venture.location)}
          </p>

          <p>
            <strong>Business problem:</strong>
            ${esc(venture.problem)}
          </p>

          <p>
            <strong>Proposed solution:</strong>
            ${esc(venture.proposition)}
          </p>

          <p>
            <strong>Readiness:</strong>
            ${Number(venture.readiness_score || 0)}/100
          </p>

          <button class="primary"
            onclick="openInvestorDiscussion(${Number(venture.id)})">
            Comment and Decide
          </button>
        </div>
      `).join('') || `
        <div class="card">
          <h3>No published opportunities yet</h3>

          <p>
            Ventures appear here after completing
            the required reviews and publication.
          </p>
        </div>
      `}

      <div class="card">
        <h3>Incubation Reviews</h3>

        <p>
          Authorised Investor reviewers can review
          Entrepreneur submissions before publication.
        </p>

        <button class="ghost"
          onclick="navigate('${canReview ? 'review' : 'activation'}')">
          ${canReview
            ? 'Open Submission Reviews'
            : 'Activate Reviewer Access'}
        </button>
      </div>
    `;

  } catch (error) {
    showError(error.message);
  }
}

// =======================================================
// INVESTOR COMMENTS AND INVESTMENT DECISIONS
// =======================================================

async function openInvestorDiscussion(ventureId) {
  try {
    const data = await api(
      `/investor/opportunities/${ventureId}/discussion`
    );

    const myDecision =
      data.my_decision?.decision ||
      'more_information';

    $('content').innerHTML = `
      <div class="hero">
        <h1>Investor Discussion</h1>

        <p>
          Comment on the business and record
          your own investment decision.
        </p>

        <button class="ghost"
          onclick="navigate('investors')">
          Back to Opportunities
        </button>
      </div>

      <div class="card">
        <h3>Your Investment Decision</h3>

        <form id="decisionForm">
          <label>
            Decision

            <select name="decision">
              ${Object.entries(DECISION_NAMES)
                .map(([key, label]) => `
                  <option
                    value="${key}"
                    ${myDecision === key ? 'selected' : ''}>
                    ${esc(label)}
                  </option>
                `).join('')}
            </select>
          </label>

          <label>
            Reason

            <textarea
              name="reason"
              rows="4"
              minlength="10"
              maxlength="2000"
              required>${esc(
                data.my_decision?.reason || ''
              )}</textarea>
          </label>

          <button class="primary">
            Save My Decision
          </button>
        </form>

        <p class="hint">
          An expression of interest does not constitute
          a binding investment agreement.
        </p>
      </div>

      <div class="card">
        <h3>Investor Comments</h3>

        ${(data.comments || []).map(item => `
          <div class="record">
            <strong>${esc(item.investor_name)}</strong>
            <p>${esc(item.body)}</p>
          </div>
        `).join('') || '<p>No comments yet.</p>'}

        <form id="investorCommentForm">
          <label>
            Add your comment

            <textarea
              name="body"
              rows="4"
              minlength="5"
              maxlength="2000"
              required></textarea>
          </label>

          <button class="primary">
            Post Comment
          </button>
        </form>
      </div>

      <div class="card">
        <h3>Investor Decisions</h3>

        ${(data.decisions || []).map(item => `
          <div class="record">
            <strong>${esc(item.investor_name)}</strong>

            <p>
              ${esc(
                DECISION_NAMES[item.decision] ||
                item.decision
              )}
            </p>

            <p>${esc(item.reason)}</p>
          </div>
        `).join('') || '<p>No decisions yet.</p>'}
      </div>
    `;

    $('decisionForm').onsubmit = async event => {
      event.preventDefault();

      try {
        await api(
          `/investor/opportunities/${ventureId}/decision`,
          'POST',
          fromForm(event.target)
        );

        await openInvestorDiscussion(ventureId);

      } catch (error) {
        err(error);
      }
    };

    $('investorCommentForm').onsubmit =
      async event => {
        event.preventDefault();

        try {
          await api(
            `/investor/opportunities/${ventureId}/comments`,
            'POST',
            fromForm(event.target)
          );

          await openInvestorDiscussion(ventureId);

        } catch (error) {
          err(error);
        }
      };

  } catch (error) {
    showError(error.message);
  }
}

// =======================================================
// AUTHORISED INVESTOR SUBMISSION REVIEWS
// =======================================================

async function renderReviews() {
  if (!canReview) {
    showError(
      'Reviewer permission is required. ' +
      'Activate access using your private token.'
    );

    return;
  }

  try {
    const submissions = await api('/review/queue');

    $('content').innerHTML = `
      <div class="hero">
        <span class="eyebrow">
          ENTREPRENEUR SUBMISSION REVIEW
        </span>

        <h1>Investor Review Queue</h1>

        <p>
          Read work submitted by Entrepreneurs,
          examine evidence, provide comments and
          approve or request corrections.
        </p>
      </div>

      ${(submissions || []).map(item => `
        <div class="card" style="margin-top:16px">
          <span class="eyebrow">
            STAGE ${Number(item.stage)}
          </span>

          <h3>${esc(item.venture)}</h3>

          <h4>${esc(item.deliverable)}</h4>

          <p>
            <strong>Entrepreneur's submitted work:</strong>
          </p>

          <div class="record">
            ${esc(item.narrative)}
          </div>

          <p>
            <strong>Evidence reference:</strong>
            ${esc(item.evidence_ref || 'Not provided')}
          </p>

          <p>
            <strong>Provisional AI score:</strong>
            ${Number(item.ai_score || 0)}/100
          </p>

          ${item.ai_feedback ? `
            <p>
              <strong>AI assessment:</strong>
              ${esc(item.ai_feedback)}
            </p>
          ` : ''}

          <p>
            <strong>Current status:</strong>
            ${esc(item.reviewer_status)}
          </p>

          <div class="toolbar">
            <button class="primary"
              onclick="makeReview(${Number(item.id)}, 'approved')">
              Approve
            </button>

            <button class="ghost"
              onclick="makeReview(${Number(item.id)}, 'needs_changes')">
              Request Corrections
            </button>

            <button class="ghost"
              onclick="makeReview(${Number(item.id)}, 'rejected')">
              Reject
            </button>
          </div>
        </div>
      `).join('') || `
        <div class="card">
          <h3>No pending submissions</h3>

          <p>
            New Entrepreneur submissions will appear
            here when they are available for review.
          </p>
        </div>
      `}
    `;

  } catch (error) {
    showError(error.message);
  }
}

async function makeReview(id, decision) {
  const actionNames = {
    approved: 'approve',
    needs_changes: 'request corrections for',
    rejected: 'reject'
  };

  const reason = prompt(
    `Enter your comments explaining why you want to ` +
    `${actionNames[decision]} this submission ` +
    `(minimum 12 characters):`
  );

  if (reason === null) return;

  if (reason.trim().length < 12) {
    notice(
      'Please write a clear comment or explanation ' +
      'of at least 12 characters.'
    );

    return;
  }

  try {
    const result = await api(
      `/review/${id}`,
      'POST',
      {
        decision,
        reason: reason.trim()
      }
    );

    notice(
      'Your review was saved successfully.\n\n' +
      `Decision: ${result.status}`
    );

    await renderReviews();

  } catch (error) {
    err(error);
  }
}

// =======================================================
// INITIALISE APPLICATION
// =======================================================

displayLogin();

// Restore existing session if the user is signed in.
boot();
