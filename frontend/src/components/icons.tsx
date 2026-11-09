import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  CircleAlert,
  Copy,
  Globe,
  Image as ImageGlyph,
  Info,
  KeyRound,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  Paperclip,
  Pencil,
  Play,
  Plug,
  Plus,
  RefreshCw,
  Sparkles,
  Sun,
  Trash2,
  X,
  type LucideIcon,
  type LucideProps,
} from "lucide-react";
import type { ReactNode, SVGProps } from "react";

function icon(paths: ReactNode) {
  return function Icon(props: SVGProps<SVGSVGElement>) {
    return (
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        {...props}
      >
        {paths}
      </svg>
    );
  };
}

// Lucide draws at stroke 2; the hand-drawn icons that remain use 1.8, so the set stays even.
const lucide = (Glyph: LucideIcon, defaults: LucideProps = {}) =>
  function Icon(props: LucideProps) {
    return <Glyph size={18} strokeWidth={1.8} aria-hidden="true" {...defaults} {...props} />;
  };

export const PlusIcon = lucide(Plus);
export const ChevronDownIcon = lucide(ChevronDown);
export const SendIcon = lucide(ArrowUp);
export const GlobeIcon = lucide(Globe);
export const ImageIcon = lucide(ImageGlyph);
export const PaperclipIcon = lucide(Paperclip);
export const SparklesIcon = lucide(Sparkles);
export const PlayIcon = lucide(Play, { fill: "currentColor" });
export const CloseIcon = lucide(X);
export const MenuIcon = lucide(Menu);
export const PencilIcon = lucide(Pencil);
export const TrashIcon = lucide(Trash2);
export const PlugIcon = lucide(Plug);
export const RefreshIcon = lucide(RefreshCw);
export const BookIcon = lucide(BookOpen);
export const CopyIcon = lucide(Copy);
export const CheckIcon = lucide(Check);
export const MoonIcon = lucide(Moon);
export const SunIcon = lucide(Sun);
export const KeyIcon = lucide(KeyRound);
export const LogOutIcon = lucide(LogOut);
export const ChevronUpIcon = lucide(ChevronUp);
export const AlertIcon = lucide(CircleAlert);
export const InfoIcon = lucide(Info);

// Brand marks are filled single-colour glyphs, so they follow the theme's text colour.
export function GoogleIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M12.48 10.92v3.28h7.84c-.24 1.84-.853 3.187-1.787 4.133-1.147 1.147-2.933 2.4-6.053 2.4-4.827 0-8.6-3.893-8.6-8.72s3.773-8.72 8.6-8.72c2.6 0 4.507 1.027 5.907 2.347l2.307-2.307C18.747 1.44 16.133 0 12.48 0 5.867 0 .307 5.387.307 12s5.56 12 12.173 12c3.573 0 6.267-1.173 8.373-3.36 2.16-2.16 2.84-5.213 2.84-7.667 0-.76-.053-1.467-.173-2.053H12.48z" />
    </svg>
  );
}

export function GitHubIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" {...props}>
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

// Filled square and a spinner arc: Lucide has no equivalents that read as well at 11px.
export const StopIcon = icon(<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />);
export const SpinnerIcon = icon(<path d="M21 12a9 9 0 1 1-6.2-8.55" />);

// An "L" whose stroke ends at a lit dot: the light in Lumio.
export function LumioMark({ size = 32, ...props }: SVGProps<SVGSVGElement> & { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" {...props}>
      <defs>
        <linearGradient id="lumio-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3f8570" />
          <stop offset="1" stopColor="#235242" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#lumio-mark)" />
      <path
        d="M11 8v12.5a2.5 2.5 0 0 0 2.5 2.5H20"
        fill="none"
        stroke="#fdfbf6"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="21.5" cy="11" r="2.6" fill="#fdfbf6" />
    </svg>
  );
}
export const ChatIcon = lucide(MessageSquare);
