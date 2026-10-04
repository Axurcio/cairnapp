import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { api } from "../api/client";
import type { ConsentScope, Observation, Report } from "../api/types";
import { formatBytes, formatDateTime, formatValue, humanize } from "../format";

export function ObservationsPanel({ observations }: { observations: Observation[] }) {
  if (observations.length === 0) {
    return <p className="muted">Nothing recorded yet. Observations appear as the conversation goes on.</p>;
  }
  const newestFirst = [...observations].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at));
  return (
    <ul className="observations">
      {newestFirst.map((o) => (
        <li key={o.id} className="observation">
          <div className="observation-head">
            <h3>{humanize(o.observation_type)}</h3>
            <span className={`pill obs-${o.status}`}>{humanize(o.status)}</span>
          </div>
          <time className="muted small" dateTime={o.occurred_at}>
            {formatDateTime(o.occurred_at)}
          </time>
          <dl>
            {Object.entries(o.fields).map(([name, value]) => (
              <div key={name}>
                <dt>{humanize(name)}</dt>
                <dd>{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
        </li>
      ))}
    </ul>
  );
}

export function ReportPanel({ journeyId }: { journeyId: string }) {
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .report(journeyId)
      .then(setReport)
      .catch((err: Error) => setError(err.message));
  }, [journeyId]);

  if (error) return <p className="error">{error}</p>;
  if (!report) return <p className="muted">Preparing report…</p>;
  return (
    <div className="report">
      <p className="callout">{report.disclaimer}</p>
      {report.sections.map((section) => (
        <section key={section.title}>
          <h3>{section.title}</h3>
          {section.statements.length === 0 ? (
            <p className="muted small">Nothing to report yet.</p>
          ) : (
            <ul>
              {section.statements.map((s, i) => (
                <li key={`${s.observation_id ?? "s"}-${i}`}>{s.text}</li>
              ))}
            </ul>
          )}
        </section>
      ))}
      <p className="muted small">Generated {formatDateTime(report.generated_at)}</p>
    </div>
  );
}

export function EvidencePanel({ journeyId, onUploaded }: { journeyId: string; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setMessage(null);
    try {
      const evidence = await api.uploadEvidence(journeyId, file);
      setMessage({ kind: "ok", text: `Uploaded ${file.name} (${formatBytes(evidence.size_bytes)}).` });
      setFile(null);
      event.currentTarget.reset();
      onUploaded();
    } catch (err) {
      setMessage({ kind: "error", text: err instanceof Error ? err.message : "Upload failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="stack" onSubmit={upload}>
      <p className="muted">
        Add a photo, recording or document that shows what you described. Files are stored securely and only
        people with access to this journey can see them.
      </p>
      <label className="field">
        <span>File</span>
        <input
          type="file"
          accept="image/jpeg,image/png,application/pdf,text/plain,application/json,audio/mpeg,audio/wav,video/mp4"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>
      <p className="muted small">JPEG, PNG, PDF, text, JSON, MP3, WAV or MP4 · up to 25 MB</p>
      {message && <p className={message.kind === "ok" ? "success" : "error"}>{message.text}</p>}
      <button type="submit" className="button primary" disabled={!file || busy}>
        {busy ? "Uploading…" : "Upload evidence"}
      </button>
    </form>
  );
}

const SCOPES: { scope: ConsentScope; title: string; description: string }[] = [
  { scope: "conversation", title: "Conversation", description: "Cairn may process the messages you send in this journey." },
  {
    scope: "context_projection",
    title: "Conversation memory",
    description: "Cairn may keep a derived memory of this journey to ask better follow-up questions.",
  },
  { scope: "evidence", title: "Evidence", description: "You may upload files, and Cairn may store them." },
  { scope: "reporting", title: "Reports", description: "Descriptive reports may be produced from your observations." },
];

export function ConsentPanel({ journeyId, onRevoked }: { journeyId: string; onRevoked: () => void }) {
  const [granted, setGranted] = useState<ConsentScope[] | null>(null);
  const [selected, setSelected] = useState<ConsentScope[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .consents(journeyId)
      .then((c) => setGranted(c.granted))
      .catch((err: Error) => setError(err.message));
  }, [journeyId]);

  function toggle(scope: ConsentScope) {
    setConfirming(false);
    setSelected((s) => (s.includes(scope) ? s.filter((x) => x !== scope) : [...s, scope]));
  }

  async function revoke() {
    setBusy(true);
    setError(null);
    try {
      await api.revokeConsent(journeyId, selected);
      setGranted((g) => (g ?? []).filter((s) => !selected.includes(s)));
      setSelected([]);
      setConfirming(false);
      onRevoked();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke consent.");
    } finally {
      setBusy(false);
    }
  }

  if (!granted) return error ? <p className="error">{error}</p> : <p className="muted">Loading…</p>;

  return (
    <div className="stack">
      <p className="muted">
        Consent can be withdrawn at any time. Withdrawing stops that kind of processing for this journey; derived
        memory is forgotten and evidence is removed where its retention rules allow. It can't be undone from here.
      </p>
      <ul className="consents">
        {SCOPES.map(({ scope, title, description }) => {
          const isGranted = granted.includes(scope);
          return (
            <li key={scope}>
              <label className={isGranted ? "" : "revoked"}>
                <input
                  type="checkbox"
                  disabled={!isGranted || busy}
                  checked={selected.includes(scope)}
                  onChange={() => toggle(scope)}
                />
                <span>
                  <strong>{title}</strong> <span className="muted small">{isGranted ? "Granted" : "Withdrawn"}</span>
                  <br />
                  <span className="muted small">{description}</span>
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      {error && <p className="error">{error}</p>}
      {!confirming ? (
        <button
          type="button"
          className="button danger"
          disabled={selected.length === 0 || busy}
          onClick={() => setConfirming(true)}
        >
          Withdraw selected consent
        </button>
      ) : (
        <div className="confirm" role="alertdialog" aria-label="Confirm withdrawal">
          <p>
            Withdraw consent for <strong>{selected.map((s) => humanize(s)).join(", ")}</strong>? This can't be undone
            from the website.
          </p>
          <div className="row">
            <button type="button" className="button danger" onClick={revoke} disabled={busy}>
              {busy ? "Withdrawing…" : "Yes, withdraw"}
            </button>
            <button type="button" className="button ghost" onClick={() => setConfirming(false)} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
