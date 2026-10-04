import { useEffect, useState } from "react";
import { Link } from "react-router";

import { api } from "../api/client";
import type { JourneySummary } from "../api/types";
import { hasRole, useAccount } from "../auth/AuthContext";
import { StatusPill, SyntheticBadge } from "../components/Badges";
import { formatDate } from "../format";

export function JourneysPage() {
  const account = useAccount();
  const [journeys, setJourneys] = useState<JourneySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .journeys()
      .then(setJourneys)
      .catch((err: Error) => setError(err.message));
  }, []);

  const isParticipantOnly = account.roles.length === 1 && hasRole(account, "participant");

  return (
    <div className="page">
      <div className="page-head">
        <h1>{isParticipantOnly ? "Your journeys" : "Journeys"}</h1>
        <p className="muted">
          {isParticipantOnly
            ? "Each journey is an ongoing conversation with Cairn."
            : "Journeys you can view in this organisation."}
        </p>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!journeys && !error && <p className="muted">Loading…</p>}
      {journeys?.length === 0 && (
        <div className="empty">
          <p>No journeys yet.</p>
          <p className="muted">
            {isParticipantOnly
              ? "Your organisation will start a journey for you."
              : "Journeys appear here once you have access to a participant."}
          </p>
        </div>
      )}

      {journeys && journeys.length > 0 && (
        <ul className="journey-grid">
          {journeys.map((j) => (
            <li key={j.id}>
              <Link to={`/journeys/${j.id}`} className="journey-card">
                <div className="journey-card-top">
                  <span className="eyebrow">{j.domain_pack_name ?? j.domain_pack}</span>
                  <StatusPill status={j.status} />
                </div>
                <h2>{j.title}</h2>
                <dl className="meta">
                  {!isParticipantOnly && j.participant_display_name && (
                    <div>
                      <dt>Participant</dt>
                      <dd>{j.participant_display_name}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Started</dt>
                    <dd>{formatDate(j.started_at)}</dd>
                  </div>
                </dl>
                {j.is_synthetic && <SyntheticBadge />}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
