'use client'

import {
  ArrowDown,
  ArrowUp,
  AudioLines,
  Check,
  FileText,
  Menu,
  Mic,
  Moon,
  Paperclip,
  Plus,
  Search,
  Sparkles,
  Sun,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

type SelectedFile = {
  id: string
  file: File
}

type Account = { id: string; email: string; display_name?: string; auth_provider: string }
type ChatSummary = { id: string; title: string }
type ChatMessage = {
  role: 'user' | 'assistant'
  content: string
  attachment?: { kind: string; name: string; data_url?: string; truncated?: boolean }
}
type ModelOption = { provider: string; id: string; label: string }

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers,
  })
  if (response.status === 401 && !path.startsWith('/api/auth/')) {
    window.location.assign('/signin')
    throw new Error('Please sign in to continue.')
  }
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
  return payload as T
}

const suggestions = [
  {
    number: '01',
    title: 'Explain something',
    description: 'Make a complex idea feel simple.',
    prompt: 'Explain a complex idea in a simple, intuitive way.',
  },
  {
    number: '02',
    title: 'Analyze a file',
    description: 'Find the important parts, without the busywork.',
    prompt: "Help me analyze the file I've attached and surface the key points.",
  },
  {
    number: '03',
    title: 'Write something',
    description: 'Find the right words and structure.',
    prompt: 'Help me write something clear, thoughtful, and well structured.',
  },
  {
    number: '04',
    title: 'Help me code',
    description: 'Untangle a problem, one step at a time.',
    prompt: 'Help me work through a coding problem step by step.',
  },
]

