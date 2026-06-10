import { forwardRef } from 'react';
import type {
  InputHTMLAttributes,
  ReactNode,
  TextareaHTMLAttributes,
} from 'react';

const CONTROL_BASE =
  'w-full rounded-md border bg-field px-3 py-2 text-sm text-ink shadow-sm ' +
  'placeholder:text-ink-subtle transition-colors ' +
  'focus:outline-none focus:border-focus focus:shadow-focus ' +
  'disabled:opacity-50 disabled:cursor-not-allowed';

function controlClasses(hasError: boolean, extra = ''): string {
  return [CONTROL_BASE, hasError ? 'border-danger-border' : 'border-strong', extra]
    .filter(Boolean)
    .join(' ');
}

interface FieldProps {
  label: string;
  htmlFor: string;
  /** Helper text shown below the control when there is no error. */
  hint?: string;
  /** Error text — replaces the hint and flags the control state. */
  error?: string;
  required?: boolean;
  children: ReactNode;
}

/**
 * Label + control + hint/error layout wrapper. Pass any control as children
 * (or use <Input>/<Textarea> below). Keeps form rows visually consistent and
 * wires the accessible description.
 */
export function Field({ label, htmlFor, hint, error, required, children }: FieldProps) {
  const describedBy = error ? `${htmlFor}-error` : hint ? `${htmlFor}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
        {label}
        {required && <span className="ml-0.5 text-danger">*</span>}
      </label>
      <div aria-describedby={describedBy}>{children}</div>
      {error ? (
        <p id={`${htmlFor}-error`} className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p id={`${htmlFor}-hint`} className="text-xs text-ink-subtle">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  hasError?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ hasError = false, className = '', ...rest }, ref) => (
    <input ref={ref} className={controlClasses(hasError, className)} {...rest} />
  ),
);
Input.displayName = 'Input';

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  hasError?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ hasError = false, className = '', ...rest }, ref) => (
    <textarea ref={ref} className={controlClasses(hasError, `resize-y ${className}`)} {...rest} />
  ),
);
Textarea.displayName = 'Textarea';
