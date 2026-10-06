import { useEffect, useState } from "react";
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
