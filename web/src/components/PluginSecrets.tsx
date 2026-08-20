import { useState } from "react";
import { useStore } from "../store";
import type { PluginRecord } from "../types";

export function PluginSecrets({ plugin }: { plugin: PluginRecord }) {
  const send = useStore((s) => s.send);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const names = Object.keys(plugin.manifest.secrets);
  const provider = plugin.manifest.oauth.label;
  const connected = plugin.secrets_set.includes("oauth");

  if (names.length === 0 && !provider) return null;

  return (
    <div className="space-y-2 border-t border-line-0 pt-2">
      {provider && (
        <div className="flex items-center gap-2">
          <span className="text-[0.7rem] text-text-2 flex-1">
            {connected ? `Connected to ${provider}.` : `Sign in to ${provider} to let it work.`}
          </span>
          <button
            className={connected ? "btn" : "btn btn-primary"}
            onClick={() =>
              send({
                cmd: "plugin.oauth",
                id: plugin.id,
                action: connected ? "forget" : "start",
                origin: window.location.origin,
              })
            }
          >
            {connected ? "Disconnect" : "Connect"}
          </button>
        </div>
      )}
      {names.map((name) => (
        <label key={name} className="block">
          <span className="label block mb-1">{name.replace(/[_-]/g, " ")}</span>
          <span className="mb-1 block text-[0.7rem] text-text-2">{plugin.manifest.secrets[name]}</span>
          <input
            className="field"
            type="password"
            placeholder={plugin.secrets_set.includes(name) ? "Stored, type to replace" : "Not set"}
            value={draft[name] ?? ""}
            onChange={(event) => setDraft({ ...draft, [name]: event.target.value })}
            onBlur={() => {
              if (!draft[name]) return;
              send({ cmd: "plugin.secrets", id: plugin.id, secrets: { ...draft } });
              setDraft({});
            }}
          />
        </label>
      ))}
      {names.length > 0 && (
        <span className="block text-[0.7rem] text-text-2">
          PrintGuard fills these in as the plugin's requests go out. Neither it nor this page reads one back.
        </span>
      )}
    </div>
  );
}
