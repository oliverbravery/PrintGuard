import { useState } from "react";
import { useStore } from "../store";
import type { PluginRecord } from "../types";

export function PluginSecrets({ plugin }: { plugin: PluginRecord }) {
  const send = useStore((s) => s.send);
  const callback = useStore((s) => s.engine?.plugin_oauth_callback ?? "");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const names = Object.keys(plugin.manifest.secrets);
  const provider = plugin.manifest.oauth.label;
  const connected = plugin.secrets_set.includes("oauth");
  const redirect = `${window.location.origin.replace("//localhost", "//127.0.0.1")}${callback}`;

  if (names.length === 0 && !provider) return null;

  return (
    <div className="space-y-2 border-t border-line-0 pt-2">
      {provider && (
        <div className="space-y-1">
          <span className="block text-[0.7rem] text-text-2">
            {provider} needs an app of your own.{" "}
            {plugin.manifest.oauth.register_url && (
              <a className="text-accent hover:underline" href={plugin.manifest.oauth.register_url} target="_blank" rel="noreferrer">
                Create one ↗
              </a>
            )}{" "}
            with this redirect URI, then paste its client id below.
          </span>
          <code className="mono block select-all break-all rounded border border-line-0 bg-ink-2 px-2 py-1 text-[0.65rem] text-text-1">
            {redirect}
          </code>
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
          PrintGuard fills these in. The plugin never reads them back.
        </span>
      )}
      {provider && (
        <div className="flex items-center gap-2">
          <span className="text-[0.7rem] text-text-2 flex-1">
            {connected ? `Connected to ${provider}.` : `Sign in to ${provider}.`}
          </span>
          <button
            className={connected ? "btn" : "btn btn-primary"}
            disabled={!connected && !plugin.secrets_set.includes("oauth_client_id")}
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
    </div>
  );
}
