import { useState } from 'react'
import type { Folder } from '../types'
import ThreadList, { type Thread } from './ThreadList'
import { useT } from '../i18n'

type ChatsScreenProps = {
  threads: Thread[]
  folders: Folder[]
  activeThreadId: string | null
  onSelectThread: (id: string) => void
  onNewThread: () => void
  onCreateFolder: (name: string) => void
  onRenameFolder: (id: string, name: string) => void
  onDeleteFolder: (id: string) => void
  onRenameThread: (id: string, title: string) => void
  onDeleteThread: (id: string) => void
  onMoveThread: (id: string, folderId: string | null) => void
  onClose: () => void
}

/**
 * Mobile-Vollbild-Verwaltung für Chats & Ordner (< md), nativ-App-Stil.
 * Ersetzt auf dem Smartphone die persistente Desktop-Sidebar-Liste. Nutzt dieselbe
 * <ThreadList/> wie die Sidebar (eine Quelle der Wahrheit) mit denselben Handlern —
 * Auswahl schließt den Screen (die Handler werden in App.tsx entsprechend verdrahtet).
 */
export default function ChatsScreen({
  threads,
  folders,
  activeThreadId,
  onSelectThread,
  onNewThread,
  onCreateFolder,
  onRenameFolder,
  onDeleteFolder,
  onRenameThread,
  onDeleteThread,
  onMoveThread,
  onClose,
}: ChatsScreenProps) {
  const t = useT()
  const [creatingFolder, setCreatingFolder] = useState(false)

  return (
    <div className="md:hidden fixed inset-0 z-40 bg-ink flex flex-col pb-[calc(3.5rem+env(safe-area-inset-bottom))]">
      {/* Kopf: Titel + Schließen */}
      <div className="flex items-center gap-2 px-4 h-14 shrink-0 border-b border-line bg-surface">
        <h2 className="font-display font-bold text-[16px] text-paper flex-1">{t('chatsscreen.title')}</h2>
        <button
          onClick={onClose}
          title={t('common.close')}
          aria-label={t('common.close')}
          className="shrink-0 w-11 h-11 grid place-items-center rounded-lg text-muted hover:text-paper hover:bg-surface2 transition"
        >
          <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* Aktionen: Neuer Chat · Neuer Ordner */}
      <div className="flex items-center gap-2 px-3 py-2.5 shrink-0 border-b border-line">
        <button
          onClick={onNewThread}
          className="flex-1 min-h-[44px] flex items-center justify-center gap-2 px-3 rounded-full text-[13.5px] font-semibold cta-grad"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M8 3v10M3 8h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          {t('chatsscreen.new_chat')}
        </button>
        <button
          onClick={() => setCreatingFolder(true)}
          className="flex-1 min-h-[44px] flex items-center justify-center gap-2 px-3 rounded-full text-[13.5px] font-medium text-muted bg-surface2 border border-line hover:text-paper transition"
        >
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M2 4.5a1 1 0 011-1h3l1.2 1.4H13a1 1 0 011 1V12a1 1 0 01-1 1H3a1 1 0 01-1-1V4.5z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
            <path d="M8 7.2v3M6.5 8.7h3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
          {t('chatsscreen.new_folder')}
        </button>
      </div>

      {/* Geteilte Ordner-/Thread-Liste (identisch zur Desktop-Sidebar) */}
      <ThreadList
        className="px-3 pt-2 pb-3"
        threads={threads}
        folders={folders}
        activeThreadId={activeThreadId}
        onSelectThread={onSelectThread}
        onCreateFolder={onCreateFolder}
        onRenameFolder={onRenameFolder}
        onDeleteFolder={onDeleteFolder}
        onRenameThread={onRenameThread}
        onDeleteThread={onDeleteThread}
        onMoveThread={onMoveThread}
        creatingFolder={creatingFolder}
        onCreatingFolderChange={setCreatingFolder}
      />
    </div>
  )
}
