const feeds = new Map<string, Set<HTMLVideoElement>>();

export function registerFeed(cameraId: string, video: HTMLVideoElement): () => void {
  const showing = feeds.get(cameraId) ?? new Set<HTMLVideoElement>();
  showing.add(video);
  feeds.set(cameraId, showing);
  return () => {
    showing.delete(video);
    if (!showing.size) feeds.delete(cameraId);
  };
}

export const floatSupported = (): boolean => document.pictureInPictureEnabled === true;

export function floatCamera(cameraId: string, onRefused: (reason: string) => void): void {
  const showing = [...(feeds.get(cameraId) ?? [])].filter((video) => video.isConnected);
  if (!showing.length) return onRefused("that camera is not on screen");
  const started = showing.find((video) => video.readyState >= HTMLMediaElement.HAVE_METADATA);
  if (!started) return onRefused("that feed has not started yet");
  started.requestPictureInPicture().catch((err: Error) => onRefused(err.message));
}
