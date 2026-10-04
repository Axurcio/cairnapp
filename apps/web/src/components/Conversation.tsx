import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";

import type { NextAction, TimelineEntry } from "../api/types";
import { formatBytes, formatDateTime, humanize } from "../format";
import { CairnMark } from "./Brand";

const MAX_LENGTH = 4000;

interface Props {
  entries: TimelineEntry[];
  /** Why Cairn said what it said, keyed by assistant event id (for replies sent this visit). */
  decisions: Record<string, NextAction>;
  participantLabel: string;
  /** null when this viewer may send messages; otherwise the reason they can't. */
  readOnlyReason: string | null;
  onSend: (text: string) => Promise<void>;
}

function SystemLine({ entry }: { entry: TimelineEntry }) {
  let text = humanize(entry.event_type);
  if (entry.event_type === "evidence.added") {
    const type = entry.details.content_type;
    const size = entry.details.size_bytes;
    text = ["Evidence added", typeof type === "string" ? type : null, typeof size === "number" ? formatBytes(size) : null]
      .filter(Boolean)
      .join(" · ");
  } else if (entry.event_type === "consent.revoked" && Array.isArray(entry.details.scopes)) {
    text = `Consent revoked: ${entry.details.scopes.map((s) => humanize(String(s))).join(", ")}`;
  }
  return (
    <li className="system-line">
      <span>{text}</span>
      <time dateTime={entry.occurred_at}>{formatDateTime(entry.occurred_at)}</time>
    </li>
  );
}

function Why({ action }: { action: NextAction }) {
  return (
    <details className="why">
      <summary>Why this reply?</summary>
      <dl>
        <dt>Decision</dt>
        <dd>{humanize(action.action_type.toLowerCase())}</dd>
        <dt>Reason</dt>
        <dd>{action.reason}</dd>
        {action.policy_id && (
          <>
            <dt>Policy</dt>
            <dd>
              {action.policy_id}@{action.policy_version}
            </dd>
          </>
        )}
      </dl>
    </details>
  );
}

export function Conversation({ entries, decisions, participantLabel, readOnlyReason, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [entries.length, pending]);

  async function send(event?: FormEvent) {
    event?.preventDefault();
    const text = draft.trim();
    if (!text || pending) return;
    setError(null);
    setPending(text);
    setDraft("");
    try {
      await onSend(text);
    } catch (err) {
      setDraft(text); // keep what they wrote
      setError(err instanceof Error ? err.message : "Your message could not be sent.");
    } finally {
      setPending(null);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  return (
    <section className="conversation" aria-label="Conversation">
      <ol className="messages">
        {entries.length === 0 && !pending && (
          <li className="system-line">
            <span>No messages yet.</span>
          </li>
        )}
        {entries.map((entry) => {
          if (entry.event_type === "participant.message" || entry.event_type === "assistant.message") {
            const fromCairn = entry.event_type === "assistant.message";
            const decision = decisions[entry.event_id];
            return (
              <li key={entry.event_id} className={`bubble-row ${fromCairn ? "from-cairn" : "from-participant"}`}>
                {fromCairn && <CairnMark size={22} />}
                <div className="bubble">
                  <div className="bubble-meta">
                    <span>{fromCairn ? "Cairn" : participantLabel}</span>
                    <time dateTime={entry.occurred_at}>{formatDateTime(entry.occurred_at)}</time>
                  </div>
                  <p>{entry.text}</p>
                  {decision && <Why action={decision} />}
                </div>
              </li>
            );
          }
          return <SystemLine key={entry.event_id} entry={entry} />;
        })}
        {pending && (
          <li className="bubble-row from-participant pending" aria-live="polite">
            <div className="bubble">
              <div className="bubble-meta">
                <span>{participantLabel}</span>
                <span>Sending…</span>
              </div>
              <p>{pending}</p>
            </div>
          </li>
        )}
      </ol>
      <div ref={endRef} />

      {readOnlyReason ? (
        <p className="read-only">{readOnlyReason}</p>
      ) : (
        <form className="composer" onSubmit={send}>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          <label className="visually-hidden" htmlFor="message">
            Message
          </label>
          <textarea
            id="message"
            rows={3}
            maxLength={MAX_LENGTH}
            placeholder="Write to Cairn… (Enter to send, Shift+Enter for a new line)"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={pending !== null}
          />
          <div className="composer-actions">
            <span className="muted small">
              {draft.length > MAX_LENGTH - 200 ? `${MAX_LENGTH - draft.length} characters left` : ""}
            </span>
            <button type="submit" className="button primary" disabled={!draft.trim() || pending !== null}>
              Send
            </button>
          </div>
        </form>
      )}
    </section>
  );
}
