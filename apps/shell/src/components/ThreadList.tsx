import { useEffect, useRef, useState } from 'react'
import type { Folder, ThreadVisibility } from '../types'
import { useT } from '../i18n'

// Sidebar-Thread: BFF-Meta + lokale Timestamp-Sortierung.
// (Re-exportiert als kanonischer Ort; Sidebar re-exportiert den Typ weiterhin für Bestandscode.)
export type Thread = {
  id: string
  title: string
  ts: number
  folder_id?: string | null
  visibility?: ThreadVisibility
  members?: string[]
  owner?: string
}

function VisibilityBadge({ visibility }: { visibility?: ThreadVisibility }) {
  const t = useT()
  const team = visibility === 'team'
  return (
    <span
      title={team ? t('threadlist.team_chat') : t('threadlist.private_chat')}
      className={`shrink-0 inline-flex ${team ? 'text-cmint' : 'text-faint'}`}
    >
      {team ? (
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
          <circle cx="6" cy="5.5" r="2.1" stroke="currentColor" strokeWidth="1.3" />
          <circle cx="11.3" cy="6" r="1.7" stroke="currentColor" strokeWidth="1.3" />
          <path d="M2 13c0-2.1 1.8-3.2 4-3.2s4 1.1 4 3.2M10 9.9c1.7 0 3.6.8 3.6 2.7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      ) : (
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
          <rect x="3.5" y="7" width="9" height="6.4" rx="1.4" stroke="currentColor" strokeWidth="1.3" />
          <path d="M5.6 7V5.2a2.4 2.4 0 014.8 0V7" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
        </svg>
      )}
    </span>
  )
}

