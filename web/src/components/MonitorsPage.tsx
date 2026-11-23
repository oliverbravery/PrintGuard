import { Navigate, useParams } from "react-router";
import { applyLayout, section, tiles } from "../layout";
import { useStore } from "../store";
import { FleetList } from "./FleetList";
import { GettingStarted } from "./GettingStarted";
import { MonitorHero } from "./MonitorHero";
import { Page, Split } from "./Page";
import { PluginList } from "./PluginPanel";

export function MonitorsPage() {
  const { monitorId } = useParams();
  const engine = useStore((s) => s.engine)!;
  const layout = section(engine.settings.layout);
  const { visible, hidden } = applyLayout(tiles(engine), layout);
  const visibleIds = visible.map((tile) => tile.id);
  const monitors = visible.flatMap((tile) => (tile.monitor ? [tile.monitor] : []));
  const panels = visible.flatMap((tile) => (tile.plugin ? [tile.plugin] : []));
  const chosen = monitorId ? engine.monitors.find((m) => m.id === monitorId) : undefined;
  if (monitorId && !chosen) return <Navigate to="/" replace />;
  const selected = chosen ?? monitors[0];
  const list = (
    <>
      <FleetList monitors={monitors} selectedId={selected?.id ?? null} visible={visibleIds} hidden={hidden} />
      <PluginList plugins={panels} visible={visibleIds} pinned={layout.pinned} />
    </>
  );
  if (engine.monitors.length === 0)
    return (
      <Page title="Monitors">
        <GettingStarted />
        {(panels.length > 0 || hidden.length > 0) && list}
      </Page>
    );
  return (
    <Page title="Monitors" phoneBack={monitorId ? { to: "/", label: "Back" } : undefined} subview={Boolean(monitorId)}>
      <Split
        list={list}
        detail={selected ? <MonitorHero monitor={selected} /> : <p className="px-4 py-4 text-sm text-text-2">Every monitor is hidden. Press Layout to show them again.</p>}
        detailShown={Boolean(monitorId)}
      />
    </Page>
  );
}
