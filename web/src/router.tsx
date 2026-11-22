import { createHashRouter, Navigate } from "react-router";
import { CamerasPage } from "./components/CamerasPage";
import { HistoryPage } from "./components/HistoryPage";
import { MonitorEditPage } from "./components/MonitorEditPage";
import { MonitorsPage } from "./components/MonitorsPage";
import { PrintersPage } from "./components/PrintersPage";
import { PrintsPage } from "./components/PrintsPage";
import { ReviewPage } from "./components/ReviewPage";
import { SettingsPage } from "./components/SettingsPage";
import { Shell } from "./components/Shell";

export const router = createHashRouter([
  {
    element: <Shell />,
    children: [
      { index: true, element: <MonitorsPage /> },
      { path: "monitors/:monitorId", element: <MonitorsPage /> },
      { path: "monitors/:monitorId/history", element: <HistoryPage /> },
      { path: "monitors/:monitorId/review/:reviewId", element: <ReviewPage /> },
      { path: "monitors/:monitorId/edit", element: <MonitorEditPage /> },
      { path: "prints/:printId?", element: <PrintsPage /> },
      { path: "cameras/:cameraId?", element: <CamerasPage /> },
      { path: "printers/:printerId?", element: <PrintersPage /> },
      { path: "settings/:section?", element: <SettingsPage /> },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
