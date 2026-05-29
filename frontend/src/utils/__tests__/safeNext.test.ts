import { describe, expect, it } from 'vitest';
import { safeNext } from '../safeNext';

describe('safeNext', () => {
  it('returns same-origin path unchanged', () => {
    expect(safeNext('/companies/signup')).toBe('/companies/signup');
    expect(safeNext('/dashboard')).toBe('/dashboard');
    expect(safeNext('/recruiter/candidates/abc')).toBe('/recruiter/candidates/abc');
  });

  it('falls back to / on null or empty', () => {
    expect(safeNext(null)).toBe('/');
    expect(safeNext(undefined)).toBe('/');
    expect(safeNext('')).toBe('/');
  });

  it('rejects protocol-relative URLs (open-redirect attack)', () => {
    // `navigate('//evil.example.com/x')` would send the user off-origin.
    expect(safeNext('//evil.example.com/path')).toBe('/');
    expect(safeNext('//evil.example.com')).toBe('/');
  });

  it('rejects absolute URLs', () => {
    expect(safeNext('http://evil.example.com/x')).toBe('/');
    expect(safeNext('https://evil.example.com/x')).toBe('/');
  });

  it('rejects relative paths that do not start with /', () => {
    expect(safeNext('companies/signup')).toBe('/');
    expect(safeNext('../etc/passwd')).toBe('/');
    expect(safeNext('javascript:alert(1)')).toBe('/');
  });

  it('preserves query strings and hashes on safe paths', () => {
    // The signup flow passes ?company=slug through; we shouldn't strip
    // intra-app query strings out of next-redirects.
    expect(safeNext('/companies/signup?source=login')).toBe('/companies/signup?source=login');
    expect(safeNext('/dashboard#tab=history')).toBe('/dashboard#tab=history');
  });
});
