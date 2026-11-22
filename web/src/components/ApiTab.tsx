import { useState } from "react";
import { useFocusKept } from "../a11y";
import { useStore } from "../store";
import { useSubmit } from "../submit";
import type { ApiToken } from "../types";
import { ConfirmButton } from "./ConfirmButton";
import { CopyButton } from "./CopyButton";

export function ApiTab() {
  const { engine, send, isPending, createdToken, clearCreatedToken } = useStore();
  const [tokenName, setTokenName] = useState("");
  const [tokenScope, setTokenScope] = useState<ApiToken["scope"]>("read");
  const createToken = useSubmit(() => setTokenName(""));
  const tokenArea = useFocusKept<HTMLDivElement>();
  const tokens = engine?.tokens ?? [];
  return (
    <div ref={tokenArea} className="space-y-4">
      <div>
        <span className="label block">API &amp; MCP access</span>
        <span className="text-xs text-text-2 block mt-1">
          Generate bearer tokens for the REST API and MCP server. Control includes read access, and manage includes everything.
        </span>
      </div>

      {createdToken && (
        <div className="relative space-y-2 border border-accent p-3 pr-12">
          <span className="absolute right-0 top-0">
            <button
              className="tap-target text-text-2 hover:text-accent text-lg leading-none cursor-pointer"
              onClick={clearCreatedToken}
              aria-label="Dismiss"
            >
              ×
            </button>
          </span>
          <span className="block text-sm text-text-1">
            Copy <span className="text-accent">{createdToken.name}</span> now. It's only shown once and can't be retrieved again later.
          </span>
          <div className="flex items-center gap-2">
            <code className="mono flex-1 break-all text-sm">{createdToken.secret}</code>
            <CopyButton text={createdToken.secret} />
          </div>
        </div>
      )}

      {tokens.length > 0 && (
        <div className="space-y-2">
          {tokens.map((t) => (
            <div key={t.id} className="flex items-center gap-3">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm">{t.name}</span>
                  <span className="chip chip-accent">{t.scope}</span>
                </div>
                <span className="mono block truncate text-xs text-text-2">{t.hint}</span>
              </div>
              <ConfirmButton disabled={isPending("token.remove", t.id)} onConfirm={() => send({ cmd: "token.remove", id: t.id })}>
                Revoke
              </ConfirmButton>
            </div>
          ))}
        </div>
      )}

      <form
        className="space-y-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (!tokenName.trim() || isPending("token.create")) return;
          createToken.submit({ cmd: "token.create", name: tokenName.trim(), scope: tokenScope });
        }}
      >
        <input
          className="field"
          aria-label="Token name"
          placeholder="Token name"
          value={tokenName}
          onChange={(e) => setTokenName(e.target.value)}
        />
        <div className="flex gap-2">
          <select className="field" aria-label="Token scope" value={tokenScope} onChange={(e) => setTokenScope(e.target.value as ApiToken["scope"])}>
            <option value="read">read</option>
            <option value="control">control</option>
            <option value="manage">manage</option>
          </select>
          <button type="submit" className="btn btn-primary whitespace-nowrap" disabled={!tokenName.trim() || isPending("token.create")}>
            {isPending("token.create") ? "…" : "Generate"}
          </button>
        </div>
        {createToken.error && (
          <span role="alert" className="chip chip-message chip-bad">
            {createToken.error}
          </span>
        )}
      </form>
    </div>
  );
}
