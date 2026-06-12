// Pure helpers for the composer's Preview mode. The preview mirrors the
// backend's render_email_html (paragraphs, line breaks, clickable links)
// but builds a SEGMENT STRUCTURE for React to render natively — never an
// HTML string, so recruiter-typed content can't become live markup.

export interface PreviewSegment {
  kind: 'text' | 'link';
  value: string;
}

export type PreviewLine = PreviewSegment[];
export type PreviewParagraph = PreviewLine[];

const URL_RE = /(https?:\/\/[^\s<>"]+)/g;

/** Split one line into text/link segments. */
export function linkifyLine(line: string): PreviewLine {
  const segments: PreviewLine = [];
  let last = 0;
  for (const match of line.matchAll(URL_RE)) {
    const index = match.index ?? 0;
    if (index > last) segments.push({ kind: 'text', value: line.slice(last, index) });
    segments.push({ kind: 'link', value: match[0] });
    last = index + match[0].length;
  }
  if (last < line.length) segments.push({ kind: 'text', value: line.slice(last) });
  return segments;
}

/**
 * Body text → paragraphs (blank-line separated) → lines → segments.
 * Mirrors the backend HTML derivation 1:1 so what the sender previews is
 * what the recipient's mail client shows.
 */
export function toPreviewParagraphs(body: string): PreviewParagraph[] {
  return (body || '')
    .split(/\n\s*\n/)
    .filter((block) => block.trim().length > 0)
    .map((block) => block.split('\n').map(linkifyLine));
}