function ThreadRow({
  thread,
  active,
  folders,
  onSelect,
  onRename,
  onDelete,
  onMove,
  selectMode = false,
  selected = false,
  onToggleSelect,
  onEnterSelect,
}: {
  thread: Thread
  active: boolean
  folders: Folder[]
  onSelect: () => void
  onRename: (title: string) => void
  onDelete: () => void
  onMove: (folderId: string | null) => void
  selectMode?: boolean
  selected?: boolean
  onToggleSelect?: () => void
  onEnterSelect?: () => void
}) {
  const t = useT()
  const [menuOpen, setMenuOpen] = useState(false)
  const [moveOpen, setMoveOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(thread.title)
  const rowRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    function onDown(e: MouseEvent) {
      if (rowRef.current && !rowRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
        setMoveOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [menuOpen])

  function commitRename() {
    const v = draft.trim()
    setEditing(false)
    if (v && v !== thread.title) onRename(v)
    else setDraft(thread.title)
  }

  // Auswahl-Modus: Checkbox-Zeile, Klick togglet Auswahl (kein Öffnen, kein „…"-Menü).
  if (selectMode) {
    return (
      <div
        onClick={onToggleSelect}
        className={`flex items-center gap-2 pr-1 rounded-lg cursor-pointer transition ${
          selected ? 'bg-primary/10' : 'hover:bg-surface2'
        }`}
      >
        <span
          className={`ml-2 my-2 shrink-0 w-4 h-4 rounded-[5px] border grid place-items-center transition ${
            selected ? 'bg-primary border-primary' : 'border-line2'
          }`}
        >
          {selected && (
            <svg width="9" height="9" viewBox="0 0 12 12"><path d="M2.5 6.2l2.2 2.2L9.5 3.5" stroke="#0F1013" strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
          )}
        </span>
        <span className={`flex-1 min-w-0 py-2 text-[12.5px] truncate ${selected ? 'text-paper' : 'text-muted'}`} title={thread.title}>
          {thread.title}
        </span>
      </div>
    )
  }

  return (
    <div ref={rowRef} className="relative group">
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitRename()
            if (e.key === 'Escape') {
              setEditing(false)
              setDraft(thread.title)
            }
          }}
          onBlur={commitRename}
          className="w-full px-2.5 py-2 rounded-lg text-[12.5px] bg-surface3 border border-primary/50 text-paper outline-none"
        />
      ) : (
        <div
          className={`flex items-center gap-1 pr-1 rounded-lg transition ${
            active ? 'bg-surface3' : 'hover:bg-surface2'
          }`}
        >
          <button
            onClick={onSelect}
            className={`flex-1 min-w-0 text-left px-2.5 py-2 text-[12.5px] transition ${
              active ? 'text-paper' : 'text-muted group-hover:text-paper'
            }`}
            title={thread.title}
          >
            <span className="flex items-center gap-1.5 min-w-0">
              <span className="truncate">{thread.title}</span>
              <VisibilityBadge visibility={thread.visibility} />
            </span>
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              setMenuOpen((v) => !v)
              setMoveOpen(false)
            }}
            title={t('threadlist.actions')}
            className={`shrink-0 p-1 rounded-md text-faint hover:text-paper hover:bg-surface3 transition ${
              menuOpen ? 'text-paper bg-surface3' : 'opacity-0 group-hover:opacity-100'
            }`}
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
              <circle cx="3" cy="8" r="1.3" />
              <circle cx="8" cy="8" r="1.3" />
              <circle cx="13" cy="8" r="1.3" />
            </svg>
          </button>
        </div>
      )}

      {menuOpen && !editing && (
        <div className="absolute right-1 top-full mt-0.5 w-48 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 py-1 z-30 animate-fade-up">
          <button
            onClick={() => {
              setMenuOpen(false)
              setEditing(true)
              setDraft(thread.title)
            }}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[12.5px] text-paper hover:bg-surface2 transition"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-muted">
              <path d="M11 2.5l2.5 2.5L5 13.5 2 14l.5-3L11 2.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
            </svg>
            {t('common.rename')}
          </button>
          <button
            onClick={() => setMoveOpen((v) => !v)}
            className="w-full flex items-center justify-between gap-2.5 px-3 py-1.5 text-[12.5px] text-paper hover:bg-surface2 transition"
          >
            <span className="flex items-center gap-2.5">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-muted">
                <path d="M2 4.5a1 1 0 011-1h3l1.2 1.4H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1V4.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
              </svg>
              {t('threadlist.move_to_folder')}
            </span>
            <svg width="10" height="10" viewBox="0 0 12 12" className={`text-faint transition-transform ${moveOpen ? 'rotate-90' : ''}`}>
              <path d="M4.5 2.5L8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.3" fill="none" strokeLinecap="round" />
            </svg>
          </button>
          {moveOpen && (
            <div className="mx-1 my-0.5 max-h-40 overflow-y-auto rounded-lg bg-surface2 border border-line">
              <button
                onClick={() => {
                  onMove(null)
                  setMenuOpen(false)
                  setMoveOpen(false)
                }}
                className={`w-full text-left px-3 py-1.5 text-[12px] hover:bg-surface3 transition ${
                  !thread.folder_id ? 'text-primary' : 'text-muted'
                }`}
              >
                {t('threadlist.no_folder')}
              </button>
              {folders.map((f) => (
                <button
                  key={f.id}
                  onClick={() => {
                    onMove(f.id)
                    setMenuOpen(false)
                    setMoveOpen(false)
                  }}
                  className={`w-full text-left px-3 py-1.5 text-[12px] truncate hover:bg-surface3 transition ${
                    thread.folder_id === f.id ? 'text-primary' : 'text-paper/90'
                  }`}
                  title={f.name}
                >
                  {f.name}
                </button>
              ))}
              {folders.length === 0 && (
                <div className="px-3 py-1.5 text-[11px] text-faint">{t('threadlist.no_folders')}</div>
              )}
            </div>
          )}
          <button
            onClick={() => {
              setMenuOpen(false)
              setMoveOpen(false)
              onEnterSelect?.()
            }}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[12.5px] text-paper hover:bg-surface2 transition"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="text-muted">
              <rect x="2" y="2" width="12" height="12" rx="3" stroke="currentColor" strokeWidth="1.3" />
              <path d="M5 8l2.2 2.2L11 6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('threadlist.multi_select')}
          </button>
          <div className="h-px bg-line my-1" />
          <button
            onClick={() => {
              setMenuOpen(false)
              if (confirm(t('threadlist.confirm_delete_thread', { title: thread.title }))) onDelete()
            }}
            className="w-full flex items-center gap-2.5 px-3 py-1.5 text-[12.5px] text-crose hover:bg-crose/10 transition"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5a1 1 0 001 1h4a1 1 0 001-1l.5-8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('common.delete')}
          </button>
        </div>
      )}
    </div>
  )
}

