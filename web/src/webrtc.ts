async function iceComplete(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return;
  await new Promise<void>((resolve) => {
    const check = () => {
      if (pc.iceGatheringState === "complete") {
        pc.removeEventListener("icegatheringstatechange", check);
        resolve();
      }
    };
    pc.addEventListener("icegatheringstatechange", check);
    setTimeout(resolve, 2000);
  });
}

async function negotiate(pc: RTCPeerConnection, url: string): Promise<void> {
  await pc.setLocalDescription(await pc.createOffer());
  await iceComplete(pc);
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/sdp" },
    body: pc.localDescription!.sdp,
  });
  if (!resp.ok) throw new Error(`WebRTC negotiation failed: HTTP ${resp.status}`);
  await pc.setRemoteDescription({ type: "answer", sdp: await resp.text() });
}

export function whepBase(configured: string): string {
  return configured.trim().replace(/\/$/, "") || `${location.protocol}//${location.hostname}:8889`;
}

export async function playWhep(video: HTMLVideoElement, url: string): Promise<() => void> {
  const pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (event) => {
    video.srcObject = event.streams[0];
  };
  await negotiate(pc, url);
  return () => pc.close();
}

export async function publishWhip(url: string, deviceId: string): Promise<() => void> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { deviceId: { exact: deviceId } },
    audio: false,
  });
  const pc = new RTCPeerConnection();
  for (const track of stream.getTracks()) pc.addTrack(track, stream);
  await negotiate(pc, url);
  return () => {
    pc.close();
    stream.getTracks().forEach((t) => t.stop());
  };
}
