import { useDraftCommit } from "../submit";

export function NameField({ name, onRename }: { name: string; onRename: (name: string) => void }) {
  const { draft, set, reset, commit } = useDraftCommit(
    () => name,
    [name],
    (value) => {
      const next = value.trim();
      if (next && next !== name) onRename(next);
      else reset(name);
    },
  );

  return (
    <label className="block">
      <span className="label block mb-1">Name</span>
      <input
        className="field"
        value={draft}
        onChange={(e) => set(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
      />
    </label>
  );
}
