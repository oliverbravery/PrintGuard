import { useEffect, useRef, useState } from "react";

export function NameField({ name, onRename }: { name: string; onRename: (name: string) => void }) {
  const [draft, setDraft] = useState(name);
  const dirty = useRef(false);
  const commitRef = useRef(() => {});

  useEffect(() => {
    dirty.current = false;
    setDraft(name);
  }, [name]);

  const commit = () => {
    if (!dirty.current) return;
    dirty.current = false;
    const next = draft.trim();
    if (next && next !== name) onRename(next);
    else setDraft(name);
  };
  commitRef.current = commit;

  useEffect(() => () => commitRef.current(), []);

  return (
    <label className="block">
      <span className="label block mb-1">Name</span>
      <input
        className="field"
        value={draft}
        onChange={(e) => {
          dirty.current = true;
          setDraft(e.target.value);
        }}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
    </label>
  );
}
