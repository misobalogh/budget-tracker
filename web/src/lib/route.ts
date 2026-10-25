// Browser-history routing. The whole view state lives in the URL hash, e.g.
//   #/transactions?month=2026-09&category=groceries&q=lidl
// so the back and forward buttons, reloads and bookmarks all work. A hash is used
// (not a path) because the backend serves static files without a SPA fallback.

import { useCallback, useMemo, useSyncExternalStore } from "react"

import { ALL, DEFAULT_FILTER, PAGES, type Page, type TxFilter } from "@/lib/navigation"

export interface Route {
  page: Page
  month: string | null
  filter: TxFilter
}

export const DEFAULT_ROUTE: Route = { page: "overview", month: null, filter: DEFAULT_FILTER }

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/

export function parseHash(hash: string): Route {
  const [path = "", query = ""] = hash.replace(/^#\/?/, "").split("?")
  const page = PAGES.find((p) => p.id === path)?.id ?? DEFAULT_ROUTE.page
  const params = new URLSearchParams(query)
  const month = params.get("month")
  return {
    page,
    month: month && MONTH_RE.test(month) ? month : null,
    filter:
      page === "transactions"
        ? {
            scope: params.get("scope") === "all" ? "all" : "month",
            group: params.get("group") || ALL,
            category: params.get("category") || ALL,
            search: params.get("q") ?? "",
          }
        : DEFAULT_FILTER,
  }
}

export function formatHash(route: Route): string {
  const params = new URLSearchParams()
  if (route.month) params.set("month", route.month)
  if (route.page === "transactions") {
    const { scope, group, category, search } = route.filter
    if (scope === "all") params.set("scope", "all")
    if (group !== ALL) params.set("group", group)
    if (category !== ALL) params.set("category", category)
    if (search) params.set("q", search)
  }
  const query = params.toString()
  return `#/${route.page}${query ? `?${query}` : ""}`
}

const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  // popstate: back/forward buttons; hashchange: the user edits the address bar
  window.addEventListener("popstate", listener)
  window.addEventListener("hashchange", listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener("popstate", listener)
    window.removeEventListener("hashchange", listener)
  }
}

const getHash = () => window.location.hash

/**
 * "push" adds a history entry (page, month and drill-down changes), "replace"
 * rewrites the current one (typing in filters, so back does not step through keystrokes).
 */
export type NavigateMode = "push" | "replace"

export function useRoute(): [Route, (next: Route, mode?: NavigateMode) => void] {
  const hash = useSyncExternalStore(subscribe, getHash)
  const route = useMemo(() => parseHash(hash), [hash])

  const navigate = useCallback((next: Route, mode: NavigateMode = "push") => {
    const target = formatHash(next)
    if (target === formatHash(parseHash(window.location.hash))) return
    if (mode === "push") window.history.pushState(null, "", target)
    else window.history.replaceState(null, "", target)
    // pushState and replaceState fire no events, so notify subscribers by hand
    listeners.forEach((listener) => listener())
  }, [])

  return [route, navigate]
}
