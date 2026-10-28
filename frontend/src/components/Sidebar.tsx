import { animated, useSpring, useTransition } from "@react-spring/web";
import { useMemo } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import type { Theme } from "../hooks/useTheme";
import type { ChatSummary } from "../types";
import { KeyIcon, LumioMark, MoonIcon, PencilIcon, PlusIcon, SunIcon, TrashIcon } from "./icons";
import { APP_NAME } from "../lib/brand";
import { PressButton } from "./PressButton";

interface Props {
  chats: ChatSummary[];
  currentId: string | null;
  open: boolean;
  theme: Theme;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (chat: ChatSummary) => void;
  onDelete: (chat: ChatSummary) => void;
  onToggleTheme: () => void;
  onOpenSettings: () => void;
}

type Row =
  | { key: string; kind: "header"; label: string }
  | { key: string; kind: "chat"; chat: ChatSummary };

const HEADER_HEIGHT = 30;
const CHAT_HEIGHT = 40;

const focus = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

const DAY = 86_400_000;

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function groupLabel(iso: string, today: number) {
  const t = startOfDay(new Date(iso));
  if (t >= today) return "Today";
  if (t >= today - DAY) return "Yesterday";
  if (t >= today - 7 * DAY) return "Previous 7 days";
  return "Older";
}

// The list arrives newest first, so each group is contiguous.
function toRows(chats: ChatSummary[]): Row[] {
  const today = startOfDay(new Date());
  const rows: Row[] = [];
  let last = "";
  for (const chat of chats) {
    const label = groupLabel(chat.updated, today);
    if (label !== last) {
      rows.push({ key: `header-${label}`, kind: "header", label });
      last = label;
    }
    rows.push({ key: chat.id, kind: "chat", chat });
  }
  return rows;
}

function ThemeIcon({ theme }: { theme: Theme }) {
  const transitions = useTransition(theme, {
    from: { opacity: 0, rotate: -80, scale: 0.4 },
    enter: { opacity: 1, rotate: 0, scale: 1 },
    leave: { opacity: 0, rotate: 80, scale: 0.4 },
    exitBeforeEnter: true,
    config: { tension: 380, friction: 22 },
  });
  return (
    <span className="relative block size-[18px]">
      {transitions((style, t) => (
        <animated.span style={style} className="absolute inset-0">
          {t === "dark" ? <SunIcon /> : <MoonIcon />}
        </animated.span>
      ))}
    </span>
  );
}

