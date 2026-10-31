import {
  ArrowUp,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Globe,
  Image as ImageGlyph,
  KeyRound,
  LogOut,
  Menu,
  Moon,
  Paperclip,
  Pencil,
  Play,
  Plug,
  Plus,
  Sparkles,
  Sun,
  Trash2,
  User,
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
export const BookIcon = lucide(BookOpen);
export const CopyIcon = lucide(Copy);
export const CheckIcon = lucide(Check);
export const MoonIcon = lucide(Moon);
export const SunIcon = lucide(Sun);
export const UserIcon = lucide(User);
export const KeyIcon = lucide(KeyRound);
export const LogOutIcon = lucide(LogOut);
export const ChevronUpIcon = lucide(ChevronUp);

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
