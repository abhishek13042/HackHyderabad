// Hash routing for five screens: #/home, #/workbench, #/vendors/<gstin>, #/insights, #/data.

import { useEffect, useState } from "react";

export type Route =
  | { name: "home" }
  | { name: "workbench" }
  | { name: "vendor"; gstin: string }
  | { name: "insights" }
  | { name: "data" };

export function parseRoute(hash: string): Route {
  const [screen, arg] = hash.replace(/^#\/?/, "").split("/");
  switch (screen) {
    case "vendors":
      return arg ? { name: "vendor", gstin: decodeURIComponent(arg) } : { name: "workbench" };
    case "insights":
      return { name: "insights" };
    case "data":
      return { name: "data" };
    case "workbench":
      return { name: "workbench" };
    default:
      return { name: "home" };
  }
}

export function routeHash(route: Route): string {
  switch (route.name) {
    case "vendor":
      return `#/vendors/${encodeURIComponent(route.gstin)}`;
    case "workbench":
      return "#/workbench";
    default:
      return `#/${route.name}`;
  }
}

export function useHashRoute(): [Route, (route: Route) => void] {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const navigate = (next: Route) => {
    window.location.hash = routeHash(next);
  };
  return [route, navigate];
}
