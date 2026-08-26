const messagesEl = document.getElementById('messages');
const inputEl = document.getElementById('userInput');
const sendBtn = document.getElementById('sendBtn');
const newChatBtn = document.getElementById('newChatBtn');
const chatListEl = document.getElementById('chatList');
const chatTitleEl = document.getElementById('chatTitle');
const micBtn = document.getElementById('micBtn');
const voiceOutputBtn = document.getElementById('voiceOutputBtn');
const voiceOffIcon = document.getElementById('voiceOffIcon');
const voiceOnIcon = document.getElementById('voiceOnIcon');
const sidebar = document.getElementById('sidebar');
const sidebarToggle = document.getElementById('sidebarToggle');
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

let pendingAttachment = null; // { kind: 'image'|'text'|'unsupported', name, dataUrl?, textContent? }

let currentChatId = null;
let voiceOutputEnabled = false;

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

function addMessage(text, role) {
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
  sidebarOpen.style.display = open ? 'none' : 'flex';
  sidebarBackdrop.classList.toggle('visible', open && isMobile());
}

function toggleSidebar() {
  const isCollapsed = sidebar.classList.contains('collapsed');
  setSidebarOpen(isCollapsed);
}

sidebarToggle.addEventListener('click', toggleSidebar);
sidebarOpen.addEventListener('click', toggleSidebar);
sidebarBackdrop.addEventListener('click', () => setSidebarOpen(false));

// On phones, start with the sidebar tucked away (tap the menu icon to open it).
// Laptop/desktop behavior is untouched — sidebar still starts open there.
if (isMobile()) {
  setSidebarOpen(false);
}

// If the window is resized/rotated across the mobile breakpoint, keep the
// sidebar in its normal (always-open) desktop state.
window.addEventListener('resize', () => {
  if (!isMobile()) {
    sidebar.classList.remove('collapsed');
    sidebarOpen.style.display = 'none';
    sidebarBackdrop.classList.remove('visible');
  }
});

// ---------- theme (dark / light) ----------

