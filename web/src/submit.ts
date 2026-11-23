import { useEffect, useRef, useState } from "react";
import { useStore } from "./store";

export function useSubmit(onSaved: () => void) {
  const send = useStore((s) => s.send);
  const outcome = useStore((s) => s.outcome);
  const [reqId, setReqId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (reqId === null || outcome?.req_id !== reqId) return;
    setError(outcome.error);
    if (outcome.error === null) onSaved();
  }, [outcome]);

  return {
    error,
    submit(cmd: Record<string, unknown>) {
      setError(null);
      setReqId(send(cmd));
    },
  };
}

export function useCreated<T extends { id: string }>(cmd: string, items: T[], onCreated: (created: T) => void) {
  const busy = useStore((s) => s.isPending(cmd));
  const seen = useRef<Set<string> | null>(null);
  const onCreatedRef = useRef(onCreated);
  onCreatedRef.current = onCreated;

  useEffect(() => {
    if (busy) {
      if (seen.current === null) seen.current = new Set(items.map((item) => item.id));
      return;
    }
    if (seen.current === null) return;
    const previous = seen.current;
    seen.current = null;
    const created = items.find((item) => !previous.has(item.id));
    if (created) onCreatedRef.current(created);
  }, [busy, items]);
}

export function useDraftCommit<T>(initial: () => T, deps: readonly unknown[], commitDraft: (draft: T) => void, paused = false) {
  const [draft, setDraft] = useState<T>(initial);
  const dirty = useRef(false);
  const commitRef = useRef(() => {});

  useEffect(() => {
    if (paused) return;
    dirty.current = false;
    setDraft(initial());
  }, [...deps, paused]);

  const commit = () => {
    if (!dirty.current) return;
    dirty.current = false;
    commitDraft(draft);
  };
  commitRef.current = commit;

  useEffect(() => () => commitRef.current(), []);

  return {
    draft,
    set(next: T) {
      dirty.current = true;
      setDraft(next);
    },
    reset(next: T) {
      dirty.current = false;
      setDraft(next);
    },
    commit,
  };
}
