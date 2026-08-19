const feeds = new Map<string, HTMLVideoElement>();

export function registerFeed(cameraId: string, video: HTMLVideoElement): () => void {
  feeds.set(cameraId, video);
  return () => {
    if (feeds.get(cameraId) === video) feeds.delete(cameraId);
  };
}

export const floatSupported = (): boolean => document.pictureInPictureEnabled === true;

export function floatCamera(cameraId: string, onRefused: (reason: string) => void): void {
  const video = feeds.get(cameraId);
  if (!video) return onRefused("that camera is not on screen");
  if (video.readyState < HTMLMediaElement.HAVE_METADATA) return onRefused("that feed has not started yet");
  video.requestPictureInPicture().catch((err: Error) => onRefused(err.message));
}
