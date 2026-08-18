import type { PluginTone } from "./types";

const MAX_TONES = 24;
const MAX_MS = 4000;
const SHAPES = ["sine", "square", "sawtooth", "triangle"];

let context: AudioContext | null = null;

export function playFile(url: string): void {
  const audio = new Audio(url);
  audio.volume = 0.6;
  void audio.play().catch(() => undefined);
}

export function play(tones: PluginTone[]): void {
  context ??= new AudioContext();
  void context.resume();
  const gain = context.createGain();
  gain.gain.value = 0.18;
  gain.connect(context.destination);
  let at = context.currentTime;
  let previous = at;
  const deadline = at + MAX_MS / 1000;
  for (const tone of tones.slice(0, MAX_TONES)) {
    const start = tone.together ? previous : at;
    const until = Math.min(start + Math.max(Number(tone.ms) || 0, 10) / 1000, deadline);
    if (start >= deadline) break;
    const oscillator = context.createOscillator();
    const envelope = context.createGain();
    oscillator.type = SHAPES.includes(String(tone.shape)) ? (tone.shape as OscillatorType) : "sine";
    oscillator.frequency.setValueAtTime(Math.min(Math.max(Number(tone.hz) || 0, 20), 12000), start);
    envelope.gain.setValueAtTime(0.0001, start);
    envelope.gain.exponentialRampToValueAtTime(1, start + 0.01);
    envelope.gain.exponentialRampToValueAtTime(0.0001, until);
    oscillator.connect(envelope).connect(gain);
    oscillator.start(start);
    oscillator.stop(until);
    previous = start;
    at = Math.max(at, until);
  }
}
