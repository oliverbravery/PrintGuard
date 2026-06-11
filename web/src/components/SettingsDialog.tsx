import { useState } from "react";
import { useStore } from "../store";
import { Dialog } from "./Dialog";

export function SettingsDialog() {
  const { engine, send, openDialog, leaveMode } = useStore();
  const [ntfy, setNtfy] = useState(engine?.settings.ntfy_url ?? "");
  const [whep, setWhep] = useState(engine?.settings.whep_base ?? "");
  const close = () => openDialog(null);
  return (
    <Dialog title="Settings" onClose={close}>
      <div className="space-y-5">
        <label className="block">
          <span className="label block mb-1">ntfy topic URL</span>
          <input
            className="field"
            placeholder="https://ntfy.sh/my-printers"
            value={ntfy}
            onChange={(e) => setNtfy(e.target.value)}
          />
          <span className="text-[0.7rem] text-text-2 block mt-1">
            Defect alerts (with snapshots) are pushed here for printers with notifications on.
          </span>
        </label>
        {engine?.mode === "hub" && (
          <label className="block">
            <span className="label block mb-1">WebRTC base URL</span>
            <input
              className="field"
              placeholder={`${location.protocol}//${location.hostname}:8889`}
              value={whep}
              onChange={(e) => setWhep(e.target.value)}
            />
            <span className="text-[0.7rem] text-text-2 block mt-1">
              Where browsers reach MediaMTX for live playback. Leave blank for the default.
            </span>
          </label>
        )}
        <button
          className="btn btn-primary w-full"
          onClick={() => {
            send({ cmd: "settings.update", patch: { ntfy_url: ntfy.trim(), whep_base: whep.trim() } });
            close();
          }}
        >
          Save
        </button>
        <div className="hairline pt-4 flex items-center justify-between">
          <span className="text-xs text-text-1">
            Mode: <span className="mono text-accent">{engine?.mode}</span>
          </span>
          <button className="btn" onClick={leaveMode}>
            Switch mode
          </button>
        </div>
      </div>
    </Dialog>
  );
}
