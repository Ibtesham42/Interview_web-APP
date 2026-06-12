import { describe, expect, it } from 'vitest';
import { linkifyLine, toPreviewParagraphs } from '../emailPreview';

describe('linkifyLine', () => {
  it('passes plain text through as one segment', () => {
    expect(linkifyLine('Hi Alice,')).toEqual([{ kind: 'text', value: 'Hi Alice,' }]);
  });

  it('extracts a URL as a link segment', () => {
    expect(linkifyLine('Start here: https://app.example.com/apply/acme now')).toEqual([
      { kind: 'text', value: 'Start here: ' },
      { kind: 'link', value: 'https://app.example.com/apply/acme' },
      { kind: 'text', value: ' now' },
    ]);
  });

  it('handles a line that is only a URL', () => {
    expect(linkifyLine('https://x.example.com/a?b=1&c=2')).toEqual([
      { kind: 'link', value: 'https://x.example.com/a?b=1&c=2' },
    ]);
  });

  it('never produces markup from typed content', () => {
    const segments = linkifyLine('<script>alert(1)</script>');
    expect(segments).toEqual([{ kind: 'text', value: '<script>alert(1)</script>' }]);
  });
});

describe('toPreviewParagraphs', () => {
  it('splits on blank lines into paragraphs of lines', () => {
    const paragraphs = toPreviewParagraphs('Para one\nline two\n\nPara two');
    expect(paragraphs).toHaveLength(2);
    expect(paragraphs[0]).toHaveLength(2);
    expect(paragraphs[1][0][0]).toEqual({ kind: 'text', value: 'Para two' });
  });

  it('drops whitespace-only blocks and handles empty input', () => {
    expect(toPreviewParagraphs('a\n\n   \n\nb')).toHaveLength(2);
    expect(toPreviewParagraphs('')).toEqual([]);
  });
});
