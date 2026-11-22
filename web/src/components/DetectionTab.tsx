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
        Automatic benchmarks the model on both runtimes and keeps the faster. ONNX Runtime can use Core ML,
        Windows ML, OpenVINO or NVIDIA hardware. LiteRT runs on the CPU.
      </span>
      <div className="flex items-center justify-between gap-3 border border-line-0 px-3 py-2">
        <span className="text-sm text-text-1">Active compute</span>
        <span className="chip">{engine?.stats.inference_device ?? "initialising"}</span>
      </div>
      <div className="flex justify-end">
        <SaveStatus scope="settings:detection" />
      </div>
    </div>
  );
}
