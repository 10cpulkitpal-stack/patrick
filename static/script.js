const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const newChatBtn = document.getElementById('newChatBtn');
const chatListEl = document.getElementById('chatList');
const chatTitleEl = document.getElementById('chatTitle');
const modelSelector = document.getElementById('modelSelector');
const modelStatus = document.getElementById('modelStatus');
const micBtn = document.getElementById('micBtn');
const voiceOutputBtn = document.getElementById('voiceOutputBtn');
const voiceOffIcon = document.getElementById('voiceOffIcon');
const voiceOnIcon = document.getElementById('voiceOnIcon');
const sidebar = document.getElementById('sidebar');
const sidebarBrand = document.getElementById('sidebarBrand');
const sidebarToggle = document.getElementById('sidebarToggle');
const sidebarHistoryBtn = document.getElementById('sidebarHistoryBtn');
const sidebarOpen = document.getElementById('sidebarOpen');
const sidebarBackdrop = document.getElementById('sidebarBackdrop');
const themeToggleBtn = document.getElementById('themeToggleBtn');
const themeIconMoon = document.getElementById('themeIconMoon');
const themeIconSun = document.getElementById('themeIconSun');
const attachBtn = document.getElementById('attachBtn');
const fileInput = document.getElementById('fileInput');
const attachmentPreview = document.getElementById('attachmentPreview');
const attachmentThumb = document.getElementById('attachmentThumb');
const attachmentName = document.getElementById('attachmentName');
const attachmentRemove = document.getElementById('attachmentRemove');
const accountButton = document.getElementById('accountButton');
const profileDialog = document.getElementById('profileDialog');
const profileForm = document.getElementById('profileForm');
const profileError = document.getElementById('profileError');
const passwordFeedback = document.getElementById('passwordFeedback');
const passwordButton = document.getElementById('passwordButton');
const logoutButton = document.getElementById('logoutButton');
const logoutFeedback = document.getElementById('logoutFeedback');

let pendingAttachment = null; // { kind: 'image'|'text'|'unsupported', name, dataUrl?, textContent? }

let currentChatId = null;
let voiceOutputEnabled = false;
let selectedModelKey = '';

// ---------- rendering helpers ----------

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// Parses a bot reply for ```lang ... ``` fenced code blocks and inline `code`,
// returning safe HTML with syntax-highlighted code blocks.
function renderMarkdown(text) {
  if (!window.marked || !window.DOMPurify) {
    return `<p>${escapeHtml(text).replace(/\n/g, '<br>')}</p>`;
  }

  const html = window.marked.parse(text, { gfm: true, breaks: false });
  return window.DOMPurify.sanitize(html, { USE_PROFILES: { html: true } });
}

function addMessage(text, role, attachment = null) {
  // role: 'user' | 'bot' | 'error'
  const row = document.createElement('div');
  row.className = 'message-row ' + role;

  if (role !== 'error') {
    const avatar = document.createElement('div');
    avatar.className = 'avatar ' + (role === 'user' ? 'user' : 'bot');
    avatar.textContent = role === 'user' ? 'U' : 'P';
    row.appendChild(avatar);
  }

  const body = document.createElement('div');
  body.className = 'message-body';

  if (role === 'bot') {
    body.innerHTML = renderMarkdown(text);
    body.querySelectorAll('pre code').forEach(block => {
      if (window.hljs) window.hljs.highlightElement(block);
    });
  } else {
    body.textContent = text;
  }

  if (role === 'user' && attachment) attachBadgeToRow(row, attachment);

  row.appendChild(body);

  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return row;
}

