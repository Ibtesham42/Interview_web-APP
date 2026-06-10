import { useState, type ReactNode } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { useTheme } from '../../contexts/ThemeContext';
import { ActingAsPicker } from '../admin/ActingAsPicker';
import type { UserRole } from '../../types';

const PRODUCT_NAME = 'Rehearsify';

/* Brand mark — kept from the existing identity, refined. */
function BrandMark() {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-md border border-primary-subtle bg-surface-2">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <circle cx="9" cy="12" r="6" fill="var(--primary)" />
          <circle cx="15" cy="12" r="6" fill="var(--accent)" opacity="0.85" />
        </svg>
      </span>
      <span className="text-sm font-semibold tracking-tight text-ink">{PRODUCT_NAME}</span>
    </Link>
  );
}

/* Minimal line icons (no icon dependency) — simple, robust shapes. */
function NavIcon({ name }: { name: string }) {
  const common = {
    width: 18,
    height: 18,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };
  switch (name) {
    case 'overview':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="9" rx="1.5" />
          <rect x="14" y="3" width="7" height="5" rx="1.5" />
          <rect x="14" y="12" width="7" height="9" rx="1.5" />
          <rect x="3" y="16" width="7" height="5" rx="1.5" />
        </svg>
      );
    case 'candidates':
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3" />
          <path d="M4 20c0-3 2.5-5 5-5s5 2 5 5" />
          <path d="M16 11a3 3 0 100-6" />
          <path d="M20 20c0-2.5-1.5-4.3-3.5-4.8" />
        </svg>
      );
    case 'analytics':
      return (
        <svg {...common}>
          <path d="M4 20V11" />
          <path d="M10 20V4" />
          <path d="M16 20v-6" />
          <path d="M3 20h18" />
        </svg>
      );
    case 'settings':
      return (
        <svg {...common}>
          <line x1="4" y1="7" x2="20" y2="7" />
          <circle cx="9" cy="7" r="2" />
          <line x1="4" y1="17" x2="20" y2="17" />
          <circle cx="15" cy="17" r="2" />
        </svg>
      );
    case 'dashboard':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="8" height="8" rx="1.5" />
          <rect x="13" y="3" width="8" height="5" rx="1.5" />
          <rect x="13" y="10" width="8" height="11" rx="1.5" />
          <rect x="3" y="13" width="8" height="8" rx="1.5" />
        </svg>
      );
    case 'new':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="9" />
          <line x1="12" y1="8" x2="12" y2="16" />
          <line x1="8" y1="12" x2="16" y2="12" />
        </svg>
      );
    default:
      return null;
  }
}

interface NavItem {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
}

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  [
    'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
    isActive
      ? 'bg-primary-subtle text-primary'
      : 'text-ink-muted hover:bg-surface-2 hover:text-ink',
  ].join(' ');

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const { user, profile, company, signOut, can } = useAuth();
  const navigate = useNavigate();
  const role = (profile?.role as UserRole | undefined) ?? 'user';
  const displayName = profile?.full_name || user?.email || 'Account';

  const items: NavItem[] = [];
  if (can('see_admin_overview')) items.push({ to: '/admin', label: 'Overview', icon: 'overview' });
  if (can('manage_candidates')) {
    items.push({ to: '/recruiter', label: 'Candidates', icon: 'candidates', end: true });
    items.push({ to: '/recruiter/analytics', label: 'Analytics', icon: 'analytics' });
  }
  if (can('manage_company_settings')) items.push({ to: '/admin/settings', label: 'Settings', icon: 'settings' });
  if (role === 'user') {
    items.push({ to: '/dashboard', label: 'Dashboard', icon: 'dashboard' });
    items.push({ to: '/new', label: 'New interview', icon: 'new' });
  }

  const roleLabel =
    role === 'admin' ? 'Platform admin' : role === 'company_admin' ? 'Company admin' : role === 'recruiter' ? 'Recruiter' : 'Candidate';

  const handleSignOut = async () => {
    await signOut();
    navigate('/login', { replace: true });
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <BrandMark />
      </div>
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto px-3 py-2">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={navLinkClass}
            onClick={onNavigate}
          >
            <NavIcon name={item.icon} />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="border-t border-subtle p-3">
        {company && (role === 'company_admin' || role === 'recruiter') && (
          <div className="mb-2 truncate px-2 text-xs text-ink-subtle" title={`Acting on behalf of ${company.name}`}>
            {company.name}
          </div>
        )}
        <div className="flex items-center justify-between gap-2 px-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium text-ink">{displayName}</div>
            <div className="text-xs text-ink-subtle">{roleLabel}</div>
          </div>
          <button
            type="button"
            onClick={handleSignOut}
            className="shrink-0 rounded-md px-2 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      type="button"
      onClick={toggleTheme}
      aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      title={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
      className="flex h-9 w-9 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink"
    >
      {theme === 'dark' ? '☀' : '☾'}
    </button>
  );
}

/**
 * Authenticated app shell — persistent left sidebar (recruiter-first IA) on
 * desktop, a slide-in drawer on mobile, and a slim topbar. Unauthenticated
 * callers (e.g. /companies/signup before sign-in) get a minimal brand + sign-in
 * header instead. Built on the design tokens, so it renders in light and dark.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { session, profile } = useAuth();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // The act-as picker hits an admin-only endpoint on mount and does not
  // self-gate — render it for platform admins only (matches the old Header).
  const isPlatformAdmin = profile?.role === 'admin';

  if (!session) {
    return (
      <div className="flex min-h-screen flex-col bg-canvas text-ink">
        <header className="flex h-14 items-center justify-between border-b border-subtle bg-surface px-4">
          <BrandMark />
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Link
              to="/login"
              className="rounded-md border border-strong px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:bg-surface-2"
            >
              Sign in
            </Link>
          </div>
        </header>
        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-app">{children}</div>
        </main>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-canvas text-ink">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 border-r border-subtle bg-surface md:block">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="md:hidden">
          <div
            className="fixed inset-0 z-40 bg-black/50"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <aside className="fixed inset-y-0 left-0 z-50 w-64 border-r border-subtle bg-surface">
            <SidebarContent onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-subtle bg-surface px-4">
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-2 hover:text-ink md:hidden"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="4" y1="7" x2="20" y2="7" />
              <line x1="4" y1="12" x2="20" y2="12" />
              <line x1="4" y1="17" x2="20" y2="17" />
            </svg>
          </button>
          <div className="md:hidden">
            <BrandMark />
          </div>
          <div className="ml-auto flex items-center gap-2">
            {isPlatformAdmin && <ActingAsPicker />}
            <ThemeToggle />
          </div>
        </header>

        <main className="flex-1 px-4 py-8 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-app">{children}</div>
        </main>
      </div>
    </div>
  );
}
