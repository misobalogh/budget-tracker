import type { BudgetItem, Group } from "@/lib/api"

const money = new Intl.NumberFormat("sk-SK", { style: "currency", currency: "EUR" })
const monthName = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" })
const shortMonth = new Intl.DateTimeFormat("en-GB", { month: "short", year: "2-digit" })
const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" })

export function formatMoney(value: number): string {
  return money.format(value)
}

export function formatMonth(month: string, short = false): string {
  const [year, m] = month.split("-").map(Number)
  return (short ? shortMonth : monthName).format(new Date(year, m - 1, 1))
}

export function formatDate(date: string): string {
  return day.format(new Date(`${date}T00:00:00`))
}

export const GROUP_LABELS: Record<Group, string> = {
  income: "Income",
  fixed: "Fixed",
  variable: "Variable",
  transfer: "Transfer",
}

export const GROUP_COLORS: Record<Group, string> = {
  income: "var(--chart-1)",
  fixed: "var(--chart-2)",
  variable: "var(--chart-3)",
  transfer: "var(--chart-4)",
}

export function humanize(category: string): string {
  const text = category.replace(/_/g, " ")
  return text.charAt(0).toUpperCase() + text.slice(1)
}

const compact = new Intl.NumberFormat("sk-SK", { maximumFractionDigits: 0 })

/** Whole euros with sign, e.g. "+3 286" or "-7 456". */
export function formatSignedWhole(value: number): string {
  const text = compact.format(Math.abs(Math.round(value)))
  return `${value < 0 ? "-" : "+"}${text}`
}

export const UNCATEGORIZED_COLOR = "var(--muted-foreground)"

/** Distinct, stable color per category (golden-angle hue rotation over a sorted list). */
export function categoryColor(index: number): string {
  return `oklch(0.66 0.14 ${(index * 137.5 + 20) % 360})`
}

export function budgetLabel(item: BudgetItem): string {
  if (item.kind === "total") return "All expenses"
  if (item.kind === "group") return item.key === "fixed" ? "Fixed expenses" : "Variable expenses"
  return humanize(item.key ?? "")
}
