const feeds = new Map<string, HTMLVideoElement>();

export function registerFeed(cameraId: string, video: HTMLVideoElement): () => void {
  feeds.set(cameraId, video);
  return () => {
    if (feeds.get(cameraId) === video) feeds.delete(cameraId);
  };
}

export const floatSupported = (): boolean => document.pictureInPictureEnabled === true;

export async function floatCamera(cameraId: string, onClose: () => void): Promise<boolean> {
  const video = feeds.get(cameraId);
  if (!video || !floatSupported()) return false;
  try {
    await video.requestPictureInPicture();
  } catch {
    return false;
  }
  video.addEventListener("leavepictureinpicture", onClose, { once: true });
  return true;
}

export function unfloat(): void {
  if (document.pictureInPictureElement) void document.exitPictureInPicture().catch(() => undefined);
}
