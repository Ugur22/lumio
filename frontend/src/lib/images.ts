import type { ImageUpload } from "../types";

export const MAX_IMAGES = 4;
// Vision models downscale anyway, so a larger image only costs upload time and storage.
export const MAX_EDGE = 1568;
const JPEG_QUALITY = 0.85;
const ACCEPTED = ["image/png", "image/jpeg", "image/webp", "image/gif"];

export const ACCEPT_ATTR = ACCEPTED.join(",");

export interface Attachment {
  id: string;
  // An object URL for the thumbnail; whoever drops the attachment must revoke it.
  preview: string;
  upload: ImageUpload;
}

export function fitWithin(width: number, height: number, max = MAX_EDGE): { width: number; height: number } {
  const scale = Math.min(1, max / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

// Returns the reason a file can't be attached, or null when it can.
export function rejectReason(file: File, current: number): string | null {
  if (!ACCEPTED.includes(file.type)) return `${file.name || "That file"} isn't a PNG, JPEG, WebP or GIF image.`;
  if (current >= MAX_IMAGES) return `You can attach up to ${MAX_IMAGES} images per message.`;
  return null;
}

// Re-encoding as JPEG keeps every upload small and gives the server a single well-known format.
export async function prepareImage(file: File): Promise<Attachment> {
  const bitmap = await createImageBitmap(file);
  try {
    const { width, height } = fitWithin(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Could not read that image");
    // JPEG has no alpha; without a backdrop transparent PNGs turn black.
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(bitmap, 0, 0, width, height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", JPEG_QUALITY));
    if (!blob) throw new Error("Could not read that image");
    return {
      id: crypto.randomUUID(),
      preview: URL.createObjectURL(blob),
      upload: { media_type: "image/jpeg", data: await toBase64(blob) },
    };
  } finally {
    bitmap.close();
  }
}

async function toBase64(blob: Blob): Promise<string> {
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  // Chunked: spreading a whole image into String.fromCharCode overflows the call stack.
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
}
