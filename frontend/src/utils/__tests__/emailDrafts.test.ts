import { beforeEach, describe, expect, it } from 'vitest';
import { clearEmailDraft, loadEmailDraft, saveEmailDraft } from '../emailDrafts';

// Vitest runs in the node environment (no DOM) — install a minimal
// in-memory localStorage so the storage helpers exercise their real paths.
function installLocalStorageMock() {
  const store = new Map<string, string>();
  (globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
    clear: () => store.clear(),
  };
}

describe('email draft storage', () => {
  beforeEach(() => {
    installLocalStorageMock();
  });

  it('round-trips a saved draft', () => {
    saveEmailDraft('recruiter:c1:shortlist', {
      to: 'a@example.com',
      subject: 'Edited subject',
      body: 'Edited body',
    });
    const loaded = loadEmailDraft('recruiter:c1:shortlist');
    expect(loaded?.subject).toBe('Edited subject');
    expect(loaded?.body).toBe('Edited body');
    expect(loaded?.savedAt).toBeTruthy();
  });

  it('returns null for a missing key', () => {
    expect(loadEmailDraft('recruiter:nope:shortlist')).toBeNull();
  });

  it('returns null for corrupt storage instead of throwing', () => {
    localStorage.setItem('email-draft:bad', '{not json');
    expect(loadEmailDraft('bad')).toBeNull();
    localStorage.setItem('email-draft:wrong-shape', JSON.stringify({ subject: 1 }));
    expect(loadEmailDraft('wrong-shape')).toBeNull();
  });

  it('clear removes the draft', () => {
    saveEmailDraft('k', { subject: 's', body: 'b' });
    clearEmailDraft('k');
    expect(loadEmailDraft('k')).toBeNull();
  });

  it('keys are namespaced per candidate + template', () => {
    saveEmailDraft('recruiter:c1:shortlist', { subject: 'one', body: 'x' });
    saveEmailDraft('recruiter:c1:rejection', { subject: 'two', body: 'y' });
    expect(loadEmailDraft('recruiter:c1:shortlist')?.subject).toBe('one');
    expect(loadEmailDraft('recruiter:c1:rejection')?.subject).toBe('two');
  });
});
