import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { CairnMark } from "../components/Brand";
import { DEMO_ACCOUNTS, DEMO_PASSWORD, showDemoAccounts } from "../demoAccounts";
import { safeNext } from "../format";

export function LoginPage() {
  const { state, login } = useAuth();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (state.status === "signed-in") {
    return <Navigate to={safeNext(params.get("next"))} replace />;
  }

  async function signIn(asEmail: string, asPassword: string) {
    setError(null);
    setSubmitting(true);
    try {
      await login(asEmail, asPassword);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? "That email and password don't match an account."
          : "Couldn't sign in right now. Please try again.",
      );
      setPassword("");
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    void signIn(email, password);
  }

  function signInAs(demoEmail: string) {
    setEmail(demoEmail);
    setPassword(DEMO_PASSWORD);
    void signIn(demoEmail, DEMO_PASSWORD);
  }

  const notice = state.status === "signed-out" ? state.reason : undefined;

  return (
    <div className="login">
      <div className="login-card">
        <div className="login-brand">
          <CairnMark size={40} />
          <h1>Sign in to Cairn</h1>
          <p className="muted">Pick up your journey where you left off.</p>
        </div>

        {notice && !error && <p className="notice">{notice}</p>}
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <form onSubmit={handleSubmit} className="stack">
          <label className="field">
            <span>Email</span>
            <input
              type="email"
              autoComplete="username"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button type="submit" className="button primary" disabled={submitting || state.status === "loading"}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        {showDemoAccounts && (
          <section className="demo-accounts" aria-labelledby="demo-accounts-title">
            <div className="demo-accounts-head">
              <h2 id="demo-accounts-title">Sign in as a demo user</h2>
              <p className="muted small">
                Synthetic accounts from <code>make seed</code>. Password for all:{" "}
                <code>{DEMO_PASSWORD}</code>
              </p>
            </div>
            <ul>
              {DEMO_ACCOUNTS.map((a) => (
                <li key={a.email}>
                  <button
                    type="button"
                    className="demo-account"
                    onClick={() => signInAs(a.email)}
                    disabled={submitting || state.status === "loading"}
                  >
                    <span className="demo-account-top">
                      <strong>{a.name}</strong>
                      <span className="pill">{a.role}</span>
                    </span>
                    <span className="demo-account-email">{a.email}</span>
                    <span className="muted small">{a.description}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
