import { useState } from "react";
import { Link, Outlet } from "react-router";

import { useAccount, useAuth } from "../auth/AuthContext";
import { roleLabel } from "../format";
import { CairnMark } from "./Brand";

export function Layout() {
  const account = useAccount();
  const { logout } = useAuth();
  const [signingOut, setSigningOut] = useState(false);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await logout();
    } finally {
      setSigningOut(false);
    }
  }

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" className="brand">
          <CairnMark />
          <span>Cairn</span>
          {account.tenant_name && <span className="tenant">{account.tenant_name}</span>}
        </Link>
        <div className="account">
          <div className="who">
            <span className="name">{account.display_name}</span>
            <span className="roles">{account.roles.map(roleLabel).join(" · ")}</span>
          </div>
          <button type="button" className="button ghost" onClick={handleSignOut} disabled={signingOut}>
            Sign out
          </button>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