export function PatrickWorkspace() {
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<SelectedFile[]>([])
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [isLight, setIsLight] = useState(false)
  const [notice, setNotice] = useState('')
  const [isListening, setIsListening] = useState(false)
  const [account, setAccount] = useState<Account | null>(null)
  const [chats, setChats] = useState<ChatSummary[]>([])
  const [activeChatId, setActiveChatId] = useState('')
  const [activeChatTitle, setActiveChatTitle] = useState('New conversation')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isSending, setIsSending] = useState(false)
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [modelSelection, setModelSelection] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [profileOpen, setProfileOpen] = useState(false)
  const [profileName, setProfileName] = useState('')
  const [profileError, setProfileError] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const initializedRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const noticeTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const showNotice = useCallback((message: string) => {
    setNotice(message)
    if (noticeTimeoutRef.current) clearTimeout(noticeTimeoutRef.current)
    noticeTimeoutRef.current = setTimeout(() => setNotice(''), 5000)
  }, [])

  const openChat = useCallback(async (id: string) => {
    try {
      const chat = await apiRequest<{ id: string; title: string; messages: ChatMessage[] }>(`/api/chats/${id}`)
      setActiveChatId(chat.id)
      setActiveChatTitle(chat.title)
      setMessages(chat.messages)
      setIsSidebarOpen(false)
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not open that conversation.')
    }
  }, [showNotice])

  const createChat = useCallback(async () => {
    try {
      const chat = await apiRequest<ChatSummary>('/api/chats', { method: 'POST', body: '{}' })
      setChats((current) => [chat, ...current])
      setActiveChatId(chat.id)
      setActiveChatTitle(chat.title)
      setMessages([])
      setDraft('')
      setFiles([])
      setIsSidebarOpen(false)
      setNotice('')
      textareaRef.current?.focus()
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not start a conversation.')
    }
  }, [showNotice])

  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    void (async () => {
      try {
        const profile = await apiRequest<{ authenticated: boolean; user: Account }>('/api/me')
        if (!profile.authenticated) {
          window.location.replace('/signin')
          return
        }
        setAccount(profile.user)
        setProfileName(profile.user.display_name || profile.user.email.split('@')[0])
        const [chatList, models] = await Promise.all([
          apiRequest<ChatSummary[]>('/api/chats'),
          apiRequest<{ models: ModelOption[]; provider: string | null; model: string | null }>('/api/models'),
        ])
        setChats(chatList)
        setModelOptions(models.models)
        setModelSelection(models.provider && models.model ? `${models.provider}:${models.model}` : '')
        if (chatList.length) {
          await openChat(chatList[0].id)
        } else {
          await createChat()
        }
      } catch (error) {
        showNotice(error instanceof Error ? error.message : 'Could not connect to Patrick.')
      }
    })()
  }, [createChat, openChat, showNotice])

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        void createChat()
      }
    }
    window.addEventListener('keydown', handleShortcut)
    return () => window.removeEventListener('keydown', handleShortcut)
  }, [createChat])

  const startNewChat = () => { void createChat() }

  const addFiles = (selected: FileList | null) => {
    if (!selected?.length) return
    const nextFiles = Array.from(selected).slice(0, 1).map((file) => ({
      id: `${file.name}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
      file,
    }))
    setFiles(nextFiles)
  }

  const removeFile = (id: string) => {
    setFiles((current) => current.filter((item) => item.id !== id))
  }

  const handleSend = async () => {
    if (!draft.trim() && files.length === 0) return
    if (!activeChatId || isSending) return
    const text = draft.trim()
    const selectedFile = files[0]?.file
    const optimistic: ChatMessage = { role: 'user', content: text }
    if (selectedFile) optimistic.attachment = { kind: selectedFile.type.startsWith('image/') ? 'image' : 'text', name: selectedFile.name }
    setMessages((current) => [...current, optimistic])
    setDraft('')
    setFiles([])
    setIsSending(true)
    try {
      const body: Record<string, unknown> = { message: text }
      if (selectedFile?.type.startsWith('image/')) {
        if (selectedFile.size > 8 * 1024 * 1024) throw new Error('Images must be 8 MB or smaller.')
        body.image = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => resolve(String(reader.result))
          reader.onerror = () => reject(new Error('Could not read the image.'))
          reader.readAsDataURL(selectedFile)
        })
        body.image_name = selectedFile.name
        setMessages((current) => current.map((message, index) => index === current.length - 1
          ? { ...message, attachment: { kind: 'image', name: selectedFile.name, data_url: String(body.image) } }
          : message))
      } else if (selectedFile) {
        if (selectedFile.size > 1024 * 1024) throw new Error('Text files must be 1 MB or smaller.')
        const fileText = await selectedFile.text()
        body.file_text = fileText.slice(0, 6000)
        body.file_name = selectedFile.name
        body.file_truncated = fileText.length > 6000
      }
      const result = await apiRequest<{ reply: string; title: string }>(`/api/chats/${activeChatId}/message`, {
        method: 'POST', body: JSON.stringify(body),
      })
      setMessages((current) => [...current, { role: 'assistant', content: result.reply }])
      setActiveChatTitle(result.title)
      setChats((current) => current.map((chat) => chat.id === activeChatId ? { ...chat, title: result.title } : chat))
    } catch (error) {
      try {
        const chat = await apiRequest<{ messages: ChatMessage[]; title: string }>(`/api/chats/${activeChatId}`)
        setMessages(chat.messages)
        setActiveChatTitle(chat.title)
      } catch { /* Keep the optimistic message if the conversation cannot be reloaded. */ }
      showNotice(error instanceof Error ? error.message : 'Patrick could not send that message.')
    } finally {
      setIsSending(false)
    }
  }

  const handleComposerKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      if (event.nativeEvent.isComposing || event.keyCode === 229) return
      event.preventDefault()
      handleSend()
    }
  }

  const startVoiceInput = () => {
    type SpeechResultEvent = { results: ArrayLike<ArrayLike<{ transcript: string }>> }
    type SpeechRecognitionLike = {
      lang: string
      interimResults: boolean
      onresult: ((event: SpeechResultEvent) => void) | null
      onend: (() => void) | null
      onerror: (() => void) | null
      start: () => void
    }
    type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

    const speechWindow = window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor
      webkitSpeechRecognition?: SpeechRecognitionConstructor
    }
    const SpeechRecognitionApi = speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition

    if (!SpeechRecognitionApi) {
      showNotice('Voice input is not supported by this browser.')
      return
    }

    const recognition = new SpeechRecognitionApi()
    recognition.lang = navigator.language || 'en-US'
    recognition.interimResults = false
    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0]?.transcript ?? '')
        .join(' ')
      setDraft((current) => `${current}${current ? ' ' : ''}${transcript}`)
      setIsListening(false)
      textareaRef.current?.focus()
    }
    recognition.onerror = () => {
      setIsListening(false)
      showNotice('Voice input could not start. Check your microphone permission and try again.')
    }
    recognition.onend = () => setIsListening(false)
    setIsListening(true)
    try {
      recognition.start()
    } catch {
      setIsListening(false)
      showNotice('Voice input could not start. Please try again.')
    }
  }

  const saveModel = async (value: string) => {
    setModelSelection(value)
    const [provider, ...modelParts] = value.split(':')
    const model = modelParts.join(':')
    try {
      await apiRequest('/api/model-preference', { method: 'POST', body: JSON.stringify({ provider, model }) })
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not save that model.')
    }
  }

  const renameConversation = async (chat: ChatSummary) => {
    const title = window.prompt('Rename conversation', chat.title)?.trim()
    if (!title || title === chat.title) return
    try {
      const result = await apiRequest<{ title: string }>(`/api/chats/${chat.id}`, {
        method: 'PATCH', body: JSON.stringify({ title }),
      })
      setChats((current) => current.map((item) => item.id === chat.id ? { ...item, title: result.title } : item))
      if (activeChatId === chat.id) setActiveChatTitle(result.title)
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not rename that conversation.')
    }
  }

  const deleteConversation = async (chat: ChatSummary) => {
    if (!window.confirm(`Delete “${chat.title}”? This cannot be undone.`)) return
    try {
      await apiRequest(`/api/chats/${chat.id}`, { method: 'DELETE' })
      const remaining = chats.filter((item) => item.id !== chat.id)
      setChats(remaining)
      if (activeChatId === chat.id) {
        if (remaining.length) await openChat(remaining[0].id)
        else await createChat()
      }
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not delete that conversation.')
    }
  }

  const saveProfile = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setProfileError('')
    try {
      const result = await apiRequest<{ name: string }>('/api/profile', {
        method: 'PATCH', body: JSON.stringify({ name: profileName }),
      })
      setAccount((current) => current ? { ...current, display_name: result.name } : current)
      showNotice('Profile saved.')
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : 'Could not save your profile.')
    }
  }

  const signOut = async () => {
    try {
      await apiRequest('/api/auth/logout', { method: 'POST', body: '{}' })
      window.location.assign('/signin')
    } catch (error) {
      showNotice(error instanceof Error ? error.message : 'Could not sign out.')
    }
  }

  const updatePassword = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setProfileError('')
    try {
      await apiRequest('/api/profile/password', {
        method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      })
      setCurrentPassword('')
      setNewPassword('')
      showNotice('Password updated.')
    } catch (error) {
      setProfileError(error instanceof Error ? error.message : 'Could not update the password.')
    }
  }

  const filteredChats = chats.filter((chat) => chat.title.toLowerCase().includes(searchQuery.toLowerCase()))

  return (
    <main className={`patrick-app${isLight ? ' theme-light' : ''}`}>
      <div className="ambient ambient-one" aria-hidden="true" />
      <div className="ambient ambient-two" aria-hidden="true" />

      {isSidebarOpen && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setIsSidebarOpen(false)}
        />
      )}

      <aside className={`sidebar${isSidebarOpen ? ' sidebar-open' : ''}`} aria-label="Main navigation">
        <div className="sidebar-topline">
          <a className="brand" href="#main" aria-label="Patrick home">
            <span className="brand-mark" aria-hidden="true"><span /></span>
            <span className="brand-name">patrick</span>
          </a>
          <button className="icon-button sidebar-close" aria-label="Close navigation" onClick={() => setIsSidebarOpen(false)}>
            <X aria-hidden="true" />
          </button>
        </div>

          <button className="new-chat-button" onClick={startNewChat} disabled={!account}>
          <Plus aria-hidden="true" />
          <span>New conversation</span>
          <span className="new-chat-shortcut" aria-hidden="true">⌘ K</span>
        </button>

        <div className="sidebar-section-label">
          <label className="sr-only" htmlFor="history-search">Search conversations</label>
          <input id="history-search" className="history-search" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="Search conversations" />
          <Search aria-hidden="true" />
        </div>

        <section className="conversation-list" aria-label="Conversation history">
          {filteredChats.length ? filteredChats.map((chat) => (
            <div className={`history-item${activeChatId === chat.id ? ' history-item-active' : ''}`} key={chat.id}>
              <button className="history-item-open" onClick={() => void openChat(chat.id)} aria-current={activeChatId === chat.id ? 'page' : undefined}>
                <span>{chat.title}</span>
              </button>
              <button className="history-item-action" aria-label={`Rename ${chat.title}`} title="Rename" onClick={() => void renameConversation(chat)}>✎</button>
              <button className="history-item-action history-item-delete" aria-label={`Delete ${chat.title}`} title="Delete" onClick={() => void deleteConversation(chat)}><X aria-hidden="true" /></button>
            </div>
          )) : (
            <>
              <div className="history-empty-mark" aria-hidden="true"><AudioLines /></div>
              <p className="history-empty-title">{searchQuery ? 'No matches found.' : 'A little room to think.'}</p>
              <p className="history-empty-copy">{searchQuery ? 'Try another search.' : 'Your conversations will find a home here.'}</p>
            </>
          )}
        </section>

        <div className="sidebar-bottom">
          <div className="workspace-status">
            <span className="status-dot" aria-hidden="true" />
            <span>{account ? 'Signed in' : 'Connecting…'}</span>
          </div>
          <button className="account-profile-button" onClick={() => setProfileOpen(true)} disabled={!account}>
            <span className="account-avatar">{(account?.display_name || account?.email || 'P').slice(0, 1).toUpperCase()}</span>
            <span className="account-profile-copy"><strong>{account?.display_name || account?.email?.split('@')[0] || 'Patrick'}</strong><small>{account?.email || 'Your private thinking space'}</small></span>
          </button>
        </div>
      </aside>

      <section className="workspace" id="main">
        <header className="topbar">
          <div className="topbar-leading">
            <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setIsSidebarOpen(true)}>
              <Menu aria-hidden="true" />
            </button>
            <div className="conversation-heading">
              <span className="conversation-kicker">WORKSPACE</span>
              <h1>{activeChatTitle}</h1>
            </div>
          </div>
          <div className="topbar-actions">
            <div className="preview-pill"><span className="status-dot" />{account ? 'Private workspace' : 'Connecting'}</div>
            <button
              className="icon-button theme-toggle"
              aria-label={isLight ? 'Switch to dark appearance' : 'Switch to light appearance'}
              onClick={() => setIsLight((current) => !current)}
            >
              {isLight ? <Moon aria-hidden="true" /> : <Sun aria-hidden="true" />}
            </button>
            <label className="sr-only" htmlFor="model-selection">AI model</label>
            <div className="model-button model-select-wrap">
              <span className="model-sparkle"><Sparkles aria-hidden="true" /></span>
              <select id="model-selection" value={modelSelection} onChange={(event) => void saveModel(event.target.value)} disabled={!modelOptions.length}>
                {modelOptions.length ? modelOptions.map((model) => <option key={`${model.provider}:${model.id}`} value={`${model.provider}:${model.id}`}>{model.label}</option>) : <option value="">No models available</option>}
              </select>
              <ArrowDown aria-hidden="true" />
            </div>
          </div>
        </header>

        <div className="conversation-stage">
          {messages.length === 0 ? <section className="welcome-content" aria-labelledby="welcome-title">
            <div className="welcome-eyebrow"><span className="eyebrow-line" />A MORE THOUGHTFUL WORKSPACE<span className="eyebrow-line" /></div>
            <div className="welcome-mark" aria-hidden="true">
              <div className="welcome-mark-halo" />
              <div className="welcome-mark-core"><span className="brand-mark large"><span /></span></div>
            </div>
            <h2 id="welcome-title">How can Patrick<br className="mobile-break" /> <span>help?</span></h2>
            <p className="welcome-description">Ask questions, explore ideas, analyze files, or turn conversations into action.</p>

            <div className="suggestions" aria-label="Conversation starters">
              {suggestions.map((item) => (
                <button
                  className="suggestion-card"
                  key={item.number}
                  onClick={() => {
                    setDraft(item.prompt)
                    textareaRef.current?.focus()
                  }}
                >
                  <span className="suggestion-index">{item.number}</span>
                  <span className="suggestion-copy">
                    <span className="suggestion-title">{item.title}</span>
                    <span className="suggestion-description">{item.description}</span>
                  </span>
                  <ArrowUp className="suggestion-arrow" aria-hidden="true" />
                </button>
              ))}
            </div>
          </section> : <section className="message-thread" aria-label="Conversation messages" aria-live="polite">
            {messages.map((message, index) => (
              <article className={`thread-message thread-message-${message.role}`} key={`${activeChatId}-${index}`}>
                <div className="thread-message-label">{message.role === 'user' ? 'You' : 'Patrick'}</div>
                {message.attachment && <div className="thread-attachment">
                  {message.attachment.kind === 'image' && message.attachment.data_url ? <img src={message.attachment.data_url} alt={message.attachment.name} /> : <span><FileText aria-hidden="true" />{message.attachment.name}{message.attachment.truncated ? ' · shortened' : ''}</span>}
                </div>}
                <div className="thread-message-content">{message.content}</div>
              </article>
            ))}
            {isSending && <div className="assistant-thinking" role="status">Patrick is thinking…</div>}
          </section>}
        </div>

        <div className="composer-dock">
          {files.length > 0 && (
            <div className="file-list" aria-label="Selected attachments">
              {files.map(({ id, file }) => (
                <div className="file-chip" key={id}>
                  <span className="file-chip-icon"><FileText aria-hidden="true" /></span>
                  <span className="file-chip-info">
                    <span className="file-chip-name">{file.name}</span>
                    <span className="file-chip-size">{file.size < 1024 * 1024 ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / (1024 * 1024)).toFixed(1)} MB`}</span>
                  </span>
                  <button className="file-remove" aria-label={`Remove ${file.name}`} onClick={() => removeFile(id)}><X aria-hidden="true" /></button>
                </div>
              ))}
            </div>
          )}
          <div className="composer-shell">
            <label className="sr-only" htmlFor="composer-input">Message Patrick</label>
            <textarea
              id="composer-input"
              ref={textareaRef}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder="Ask Patrick anything..."
              rows={1}
              aria-describedby="composer-hint"
            />
            <div className="composer-toolbar">
              <div className="composer-tools">
                <input
                  ref={fileInputRef}
                  className="sr-only"
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif,.txt,.md,.csv,.json,.js,.py,.html,.css,.log"
                  onChange={(event) => {
                    addFiles(event.currentTarget.files)
                    event.currentTarget.value = ''
                  }}
                  aria-label="Choose attachments"
                />
                <button className="composer-tool-button" aria-label="Attach files" onClick={() => fileInputRef.current?.click()}>
                  <Paperclip aria-hidden="true" /><span>Attach</span>
                </button>
                <span className="composer-tool-separator" aria-hidden="true" />
                <button className={`composer-tool-button mic-button${isListening ? ' is-listening' : ''}`} aria-label={isListening ? 'Listening for voice input' : 'Start voice input'} onClick={startVoiceInput}>
                  <Mic aria-hidden="true" /><span>{isListening ? 'Listening' : 'Voice'}</span>
                </button>
              </div>
              <div className="composer-send-area">
                <span className="composer-hint" id="composer-hint">Shift + Enter for a new line</span>
                <button className="send-button" aria-label="Send message" onClick={() => void handleSend()} disabled={isSending || (!draft.trim() && files.length === 0)}>
                  <ArrowUp aria-hidden="true" />
                </button>
              </div>
            </div>
          </div>
          <p className="composer-footnote">Patrick can make mistakes. Check important details.</p>
        </div>
      </section>

      {profileOpen && <div className="profile-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setProfileOpen(false) }}>
        <section className="profile-panel" role="dialog" aria-modal="true" aria-labelledby="profile-heading">
          <button className="profile-dismiss" aria-label="Close profile" onClick={() => setProfileOpen(false)}><X aria-hidden="true" /></button>
          <span className="profile-eyebrow">ACCOUNT</span>
          <h2 id="profile-heading">Your profile</h2>
          <p className="profile-email">{account?.email}</p>
          <form onSubmit={saveProfile} className="profile-edit-form">
            <label htmlFor="profile-name">Name</label>
            <input id="profile-name" value={profileName} maxLength={120} onChange={(event) => setProfileName(event.target.value)} required />
            <button className="profile-save-button" type="submit">Save name</button>
          </form>
          <form onSubmit={(event) => void updatePassword(event)} className="profile-edit-form profile-password-form">
            <label htmlFor="new-password">New password</label>
            {account?.auth_provider !== 'google' && <input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} placeholder="Current password" />}
            <input id="new-password" type="password" minLength={8} maxLength={128} autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="At least 8 characters" required />
            <button className="profile-save-button" type="submit">Update password</button>
          </form>
          {profileError && <p className="profile-error" role="alert">{profileError}</p>}
          <button className="profile-signout-button" onClick={() => void signOut()}>Sign out</button>
        </section>
      </div>}

      <div className={`notice${notice ? ' notice-visible' : ''}`} role="status" aria-live="polite">
        <span className="notice-indicator"><Check aria-hidden="true" /></span>
        <span>{notice}</span>
        {notice && <button className="notice-close" aria-label="Dismiss message" onClick={() => setNotice('')}><X aria-hidden="true" /></button>}
      </div>
    </main>
  )
}

export default PatrickWorkspace

export type { SelectedFile }
