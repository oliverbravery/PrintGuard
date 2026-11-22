import { useSyncExternalStore, type ReactNode } from "react";
import { Group, Panel, Separator, useDefaultLayout } from "react-resizable-panels";
import { Navigate, useParams } from "react-router";
import { applyLayout, section, tiles } from "../layout";
import { useStore } from "../store";
import { FleetLedger } from "./FleetLedger";
import { GettingStarted } from "./GettingStarted";
import { useReorder } from "./LayoutControls";
import { MonitorHero } from "./MonitorHero";
import { Page } from "./Page";
import { PluginPanel } from "./PluginPanel";
import { rectSortingStrategy, Sortable } from "./Sortable";

const PHONE = "(width < 48rem)";

function usePhone(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const query = matchMedia(PHONE);
      query.addEventListener("change", onChange);
      return () => query.removeEventListener("change", onChange);
    },
    () => matchMedia(PHONE).matches,
  );
}

const HERO_MIN = "23rem";

function HeroOverFleet({ hero, fleet }: { hero: ReactNode; fleet: ReactNode }) {
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({ id: "pg.monitors" });
  return (
    <Group
      orientation="vertical"
      className="page-fill"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      resizeTargetMinimumSize={{ fine: 12, coarse: 24 }}
    >
      <Panel id="hero" defaultSize="62%" minSize={HERO_MIN}>
        <div className="h-full overflow-y-auto max-lg:pb-2">{hero}</div>
      </Panel>
      <Separator className="splitter" aria-label="Selected monitor height" />
      <Panel id="fleet" minSize="9rem">
        <div className="h-full scroll-pt-20 overflow-y-auto">{fleet}</div>
      </Panel>
    </Group>
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
  const phone = usePhone();
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
        {(panels.length > 0 || hidden.length > 0) && <FleetLedger monitors={[]} selectedId={null} visible={visibleIds} hidden={hidden} />}
        {panelStrip}
      </Page>
    );
  if (phone && monitorId && selected)
    return (
      <Page title="Monitors" back={{ to: "/", label: "Back" }} subview>
        <MonitorHero monitor={selected} />
      </Page>
    );
  const fleet = (
    <>
      <FleetLedger monitors={monitors} selectedId={phone ? null : (selected?.id ?? null)} visible={visibleIds} hidden={hidden} />
      {panelStrip}
    </>
  );
  return (
    <Page title="Monitors" titleHidden>
      {selected && !phone ? <HeroOverFleet hero={<MonitorHero monitor={selected} />} fleet={fleet} /> : fleet}
    </Page>
  );
}
