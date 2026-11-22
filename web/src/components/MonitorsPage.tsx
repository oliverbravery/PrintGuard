import { Link, Navigate, useParams } from "react-router";
import { applyLayout, section, tiles } from "../layout";
import { useStore } from "../store";
import { FleetLedger } from "./FleetLedger";
import { GettingStarted } from "./GettingStarted";
import { useReorder } from "./LayoutControls";
import { MonitorHero } from "./MonitorHero";
import { Page } from "./Page";
import { PluginPanel } from "./PluginPanel";
import { rectSortingStrategy, Sortable } from "./Sortable";
import { monitorState, Status } from "./Status";

function Switcher({ monitors, selectedId }: { monitors: { id: string; name: string }[]; selectedId: string }) {
  const engine = useStore((s) => s.engine);
  if (monitors.length < 2) return null;
  return (
    <nav aria-label="Switch monitor" className="scroll-x flex border-b border-rule md:hidden">
      {engine?.monitors
        .filter((m) => monitors.some((shown) => shown.id === m.id))
        .map((monitor) => {
          const camera = engine.cameras.find((c) => c.id === monitor.camera_id);
          const state = monitorState(monitor, Boolean(camera?.online));
          return (
            <Link
              key={monitor.id}
              to={`/monitors/${monitor.id}`}
              replace
              aria-current={monitor.id === selectedId ? "true" : undefined}
              className="flex min-h-11 shrink-0 items-center gap-2 border-r border-line-0 px-4 text-sm font-semibold aria-[current]:bg-text-0 aria-[current]:text-ink-0"
            >
              <Status tone={state.tone}>
                <span className="sr-only">{state.text}</span>
              </Status>
              {monitor.name}
            </Link>
          );
        })}
    </nav>
  );
}

export function MonitorsPage() {
  const { monitorId } = useParams();
  const engine = useStore((s) => s.engine)!;
  const customising = useStore((s) => s.customising);
  const layout = section(engine.settings.layout);
  const { visible, hidden } = applyLayout(tiles(engine), layout);
  const visibleIds = visible.map((tile) => tile.id);
  const monitors = visible.flatMap((tile) => (tile.monitor ? [tile.monitor] : []));
  const panels = visible.flatMap((tile) => (tile.plugin ? [tile.plugin] : []));
  const panelIds = panels.map((plugin) => plugin.id);
  const reorderPanels = useReorder(visibleIds);
  const selected = monitorId ? engine.monitors.find((m) => m.id === monitorId) : monitors[0];
  if (monitorId && !selected) return <Navigate to="/" replace />;
  const panelStrip = panels.length > 0 && (
    <Sortable ids={panelIds} pinned={layout.pinned} strategy={rectSortingStrategy} disabled={!customising} onReorder={reorderPanels}>
      <div className="grid md:grid-cols-2 2xl:grid-cols-3">
        {panels.map((plugin) => (
          <PluginPanel key={plugin.id} plugin={plugin} visible={visibleIds} group={panelIds} />
        ))}
      </div>
    </Sortable>
  );
  if (engine.monitors.length === 0)
    return (
      <Page title="Monitors">
        <GettingStarted />
        {panelStrip}
      </Page>
    );
  return (
    <Page title="Monitors" titleHidden>
      {selected && <Switcher monitors={monitors} selectedId={selected.id} />}
      {selected && <MonitorHero monitor={selected} />}
      <FleetLedger monitors={monitors} selectedId={selected?.id ?? null} visible={visibleIds} hidden={hidden} />
      {panelStrip}
    </Page>
  );
}
