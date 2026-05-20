# Frontend Engineering Standards

## Core Principles

- **TypeScript-first**: All components, hooks, and services must be fully typed. No `any` types.
- **Component isolation**: Each component owns its state. Lift state only when genuinely shared.
- **Import order**: External libs → Internal services → Components → Types → Hooks
- **No inline styles for layout**: Use CSS classes. Inline only for dynamic values.

## React Patterns

### Hooks
```
useXxx() → returns object with state + callbacks
useXxx() → returns [state, actions] only if tuple pattern adds clarity
```
- Custom hooks encapsulate side effects and state
- Prefer composition over prop drilling
- Use `useCallback` for event handlers passed to memoized children

### Component Structure
```tsx
// Imports
// Types (inline or imported)
// Component definition
// - early returns for loading/error/empty
// - main render with clear sections
// - tail: modals, tooltips, portals
// Export
```

### State Management
- Local state: `useState` for component-only data
- Shared state: React Context for truly global (auth, theme)
- Server state: Not using React Query yet - prefer custom fetch hooks
- Avoid: global state for transient UI data

## File Organization

```
src/
├── components/     # Dumb UI components
├── hooks/         # Custom hooks (useXxx.ts)
├── services/      # API clients, WebSocket
├── types/         # TypeScript definitions
└── utils/         # Pure functions
```

## Build & Deployment

- Vite for dev server and builds
- Environment variables via `import.meta.env`
- Build output must be < 250KB gzipped (excluding vendor)
- No heavy animation libraries - CSS only

## Code Standards

- No default exports for components (named exports only)
- Props interface: `interface ComponentNameProps { ... }`
- Event handlers: `handleXxx` prefix for handlers, `onXxx` for props
- Early returns for conditionals (loading, error, empty)
- No magic numbers - use CSS variables or named constants
- Responsive: mobile-first, use relative units (rem, %, dvh)

## Testing Philosophy

- Unit tests for hooks and utilities
- Integration tests for critical flows (upload, voice submit)
- No shallow rendering - test actual DOM
- Prefer user-facing test IDs over CSS selectors