# Frontend — Claude Instructions

Always read these skill files before any frontend task:
- .claude/Skills/frontend.md
- .claude/Skills/ui-ux.md
- .claude/Skills/accessibility.md
- .claude/Skills/performance.md
- .claude/Skills/realtime.md
- .claude/Skills/voice-ai.md
- .claude/Skills/product-thinking.md

## Stack
React + TypeScript + Vite + Tailwind

## Standards

### Components
- Named exports only
- Props interface: `interface ComponentNameProps {}`
- Event handlers: handleXxx (internal), onXxx (props)
- Early returns for loading / error / empty states
- Dumb UI components, smart custom hooks

### Hooks
- All side effects and state in custom hooks (useXxx)
- useCallback for handlers passed to memoized children
- useMemo for derived data

### Styling
- Tailwind or existing design system only
- No inline layout styles
- Mobile-first, relative units (rem, %, dvh)
- CSS variables for spacing, color, radius (see ui-ux.md)

### TypeScript
- No `any` types
- Strict mode on
- All components, hooks, services fully typed

### State
- Local: useState for component-only data
- Global: React Context for auth/theme only
- Server: custom fetch hooks (no React Query yet)

## UI Philosophy (from ui-ux.md)
- Dark theme primary: #0d0d0f base
- Font: Inter
- No gradients, no glows, no mesh effects
- Min touch targets: 44x44px
- Animations: 120-300ms, ease, purpose-only

## Performance (from performance.md)
- Bundle: < 250KB gzipped (excluding vendor)
- 60fps animations (transform/opacity only)
- Memoize expensive components
- Debounce rapid events

## Voice UI (from voice-ai.md)
- Sample rate: 16000Hz, mono, webm/opus
- Show audio level in real-time
- States: Listening → Speech detected → Processing
- No auto-stop — user controls recording
- Visual fallback when mic denied

## Accessibility (from accessibility.md)
- WCAG 2.1 AA
- All interactive elements keyboard accessible
- Focus visible: 3px outline
- Logical tab order
- aria-label for icon buttons
- aria-live for transcript/dynamic content
- Respect prefers-reduced-motion

## WebSocket (from realtime.md)
- Single connection per interview session
- Auto-reconnect: max 3 attempts, exponential backoff (1s → 2s → 4s)
- Message queue during reconnection
- WebSocket messages are source of truth for state