function applyTheme(theme) {
  document.body.classList.toggle('light-theme', theme === 'light');
  themeIconMoon.style.display = theme === 'light' ? 'block' : 'none';
  themeIconSun.style.display = theme === 'light' ? 'none' : 'block';
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
  recognition.lang = 'en-US';

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    inputEl.value = transcript;
    sendMessage();
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
    .replace(/```[\s\S]*?```/g, 'Code block omitted.')
    .replace(/`([^`]+)`/g, '$1');
  const utterance = new SpeechSynthesisUtterance(spokenText);
  utterance.rate = 1;
  utterance.pitch = 1;
  window.speechSynthesis.speak(utterance);
}

function updateVoiceOutputIcon() {
  voiceOffIcon.style.display = voiceOutputEnabled ? 'none' : 'block';
  voiceOnIcon.style.display = voiceOutputEnabled ? 'block' : 'none';
  voiceOutputBtn.classList.toggle('active', voiceOutputEnabled);
  voiceOutputBtn.title = voiceOutputEnabled ? 'Voice replies: ON (click to mute)' : 'Voice replies: OFF (click to enable)';
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

function closeAllMenus() {
  document.querySelectorAll('.chat-menu').forEach(m => m.remove());
  document.querySelectorAll('.kebab-btn.menu-open').forEach(b => b.classList.remove('menu-open'));
}

document.addEventListener('click', closeAllMenus);

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

    const titleSpan = document.createElement('span');
    titleSpan.className = 'title';
    titleSpan.textContent = chat.title;
    item.appendChild(titleSpan);

    const menuWrapper = document.createElement('div');
    menuWrapper.className = 'menu-wrapper';

    const kebabBtn = document.createElement('button');
    kebabBtn.className = 'kebab-btn';
    kebabBtn.textContent = '⋮';
    kebabBtn.title = 'Chat options';

    kebabBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const alreadyOpen = kebabBtn.classList.contains('menu-open');
      closeAllMenus();
      if (alreadyOpen) return;

      kebabBtn.classList.add('menu-open');
      const menu = document.createElement('div');
      menu.className = 'chat-menu';

      const renameBtn = document.createElement('button');
      renameBtn.textContent = '✏️ Rename';
      renameBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        closeAllMenus();
        startRename(item, titleSpan, chat.id, chat.title);
      });

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'menu-delete';
      deleteBtn.textContent = '🗑️ Delete';
      deleteBtn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        closeAllMenus();
        deleteChat(chat.id);
      });

      menu.appendChild(renameBtn);
      menu.appendChild(deleteBtn);
      menuWrapper.appendChild(menu);
    });

    menuWrapper.appendChild(kebabBtn);
    item.appendChild(menuWrapper);
    item.addEventListener('click', () => openChat(chat.id));

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
      addMessage(m.content, m.role === 'user' ? 'user' : 'bot');
    });
  }

  await loadChatList(chatId);
  inputEl.disabled = false;
  inputEl.focus();

  if (isMobile()) setSidebarOpen(false);
}

async function deleteChat(chatId) {
  await fetch('/api/chats/' + chatId, { method: 'DELETE' });

  if (chatId === currentChatId) {
    currentChatId = null;
    messagesEl.innerHTML = '';
    chatTitleEl.textContent = 'New conversation';
    inputEl.disabled = true;
  }

  const res = await fetch('/api/chats');
  const chats = await res.json();

  if (chats.length > 0) {
    await openChat(chats[0].id);
  } else {
    showEmptyState();
    await loadChatList(null);
  }
}

// ---------- file / image attachment ----------

const TEXT_FILE_PATTERN = /\.(txt|md|csv|json|js|py|html|css|log)$/i;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;      // 8 MB
const MAX_TEXT_CHARS = 6000;                  // truncate long text files

function showAttachmentPreview() {
  if (!pendingAttachment) {
    attachmentPreview.style.display = 'none';
    return;
  }
  attachmentPreview.style.display = 'block';
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
      if (content.length > MAX_TEXT_CHARS) {
        content = content.slice(0, MAX_TEXT_CHARS) + '\n... (truncated)';
      }
      pendingAttachment = { kind: 'text', name: file.name, textContent: content };
      showAttachmentPreview();
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
    badge.innerHTML = `<img src="${attachment.dataUrl}" alt=""><span>${escapeHtml(attachment.name)}</span>`;
  } else {
    const icon = attachment.kind === 'text' ? '📄' : '📎';
    badge.innerHTML = `<span class="msg-attachment-icon">${icon}</span><span>${escapeHtml(attachment.name)}</span>`;
  }

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
  window.open(url, '_blank');

  addMessage(text, 'user');
  addMessage(`Opening a Google search for "${query}" in a new tab.`, 'bot');
  inputEl.value = '';
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

  const userRow = addMessage(displayText, 'user');
  if (attachment) attachBadgeToRow(userRow, attachment);

  const body = { message: text };
  if (attachment && attachment.kind === 'image') {
    body.image = attachment.dataUrl;
    body.image_name = attachment.name;
  } else if (attachment && attachment.kind === 'text') {
    body.message = (text ? text + '\n\n' : '') +
      `[Attached file: ${attachment.name}]\n\`\`\`\n${attachment.textContent}\n\`\`\``;
  } else if (attachment && attachment.kind === 'unsupported') {
    body.message = (text ? text + '\n\n' : '') +
      `[User attached a file named "${attachment.name}" but its contents can't be read by the assistant. Supported: images and plain text files.]`;
  }

  inputEl.value = '';
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
  if (e.key === 'Enter') sendMessage();
});
newChatBtn.addEventListener('click', createNewChat);

// ---------- init ----------

async function init() {
  const res = await fetch('/api/chats');
  if (res.status === 401) {
    window.location.href = '/signin';
    return;
  }
  const chats = await res.json();

  if (chats.length > 0) {
    await openChat(chats[0].id);
  } else {
    inputEl.disabled = true;
    showEmptyState();
    await loadChatList(null);
  }
}

init();
