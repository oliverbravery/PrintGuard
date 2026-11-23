import { benchmark, GOLD_TEST, MODELS } from "../models";
import { useStore } from "../store";
import { ModelChart } from "./ModelChart";
import { SaveStatus } from "./SaveStatus";

export function ModelPicker() {
  const model = useStore((s) => s.engine?.settings.model ?? "standard");
  const updateSettings = useStore((s) => s.updateSettings);
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="grid gap-2 sm:grid-cols-3" role="group" aria-label="Detection model">
          {MODELS.map((option) => {
            const stats = benchmark(option.id);
            const chosen = model === option.id;
            return (
              <button
                key={option.id}
                type="button"
                aria-pressed={chosen}
                onClick={() => updateSettings({ model: option.id }, "model")}
                className={`flex cursor-pointer flex-col gap-1 border px-3 py-2.5 text-left transition-colors ${
                  chosen ? "border-accent bg-accent/5" : "border-line-0 hover:border-line-1"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold">{option.name}</span>
                  {chosen && <span className="label text-accent">in use</span>}
                </span>
                <span className="text-xs leading-snug text-text-1">{option.about}</span>
                <span className="mono mt-auto flex flex-wrap gap-x-2 pt-1 text-xs text-text-2">
                  <span className="whitespace-nowrap">
                    Caught {stats.caught} of {GOLD_TEST.failedPrints}
                  </span>
                  <span className="whitespace-nowrap">{stats.ms} ms a frame</span>
                </span>
              </button>
            );
          })}
        </div>
        <div className="flex justify-end">
          <SaveStatus scope="settings:model" />
        </div>
      </div>
      <ModelChart selected={model} />
    </div>
  );
}