function addTyping() {
  const row = document.createElement('div');
  row.className = 'message-row typing-row';
  row.id = 'typingIndicator';

  const avatar = document.createElement('div');
  avatar.className = 'avatar bot';
  avatar.textContent = 'P';
  row.appendChild(avatar);

  const body = document.createElement('div');
  body.className = 'message-body';
  body.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  row.appendChild(body);

  messagesEl.appendChild(row);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

function showEmptyState() {
  messagesEl.innerHTML = `
    <div class="empty-state">
      <h2>How can I help you today?</h2>
      <p>Type a message below or use the mic to speak.</p>
    </div>`;
}

// ---------- sidebar collapse ----------

const isMobile = () => window.matchMedia('(max-width: 768px)').matches;

function setSidebarOpen(open) {
  sidebar.classList.toggle('collapsed', !open);
  syncSidebarLayout();
}

function syncSidebarLayout() {
  const collapsed = sidebar.classList.contains('collapsed');
  sidebarOpen.classList.toggle('is-hidden', !collapsed || !isMobile());
  sidebarBackdrop.classList.toggle('visible', !collapsed && isMobile());
}

function toggleSidebar() {
  const isCollapsed = sidebar.classList.contains('collapsed');
  setSidebarOpen(isCollapsed);
}

sidebarToggle.addEventListener('click', toggleSidebar);
sidebarBrand.addEventListener('click', toggleSidebar);
sidebarHistoryBtn.addEventListener('click', () => setSidebarOpen(true));
sidebarOpen.addEventListener('click', toggleSidebar);
sidebarBackdrop.addEventListener('click', () => setSidebarOpen(false));

// On phones, start with the sidebar tucked away (tap the menu icon to open it).
// Laptop/desktop behavior is untouched — sidebar still starts open there.
if (isMobile()) {
  setSidebarOpen(false);
}

// Resize only updates viewport-specific controls; it preserves the user's
// collapsed/open choice across resize and device rotation.
window.addEventListener('resize', syncSidebarLayout);
syncSidebarLayout();

// ---------- theme (dark / light) ----------

function applyTheme(theme) {
  document.body.classList.toggle('light-theme', theme === 'light');
  themeIconMoon.classList.toggle('is-hidden', theme === 'light');
  themeIconSun.classList.toggle('is-hidden', theme !== 'light');
  localStorage.setItem('theme', theme);
}

themeToggleBtn.addEventListener('click', () => {
  const isLight = document.body.classList.contains('light-theme');
  applyTheme(isLight ? 'dark' : 'light');
});

applyTheme(localStorage.getItem('theme') || 'dark');

// ---------- voice input (speech-to-text) ----------

const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let isListening = false;

if (SpeechRecognitionAPI) {
  recognition = new SpeechRecognitionAPI();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = navigator.language || 'en-US';

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    inputEl.value = transcript;
    resizeComposer();
    inputEl.focus();
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    stopListening();

    let message = 'Voice input error: ' + event.error;
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      message = 'Microphone access was blocked. Check your browser\'s site permissions and allow microphone access.';
    } else if (event.error === 'no-speech') {
      message = 'No speech detected. Try again.';
    } else if (event.error === 'audio-capture') {
      message = 'No microphone was found. Check that one is connected and enabled.';
    }
    addMessage(message, 'error');
  };

  recognition.onend = () => {
    stopListening();
  };
} else {
  micBtn.disabled = true;
  micBtn.title = 'Voice input is not supported in this browser';
}

function startListening() {
  if (!recognition || isListening) return;
  isListening = true;
  micBtn.classList.add('listening');
  try {
    recognition.start();
  } catch (e) {
    console.error('Failed to start recognition:', e);
    stopListening();
  }
}

function stopListening() {
  isListening = false;
  micBtn.classList.remove('listening');
}

micBtn.addEventListener('click', () => {
  if (isListening) {
    recognition.stop();
    stopListening();
  } else {
    startListening();
  }
});

// ---------- voice output (text-to-speech) ----------