function FolderHeader({
  folder,
  collapsed,
  count,
  onToggle,
  onRename,
  onDelete,
}: {
  folder: Folder
  collapsed: boolean
  count: number
  onToggle: () => void
  onRename: (name: string) => void
  onDelete: () => void
}) {
  const t = useT()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(folder.name)

  function commit() {
    const v = draft.trim()
    setEditing(false)
    if (v && v !== folder.name) onRename(v)
    else setDraft(folder.name)
  }

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') {
            setEditing(false)
            setDraft(folder.name)
          }
        }}
        onBlur={commit}
        className="w-full px-2.5 py-2 rounded-lg text-[12.5px] bg-surface3 border border-primary/50 text-paper outline-none"
      />
    )
  }

  return (
    <div className="flex items-center gap-1 pr-1 group/folder rounded-lg hover:bg-surface2 transition">
      <button onClick={onToggle} className="flex items-center gap-1.5 min-w-0 flex-1 text-left px-2.5 py-2 text-[12.5px] text-muted group-hover/folder:text-paper transition">
        <svg width="11" height="11" viewBox="0 0 12 12" className={`shrink-0 text-faint transition-transform ${collapsed ? '' : 'rotate-90'}`}>
          <path d="M4.5 2.5L8 6l-3.5 3.5" stroke="currentColor" strokeWidth="1.3" fill="none" strokeLinecap="round" />
        </svg>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" className="shrink-0">
          <path d="M2 4.5a1 1 0 011-1h3l1.2 1.4H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1V4.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
        </svg>
        <span className="truncate">{folder.name}</span>
        <span className="text-[10px] text-faint shrink-0">{count}</span>
      </button>
      <button
        onClick={() => {
          setEditing(true)
          setDraft(folder.name)
        }}
        title={t('threadlist.rename_folder')}
        className="shrink-0 p-1 rounded text-faint hover:text-paper opacity-0 group-hover/folder:opacity-100 transition"
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
          <path d="M11 2.5l2.5 2.5L5 13.5 2 14l.5-3L11 2.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
        </svg>
      </button>
      <button
        onClick={() => {
          if (confirm(t('threadlist.confirm_delete_folder', { name: folder.name }))) onDelete()
        }}
        title={t('threadlist.delete_folder')}
        className="shrink-0 p-1 rounded text-faint hover:text-crose opacity-0 group-hover/folder:opacity-100 transition"
      >
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
          <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5a1 1 0 001 1h4a1 1 0 001-1l.5-8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  )
}

type ThreadListProps = {
  threads: Thread[]
  folders: Folder[]
  activeThreadId: string | null
  onSelectThread: (id: string) => void
  onCreateFolder: (name: string) => void
  onRenameFolder: (id: string, name: string) => void
  onDeleteFolder: (id: string) => void
  onRenameThread: (id: string, title: string) => void
  onDeleteThread: (id: string) => void
  onMoveThread: (id: string, folderId: string | null) => void
  // „Neuer Ordner"-Eingabe: extern getriggert (Button liegt außerhalb der Liste),
  // die Eingabe selbst lebt aber in der Liste. Controlled via creatingFolder.
  creatingFolder?: boolean
  onCreatingFolderChange?: (v: boolean) => void
  className?: string
}

/**
 * Gemeinsame Ordner-/Thread-Liste (eine Quelle der Wahrheit) für die Desktop-Sidebar
 * UND den mobilen Chats-Screen: Auswahl, Umbenennen/Löschen/Verschieben je Zeile,
 * Ordner-CRUD und Mehrfachauswahl (Bulk verschieben/löschen).
 */
