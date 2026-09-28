// The frame: top bar, screen nav, the current screen and the memory panel.

import { lazy, Suspense } from "react";

import { MemoryPanel } from "./components/MemoryPanel";
import { TopBar } from "./components/TopBar";
import { Skeleton } from "./components/ui";
import type { Route } from "./lib/route";
import { useWorkspace } from "./lib/workspace";
import { DataScreen } from "./screens/DataScreen";
import { VendorProfile } from "./screens/VendorProfile";
import { Workbench } from "./screens/Workbench";

// The chart library is most of the bundle; load it with the Insights screen.
const Insights = lazy(() => import("./screens/Insights").then((m) => ({ default: m.Insights })));

const NAV: { name: Route["name"]; label: string; href: string }[] = [
  { name: "workbench", label: "Workbench", href: "#/workbench" },
  { name: "insights", label: "Insights", href: "#/insights" },
  { name: "data", label: "Data", href: "#/data" },
];

function Screen({ route }: { route: Route }) {
  switch (route.name) {
    case "vendor":
      return <VendorProfile key={route.gstin} gstin={route.gstin} />;
    case "insights":
      return (
        <Suspense fallback={<Skeleton rows={4} />}>
          <Insights />
        </Suspense>
      );
    case "data":
      return <DataScreen />;
    case "workbench":
      return <Workbench />;
  }
}

export function App() {
  const { route } = useWorkspace();
  // A vendor profile is reached from the workbench, so it keeps that tab lit.
  const current = route.name === "vendor" ? "workbench" : route.name;
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar />
      <div className="flex flex-1 flex-col md:flex-row">
        <nav aria-label="Screens" className="border-b border-stone-200 bg-white md:w-40 md:shrink-0 md:border-r md:border-b-0">
          <ul className="flex gap-1 p-2 md:flex-col">
            {NAV.map((item) => (
              <li key={item.name}>
                <a
                  href={item.href}
                  aria-current={current === item.name ? "page" : undefined}
                  className={`block rounded-md px-3 py-1.5 text-sm ${
                    current === item.name ? "bg-accent-50 font-medium text-accent-800" : "text-stone-600 hover:bg-stone-100"
                  }`}
                >
                  {item.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
        {/* Below 1024px the memory panel moves under the screen, so cards keep their width. */}
        <div className="flex min-w-0 flex-1 flex-col lg:flex-row">
          <main className="min-w-0 flex-1 p-4 md:p-6">
            <Screen route={route} />
          </main>
          <div className="h-80 border-t border-stone-200 lg:sticky lg:top-0 lg:h-screen lg:w-80 lg:shrink-0 lg:border-t-0">
            <MemoryPanel />
          </div>
        </div>
      </div>
    </div>
  );
}
