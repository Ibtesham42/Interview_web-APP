// Client-side draft persistence for the email composer ("Save Draft").
// No server-side draft store exists (the /email/draft endpoints render
// *templates*, they don't persist edits), so drafts live in localStorage:
// per-browser, which fits the composer's per-recruiter editing model.
// Every operation is try/catch'd — storage being full/blocked must never
// break composing.

export interface SavedEmailDraft {
  to?: string;
  subject: string;
  body: string;
  savedAt: string;
}

const PREFIX = 'email-draft:';

export function saveEmailDraft(
  key: string,
  draft: { to?: string; subject: string; body: string },
): SavedEmailDraft | null {
  const record: SavedEmailDraft = { ...draft, savedAt: new Date().toISOString() };
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(record));
    return record;
  } catch {
    return null;
  }
}

export function loadEmailDraft(key: string): SavedEmailDraft | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SavedEmailDraft;
    if (typeof parsed.subject !== 'string' || typeof parsed.body !== 'string') {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function clearEmailDraft(key: string): void {
  try {
    localStorage.removeItem(PREFIX + key);
  } catch {
    // Nothing useful to do — the draft will be overwritten next save.
  }
}
