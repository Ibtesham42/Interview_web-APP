import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import type { Session, User } from '@supabase/supabase-js';
import { supabase } from '../utils/supabase/client';
import { companiesApi, profileApi } from '../services/api';
import type { Company, Profile } from '../types';

interface SignUpResult {
  error: string | null;
  needsEmailConfirm: boolean;
}

interface AuthContextValue {
  session: Session | null;
  user: User | null;
  profile: Profile | null;
  // The caller's own Company — populated by AuthContext after profile
  // lands (only when profile.company_id is non-null). Used by the
  // Header chip + the /admin/settings page (multi-tenant PR 5).
  company: Company | null;
  loading: boolean;
  profileLoading: boolean;
  // Both platform admins (role='admin') and tenant-local admins
  // (role='company_admin', PR 3+) see admin pages. Use isPlatformAdmin
  // when the distinction matters (rare in the UI).
  isAdmin: boolean;
  isPlatformAdmin: boolean;
  isRecruiter: boolean;
  signUp: (
    email: string,
    password: string,
    fullName: string,
    options?: { emailRedirectTo?: string },
  ) => Promise<SignUpResult>;
  signIn: (email: string, password: string) => Promise<{ error: string | null }>;
  // `redirectTo` overrides the default /auth/callback redirect — used by
  // the apply flow (PR 4) to thread ?company=slug through the OAuth
  // round-trip so AuthCallback can claim a tenant after sign-in.
  signInWithGoogle: (redirectTo?: string) => Promise<{ error: string | null }>;
  signOut: () => Promise<void>;
  // Re-fetch the profile from /api/auth/me. Called after actions that
  // mutate role/company_id server-side (currently: POST /api/companies/
  // from PR 3) so the SPA's role-aware routing updates without a page
  // refresh.
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [loading, setLoading] = useState(true);
  const [profileLoading, setProfileLoading] = useState(true);

  // Establish the session once, then keep it in sync.
  useEffect(() => {
    let mounted = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!mounted) return;
      setSession(data.session);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
    });

    return () => {
      mounted = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  // Load the profile (role, name) from the backend whenever the user changes.
  // The backend uses the service-role key, so this never depends on RLS.
  useEffect(() => {
    const userId = session?.user?.id;
    if (!userId) {
      setProfile(null);
      setCompany(null);
      setProfileLoading(false);
      return;
    }
    let cancelled = false;
    setProfileLoading(true);
    profileApi
      .me()
      .then((p) => {
        if (!cancelled) setProfile(p);
      })
      .catch(() => {
        // Backend unreachable / error — degrade gracefully instead of
        // spinning forever. The user is treated as a non-admin candidate.
        if (!cancelled) setProfile(null);
      })
      .finally(() => {
        if (!cancelled) setProfileLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session?.user?.id]);

  // Load the caller's Company info whenever their profile gains a
  // company_id (multi-tenant PR 5). One extra request after profile
  // lands; cached in context for the Header chip + Settings page so
  // they never need to re-fetch. Skipped for platform admins and B2C
  // users (NULL company_id) — they have no Company to show.
  useEffect(() => {
    if (!profile?.company_id) {
      setCompany(null);
      return;
    }
    let cancelled = false;
    companiesApi
      .getMine()
      .then((c) => {
        if (!cancelled) setCompany(c);
      })
      .catch(() => {
        // Same graceful degrade as the profile load.
        if (!cancelled) setCompany(null);
      });
    return () => {
      cancelled = true;
    };
  }, [profile?.company_id]);

  const signUp = async (
    email: string,
    password: string,
    fullName: string,
    options: { emailRedirectTo?: string } = {},
  ): Promise<SignUpResult> => {
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: { full_name: fullName },
        // emailRedirectTo carries query params (e.g. ?company=slug)
        // through Supabase's email-confirm link so the AuthCallback
        // can claim a tenant after the round-trip (multi-tenant PR 4).
        emailRedirectTo: options.emailRedirectTo,
      },
    });
    return {
      error: error?.message ?? null,
      needsEmailConfirm: !error && !data.session,
    };
  };

  const signIn = async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    return { error: error?.message ?? null };
  };

  const signInWithGoogle = async (redirectTo?: string) => {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: redirectTo ?? `${window.location.origin}/auth/callback` },
    });
    if (!error) return { error: null };
    const friendly = /provider is not enabled/i.test(error.message)
      ? 'Google sign-in is not enabled for this project yet. Use email and password, or enable the Google provider in Supabase.'
      : error.message;
    return { error: friendly };
  };

  const signOut = async () => {
    await supabase.auth.signOut();
    setProfile(null);
    setCompany(null);
  };

  const refreshProfile = async () => {
    setProfileLoading(true);
    try {
      const p = await profileApi.me();
      setProfile(p);
    } catch {
      // Same degrade-gracefully as the load effect — never let a transient
      // backend error wipe the user's session.
    } finally {
      setProfileLoading(false);
    }
  };

  const role = profile?.role;
  const value: AuthContextValue = {
    session,
    user: session?.user ?? null,
    profile,
    company,
    loading,
    profileLoading,
    isAdmin: role === 'admin' || role === 'company_admin',
    isPlatformAdmin: role === 'admin',
    isRecruiter: role === 'recruiter' || role === 'admin' || role === 'company_admin',
    signUp,
    signIn,
    signInWithGoogle,
    signOut,
    refreshProfile,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
