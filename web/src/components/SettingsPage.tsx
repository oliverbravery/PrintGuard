import { Navigate, Link, useParams } from "react-router";
import { AlertsTab } from "./AlertsTab";
import { ApiTab } from "./ApiTab";
import { AppearanceTab } from "./AppearanceTab";
import { DetectionTab } from "./DetectionTab";
import { HomeAssistantTab } from "./HomeAssistantTab";
import { DetailHead, ListHead, Page, Split } from "./Page";
import { PluginsTab } from "./PluginsTab";
import { SettingsFooter } from "./SettingsFooter";
import { StorageTab } from "./StorageTab";
import { UpdatesTab } from "./UpdatesTab";

const SECTIONS = [
  { id: "appearance", label: "Appearance", body: AppearanceTab },
  { id: "alerts", label: "Alerts", body: AlertsTab },
  { id: "detection", label: "Detection", body: DetectionTab },
  { id: "plugins", label: "Plugins", body: PluginsTab },
  { id: "home-assistant", label: "Home Assistant", body: HomeAssistantTab },
  { id: "updates", label: "Updates", body: UpdatesTab },
  { id: "api", label: "API and MCP", body: ApiTab },
  { id: "storage", label: "Storage", body: StorageTab },
];

const DEFAULT_SECTION = "alerts";

export function SettingsPage() {
  const { section: chosen } = useParams();
  const section = SECTIONS.find((s) => s.id === (chosen ?? DEFAULT_SECTION));
  if (!section) return <Navigate to="/settings" replace />;
  const Body = section.body;
  const list = (
    <nav aria-label="Settings sections">
      <ListHead title="Sections" />
      {SECTIONS.map((s) => (
        <Link key={s.id} to={`/settings/${s.id}`} aria-current={s.id === section.id ? "page" : undefined} className="list-row text-sm font-semibold">
          {s.label}
        </Link>
      ))}
    </nav>
  );
  return (
    <Page title="Settings" phoneBack={chosen ? { to: "/settings", label: "Back" } : undefined} subview={Boolean(chosen)}>
      <Split
        list={list}
        detailShown={Boolean(chosen)}
        detail={
          <SettingsFooter>
            {(footer) => (
              <section aria-label={section.label}>
                <DetailHead title={section.label} />
                <div className="max-w-3xl px-4 py-4">
                  <Body key={section.id} />
                </div>
                {footer && <p className="mono truncate border-t border-line-0 px-4 py-3 text-xs text-text-2">{footer}</p>}
              </section>
            )}
          </SettingsFooter>
        }
      />
    </Page>
  );
}
