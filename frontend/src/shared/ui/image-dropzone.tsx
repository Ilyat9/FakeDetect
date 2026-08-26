import { useCallback, useEffect, useRef, useState } from "react";

import { cn } from "./lib/cn";

export interface DroppedImage {
  file: File;
  previewUrl: string;
}

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp"];

export interface ImageDropzoneProps {
  label: string;
  value: DroppedImage | null;
  onChange: (image: DroppedImage | null) => void;
  /** Client-side validation BEFORE any upload hits the server. */
  maxBytes?: number;
}

function validate(file: File, maxBytes: number): string | null {
  if (!ACCEPTED_TYPES.includes(file.type)) {
    return "Поддерживаются только JPEG / PNG / WebP";
  }
  if (file.size > maxBytes) {
    return `Файл больше ${Math.round(maxBytes / 1024 / 1024)} МБ`;
  }
  return null;
}

/**
 * Reusable image input: drag & drop, click-to-browse AND clipboard paste
 * (Ctrl+V) — the fastest path for marketplace screenshots.
 */
export function ImageDropzone({
  label,
  value,
  onChange,
  maxBytes = 10 * 1024 * 1024,
}: ImageDropzoneProps) {
  const [error, setError] = useState<string | null>(null);
  const [isOver, setIsOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const accept = useCallback(
    (file: File | undefined | null) => {
      if (!file) return;
      const problem = validate(file, maxBytes);
      if (problem) {
        setError(problem);
        return;
      }
      setError(null);
      if (value) URL.revokeObjectURL(value.previewUrl);
      onChange({ file, previewUrl: URL.createObjectURL(file) });
    },
    [maxBytes, onChange, value],
  );

  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = Array.from(e.clipboardData?.files ?? []).find((f) =>
        f.type.startsWith("image/"),
      );
      if (item) accept(item);
    };
    document.addEventListener("paste", onPaste);
    return () => { document.removeEventListener("paste", onPaste); };
  }, [accept]);

  useEffect(
    () => () => {
      if (value) URL.revokeObjectURL(value.previewUrl);
    },
    [value],
  );

  return (
    <div>
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
        {label}
      </span>
      {value ? (
        <div className="relative overflow-hidden rounded-xl border border-line">
          {/* Explicit dimensions prevent layout shift while the preview loads. */}
          <img
            src={value.previewUrl}
            alt={`Предпросмотр: ${label}`}
            width={400}
            height={300}
            loading="lazy"
            decoding="async"
            className="max-h-48 w-full object-cover"
          />
          <button
            type="button"
            aria-label={`Удалить изображение ${label}`}
            onClick={() => {
              URL.revokeObjectURL(value.previewUrl);
              onChange(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
            className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-1 text-xs font-bold text-white hover:bg-black/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info"
          >
            ✕
          </button>
        </div>
      ) : (
        <div
          role="button"
          tabIndex={0}
          aria-label={`${label}: перетащите файл или нажмите для выбора`}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setIsOver(true);
          }}
          onDragLeave={() => { setIsOver(false); }}
          onDrop={(e) => {
            e.preventDefault();
            setIsOver(false);
            accept(e.dataTransfer.files[0]);
          }}
          className={cn(
            "flex h-36 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed text-center text-sm text-ink-muted transition-colors",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info",
            isOver ? "border-verdict-fake bg-verdict-fake/5" : "border-line hover:border-ink-muted",
          )}
        >
          <p className="font-semibold">Перетащите фото сюда</p>
          <p className="mt-1 text-xs">или кликните · Ctrl+V из буфера · JPEG/PNG/WebP до {Math.round(maxBytes / 1024 / 1024)} МБ</p>
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPTED_TYPES.join(",")}
        className="hidden"
        aria-hidden
        tabIndex={-1}
        onChange={(e) => { accept(e.target.files?.[0]); }}
      />
      {error && (
        <p role="alert" className="mt-1 text-xs text-verdict-fake">
          {error}
        </p>
      )}
    </div>
  );
}
