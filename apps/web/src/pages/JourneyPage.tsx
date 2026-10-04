import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError, api } from "../api/client";
import type { Journey, NextAction, Observation, TimelineEntry } from "../api/types";
import { hasRole, useAccount } from "../auth/AuthContext";
import { StatusPill, SyntheticBadge } from "../components/Badges";
import { Conversation } from "../components/Conversation";
import { ConsentPanel, EvidencePanel, ObservationsPanel, ReportPanel } from "../components/Panels";
import { formatDate } from "../format";

type Tab = "observations" | "report" | "evidence" | "consent";

export function JourneyPage() {
  const { journeyId = "" } = useParams();
  const account = useAccount();
  const [journey, setJourney] = useState<Journey | null>(null);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [decisions, setDecisions] = useState<Record<string, NextAction>>({});
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [tab, setTab] = useState<Tab>("observations");

  const reloadTimeline = useCallback(
    () => api.timeline(journeyId).then(setTimeline),
    [journeyId],
  );
  const reloadObservations = useCallback(
    () => api.observations(journeyId).then(setObservations),
    [journeyId],
  );

  useEffect(() => {
    setJourney(null);
    setError(null);
    Promise.all([api.journey(journeyId), reloadTimeline(), reloadObservations()])
      .then(([j]) => setJourney(j))
      .catch((err: Error) => setError(err));
  }, [journeyId, reloadTimeline, reloadObservations]);

  if (error) {
    const status = error instanceof ApiError ? error.status : 0;
    return (
      <div className="page narrow">
        <h1>{status === 404 ? "Journey not found" : status === 403 ? "No access" : "Something went wrong"}</h1>
        <p className="muted">
          {status === 403
            ? "You don't have access to this journey."
            : status === 404
              ? "It may have been removed, or the link is wrong."
              : error.message}
        </p>
        <p>
          <Link to="/">Back to journeys</Link>
        </p>
      </div>
    );
  }
  if (!journey) return <div className="page muted">Loading…</div>;

  const isOwner = hasRole(account, "participant") && account.participant_id === journey.participant_id;
  const canRevoke = isOwner || hasRole(account, "tenant_admin");
  const readOnlyReason = !isOwner
    ? "You're viewing this journey. Only the participant can send messages."
    : journey.status !== "active"
      ? "This journey isn't active, so new messages can't be sent."
      : null;

  async function send(text: string) {
    const result = await api.sendMessage(journeyId, text);
    const now = new Date().toISOString();
    setTimeline((t) => [
      ...t,
      {
        event_id: result.participant_event_id,
        event_type: "participant.message",
        actor_type: "participant",
        occurred_at: now,
        source: "web",
        text,
        evidence_refs: [],
        details: {},
      },
      {
        event_id: result.assistant_event_id,
        event_type: "assistant.message",
        actor_type: "assistant",
        occurred_at: now,
        source: "web",
        text: result.response.text,
        evidence_refs: [],
        details: {},
      },
    ]);
    setDecisions((d) => ({ ...d, [result.assistant_event_id]: result.next_action }));
    void reloadObservations();
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: "observations", label: "Observations" },
    { id: "report", label: "Report" },
    ...(isOwner ? [{ id: "evidence" as const, label: "Evidence" }] : []),
    ...(canRevoke ? [{ id: "consent" as const, label: "Consent" }] : []),
  ];

  return (
    <div className="page journey">
      <div className="page-head">
        <p className="crumbs">
          <Link to="/">Journeys</Link> /
        </p>
        <div className="title-row">
          <h1>{journey.title}</h1>
          <StatusPill status={journey.status} />
          {journey.is_synthetic && <SyntheticBadge />}
        </div>
        <p className="muted small">
          {journey.domain_pack}@{journey.domain_pack_version} · started {formatDate(journey.started_at)}
        </p>
      </div>

      <div className="journey-layout">
        <Conversation
          entries={timeline}
          decisions={decisions}
          participantLabel={isOwner ? "You" : "Participant"}
          readOnlyReason={readOnlyReason}
          onSend={send}
        />

        <aside className="sidebar">
          <div className="tabs" role="tablist" aria-label="Journey details">
            {tabs.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                className={tab === t.id ? "tab active" : "tab"}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="tab-panel" role="tabpanel">
            {tab === "observations" && <ObservationsPanel observations={observations} />}
            {tab === "report" && <ReportPanel journeyId={journeyId} />}
            {tab === "evidence" && isOwner && (
              <EvidencePanel journeyId={journeyId} onUploaded={() => void reloadTimeline()} />
            )}
            {tab === "consent" && canRevoke && (
              <ConsentPanel
                journeyId={journeyId}
                onRevoked={() => {
                  void api.journey(journeyId).then(setJourney);
                  void reloadTimeline();
                }}
              />
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
