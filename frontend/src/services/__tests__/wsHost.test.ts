import { afterEach, describe, expect, it, vi } from 'vitest';
import { normalizeWsHost } from '../wsHost';

describe('normalizeWsHost', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('falls back to ws://localhost:8000 when input is undefined', () => {
    expect(normalizeWsHost(undefined)).toBe('ws://localhost:8000');
  });

  it('falls back to ws://localhost:8000 when input is empty', () => {
    expect(normalizeWsHost('')).toBe('ws://localhost:8000');
  });

  it('falls back to ws://localhost:8000 when input is whitespace only', () => {
    expect(normalizeWsHost('   ')).toBe('ws://localhost:8000');
  });

  it('passes a clean wss URL through unchanged', () => {
    expect(normalizeWsHost('wss://interview-web-app.onrender.com')).toBe(
      'wss://interview-web-app.onrender.com',
    );
  });

  it('strips surrounding whitespace and trailing newlines', () => {
    expect(normalizeWsHost('  wss://host.example.com\n')).toBe(
      'wss://host.example.com',
    );
  });

  it('strips a trailing slash', () => {
    expect(normalizeWsHost('wss://host.example.com/')).toBe(
      'wss://host.example.com',
    );
  });

  it('strips multiple trailing slashes', () => {
    expect(normalizeWsHost('wss://host.example.com///')).toBe(
      'wss://host.example.com',
    );
  });

  it('rewrites https:// to wss://', () => {
    expect(normalizeWsHost('https://host.example.com')).toBe(
      'wss://host.example.com',
    );
  });

  it('rewrites http:// to ws://', () => {
    expect(normalizeWsHost('http://localhost:8000')).toBe(
      'ws://localhost:8000',
    );
  });

  it('rewrites HTTPS:// case-insensitively', () => {
    expect(normalizeWsHost('HTTPS://Host.Example.com')).toBe(
      'wss://Host.Example.com',
    );
  });

  it('de-duplicates a host that was pasted twice', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(normalizeWsHost('wss://host.example.comwss://host.example.com')).toBe(
      'wss://host.example.com',
    );
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('de-duplicates when the inner scheme is uppercased', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(normalizeWsHost('wss://host.example.comWSS://host.example.com')).toBe(
      'wss://host.example.com',
    );
    expect(warn).toHaveBeenCalledTimes(1);
  });

  it('does not warn when the URL is clean', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    normalizeWsHost('wss://host.example.com');
    expect(warn).not.toHaveBeenCalled();
  });

  it('strips a trailing slash then de-duplicates', () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    expect(normalizeWsHost('wss://host.example.com/wss://host.example.com/')).toBe(
      'wss://host.example.com',
    );
  });
});
