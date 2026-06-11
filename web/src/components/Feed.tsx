import { useEffect, useRef } from "react";
import { bridge } from "../local";
import type { Camera } from "../types";
import { playWhep, whepBase } from "../webrtc";

export function Feed({ camera, mode, whep }: { camera: Camera | undefined; mode: string; whep: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const online = camera?.online ?? false;

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !camera) return;
    if (mode === "local") {
      video.srcObject = bridge.getStream(camera.id);
      void video.play().catch(() => {});
      return () => {
        video.srcObject = null;
      };
    }
    let stop: (() => void) | undefined;
    let cancelled = false;
    const path = camera.source.kind === "path" ? camera.source.path! : camera.id;
    playWhep(video, `${whepBase(whep)}/${path}/whep`)
      .then((fn) => {
        if (cancelled) fn();
        else stop = fn;
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      stop?.();
      video.srcObject = null;
    };
  }, [camera?.id, camera?.online, mode, whep]);

  return (
    <div className="scan relative aspect-video bg-ink-0 overflow-hidden">
      <video ref={videoRef} autoPlay muted playsInline className="absolute inset-0 w-full h-full object-cover" />
      {(!camera || !online) && (
        <div className="absolute inset-0 grid place-items-center bg-ink-0/85 z-[2]">
          <span className="mono text-[0.65rem] tracking-[0.2em] text-text-2 uppercase">
            {camera ? "no signal" : "no camera bound"}
          </span>
        </div>
      )}
    </div>
  );
}
