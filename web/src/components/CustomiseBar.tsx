import { applyLayout, section, tiles, toggleHidden } from "../layout";
import { useStore } from "../store";
import { HiddenTray } from "./Sortable";

export function CustomiseBar() {
  const { engine, customising, mutateLayout, setCustomising, resetLayout } = useStore();
  if (!customising || !engine) return null;
  const hiddenTiles = applyLayout(tiles(engine), section(engine.settings.layout, "monitors")).hidden;
  const hiddenCameras = applyLayout(engine.cameras, section(engine.settings.layout, "cameras")).hidden;
  return (
    <div className="mx-auto max-w-[1500px] px-4 pt-5 sm:px-6">
      <div className="panel flex items-center gap-3 px-4 py-2.5">
        <span className="label">Customising, drag to reorder, pin or hide</span>
        <div className="flex-1" />
        <button className="btn btn-danger !py-1.5 !px-3 !text-[0.68rem]" onClick={resetLayout}>
          Reset layout
        </button>
        <button className="btn btn-primary !py-1.5 !px-3 !text-[0.68rem]" onClick={() => setCustomising(false)}>
          Done
        </button>
      </div>
      <HiddenTray
        label="HIDDEN"
        items={hiddenTiles}
        onShow={(id) => mutateLayout("monitors", (s) => toggleHidden(s, id))}
      />
      <HiddenTray
        label="HIDDEN CAMERAS"
        items={hiddenCameras}
        onShow={(id) => mutateLayout("cameras", (s) => toggleHidden(s, id))}
      />
    </div>
  );
}
