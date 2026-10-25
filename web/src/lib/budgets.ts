import type { BudgetConfig, BudgetItem } from "@/lib/api"

/** A copy of the config with one limit set, or removed when `limit` is null. */
export function withLimit(config: BudgetConfig, item: Pick<BudgetItem, "kind" | "key">, limit: number | null): BudgetConfig {
  const next: BudgetConfig = { total: config.total, groups: { ...config.groups }, categories: { ...config.categories } }
  if (item.kind === "total") next.total = limit
  else {
    const bucket = item.kind === "group" ? next.groups : next.categories
    if (limit === null) delete bucket[item.key!]
    else bucket[item.key!] = limit
  }
  return next
}
