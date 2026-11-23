import { useState } from "react";
import { useStore } from "../store";
import type { PluginRecord } from "../types";
import { webUrl } from "../urls";
import { NewTab } from "./NewTab";
import { SignInAddresses } from "./PluginConsent";

export function PluginSecrets({ plugin }: { plugin: PluginRecord }) {
  const send = useStore((s) => s.send);
  const signIn = useStore((s) => s.signIn);
  const callback = useStore((s) => s.engine?.plugin_oauth_callback ?? "");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const names = Object.keys(plugin.manifest.secrets);
  const provider = plugin.manifest.oauth.label;
  const registerUrl = plugin.manifest.oauth.register_url ? webUrl(plugin.manifest.oauth.register_url) : null;
  const connected = plugin.secrets_set.includes("oauth");
  const hub = new URL(window.location.origin);
  if (hub.hostname === "localhost") hub.hostname = "127.0.0.1";
  const redirect = `${hub.origin}${callback}`;

  if (names.length === 0 && !provider) return null;

  return (
    <div className="space-y-2 border-t border-line-0 pt-2">
      {provider && (
        <div className="space-y-1">
          <span className="block text-xs text-text-2">
            {provider} needs an app of your own.{" "}
            {registerUrl && (
              <a className="text-accent hover:underline" href={registerUrl} target="_blank" rel="noreferrer">
                Create one <NewTab />
              </a>
            )}{" "}
            with this redirect URI, then paste its client id below.
          </span>
          <code className="mono block select-all break-all border border-line-0 bg-ink-2 px-2 py-1 text-xs text-text-1">
            {redirect}
          </code>
          <SignInAddresses oauth={plugin.manifest.oauth} />
        </div>
      )}
      {names.map((name) => (
        <label key={name} className="block">
          <span className="label block mb-1">{name.replace(/[_-]/g, " ")}</span>
          <span className="mb-1 block text-xs text-text-2">{plugin.manifest.secrets[name]}</span>
          <input
            className="field"
            type="password"
            autoComplete="new-password"
            placeholder={plugin.secrets_set.includes(name) ? "Stored, type to replace" : "Not set"}
            value={draft[name] ?? ""}
            onChange={(event) => setDraft({ ...draft, [name]: event.target.value })}
            onBlur={() => {
              if (!draft[name]) return;
              if (send({ cmd: "plugin.secrets", id: plugin.id, secrets: { ...draft } }) !== null) setDraft({});
            }}
          />
        </label>
      ))}
      {names.length > 0 && (
        <span className="block text-xs text-text-2">
          PrintGuard injects these into requests for you, so the plugin itself can never read them back.
        </span>
      )}
      {provider && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-2 flex-1">
            {connected ? `Connected to ${provider}.` : `Sign in to ${provider}.`}
          </span>
          <button
            className={connected ? "btn" : "btn btn-primary"}
            disabled={!connected && !plugin.secrets_set.includes("oauth_client_id")}
            onClick={() => (connected ? send({ cmd: "plugin.oauth", id: plugin.id, action: "forget" }) : signIn(plugin.id))}
          >
            {connected ? "Disconnect" : "Connect"}
          </button>
        </div>
      )}
    </div>
  );
}
