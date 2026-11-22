import { useStore } from "../store";
import { ModelPicker } from "./ModelPicker";
import { SaveStatus } from "./SaveStatus";

export function DetectionTab() {
  const { engine, updateSettings } = useStore();
  return (
    <div className="space-y-3">
      <span className="label block">Model</span>
      <ModelPicker />
      <label className="label block pt-2" htmlFor="inference-runtime">
        Runtime
      </label>
      <select
        id="inference-runtime"
        className="field w-full"
        value={engine?.settings.inference_runtime ?? "auto"}
        onChange={(event) => updateSettings({ inference_runtime: event.target.value }, "detection")}
      >
        <option value="auto">Automatic</option>
        <option value="litert">LiteRT</option>
        <option value="onnx">ONNX Runtime</option>
      </select>
      <span className="block text-sm text-text-2">
        Automatic benchmarks both runtimes at startup and keeps whichever is faster. ONNX Runtime can use Core ML,
        Windows ML, OpenVINO or NVIDIA GPUs, while LiteRT runs on CPU.
      </span>
      <dl className="grid grid-cols-3 border border-line-0">
        {[
          ["Active compute", engine?.stats.inference_device ?? "initialising"],
          ["Capacity", engine ? `${engine.stats.capacity_fps.toFixed(1)} fps` : "-"],
          ["Latency", engine ? `${engine.stats.infer_ms.toFixed(0)} ms` : "-"],
        ].map(([label, value], index) => (
          <div key={label} className={`min-w-0 px-3 py-2 ${index ? "border-l border-line-0" : ""}`}>
            <dt className="label">{label}</dt>
            <dd className="mono truncate text-sm">{value}</dd>
          </div>
        ))}
      </dl>
      <div className="flex justify-end">
        <SaveStatus scope="settings:detection" />
      </div>
    </div>
  );
}
