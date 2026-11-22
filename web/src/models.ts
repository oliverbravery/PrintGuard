export type ModelId = "legacy" | "light" | "standard";

export type ModelFamily = "printguard" | "obico" | "legacy";

export interface Benchmark {
  id: ModelId | "obico-2025" | "obico-2023";
  short: string;
  name: string;
  family: ModelFamily;
  mb: number;
  ms: number;
  pr: number;
  roc: number;
  r80: number;
  r90: number;
  caught: number;
  alarmed: number;
}

export const GOLD_TEST = { frames: 1534, hubs: 30, failedPrints: 20, goodPrints: 70 };

export const FAMILIES: Record<ModelFamily, { name: string; colour: string; shape: "circle" | "square" | "diamond" }> = {
  printguard: { name: "PrintGuard", colour: "var(--color-series-orange)", shape: "circle" },
  obico: { name: "Obico", colour: "var(--color-series-blue)", shape: "square" },
  legacy: { name: "PrintGuard Legacy", colour: "var(--color-series-aqua)", shape: "diamond" },
};

export const BENCHMARKS: Benchmark[] = [
  { id: "standard", short: "Standard", name: "Standard (ConvNeXt-Atto)", family: "printguard", mb: 12.9, ms: 28.7, pr: 0.722, roc: 0.92, r80: 0.606, r90: 0.462, caught: 10, alarmed: 1 },
  { id: "light", short: "Light", name: "Light (MobileNetV4-S)", family: "printguard", mb: 9.5, ms: 11.2, pr: 0.613, roc: 0.858, r80: 0.47, r90: 0.402, caught: 5, alarmed: 1 },
  { id: "obico-2025", short: "Obico 2025", name: "Obico darknet, Dec 2025", family: "obico", mb: 193, ms: 360, pr: 0.628, roc: 0.82, r80: 0.538, r90: 0.455, caught: 3, alarmed: 0 },
  { id: "obico-2023", short: "Obico 2023", name: "Obico ONNX, May 2023", family: "obico", mb: 193, ms: 359, pr: 0.603, roc: 0.816, r80: 0.5, r90: 0.341, caught: 6, alarmed: 0 },
  { id: "legacy", short: "Legacy", name: "Legacy (ShuffleNetV2)", family: "legacy", mb: 4.8, ms: 5.3, pr: 0.183, roc: 0.746, r80: 0, r90: 0, caught: 1, alarmed: 1 },
];

export const MODELS: { id: ModelId; name: string; about: string }[] = [
  { id: "standard", name: "Standard", about: "The most accurate. It catches twice as many failed prints as Light." },
  { id: "light", name: "Light", about: "About 2.5x faster than Standard, for a slower CPU or many cameras." },
  { id: "legacy", name: "Legacy", about: "The model PrintGuard started with. The fastest, but it misses most failures." },
];

export function benchmark(id: Benchmark["id"]): Benchmark {
  return BENCHMARKS.find((entry) => entry.id === id)!;
}
