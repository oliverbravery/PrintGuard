export function cameraApi(): MediaDevices {
  if (!navigator.mediaDevices) {
    throw new Error("cameras are blocked on insecure pages — open PrintGuard over HTTPS or on localhost");
  }
  return navigator.mediaDevices;
}

export async function listVideoInputs(): Promise<MediaDeviceInfo[]> {
  const primer = await cameraApi().getUserMedia({ video: true, audio: false });
  primer.getTracks().forEach((t) => t.stop());
  return (await cameraApi().enumerateDevices()).filter((d) => d.kind === "videoinput");
}