function speak(text) {
  if (!voiceOutputEnabled || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const spokenText = text
    .replace(/```[^\n]*\n?([\s\S]*?)```/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/^\s{0,3}#{1,6}\s*/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+[.)]\s+/gm, '')
    .replace(/\|/g, ' ')
    .replace(/[*_~]/g, '')
    .replace(/`/g, '')
    .replace(/https?:\/\/\S+/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
  const utterance = new SpeechSynthesisUtterance(spokenText);
  utterance.rate = 1;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

function updateVoiceOutputIcon() {
  voiceOffIcon.classList.toggle('is-hidden', voiceOutputEnabled);
  voiceOnIcon.classList.toggle('is-hidden', !voiceOutputEnabled);
  voiceOutputBtn.classList.toggle('active', voiceOutputEnabled);
  voiceOutputBtn.title = voiceOutputEnabled ? 'Voice replies: ON (click to mute)' : 'Voice replies: OFF (click to enable)';
  voiceOutputBtn.setAttribute('aria-pressed', String(voiceOutputEnabled));
}

voiceOutputBtn.addEventListener('click', () => {
  voiceOutputEnabled = !voiceOutputEnabled;
  updateVoiceOutputIcon();
  if (!voiceOutputEnabled && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
});

updateVoiceOutputIcon();

if (!window.speechSynthesis) {
  voiceOutputBtn.disabled = true;
  voiceOutputBtn.title = 'Voice replies are not supported in this browser';
}

// ---------- chat list ----------

function closeAllMenus(restoreButton = null) {
  document.querySelectorAll('.chat-menu').forEach(m => m.remove());
  document.querySelectorAll('.kebab-btn.menu-open').forEach(b => {
    b.classList.remove('menu-open');
    b.setAttribute('aria-expanded', 'false');
  });
  if (restoreButton) restoreButton.focus();
}

document.addEventListener('click', () => closeAllMenus());

async function loadChatList(selectId) {
  const res = await fetch('/api/chats');
  if (res.status === 401) {
    window.location.href = '/signin';
    return;
  }
  const chats = await res.json();

  chatListEl.innerHTML = '';

  if (chats.length === 0) {
    chatListEl.innerHTML = '<div class="empty-list">No chats yet</div>';
    return;
  }

  chats.forEach(chat => {
    const item = document.createElement('div');
    item.className = 'chat-list-item' + (chat.id === selectId ? ' active' : '');
    item.dataset.id = chat.id;
    item.setAttribute('role', 'group');
    item.setAttribute('aria-label', `Chat actions and title: ${chat.title}`);

    const titleSpan = document.createElement('span');
    titleSpan.className = 'title';
    titleSpan.textContent = chat.title;
    titleSpan.tabIndex = 0;
    titleSpan.setAttribute('role', 'button');
    titleSpan.setAttribute('aria-label', `Open chat: ${chat.title}`);
    titleSpan.addEventListener('click', () => openChat(chat.id));
    titleSpan.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openChat(chat.id);
      }
    });
    item.appendChild(titleSpan);

    const menuWrapper = document.createElement('div');
    menuWrapper.className = 'menu-wrapper';

    const kebabBtn = document.createElement('button');
    kebabBtn.className = 'kebab-btn';
    kebabBtn.textContent = '⋮';
    kebabBtn.title = 'Chat options';
    kebabBtn.setAttribute('aria-label', `Actions for ${chat.title}`);
    kebabBtn.setAttribute('aria-haspopup', 'menu');
    kebabBtn.setAttribute('aria-expanded', 'false');

    kebabBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const alreadyOpen = kebabBtn.classList.contains('menu-open');
      closeAllMenus();
      if (alreadyOpen) return;

      kebabBtn.classList.add('menu-open');
      kebabBtn.setAttribute('aria-expanded', 'true');
      const menu = document.createElement('div');
      menu.className = 'chat-menu';
      menu.setAttribute('role', 'menu');
      menu.setAttribute('aria-label', `Actions for ${chat.title}`);

      const renameBtn = document.createElement('button');
      renameBtn.setAttribute('role', 'menuitem');
      renameBtn.textContent = '✏️ Rename';
      renameBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        closeAllMenus();
        startRename(item, titleSpan, chat.id, chat.title);
      });

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'menu-delete';
      deleteBtn.setAttribute('role', 'menuitem');
      deleteBtn.textContent = '🗑️ Delete';
      deleteBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        closeAllMenus();
        deleteChat(chat.id);
      });

      menu.appendChild(renameBtn);
      menu.appendChild(deleteBtn);
      menuWrapper.appendChild(menu);
      menu.addEventListener('keydown', (event) => {
        const actions = [...menu.querySelectorAll('button')];
        const index = actions.indexOf(document.activeElement);
        if (event.key === 'Escape') {
          event.preventDefault();
          closeAllMenus(kebabBtn);
        } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          const direction = event.key === 'ArrowDown' ? 1 : -1;
          actions[(index + direction + actions.length) % actions.length].focus();
        } else if (event.key === 'Home' || event.key === 'End') {
          event.preventDefault();
          actions[event.key === 'Home' ? 0 : actions.length - 1].focus();
        }
      });
      renameBtn.focus();
    });

    menuWrapper.appendChild(kebabBtn);
    item.appendChild(menuWrapper);
    chatListEl.appendChild(item);
  });
}

function startRename(item, titleSpan, chatId, currentTitle) {
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'rename-input';
  input.value = currentTitle;

  titleSpan.replaceWith(input);
  input.focus();
  input.select();

  let finished = false;

  async function finishRename(save) {
    if (finished) return;
    finished = true;

    const newTitle = input.value.trim();
    if (save && newTitle && newTitle !== currentTitle) {
      try {
        const res = await fetch('/api/chats/' + chatId, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title: newTitle })
        });
        if (res.ok) {
          const data = await res.json();
          if (chatId === currentChatId) {
            chatTitleEl.textContent = data.title;
          }
          await loadChatList(currentChatId);
          return;
        }
      } catch (e) {
        console.error('Rename failed:', e);
      }
    }
    // no change, or failed — just restore the label
    input.replaceWith(titleSpan);
  }

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') finishRename(true);
    if (e.key === 'Escape') finishRename(false);
  });
  input.addEventListener('blur', () => finishRename(true));
  input.addEventListener('click', (e) => e.stopPropagation());
}

// ---------- chat actions ----------

async function createNewChat() {
  const res = await fetch('/api/chats', { method: 'POST' });
  const chat = await res.json();
  await loadChatList(chat.id);
  await openChat(chat.id);
}

async function openChat(chatId) {
  currentChatId = chatId;
  const res = await fetch('/api/chats/' + chatId);

  if (!res.ok) {
    return;
  }

  const chat = await res.json();
  chatTitleEl.textContent = chat.title;

  messagesEl.innerHTML = '';
  if (chat.messages.length === 0) {
    showEmptyState();
  } else {
    chat.messages.forEach(m => {
      addMessage(m.content, m.role === 'user' ? 'user' : 'bot', m.attachment || null);
    });
  }

  await loadChatList(chatId);
  inputEl.disabled = false;
  inputEl.focus();

  if (isMobile()) setSidebarOpen(false);
}

async function deleteChat(chatId) {
  const wasCurrent = chatId === currentChatId;
  const deleted = await fetch('/api/chats/' + chatId, { method: 'DELETE' });
  if (!deleted.ok) return;

  const res = await fetch('/api/chats');
  const chats = await res.json();

  if (!wasCurrent) {
    await loadChatList(currentChatId);
  } else if (chats.length > 0) {
    await openChat(chats[0].id);
  } else {
    await createNewChat();
  }
}

// ---------- file / image attachment ----------

const TEXT_FILE_PATTERN = /\.(txt|md|csv|json|js|py|html|css|log)$/i;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;      // 8 MB
const MAX_TEXT_CHARS = 6000;                  // truncate long text files

function showAttachmentPreview() {
  if (!pendingAttachment) {
    attachmentPreview.classList.add('is-hidden');
    return;
  }
  attachmentPreview.classList.remove('is-hidden');
  attachmentName.textContent = pendingAttachment.name;

  if (pendingAttachment.kind === 'image') {
    attachmentThumb.innerHTML = `<img src="${pendingAttachment.dataUrl}" alt="">`;
  } else if (pendingAttachment.kind === 'text') {
    attachmentThumb.textContent = '📄';
  } else {
    attachmentThumb.textContent = '📎';
  }
}

function clearAttachment() {
  pendingAttachment = null;
  fileInput.value = '';
  showAttachmentPreview();
}

attachBtn.addEventListener('click', () => fileInput.click());
attachmentRemove.addEventListener('click', clearAttachment);

fileInput.addEventListener('change', () => {
  const file = fileInput.files[0];
  if (!file) return;

  const isImage = file.type.startsWith('image/');
  const isText = TEXT_FILE_PATTERN.test(file.name) || file.type.startsWith('text/');

  if (isImage) {
    if (file.size > MAX_IMAGE_BYTES) {
      addMessage(`"${file.name}" is too large (max 8 MB for images).`, 'error');
      fileInput.value = '';
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      pendingAttachment = { kind: 'image', name: file.name, dataUrl: reader.result };
      showAttachmentPreview();
    };
    reader.readAsDataURL(file);
  } else if (isText) {
    const reader = new FileReader();
    reader.onload = () => {
      let content = reader.result;
      const truncated = content.length > MAX_TEXT_CHARS;
      if (content.length > MAX_TEXT_CHARS) {
        content = content.slice(0, MAX_TEXT_CHARS);
      }
      pendingAttachment = { kind: 'text', name: file.name, textContent: content, truncated };
      showAttachmentPreview();
      if (truncated) addMessage(`Only the first ${MAX_TEXT_CHARS.toLocaleString()} characters of "${file.name}" will be sent.`, 'error');
    };
    reader.readAsText(file);
  } else {
    pendingAttachment = { kind: 'unsupported', name: file.name };
    showAttachmentPreview();
  }
});

function attachBadgeToRow(row, attachment) {
  const body = row.querySelector('.message-body');
  const badge = document.createElement('div');
  badge.className = 'msg-attachment-chip';

  if (attachment.kind === 'image') {
    const image = document.createElement('img');
    image.src = attachment.dataUrl;
    image.alt = '';
    badge.appendChild(image);
  } else {
    const icon = attachment.kind === 'text' ? '📄' : '📎';
    const iconNode = document.createElement('span');
    iconNode.className = 'msg-attachment-icon';
    iconNode.textContent = icon;
    badge.appendChild(iconNode);
  }
  const label = document.createElement('span');
  label.textContent = attachment.truncated
    ? `${attachment.name} · first ${MAX_TEXT_CHARS.toLocaleString()} characters`
    : attachment.name;
  badge.appendChild(label);

  body.appendChild(badge);
}

// ---------- Google search shortcut ----------

const GOOGLE_SEARCH_PATTERN = /^(?:open google(?: and)? search(?: for)?|google search(?: for)?|search google for)\s+(.+)$/i;

function tryHandleGoogleSearchCommand(text) {
  const match = text.match(GOOGLE_SEARCH_PATTERN);
  if (!match) return false;

  const query = match[1].trim();
  if (!query) return false;

  const url = 'https://www.google.com/search?q=' + encodeURIComponent(query);
  // Open the tab inside the original click gesture so browsers do not block it.
  window.open(url, '_blank');

  addMessage(text, 'user');
  inputEl.value = '';
  const chatId = currentChatId;
  fetch('/api/chats/' + chatId + '/shortcut', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: text, query })
  }).then(async (res) => {
    const data = await res.json();
    if (!res.ok) {
      addMessage('Error: ' + (data.error || 'Unable to save this search.'), 'error');
      return;
    }
    addMessage(data.reply, 'bot');
    if (data.title && data.title !== chatTitleEl.textContent) {
      chatTitleEl.textContent = data.title;
      loadChatList(chatId);
    }
  }).catch((error) => addMessage('Network error: ' + error.message, 'error'));
  return true;
}

// ---------- sending messages ----------

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text && !pendingAttachment) return;
  if (!currentChatId) return;

  if (text && !pendingAttachment && tryHandleGoogleSearchCommand(text)) return;

  const emptyState = messagesEl.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  const attachment = pendingAttachment;
  const displayText = text || (attachment
    ? (attachment.kind === 'image' ? '📷 Sent an image' : '📎 Sent a file')
    : '');

  addMessage(displayText, 'user', attachment);

  const body = { message: text };
  if (attachment && attachment.kind === 'image') {
    body.image = attachment.dataUrl;
    body.image_name = attachment.name;
  } else if (attachment && attachment.kind === 'text') {
    body.file_text = attachment.textContent;
    body.file_name = attachment.name;
    body.file_truncated = attachment.truncated === true;
  } else if (attachment && attachment.kind === 'unsupported') {
    body.unsupported_name = attachment.name;
  }

  inputEl.value = '';
  resizeComposer();
  clearAttachment();
  sendBtn.disabled = true;
  addTyping();

  try {
    const res = await fetch('/api/chats/' + currentChatId + '/message', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    removeTyping();

    if (res.ok) {
      addMessage(data.reply, 'bot');
      speak(data.reply);
      if (data.title && data.title !== chatTitleEl.textContent) {
        chatTitleEl.textContent = data.title;
        loadChatList(currentChatId);
      }
    } else {
      addMessage('Error: ' + data.error, 'error');
    }
  } catch (err) {
    removeTyping();
    addMessage('Network error: ' + err.message, 'error');
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}

// ---------- events ----------

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    sendMessage();
  }
});
inputEl.addEventListener('input', resizeComposer);

function resizeComposer() {
  inputEl.dataset.lines = '1';
  const visibleLines = Math.max(1, Math.min(8, Math.ceil(inputEl.scrollHeight / 24)));
  inputEl.dataset.lines = String(visibleLines);
}
newChatBtn.addEventListener('click', createNewChat);

async function loadModelOptions() {
  modelStatus.textContent = '';
  try {
    const res = await fetch('/api/models');
    const data = await res.json();
    if (!res.ok || !Array.isArray(data.models) || data.models.length === 0) {
      throw new Error(data.error || 'No models are available. Check the server API keys.');
    }
    modelSelector.innerHTML = '';
    for (const provider of ['groq', 'gemini']) {
      const providerModels = data.models.filter(model => model.provider === provider);
      if (!providerModels.length) continue;
      const group = document.createElement('optgroup');
      group.label = provider === 'groq' ? 'Groq models' : 'Gemini models';
      for (const model of providerModels) {
        const option = document.createElement('option');
        option.value = `${model.provider}|${model.id}`;
        option.textContent = model.id;
        group.appendChild(option);
      }
      modelSelector.appendChild(group);
    }
    selectedModelKey = data.provider && data.model ? `${data.provider}|${data.model}` : modelSelector.options[0].value;
    modelSelector.value = selectedModelKey;
    if (!data.saved && data.provider && data.model) {
      const separator = selectedModelKey.indexOf('|');
      const saved = await fetch('/api/model-preference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: selectedModelKey.slice(0, separator), model: selectedModelKey.slice(separator + 1) })
      });
      if (!saved.ok) throw new Error('Could not save the default model preference.');
    }
    modelSelector.disabled = false;
  } catch (error) {
    modelSelector.innerHTML = '';
    const option = document.createElement('option');
    option.textContent = 'Models unavailable';
    modelSelector.appendChild(option);
    modelSelector.disabled = true;
    modelStatus.textContent = error.message;
  }
}

modelSelector.addEventListener('change', async () => {
  const nextKey = modelSelector.value;
  const separator = nextKey.indexOf('|');
  if (separator < 0) return;
  const provider = nextKey.slice(0, separator);
  const model = nextKey.slice(separator + 1);
  modelSelector.disabled = true;
  modelStatus.textContent = 'Saving model preference…';
  try {
    const res = await fetch('/api/model-preference', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Could not save the selected model.');
    selectedModelKey = `${data.provider}|${data.model}`;
    modelStatus.textContent = 'Model saved';
  } catch (error) {
    modelSelector.value = selectedModelKey;
    modelStatus.textContent = error.message;
  } finally {
    modelSelector.disabled = false;
  }
});

// ---------- account profile ----------

accountButton.addEventListener('click', () => {
  profileError.textContent = '';
  passwordFeedback.textContent = '';
  profileDialog.showModal();
});

profileDialog.addEventListener('click', (event) => {
  if (event.target === profileDialog) profileDialog.close();
});

profileForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  profileError.textContent = '';
  const button = profileForm.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const res = await fetch('/api/profile', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: document.getElementById('profileName').value })
    });
    const data = await res.json();
    if (!res.ok) {
      profileError.textContent = data.error || 'Unable to save your name.';
      return;
    }
    document.getElementById('accountName').textContent = data.name;
    document.getElementById('accountAvatar').textContent = data.name.trim().charAt(0).toUpperCase();
    profileError.textContent = 'Name saved.';
  } catch (error) {
    profileError.textContent = 'Network error. Please try again.';
  } finally {
    button.disabled = false;
  }
});

passwordButton.addEventListener('click', async () => {
  passwordFeedback.textContent = '';
  const currentPassword = document.getElementById('currentPassword');
  const newPassword = document.getElementById('newPassword');
  passwordButton.disabled = true;
  try {
    const res = await fetch('/api/profile/password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        current_password: currentPassword ? currentPassword.value : '',
        new_password: newPassword.value
      })
    });
    const data = await res.json();
    if (!res.ok) {
      passwordFeedback.textContent = data.error || 'Unable to update password.';
      return;
    }
    if (currentPassword) currentPassword.value = '';
    newPassword.value = '';
    passwordFeedback.textContent = 'Password updated.';
  } catch (error) {
    passwordFeedback.textContent = 'Network error. Please try again.';
  } finally {
    passwordButton.disabled = false;
  }
});

logoutButton.addEventListener('click', async () => {
  logoutFeedback.textContent = '';
  logoutButton.disabled = true;
  try {
    const res = await fetch('/api/auth/logout', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) {
      logoutFeedback.textContent = data.error || 'Unable to sign out.';
      logoutButton.disabled = false;
      return;
    }
    window.location.href = '/signin';
  } catch (error) {
    logoutFeedback.textContent = 'Network error. Please try again.';
    logoutButton.disabled = false;
  }
});

// ---------- init ----------

async function init() {
  await loadModelOptions();
  const res = await fetch('/api/chats');
  if (res.status === 401) {
    window.location.href = '/signin';
    return;
  }
  const chats = await res.json();

  // Start on a blank conversation whenever the app opens. Reuse the latest
  // empty draft on refresh so an untouched chat does not create duplicates.
  if (chats.length > 0) {
    const latestChatResponse = await fetch('/api/chats/' + chats[0].id);
    if (latestChatResponse.ok) {
      const latestChat = await latestChatResponse.json();
      if (latestChat.messages.length === 0) {
        await openChat(chats[0].id);
        return;
      }
    }
  }

  await createNewChat();
}

init();
