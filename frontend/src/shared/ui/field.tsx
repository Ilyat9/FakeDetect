import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import { useId } from "react";

import { cn } from "./lib/cn";

const FIELD_CLASS =
  "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-muted/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-verdict-info disabled:opacity-50";

export function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-widest text-ink-muted">
        {label}
      </span>
      {children}
      {error && (
        <span role="alert" className="mt-1 block text-xs text-verdict-fake">
          {error}
        </span>
      )}
    </label>
  );
}

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export function Input({ label, error, id, className, ...rest }: InputProps) {
  const autoId = useId();
  return (
    <Field label={label} error={error}>
      <input id={id ?? autoId} className={cn(FIELD_CLASS, className)} {...rest} />
    </Field>
  );
}

export interface TextAreaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  error?: string;
}

export function TextArea({ label, error, id, className, ...rest }: TextAreaProps) {
  const autoId = useId();
  return (
    <Field label={label} error={error}>
      <textarea id={id ?? autoId} rows={3} className={cn(FIELD_CLASS, className)} {...rest} />
    </Field>
  );
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  options: readonly { value: string; label: string }[];
  error?: string;
}

export function Select({ label, options, error, id, className, ...rest }: SelectProps) {
  const autoId = useId();
  return (
    <Field label={label} error={error}>
      <select id={id ?? autoId} className={cn(FIELD_CLASS, className)} {...rest}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </Field>
  );
}
