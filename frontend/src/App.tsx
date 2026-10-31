import { animated, useSpring, useTransition } from "@react-spring/web";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { CodeActionsContext } from "./components/CodeActionsContext";
import { ContextMeter } from "./components/ContextMeter";
import { Composer, type ComposerHandle } from "./components/Composer";
import { BookIcon, MenuIcon } from "./components/icons";
import { MessageList, Starters } from "./components/MessageList";
import { Button, ConfirmDialog, PressButton, PromptDialog } from "./components/ui";
import { ProviderSwitcher } from "./components/ProviderSwitcher";
import { ProvidersDialog } from "./components/ProvidersDialog";
import { Sidebar } from "./components/Sidebar";
import { StoryDialog, type StoryTab } from "./components/StoryDialog";
import { useChat, useChatContext, useChatList, useCreateChat, useDeleteChat, useRenameChat } from "./hooks/useChats";
import { useProfiles } from "./hooks/useProfiles";
import { useStreamingSend } from "./hooks/useStreamingSend";
import { useTheme } from "./hooks/useTheme";
import type { Attachment } from "./lib/images";
import { effectiveProfile } from "./lib/providers";
import { isRestoring } from "./lib/restoring";
import { useStream } from "./store/stream";
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
  const [story, setStory] = useState<{ open: boolean; tab: StoryTab }>({ open: false, tab: "bible" });
  const [renaming, setRenaming] = useState<ChatSummary | null>(null);
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const composer = useRef<ComposerHandle>(null);

  const context = useChatContext(currentId);
  const pendingHere = useStream((s) => s.pending?.chatId === currentId);
  // One Composer instance serves both layouts, so a draft survives the move to the bottom.
  const blank = !restoring && !pendingHere && (currentId === null || (chat.isSuccess && chat.data.messages.length === 0));

  // On a phone the keyboard would cover a centred input, so focusing it docks the layout early.
  const [focused, setFocused] = useState(false);
  const centered = blank && !(focused && window.matchMedia("(pointer: coarse)").matches);

  // FLIP: when the layout docks it snaps, so play the composer from where it was.
  const dock = useRef<HTMLDivElement>(null);
  const tiles = useRef<HTMLDivElement>(null);
  const tilesTop = useRef(0);
  const last = useRef<{ top: number; centered: boolean } | null>(null);
  const [fading, setFading] = useState(false);
  const [dockStyle, dockApi] = useSpring(() => ({ y: 0 }));
  useLayoutEffect(() => {
    const top = dock.current?.getBoundingClientRect().top;
    if (top === undefined) return;
    if (centered && tiles.current) tilesTop.current = tiles.current.offsetTop;
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (last.current?.centered && !centered && !calm) {
      dockApi.set({ y: last.current.top - top });
      dockApi.start({ y: 0, config: { tension: 170, friction: 22 } });
    }
    last.current = { top, centered };
  });
  const wasCentered = useRef(centered);
  useLayoutEffect(() => {
    if (wasCentered.current && !centered && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) setFading(true);
    wasCentered.current = centered;
  }, [centered]);
  // The tiles linger, out of flow, just long enough to fade.
  useEffect(() => {
    if (!fading) return;
    const t = setTimeout(() => setFading(false), 220);
    return () => clearTimeout(t);
  }, [fading]);

  const create = useCreateChat();
  const rename = useRenameChat();
  const remove = useDeleteChat();
  const { send, stop, isPending: sending } = useStreamingSend();
  const profiles = useProfiles().data;
  const activeProfile = effectiveProfile(profiles, chat.data?.profile_id).profile;

  const select = (id: string | null) => {
    useStream.getState().clearFailures();
    setChosen(id);
    setMenuOpen(false);
    if (id === null) composer.current?.focus();
  };

  function onSend(content: string, attachments: Attachment[], web: boolean, illustrate: boolean) {
    const chatId = currentId;
    send(chatId, content, attachments, web, illustrate, (saved) => {
      // Only jump to the new chat if the user is still on the blank one.
      setChosen((cur) => (chatId === null && (cur === null || cur === undefined) ? saved.id : cur));
    });
  }

  // The story lives in the chat file, so a blank chat has to be created before the dialog can save to it.
  function openStory() {
    if (currentId) return setStory({ open: true, tab: "bible" });
    if (create.isPending) return;
    create.mutate(undefined, {
      onSuccess: (created) => {
        select(created.id);
        setStory({ open: true, tab: "bible" });
      },
    });
  }

  function confirmDelete(c: ChatSummary) {
    setDeleting(null);
    remove.mutate(c.id, { onSuccess: () => c.id === currentId && select(null) });
  }

  const title = currentId
    ? (chat.data?.title ?? chats.find((c) => c.id === currentId)?.title ?? "")
    : restoring
      ? ""
      : "New chat";
  const loadError = list.error ?? chat.error ?? create.error;

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
        onRename={setRenaming}
        onDelete={setDeleting}
        onToggleTheme={toggle}
        onOpenSettings={() => {
          setMenuOpen(false);
          setSettingsOpen(true);
        }}
      />
      <ProvidersDialog open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      <PromptDialog
        open={renaming !== null}
        title="Rename chat"
        label="Title"
        initialValue={renaming?.title ?? ""}
        submitLabel="Rename"
        maxLength={100}
        onSubmit={(title) => {
          if (renaming) rename.mutate({ id: renaming.id, title });
          setRenaming(null);
        }}
        onCancel={() => setRenaming(null)}
      />
      <ConfirmDialog
        open={deleting !== null}
        title="Delete this chat?"
        description={deleting ? `"${deleting.title}" and its messages will be removed.` : undefined}
        confirmLabel="Delete"
        danger
        onConfirm={() => deleting && confirmDelete(deleting)}
        onCancel={() => setDeleting(null)}
      />
      <StoryDialog
        open={story.open}
        chatId={currentId}
        tab={story.tab}
        onClose={() => setStory((s) => ({ ...s, open: false }))}
      />
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
      <main className="relative flex min-w-0 flex-1 flex-col">
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
          <Button variant="bare"
            type="button"
            aria-label="Story"
            title="Story bible, lore and summary"
            disabled={create.isPending}
            onClick={openStory}
            className="ml-auto flex flex-none items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] text-muted hover:bg-bubble hover:text-text disabled:opacity-60"
          >
            <BookIcon width={16} height={16} />
            <span className="max-[480px]:hidden">Story</span>
          </Button>
          <ProviderSwitcher chatId={currentId} onManage={() => setSettingsOpen(true)} />
        </header>
        {loadError && (
          <div role="alert" className="px-5 py-2 text-warn-bar">
            Failed: {loadError.message}
          </div>
        )}
        <CodeActionsContext.Provider value={{ askAboutRun: (text) => onSend(text, [], false, false), busy: sending }}>
          <MessageList
            messages={currentId ? (chat.data?.messages ?? []) : []}
            chatId={currentId}
            loading={restoring}
          />
        </CodeActionsContext.Provider>
        <ContextMeter
          context={currentId ? context.data : undefined}
          onSetWindow={() => setSettingsOpen(true)}
          onSummarize={() => setStory({ open: true, tab: "summary" })}
        />
        <animated.div ref={dock} style={dockStyle} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}>
          <Composer
            ref={composer}
            disabled={sending}
            vision={activeProfile?.vision ?? false}
            canIllustrate={Boolean(activeProfile?.image_model)}
            providerName={activeProfile?.name ?? null}
            onStop={stop}
            onSend={onSend}
          />
        </animated.div>
        {(centered || fading) && (
          <Starters
            ref={tiles}
            leavingAt={centered ? undefined : tilesTop.current}
            disabled={sending}
            onStory={openStory}
            onPick={(text, now) => (now ? onSend(text, [], false, false) : composer.current?.setText(text))}
          />
        )}
        {centered && <div className="flex-[1.2]" />}
      </main>
    </div>
  );
}
