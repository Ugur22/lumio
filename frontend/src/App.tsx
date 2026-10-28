import { animated, useTransition } from "@react-spring/web";
import { useRef, useState } from "react";
import { Composer, type ComposerHandle } from "./components/Composer";
import { MenuIcon } from "./components/icons";
import { MessageList } from "./components/MessageList";
import { PressButton } from "./components/PressButton";
import { ProviderSwitcher } from "./components/ProviderSwitcher";
import { ProvidersDialog } from "./components/ProvidersDialog";
import { Sidebar } from "./components/Sidebar";
import { useChat, useChatList, useDeleteChat, useRenameChat } from "./hooks/useChats";
import { useProfiles } from "./hooks/useProfiles";
import { useStreamingSend } from "./hooks/useStreamingSend";
import { useTheme } from "./hooks/useTheme";
import type { Attachment } from "./lib/images";
import { isRestoring } from "./lib/restoring";
import type { ChatSummary } from "./types";

export function App() {
  const { theme, toggle } = useTheme();
  const list = useChatList();
  const chats = list.data ?? [];

  // undefined = nothing chosen yet, so the newest chat opens once the list loads.
  const [chosen, setChosen] = useState<string | null | undefined>(undefined);
  const currentId = chosen === undefined ? (chats[0]?.id ?? null) : chosen;
  const chat = useChat(currentId);
  const restoring = isRestoring({ chosen, listPending: list.isPending, currentId, chatPending: chat.isPending });

  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const composer = useRef<ComposerHandle>(null);

  const rename = useRenameChat();
  const remove = useDeleteChat();
  const { send, stop, isPending: sending } = useStreamingSend();
  const profiles = useProfiles().data;
  const activeProfile = profiles?.profiles.find((p) => p.id === profiles.active);

  const select = (id: string | null) => {
    setChosen(id);
    setMenuOpen(false);
    if (id === null) composer.current?.focus();
  };

  function onSend(content: string, attachments: Attachment[], web: boolean) {
    const chatId = currentId;
    send(chatId, content, attachments, web, (saved) => {
      // Only jump to the new chat if the user is still on the blank one.
      setChosen((cur) => (chatId === null && (cur === null || cur === undefined) ? saved.id : cur));
    });
  }

  function onRename(c: ChatSummary) {
    const title = window.prompt("Rename chat", c.title)?.trim();
    if (title) rename.mutate({ id: c.id, title });
  }

  function onDelete(c: ChatSummary) {
    if (!window.confirm(`Delete "${c.title}"?`)) return;
    remove.mutate(c.id, { onSuccess: () => c.id === currentId && select(null) });
  }

  const title = currentId
    ? (chat.data?.title ?? chats.find((c) => c.id === currentId)?.title ?? "")
    : restoring
      ? ""
      : "New chat";
  const loadError = list.error ?? chat.error;

  const scrim = useTransition(menuOpen, {
    from: { opacity: 0 },
    enter: { opacity: 1 },
    leave: { opacity: 0 },
    config: { tension: 260, friction: 30 },
  });

  return (
    <div className="flex h-dvh font-sans text-[15px] leading-[1.6] text-text">
      <Sidebar
        chats={chats}
        currentId={currentId}
        open={menuOpen}
        theme={theme}
        onNew={() => select(null)}
        onOpen={select}
        onRename={onRename}
        onDelete={onDelete}
        onToggleTheme={toggle}
        onOpenSettings={() => {
          setMenuOpen(false);
          setSettingsOpen(true);
        }}
      />
      <ProvidersDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      {scrim(
        (style, show) =>
          show && (
            <animated.div
              aria-hidden="true"
              style={style}
              onClick={() => setMenuOpen(false)}
              className="fixed inset-0 z-10 bg-black/40 min-[721px]:hidden"
            />
          ),
      )}
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border/70 px-5 py-3 backdrop-blur">
          <PressButton
            type="button"
            aria-label="Open chats"
            onClick={() => setMenuOpen(true)}
            className="rounded-xl p-2 text-muted hover:bg-bubble focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent min-[721px]:hidden"
          >
            <MenuIcon />
          </PressButton>
          <h1 className="min-w-0 truncate font-display text-lg font-semibold">{title}</h1>
          <ProviderSwitcher onManage={() => setSettingsOpen(true)} />
        </header>
        {loadError && (
          <div role="alert" className="px-5 py-2 text-warn-bar">
            Failed: {loadError.message}
          </div>
        )}
        <MessageList
          messages={currentId ? (chat.data?.messages ?? []) : []}
          chatId={currentId}
          loading={restoring}
          onPick={(text) => composer.current?.setText(text)}
        />
        <Composer
          ref={composer}
          disabled={sending}
          vision={activeProfile?.vision ?? false}
          providerName={activeProfile?.name ?? null}
          onStop={stop}
          onSend={onSend}
        />
      </main>
    </div>
  );
}
