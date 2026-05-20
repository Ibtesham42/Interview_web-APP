# Accessibility Standards

## WCAG Compliance

- **Target**: WCAG 2.1 AA
- **Minimum**: All interactive elements keyboard accessible
- **Color contrast**: 4.5:1 for text, 3:1 for large text

## Keyboard Navigation

### Requirements
- All buttons/links keyboard accessible (Tab/Enter/Space)
- Logical tab order (visual = DOM order)
- Focus visible: 3px outline on focus
- No keyboard traps

### Focus Management
- Focus moves to relevant element on modal open
- Focus returns to trigger on modal close
- Skip links for main content

## Screen Reader

### Semantic HTML
- Use native elements: button, nav, main, section
- Avoid div soup - use appropriate ARIA roles
- Headings: h1 → h2 → h3 (no skipping levels)

### ARIA
- Only when native HTML insufficient
- aria-label for icon buttons without text
- aria-live for dynamic content (transcripts)

### Form Accessibility
- Labels associated with inputs (htmlFor or nesting)
- Error messages linked to fields
- Required fields marked visually and semantically

## Touch Targets

- **Minimum size**: 44x44px
- **Spacing**: 8px between adjacent targets
- **No small tap targets in lists**

## Visual Accessibility

### Color
- Don't rely on color alone for information
- Pair color with icons/text/borders
- Check contrast in both light and dark themes

### Motion
- Respect prefers-reduced-motion
- No auto-playing animations
- Pausable animations in interview

## Voice Interface Accessibility

- Visual feedback for audio states
- Transcript always visible (not just audio)
- Manual stop recording option
- Clear "recording" indicator

## Testing

- Keyboard-only navigation weekly
- Browser developer tools accessibility audit
- Automated: axe-core or similar
- Manual: regular screen reader testing