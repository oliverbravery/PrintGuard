import { useState, useSyncExternalStore, type ReactNode } from "react";
import { Group, Panel, Separator, useDefaultLayout, usePanelRef } from "react-resizable-panels";
import { Navigate, useParams } from "react-router";
import { applyLayout, section, tiles } from "../layout";
import { useStore } from "../store";
import { FleetFold, FleetLedger } from "./FleetLedger";
import { GettingStarted } from "./GettingStarted";
import { MonitorHero } from "./MonitorHero";
import { Page } from "./Page";
import { PluginLedger } from "./PluginPanel";

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
const FLEET_HEADER = "3.0625rem";

function HeroOverFleet({ hero, fleet }: { hero: ReactNode; fleet: ReactNode }) {
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({ id: "pg.monitors" });
  const fleetPanel = usePanelRef();
  const [folded, setFolded] = useState(false);
  const fold = { folded, toggle: () => (folded ? fleetPanel.current?.expand() : fleetPanel.current?.collapse()) };
  return (
    <Group
      orientation="vertical"
      className="page-fill"
      defaultLayout={defaultLayout}
      onLayoutChanged={onLayoutChanged}
      resizeTargetMinimumSize={{ fine: 12, coarse: 24 }}
    >
      <Panel id="hero" defaultSize="62%" minSize={HERO_MIN}>
        <div className="relative h-full overflow-y-auto max-lg:pb-2">{hero}</div>
      </Panel>
      <Separator className="splitter" aria-label="Selected monitor height" />
      <Panel
        id="fleet"
        panelRef={fleetPanel}
        minSize="9rem"
        collapsible
        collapsedSize={FLEET_HEADER}
        onResize={() => setFolded(fleetPanel.current?.isCollapsed() ?? false)}
      >
        <div className={`relative h-full scroll-pt-20 ${folded ? "overflow-hidden" : "overflow-y-auto"}`}>
          <FleetFold value={fold}>{fleet}</FleetFold>
        </div>
      </Panel>
    </Group>
  );
}

export function MonitorsPage() {
  const { monitorId } = useParams();
  const engine = useStore((s) => s.engine)!;
  const layout = section(engine.settings.layout);
  const { visible, hidden } = applyLayout(tiles(engine), layout);
  const visibleIds = visible.map((tile) => tile.id);
  const monitors = visible.flatMap((tile) => (tile.monitor ? [tile.monitor] : []));
  const panels = visible.flatMap((tile) => (tile.plugin ? [tile.plugin] : []));
  const phone = usePhone();
  const selected = monitorId ? engine.monitors.find((m) => m.id === monitorId) : monitors[0];
  if (monitorId && !selected) return <Navigate to="/" replace />;
  const pluginLedger = <PluginLedger plugins={panels} visible={visibleIds} pinned={layout.pinned} />;
  if (engine.monitors.length === 0)
    return (
      <Page title="Monitors">
        <GettingStarted />
        {(panels.length > 0 || hidden.length > 0) && <FleetLedger monitors={[]} selectedId={null} visible={visibleIds} hidden={hidden} />}
        {pluginLedger}
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
      {pluginLedger}
    </>
  );
  return (
    <Page title="Monitors" titleHidden>
      {selected && !phone ? <HeroOverFleet hero={<MonitorHero monitor={selected} />} fleet={fleet} /> : fleet}
    </Page>
  );
}
