import { createHashRouter, Navigate } from "react-router";
import { BootScreen } from "./components/BootScreen";
import { DrawFailure } from "./components/DrawFailure";
import { MonitorsPage } from "./components/MonitorsPage";
import { Shell } from "./components/Shell";

export const router = createHashRouter([
  {
    element: <Shell />,
    errorElement: <DrawFailure />,
    HydrateFallback: BootScreen,
    children: [
      { index: true, element: <MonitorsPage /> },
      { path: "monitors/:monitorId", element: <MonitorsPage /> },
      { path: "monitors/:monitorId/history", lazy: () => import("./components/HistoryPage").then((m) => ({ Component: m.HistoryPage })) },
      { path: "monitors/:monitorId/review/:reviewId?", lazy: () => import("./components/ReviewPage").then((m) => ({ Component: m.ReviewPage })) },
      { path: "prints/:printId?", lazy: () => import("./components/PrintsPage").then((m) => ({ Component: m.PrintsPage })) },
      { path: "cameras/:cameraId?", lazy: () => import("./components/CamerasPage").then((m) => ({ Component: m.CamerasPage })) },
      { path: "printers/:printerId?", lazy: () => import("./components/PrintersPage").then((m) => ({ Component: m.PrintersPage })) },
      { path: "settings/:section?/:pluginId?", lazy: () => import("./components/SettingsPage").then((m) => ({ Component: m.SettingsPage })) },
      { path: "*", element: <Navigate to="/" replace /> },
    ],
  },
]);
