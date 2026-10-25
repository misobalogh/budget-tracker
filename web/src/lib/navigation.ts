import { createContext, useContext } from "react"

import type { Group } from "@/lib/api"

export type Page = "overview" | "uncategorized" | "trend" | "transactions" | "budgets" | "plan" | "rules"

export const PAGES: { id: Page; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "uncategorized", label: "Uncategorized" },
  { id: "trend", label: "Trend" },
  { id: "transactions", label: "Transactions" },
  { id: "budgets", label: "Budgets" },
  { id: "plan", label: "Plan" },
  { id: "rules", label: "Rules" },
]

export const ALL = "__all__"
export const UNCATEGORIZED = "__uncategorized__"

export interface TxFilter {
  scope: "month" | "all"
  group: string
  category: string
  search: string
}

export const DEFAULT_FILTER: TxFilter = { scope: "month", group: ALL, category: ALL, search: "" }

/** Target of a click in a chart or table: open Transactions filtered to it. */
export interface DrillDown {
  month?: string
  group?: Group
  category?: string
}

export const DrillDownContext = createContext<(target: DrillDown) => void>(() => {})

export function useDrillDown() {
  return useContext(DrillDownContext)
}
