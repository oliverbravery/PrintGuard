import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const FRAME_INTERVAL_MS = 200;
const BOUNDARY = "frame";
const feeds = new Map(
  ["healthy", "defect"].map((name) => [`/${name}.mjpg`, readFileSync(new URL(`../screenshots/frames/${name}.jpg`, import.meta.url))]),
);

createServer((request, response) => {
  const frame = feeds.get(request.url ?? "");
  if (!frame) {
    response.end();
    return;
  }
  response.writeHead(200, { "Content-Type": `multipart/x-mixed-replace; boundary=${BOUNDARY}` });
  const send = () => {
    response.write(`--${BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: ${frame.length}\r\n\r\n`);
    response.write(frame);
    response.write("\r\n");
  };
  const timer = setInterval(send, FRAME_INTERVAL_MS);
  request.on("close", () => clearInterval(timer));
}).listen(Number(process.argv[2]), "0.0.0.0");
