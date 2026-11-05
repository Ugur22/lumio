import { animated, useSpring, useTransition } from "@react-spring/web";
import { useEffect, useLayoutEffect, useRef, useState, type TouchEvent } from "react";
import { CodeActionsContext } from "./components/CodeActionsContext";
import { ContextMeter } from "./components/ContextMeter";
import { Composer, type ComposerHandle } from "./components/Composer";
import { BookIcon, MenuIcon } from "./components/icons";
import { MessageList, QuickActions, Starters } from "./components/MessageList";
import { Button, ConfirmDialog, PressButton, PromptDialog } from "./components/ui";
import { ProviderSwitcher } from "./components/ProviderSwitcher";
import { FlashNotice } from "./components/FlashNotice";
import { ProvidersDialog } from "./components/ProvidersDialog";
import { Sidebar } from "./components/Sidebar";
import { StoryDialog, type StoryTab } from "./components/StoryDialog";
import { useChat, useChatContext, useChatList, useCreateChat, useDeleteChat, useRenameChat, useSetChatModel } from "./hooks/useChats";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { useProfiles } from "./hooks/useProfiles";
import { useStreamingSend } from "./hooks/useStreamingSend";
import { useTrial } from "./hooks/useTrial";
import { useTheme } from "./hooks/useTheme";
import { useVisualViewport } from "./hooks/useVisualViewport";
import type { Attachment } from "./lib/images";
import { effectiveProfile } from "./lib/providers";
import { isManaged, sendBlocked } from "./lib/trial";
import { useStream } from "./store/stream";
import type { ChatModelBody, ChatSummary } from "./types";