export function Sidebar({ chats, currentId, open, theme, onNew, onOpen, onRename, onDelete, onToggleTheme, onOpenSettings }: Props) {
  const mobile = useMediaQuery("(max-width: 720px)");
  const slide = useSpring({ x: mobile && !open ? -105 : 0, config: { tension: 300, friction: 32 } });

  const rows = useMemo(() => toRows(chats), [chats]);
  const transitions = useTransition(rows, {
    keys: (row) => row.key,
    from: { opacity: 0, height: 0, x: -14 },
    enter: (row) => ({ opacity: 1, height: row.kind === "header" ? HEADER_HEIGHT : CHAT_HEIGHT, x: 0 }),
    update: (row) => ({ height: row.kind === "header" ? HEADER_HEIGHT : CHAT_HEIGHT }),
    leave: { opacity: 0, height: 0, x: -14 },
    trail: 18,
    config: { tension: 320, friction: 30 },
  });

  return (
    <animated.aside
      style={mobile ? { transform: slide.x.to((v) => `translateX(${v}%)`) } : undefined}
      className="flex w-[264px] flex-none flex-col gap-3 border-r border-border bg-panel p-3 max-[720px]:fixed max-[720px]:inset-y-0 max-[720px]:left-0 max-[720px]:z-20 max-[720px]:shadow-lift"
    >
      <div className="flex items-center gap-2.5 px-1.5 pt-1">
        <LumioMark size={30} />
        <span className="font-display text-lg font-semibold">{APP_NAME}</span>
      </div>

      <PressButton
        type="button"
        onClick={onNew}
        hover={1.02}
        press={0.97}
        className={`flex items-center justify-center gap-2 rounded-xl bg-accent px-3.5 py-2.5 font-semibold text-on-accent hover:brightness-90 ${focus} focus-visible:outline-offset-2`}
      >
        <PlusIcon /> New chat
      </PressButton>

      <nav aria-label="Saved chats" className="-mx-1 flex flex-1 flex-col overflow-y-auto">
        {transitions((style, row) => (
          <animated.div
            style={{ opacity: style.opacity, height: style.height, x: style.x }}
            className="overflow-hidden"
          >
            {row.kind === "header" ? (
              <div className="flex h-full items-end px-3.5 pb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">
                {row.label}
              </div>
            ) : (
              <ChatRow
                chat={row.chat}
                active={row.chat.id === currentId}
                onOpen={onOpen}
                onRename={onRename}
                onDelete={onDelete}
              />
            )}
          </animated.div>
        ))}
      </nav>

      <PressButton
        type="button"
        onClick={onOpenSettings}
        press={0.97}
        className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-muted hover:bg-bubble hover:text-text ${focus}`}
      >
        <KeyIcon /> Providers
      </PressButton>

      <PressButton
        type="button"
        aria-label="Toggle theme"
        onClick={onToggleTheme}
        press={0.97}
        className={`flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-muted hover:bg-bubble hover:text-text ${focus}`}
      >
        <ThemeIcon theme={theme} />
        {theme === "dark" ? "Light mode" : "Dark mode"}
      </PressButton>
    </animated.aside>
  );
}

interface RowProps {
  chat: ChatSummary;
  active: boolean;
  onOpen: (id: string) => void;
  onRename: (chat: ChatSummary) => void;
  onDelete: (chat: ChatSummary) => void;
}

const iconBtn = `rounded-lg p-1.5 text-muted transition-colors duration-200 hover:bg-bubble ${focus}`;

function ChatRow({ chat, active, onOpen, onRename, onDelete }: RowProps) {
  return (
    <div
      className={`group relative mx-1 my-0.5 flex h-9 items-center gap-0.5 rounded-lg pl-2.5 pr-1.5 transition-colors ${
        active ? "bg-border" : "hover:bg-bubble"
      }`}
    >
      <button
        type="button"
        onClick={() => onOpen(chat.id)}
        title={chat.title}
        aria-current={active ? "page" : undefined}
        className={`flex-1 truncate rounded text-left ${active ? "font-medium" : ""} ${focus}`}
      >
        {chat.title}
      </button>
      <div
        className={`flex items-center gap-0.5 transition-opacity duration-200 ease-out min-[721px]:absolute min-[721px]:inset-y-0 min-[721px]:right-0 min-[721px]:rounded-r-lg min-[721px]:bg-gradient-to-l min-[721px]:to-transparent min-[721px]:pl-10 min-[721px]:pr-1.5 min-[721px]:opacity-0 min-[721px]:group-hover:opacity-100 min-[721px]:group-focus-within:opacity-100 ${
          active ? "min-[721px]:from-border min-[721px]:from-55%" : "min-[721px]:from-bubble min-[721px]:from-55%"
        }`}
      >
        <PressButton
          type="button"
          aria-label={`Rename ${chat.title}`}
          title="Rename"
          onClick={() => onRename(chat)}
          className={`${iconBtn} hover:text-text`}
        >
          <PencilIcon width={15} height={15} />
        </PressButton>
        <PressButton
          type="button"
          aria-label={`Delete ${chat.title}`}
          title="Delete"
          onClick={() => onDelete(chat)}
          className={`${iconBtn} hover:text-warn-bar`}
        >
          <TrashIcon width={15} height={15} />
        </PressButton>
      </div>
    </div>
  );
}
