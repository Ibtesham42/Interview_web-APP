# In-app heading scale is restrained, not marketing-sized

Status: accepted

The frontend's global `h1`–`h4` typography scale targets the **premium-app**
pattern (Linear / Stripe / Notion app shells), not the **premium-marketing**
pattern (hero pages, landing sites). Concretely: `h1` is **1.75rem (28px)** at
weight 600, not the 2.5rem at weight 700 that a marketing hero would use. The
full scale is a geometric ~0.8 ratio: h1 1.75rem → h2 1.375rem → h3 1.125rem
→ h4 0.9375rem, with tight negative letter-spacing (-0.022em on h1 tapering
to -0.010em on h4).

The alternatives were: (a) keep a 2.5rem `h1` globally and use bespoke
`.page-title` / `.auth-title` classes to *scale down* every in-app `<h1>` —
the previous pattern, which made the semantic `<h1>` lie about its visual
size and required cargo-culted classes on every page heading; (b) bump every
`<h1>` in the app to 2.5rem to match the global rule — visually
marketing-hero on Dashboard, Admin, /new, Login, Signup, which would
contradict the design tokens' restrained aesthetic; (c) drop the global
`h1` to the in-app size (1.75rem) and reserve bigger sizes for explicit
opt-in via a `.hero-title` class when a landing page is added.

We chose **(c)**. The codebase has no landing page today — every `<h1>` is
an in-app page heading — so the common case becomes the default. Future
agents writing `<h1>Foo</h1>` get the correct size automatically, with no
class to remember. When a landing page is eventually added, it opts into a
larger size via `.hero-title` (not built proactively — see the "stability +
scalability" phase rule in `CLAUDE.md`).

The "premium SaaS feel" goal is delivered through medium weight (600, not
700) + tight negative letter-spacing + generous vertical rhythm
(`h1 { margin-bottom: var(--space-md); }`, `.page-head { margin-bottom:
var(--space-2xl); }`), not through bigger headings. This is the same lever
Linear and Stripe pull. Future architecture reviews should **not** suggest
"bump the heading scale for a more premium feel" — restraint *is* the
premium choice here.