export function App() {
  const { theme, toggle } = useTheme();
  const list = useChatList();
  const chats = list.data ?? [];

  // The app opens on a blank chat; an older chat only opens when picked from the drawer.
  const [currentId, setCurrentId] = useState<string | null>(null);
  const chat = useChat(currentId);

  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [story, setStory] = useState<{ open: boolean; tab: StoryTab }>({ open: false, tab: "bible" });
  const [renaming, setRenaming] = useState<ChatSummary | null>(null);
  const [deleting, setDeleting] = useState<ChatSummary | null>(null);
  const composer = useRef<ComposerHandle>(null);
  // A blank chat's model pick; not persisted, it only lives until the chat exists.
  const [pendingModel, setPendingModel] = useState<ChatModelBody | null>(null);

  const context = useChatContext(currentId);
  const pendingHere = useStream((s) => s.pending?.chatId === currentId);
  // One Composer instance serves both layouts, so a draft survives the move to the bottom.
  const blank = !pendingHere && (currentId === null || (chat.isSuccess && chat.data.messages.length === 0));

  // On a phone the keyboard would cover a centred input, so focusing it docks the layout early.
  const phone = useMediaQuery("(max-width: 720px)");
  const [focused, setFocused] = useState(false);
  // Phones never centre: the input stays at the bottom like a messaging app, so focusing it moves nothing.
  const centered = blank && !phone && !(focused && window.matchMedia("(pointer: coarse)").matches);

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

  useVisualViewport();

  const create = useCreateChat();
  const rename = useRenameChat();
  const remove = useDeleteChat();
  const { send, stop, isPending: sending } = useStreamingSend({
    // Used up: the way forward is a provider of their own. Full for today needs nothing but the message.
    onTrialRefused: (failure) => failure.kind === "ended" && setSettingsOpen(true),
  });
  const profiles = useProfiles().data;
  const activeProfile = effectiveProfile(profiles, chat.data?.profile_id).profile;
  const trial = useTrial().data;
  const managed = isManaged(activeProfile);

  const setChatModel = useSetChatModel();

  const select = (id: string | null) => {
    useStream.getState().clearFailures();
    if (id !== currentId) setPendingModel(null);
    setCurrentId(id);
    setMenuOpen(false);
    if (id === null) composer.current?.focus();
  };

  function onSend(content: string, attachments: Attachment[], web: boolean, illustrate: boolean) {
    // Starters and code actions send without passing the composer's own check.
    if (sendBlocked(trial, activeProfile)) return setSettingsOpen(true);
    const chatId = currentId;
    const model = chatId === null ? (pendingModel ?? undefined) : undefined;
    send(
      chatId,
      content,
      attachments,
      web,
      illustrate,
      (saved) => {
        // Only jump to the new chat if the user is still on the blank one.
        setCurrentId((cur) => (chatId === null && cur === null ? saved.id : cur));
        // Not if a newer pick was made while this send was in flight.
        if (chatId === null) setPendingModel((cur) => (cur === model ? null : cur));
      },
      model,
    );
  }

  // The story lives in the chat file, so a blank chat has to be created before the dialog can save to it.
  function openStory() {
    if (currentId) return setStory({ open: true, tab: "bible" });
    if (create.isPending) return;
    create.mutate(undefined, {
      onSuccess: (created) => {
        // The story dialog creates the chat early, so the pick is stored on it here instead of at the first send.
        if (pendingModel) setChatModel.mutate({ id: created.id, body: pendingModel });
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
    : "New chat";
  const loadError = list.error ?? chat.error ?? create.error;

  const scrim = useTransition(menuOpen, {
    from: { opacity: 0 },
    enter: { opacity: 1 },
    leave: { opacity: 0 },
    config: { tension: 260, friction: 30 },
  });

  // Touches that start on the composer can't scroll anything themselves, so hand the drag to the message list.
  const lastY = useRef<number | null>(null);
  const dragStart = (e: TouchEvent) => {
    lastY.current = e.touches[0]?.clientY ?? null;
  };
  const dragScroll = (e: TouchEvent) => {
    const t = e.target as HTMLElement;
    const y = e.touches[0]?.clientY;
    const prev = lastY.current;
    lastY.current = y ?? null;
    if (y === undefined || prev === null) return;
    if (t instanceof HTMLTextAreaElement && t.scrollHeight > t.clientHeight) return;
    e.currentTarget.parentElement?.querySelector<HTMLElement>("[data-image-bounds]")?.scrollBy(0, prev - y);
  };

  return (
    <div className="app-root flex h-dvh w-full max-[720px]:fixed max-[720px]:inset-x-0 max-[720px]:top-[var(--vv-top,0px)] max-[720px]:h-[var(--vv-height,100dvh)] max-w-full overflow-x-hidden font-sans text-[15px] leading-[1.6] text-text">
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
        onOpenChange={setMenuOpen}
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
        {/* backdrop-blur makes the header its own stacking context; without a z-index the model popover paints under the composer and tiles. Stays below the drawer overlay (z-10). */}
        {/* On phones the header is a 44px | title + model chip | 44px grid. It drops the blur (costly to repaint while the keyboard moves) for a solid bg, and order-first keeps it above the meter, which is later in the DOM. */}
        <header className="relative z-[5] flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border/70 px-5 pb-3 pt-[calc(0.75rem+env(safe-area-inset-top,0px))] backdrop-blur max-[720px]:order-first max-[720px]:grid max-[720px]:grid-cols-[44px_1fr_44px] max-[720px]:gap-y-0 max-[720px]:border-b-0 max-[720px]:bg-bg max-[720px]:px-2.5 max-[720px]:pb-2 max-[720px]:pt-[calc(0.375rem+env(safe-area-inset-top,0px))] max-[720px]:backdrop-blur-none">
          <PressButton
            type="button"
            aria-label="Open chats"
            onClick={() => setMenuOpen(true)}
            className="flex items-center justify-center rounded-xl p-2 text-muted hover:bg-bubble focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent max-[720px]:col-start-1 max-[720px]:row-span-2 max-[720px]:row-start-1 max-[720px]:size-11 max-[720px]:rounded-full max-[720px]:border max-[720px]:border-border max-[720px]:bg-surface max-[720px]:p-0 max-[720px]:text-text min-[721px]:hidden"
          >
            <MenuIcon />
          </PressButton>
          <h1 title={title} className="min-w-0 flex-1 truncate font-display text-lg font-semibold max-[720px]:col-start-2 max-[720px]:row-start-1 max-[720px]:text-center max-[720px]:text-base">{title}</h1>
          <Button variant="bare"
            type="button"
            aria-label="Story"
            title="Story bible, lore and summary"
            disabled={create.isPending}
            onClick={openStory}
            className="flex flex-none items-center justify-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] text-muted hover:bg-bubble hover:text-text disabled:opacity-60 max-[720px]:col-start-3 max-[720px]:row-span-2 max-[720px]:row-start-1 max-[720px]:size-11 max-[720px]:rounded-full max-[720px]:border max-[720px]:border-border max-[720px]:bg-surface max-[720px]:p-0 max-[720px]:text-text"
          >
            <BookIcon width={16} height={16} className="max-[720px]:size-[22px]" />
            <span className="max-[720px]:hidden">Story</span>
          </Button>
          <div className="min-w-0 max-[720px]:col-start-2 max-[720px]:row-start-2 max-[720px]:justify-self-center">
            <ProviderSwitcher
              chatId={currentId}
              pendingModel={pendingModel}
              onPendingModel={setPendingModel}
              onManage={() => setSettingsOpen(true)}
            />
          </div>
        </header>
        <FlashNotice onAddProvider={() => setSettingsOpen(true)} />
        {loadError && (
          <div role="alert" className="px-5 py-2 text-warn-bar">
            Failed: {loadError.message}
          </div>
        )}
        <CodeActionsContext.Provider value={{ askAboutRun: (text) => onSend(text, [], false, false), busy: sending }}>
          <MessageList
            messages={currentId ? (chat.data?.messages ?? []) : []}
            chatId={currentId}
          />
        </CodeActionsContext.Provider>
        <ContextMeter
          context={currentId && !(blank && phone) ? context.data : undefined}
          onSetWindow={() => setSettingsOpen(true)}
          onSummarize={managed ? undefined : () => setStory({ open: true, tab: "summary" })}
        />
        {blank && phone && (
          <QuickActions
            focused={focused}
            canAttach={activeProfile?.vision ?? false}
            canWeb={!managed}
            onStory={openStory}
            onScene={() => composer.current?.setText("Write a scene where ")}
            onWeb={() => composer.current?.enableWeb()}
            onAttach={() => composer.current?.openPicker()}
          />
        )}
        <animated.div ref={dock} style={dockStyle} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} onTouchStart={dragStart} onTouchMove={dragScroll}>
          <Composer
            ref={composer}
            disabled={sending}
            vision={activeProfile?.vision ?? false}
            canIllustrate={Boolean(activeProfile?.image_model)}
            managed={managed}
            trial={trial}
            onAddProvider={() => setSettingsOpen(true)}
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
