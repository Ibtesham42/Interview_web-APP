import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type ToastVariant = 'neutral' | 'success' | 'warning' | 'danger' | 'info';

interface ToastInput {
  title: string;
  description?: string;
  variant?: ToastVariant;
  /** Auto-dismiss delay in ms. 0 keeps it until dismissed. Default 5000. */
  duration?: number;
}

interface ToastItem extends Required<Omit<ToastInput, 'description'>> {
  id: string;
  description?: string;
}

interface ToastContextValue {
  toast: (input: ToastInput) => void;
  dismiss: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

const DOT: Record<ToastVariant, string> = {
  neutral: 'bg-ink-subtle',
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
};

/**
 * App-wide success/error feedback. Replaces the scattered ad-hoc inline
 * banners with one consistent, non-blocking pattern. Mount <ToastProvider>
 * once near the root; call `useToast().toast({ title, variant })` anywhere.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  const dismiss = useCallback((id: string) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
    const handle = timers.current[id];
    if (handle) {
      clearTimeout(handle);
      delete timers.current[id];
    }
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      const id =
        typeof crypto !== 'undefined' && 'randomUUID' in crypto
          ? crypto.randomUUID()
          : String(Date.now() + Math.random());
      const item: ToastItem = {
        id,
        title: input.title,
        description: input.description,
        variant: input.variant ?? 'neutral',
        duration: input.duration ?? 5000,
      };
      setItems((prev) => [...prev, item]);
      if (item.duration > 0) {
        timers.current[id] = setTimeout(() => dismiss(id), item.duration);
      }
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ toast, dismiss }}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[200] flex w-[min(92vw,360px)] flex-col gap-2"
        role="region"
        aria-label="Notifications"
      >
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className="pointer-events-auto flex items-start gap-3 rounded-lg border border-subtle bg-elevated p-3 shadow-lg animate-[surface-in_200ms_ease]"
          >
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[t.variant]}`} />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink">{t.title}</p>
              {t.description && <p className="mt-0.5 text-xs text-ink-muted">{t.description}</p>}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className="shrink-0 text-ink-subtle transition-colors hover:text-ink"
            >
              ✕
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within a ToastProvider');
  return ctx;
}
