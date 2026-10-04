import { Link, Navigate, Route, Routes, useLocation } from "react-router";

import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { JourneyPage } from "./pages/JourneyPage";
import { JourneysPage } from "./pages/JourneysPage";
import { LoginPage } from "./pages/LoginPage";

function RequireAuth() {
  const { state } = useAuth();
  const location = useLocation();
  if (state.status === "loading") {
    return <div className="splash" aria-busy="true" />;
  }
  if (state.status === "signed-out") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return <Layout />;
}

function NotFound() {
  return (
    <div className="page narrow">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to your journeys</Link>
      </p>
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route index element={<JourneysPage />} />
        <Route path="journeys/:journeyId" element={<JourneyPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
