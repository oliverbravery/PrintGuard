import { PIXELS_MAX } from "./limits";

const isStartOfFrame = (marker: number) => marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker);
const START_OF_SCAN = 0xda;
const FRAME_HEADER_BYTES = 9;

export function isJpeg(bytes: Uint8Array): boolean {
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8 || bytes.at(-2) !== 0xff || bytes.at(-1) !== 0xd9) return false;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 2;
  while (offset + FRAME_HEADER_BYTES <= bytes.length && bytes[offset] === 0xff) {
    const marker = bytes[offset + 1];
    if (isStartOfFrame(marker)) {
      const height = view.getUint16(offset + 5);
      const width = view.getUint16(offset + 7);
      return height > 0 && width > 0 && height * width <= PIXELS_MAX;
    }
    if (marker === START_OF_SCAN) return false;
    offset += 2 + view.getUint16(offset + 2);
  }
  return false;
}
