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

export const PlusIcon = icon(<path d="M12 5v14M5 12h14" />);
export const ChevronDownIcon = icon(<path d="m6 9 6 6 6-6" />);
export const SendIcon = icon(<path d="M12 19V5M5 12l7-7 7 7" />);
export const StopIcon = icon(<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" />);
export const GlobeIcon = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
  </>,
);
export const ImageIcon = icon(
  <>
    <rect x="3" y="4" width="18" height="16" rx="2.5" />
    <circle cx="9" cy="10" r="1.6" />
    <path d="m21 16-5-5-8 9" />
  </>,
);
export const PaperclipIcon = icon(
  <path d="m21 11.5-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9" />,
);
export const SparklesIcon = icon(
  <path d="M10 4l1.8 4.7L16.5 10.5l-4.7 1.8L10 17l-1.8-4.7L3.5 10.5l4.7-1.8zM18 3v4M16 5h4M18 15v4M16 17h4" />,
);
export const PlayIcon = icon(<path d="M7 5v14l12-7z" fill="currentColor" />);
export const SpinnerIcon = icon(<path d="M21 12a9 9 0 1 1-6.2-8.55" />);
export const CloseIcon = icon(<path d="M6 6l12 12M18 6 6 18" />);
export const MenuIcon = icon(<path d="M4 7h16M4 12h16M4 17h16" />);
export const PencilIcon = icon(<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />);
export const TrashIcon = icon(<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" />);
export const KeyIcon = icon(
  <>
    <circle cx="8" cy="15" r="4" />
    <path d="M11 12l9-9M16 7l3 3" />
  </>,
);
export const BookIcon = icon(<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5zM4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5" />);
export const CopyIcon = icon(
  <>
    <rect x="9" y="9" width="11" height="11" rx="2.5" />
    <path d="M5 15V6.5A2.5 2.5 0 0 1 7.5 4H15" />
  </>,
);
export const CheckIcon = icon(<path d="m5 12.5 4.5 4.5L19 7.5" />);
export const MoonIcon = icon(<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />);
export const SunIcon = icon(
  <>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </>
);

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
