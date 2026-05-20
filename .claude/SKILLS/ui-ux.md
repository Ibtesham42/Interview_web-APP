# UI/UX Design Standards

## Design Philosophy

- **Understated premium**: No flashy gradients, no glow effects, no AI aesthetic
- **Human-crafted feel**: Intentional spacing, refined typography, subtle interactions
- **Calm authority**: Trust through competence, not through visual noise

## Color System

### Dark Theme (Primary)
```
--bg-primary: #0d0d0f      // Deep black
--bg-secondary: #141416    // Card backgrounds
--bg-tertiary: #1a1a1d    // Elevated surfaces
--bg-input: #18181c       // Form fields
```
### Contrast Rules
- Text: #FFFFFF for primary, #A1A1AA for secondary, #71717A for tertiary
- Never use color alone for state - combine with shape/position
- Focus states: 3px outline, not just color change

### Accent Colors
```
--primary: #4f46e5        // Indigo - main brand
--accent-green: #059669  // Success, positive states
--accent-amber: #d97706  // Warnings, holds
--accent-rose: #dc2626   // Errors, destructive
```

## Typography

- **Font**: Inter (system fallback: -apple-system, BlinkMacSystemFont, Segoe UI)
- **Scale**: 12px / 14px / 15px / 16px / 18px / 20px / 24px / 32px / 48px
- **Line height**: 1.5 for body, 1.25 for headings
- **Letter spacing**: -0.02em for headings, normal for body

## Spacing System

```
--space-xs: 0.25rem   // 4px
--space-sm: 0.5rem   // 8px
--space-md: 1rem     // 16px
--space-lg: 1.5rem   // 24px
--space-xl: 2rem     // 32px
--space-2xl: 3rem   // 48px
```
- Components use spacing variables, not ad-hoc values
- Consistent padding within component types

## Component Standards

### Cards
- Background: --bg-secondary
- Border: 1px solid --border-subtle (rgba(255,255,255,0.06))
- Border-radius: 12px (--radius-lg)
- No shadows on dark theme (use subtle borders instead)

### Buttons
- Min height: 44px (touch target)
- Padding: 0.625rem 1.25rem
- Border-radius: 8px
- States: default → hover → active → disabled
- No gradient backgrounds

### Forms
- Input height: 44px minimum
- Border: 1px solid --border-default
- Focus: --border-focus with box-shadow
- Select dropdowns: explicit color in all states (Firefox bug)

### Animations
- Duration: 120ms (fast), 200ms (normal), 300ms (slow)
- Easing: ease, not bezier curves
- Purpose: feedback only, not decoration
- No keyframes for hover states - use transitions

## Layout Breakpoints

```
360px   // Very small mobile
480px   // Mobile portrait
640px   // Mobile landscape
768px   // Tablet portrait
1024px  // Tablet landscape / small laptop
1440px  // Laptop
1600px+ // Ultrawide
```

## Interactions

- Touch targets: min 44x44px
- Hover states: subtle background shift, not dramatic color changes
- Focus: visible 3px outline
- Loading: spinner with text, no skeleton screens
- Errors: inline validation, not alert dialogs

## Realism Standards

- No "AI-generated" aesthetic indicators:
  - No mesh gradients
  - No glowing borders
  - No excessive blur effects
  - No emoji-heavy interfaces
  - No template-like layouts
- Professional, enterprise-grade only