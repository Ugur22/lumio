import { useRef, useState } from "react";
import { ImageLightbox } from "./ImageLightbox";

// Images are pruned after a while; the server then answers 410 and the chat keeps a placeholder.
export function AttachedImage({ url, label }: { url: string; label: string }) {
  const [expired, setExpired] = useState(false);
  const [open, setOpen] = useState(false);
  const thumb = useRef<HTMLButtonElement>(null);

  if (expired) {
    return (
      <span className="grid h-28 w-28 place-items-center rounded-xl border border-dashed border-border px-2 text-center text-[12px] text-muted">
        Image no longer stored
      </span>
    );
  }
  return (
    <>
      <button
        ref={thumb}
        type="button"
        aria-label={`View ${label.toLowerCase()} full size`}
        title="View full size"
        onClick={() => setOpen(true)}
        // Hidden while the lightbox shows it, so the image looks lifted off the page rather than copied.
        className={`block cursor-zoom-in rounded-xl focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
          open ? "invisible" : ""
        }`}
      >
        <img
          src={url}
          alt={label}
          onError={() => setExpired(true)}
          className="max-h-48 max-w-full rounded-xl border border-border object-cover shadow-soft sm:max-h-56"
        />
      </button>
      {open && (
        <ImageLightbox
          src={url}
          alt={label}
          getOrigin={() => {
            const el = thumb.current;
            if (!el) return null;
            const bounds = el.closest("[data-image-bounds]")?.getBoundingClientRect() ?? null;
            return { thumb: el.getBoundingClientRect(), bounds };
          }}
          onClose={() => {
            setOpen(false);
            // preventScroll: refocusing a partly hidden thumbnail must not scroll the chat.
            thumb.current?.focus({ preventScroll: true });
          }}
        />
      )}
    </>
  );
}