export default function ThreadList({
  threads,
  folders,
  activeThreadId,
  onSelectThread,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onRenameThread,
  onDeleteThread,
  onMoveThread,
  creatingFolder = false,
  onCreatingFolderChange,
  className = '',
}: ThreadListProps) {
  const t = useT()
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [folderDraft, setFolderDraft] = useState('')

  // Neue-Ordner-Eingabe frisch starten, wenn extern geöffnet.
  useEffect(() => {
    if (creatingFolder) setFolderDraft('')
  }, [creatingFolder])

  function toggleFolder(id: string) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function commitNewFolder() {
    const v = folderDraft.trim()
    onCreatingFolderChange?.(false)
    setFolderDraft('')
    if (v) onCreateFolder(v)
  }

  const sorted = [...threads].sort((a, b) => b.ts - a.ts)
  const unfiled = sorted.filter((t) => !t.folder_id)

  // ---- Multi-Select für Chats (Bulk: verschieben / löschen) ----
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkMoveOpen, setBulkMoveOpen] = useState(false)
  const bulkRef = useRef<HTMLDivElement>(null)
  const allIds = sorted.map((t) => t.id)
  const allSelected = selected.size > 0 && selected.size === allIds.length

  const toggleSel = (id: string) =>
    setSelected((prev) => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  const toggleAll = () => setSelected(allSelected ? new Set() : new Set(allIds))
  const enterSelect = (id: string) => {
    setSelectMode(true)
    setSelected(new Set([id]))
  }
  const exitSelect = () => {
    setSelectMode(false)
    setSelected(new Set())
    setBulkMoveOpen(false)
  }
  const bulkMove = (fid: string | null) => {
    selected.forEach((id) => onMoveThread(id, fid))
    exitSelect()
  }
  const bulkDelete = () => {
    if (!selected.size) return
    const msg = selected.size > 1
      ? t('threadlist.confirm_delete_selected_many', { count: selected.size })
      : t('threadlist.confirm_delete_selected_one')
    if (confirm(msg)) {
      selected.forEach((id) => onDeleteThread(id))
      exitSelect()
    }
  }
  useEffect(() => {
    if (!bulkMoveOpen) return
    function onDown(e: MouseEvent) {
      if (bulkRef.current && !bulkRef.current.contains(e.target as Node)) setBulkMoveOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [bulkMoveOpen])

  const renderThread = (t: Thread) => (
    <ThreadRow
      key={t.id}
      thread={t}
      active={t.id === activeThreadId}
      folders={folders}
      onSelect={() => onSelectThread(t.id)}
      onRename={(title) => onRenameThread(t.id, title)}
      onDelete={() => onDeleteThread(t.id)}
      onMove={(fid) => onMoveThread(t.id, fid)}
      selectMode={selectMode}
      selected={selected.has(t.id)}
      onToggleSelect={() => toggleSel(t.id)}
      onEnterSelect={() => enterSelect(t.id)}
    />
  )

  return (
    <div className={`flex-1 min-h-0 flex flex-col ${className}`}>
      {/* Multi-Select — zweizeilig, damit nichts gequetscht wird */}
      {selectMode && (
        <div ref={bulkRef} className="relative mb-1.5 rounded-xl border border-line bg-surface2/60 px-2 py-2 flex flex-col gap-2 animate-fade-down">
          {/* Zeile 1: Alle-Checkbox + Zähler + Schließen */}
          <div className="flex items-center gap-2">
            <button
              onClick={toggleAll}
              title={allSelected ? t('threadlist.deselect_all') : t('threadlist.select_all')}
              className={`shrink-0 w-[18px] h-[18px] rounded-[6px] border grid place-items-center transition ${
                allSelected ? 'bg-primary border-primary' : 'border-line2 hover:border-primary'
              }`}
            >
              {allSelected && (
                <svg width="10" height="10" viewBox="0 0 12 12"><path d="M2.5 6.2l2.2 2.2L9.5 3.5" stroke="#0F1013" strokeWidth="1.9" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>
              )}
            </button>
            <span className="text-[12px] text-paper font-medium tabular-nums">
              {t('threadlist.selected_count', { count: selected.size })}
            </span>
            <button
              onClick={exitSelect}
              title={t('threadlist.exit_select')}
              className="ml-auto shrink-0 p-1 rounded-md text-muted hover:text-paper hover:bg-surface3 transition"
            >
              <svg width="14" height="14" viewBox="0 0 14 14"><path d="M3.5 3.5l7 7M10.5 3.5l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
            </button>
          </div>
          {/* Zeile 2: Aktionen als vollwertige Buttons */}
          <div className="flex items-center gap-1.5">
            <button
              disabled={!selected.size}
              onClick={() => setBulkMoveOpen((v) => !v)}
              className="flex-1 flex items-center justify-between gap-1 px-2.5 py-1.5 rounded-lg text-[12px] bg-surface border border-line text-paper hover:border-line2 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <span className="flex items-center gap-1.5">
                <svg width="13" height="13" viewBox="0 0 16 16" fill="none" className="text-muted">
                  <path d="M2 4.5a1 1 0 011-1h3l1.2 1.4H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1V4.5z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
                </svg>
                {t('threadlist.move_to_folder')}
              </span>
              <svg width="10" height="10" viewBox="0 0 12 12" className={`text-faint transition-transform ${bulkMoveOpen ? 'rotate-180' : ''}`}><path d="M2.5 4.5L6 8l3.5-3.5" stroke="currentColor" strokeWidth="1.3" fill="none" strokeLinecap="round" /></svg>
            </button>
            <button
              disabled={!selected.size}
              onClick={bulkDelete}
              title={t('threadlist.delete_selected')}
              className="shrink-0 flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[12px] bg-surface border border-crose/30 text-crose hover:bg-crose/10 transition disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.5 8.5a1 1 0 001 1h4a1 1 0 001-1l.5-8.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {t('common.delete')}
            </button>
          </div>
          {bulkMoveOpen && (
            <div className="absolute left-2 top-full -mt-0.5 w-48 rounded-xl bg-surface border border-line shadow-2xl shadow-black/50 py-1 z-30 animate-fade-up max-h-52 overflow-y-auto">
              <div className="px-3 pt-1 pb-1 text-[10px] font-mono uppercase tracking-wider text-faint">{t('threadlist.move_to')}</div>
              <button onClick={() => bulkMove(null)} className="w-full text-left px-3 py-1.5 text-[12px] text-muted hover:bg-surface2 transition">{t('threadlist.no_folder')}</button>
              {folders.map((f) => (
                <button key={f.id} onClick={() => bulkMove(f.id)} className="w-full text-left px-3 py-1.5 text-[12px] text-paper/90 truncate hover:bg-surface2 transition" title={f.name}>{f.name}</button>
              ))}
              {folders.length === 0 && <div className="px-3 py-1.5 text-[11px] text-faint">{t('threadlist.no_folders')}</div>}
            </div>
          )}
        </div>
      )}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1 pt-1">
        {creatingFolder && (
          <input
            autoFocus
            value={folderDraft}
            onChange={(e) => setFolderDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitNewFolder()
              if (e.key === 'Escape') {
                onCreatingFolderChange?.(false)
                setFolderDraft('')
              }
            }}
            onBlur={commitNewFolder}
            placeholder={t('threadlist.folder_name_placeholder')}
            className="w-full px-2.5 py-1.5 rounded-lg text-[12px] bg-surface3 border border-primary/50 text-paper placeholder:text-faint outline-none"
          />
        )}

        {folders.map((f) => {
          const items = sorted.filter((t) => t.folder_id === f.id)
          const isCollapsed = collapsed.has(f.id)
          return (
            <div key={f.id} className="flex flex-col">
              <FolderHeader
                folder={f}
                collapsed={isCollapsed}
                count={items.length}
                onToggle={() => toggleFolder(f.id)}
                onRename={(name) => onRenameFolder(f.id, name)}
                onDelete={() => onDeleteFolder(f.id)}
              />
              {!isCollapsed && (
                <div className="pl-2 flex flex-col gap-0.5 mt-0.5">
                  {items.length === 0 ? (
                    <div className="text-[11px] text-faint px-2 py-1">{t('threadlist.empty_folder')}</div>
                  ) : (
                    items.map(renderThread)
                  )}
                </div>
              )}
            </div>
          )
        })}

        <div className="flex flex-col gap-0.5">
          {folders.length > 0 && unfiled.length > 0 && <div className="h-1" />}
          {threads.length === 0 && !creatingFolder && (
            <div className="text-[12px] text-faint px-1 py-2">{t('threadlist.no_chats')}</div>
          )}
          {unfiled.map(renderThread)}
        </div>
      </div>
    </div>
  )
}
