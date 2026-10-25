import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw, Wallet } from "lucide-react"
import { useCallback } from "react"

import { EmptyState, ErrorState } from "@/components/common"
import { Budgets } from "@/components/budgets"
import { Overview } from "@/components/overview"
import { Plan } from "@/components/plan"
import { Rules } from "@/components/rules"
import { Transactions } from "@/components/transactions"
import { Trend } from "@/components/trend"
import { Uncategorized } from "@/components/uncategorized"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { api, type Meta } from "@/lib/api"
import { formatDate, formatMonth, formatSignedWhole } from "@/lib/format"
import { ALL, DEFAULT_FILTER, DrillDownContext, PAGES, type DrillDown, type Page } from "@/lib/navigation"
import { useRoute } from "@/lib/route"
import { cn } from "@/lib/utils"

function defaultMonth(meta: Meta): string | null {
  const full = meta.months.filter((m) => !m.partial)
  return (full.at(-1) ?? meta.months.at(-1))?.month ?? null
}

function Sidebar({ meta, month, onMonth }: { meta: Meta; month: string; onMonth: (m: string) => void }) {
  const queryClient = useQueryClient()
  const reload = useMutation({
    mutationFn: api.reload,
    onSuccess: () => queryClient.invalidateQueries(),
  })

  return (
    <aside className="flex w-full shrink-0 flex-col gap-6 border-b bg-card p-4 md:sticky md:top-0 md:h-screen md:w-60 md:border-r md:border-b-0">
      <div className="flex h-8 items-center gap-2 font-semibold">
        <Wallet className="size-5" />
        Budget
      </div>

      <nav className="min-h-0 space-y-1">
        <div className="px-2 pb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">Month</div>
        <div className="flex gap-1 overflow-x-auto md:max-h-[calc(100vh-14rem)] md:flex-col md:overflow-y-auto">
          {[...meta.months].reverse().map((m) => {
            const active = m.month === month
            return (
              <button
                key={m.month}
                type="button"
                onClick={() => onMonth(m.month)}
                className={cn(
                  "shrink-0 rounded-md px-2 py-1.5 text-left text-sm transition-colors",
                  active ? "bg-foreground/10" : "hover:bg-muted",
                )}
              >
                <div className={cn(active && "font-medium")}>{formatMonth(m.month)}</div>
                <div className="mt-0.5 flex gap-2 text-xs tabular-nums">
                  <span className="text-income">{formatSignedWhole(m.income)}</span>
                  <span className="text-expense">{formatSignedWhole(m.expenses)}</span>
                </div>
              </button>
            )
          })}
        </div>
      </nav>

      <div className="mt-auto space-y-3 text-xs text-muted-foreground">
        <div>
          {meta.count} transactions
          {meta.date_from && meta.date_to && (
            <div>
              {formatDate(meta.date_from)} &ndash; {formatDate(meta.date_to)}
            </div>
          )}
        </div>
        <Button variant="outline" size="sm" className="w-full" onClick={() => reload.mutate()} disabled={reload.isPending}>
          <RefreshCw className={cn("size-4", reload.isPending && "animate-spin")} />
          Reload data
        </Button>
        {reload.isError && <ErrorState error={reload.error} />}
      </div>
    </aside>
  )
}

function Header({
  month,
  page,
  onPage,
  uncategorized,
}: {
  month: string
  page: Page
  onPage: (p: Page) => void
  uncategorized: number
}) {
  return (
    <header className="sticky top-0 z-10 border-b bg-background/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-2 px-4 pt-3 md:px-8">
        <h1 className="text-xl font-semibold tracking-tight">{formatMonth(month)}</h1>
        <nav className="-mb-px flex gap-1 overflow-x-auto">
          {PAGES.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onPage(p.id)}
              className={cn(
                "flex items-center gap-1.5 border-b-2 px-3 pt-1 pb-3 text-sm font-medium whitespace-nowrap transition-colors",
                page === p.id
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {p.label}
              {p.id === "uncategorized" && uncategorized > 0 && (
                <Badge variant="secondary" className="h-5 px-1.5 tabular-nums">
                  {uncategorized}
                </Badge>
              )}
            </button>
          ))}
        </nav>
      </div>
    </header>
  )
}

export default function App() {
  const { data: meta, error } = useQuery({ queryKey: ["meta"], queryFn: api.meta })
  const [route, navigate] = useRoute()
  const { page, filter } = route

  // A month from the URL that has no data (stale link, removed export) falls back to the default.
  const month = meta ? (meta.months.some((m) => m.month === route.month) ? route.month : defaultMonth(meta)) : null
  const { data: summary } = useQuery({
    queryKey: ["summary", month],
    queryFn: () => api.summary(month!),
    enabled: month !== null,
  })

  const setPage = (next: Page) => navigate({ page: next, month: route.month, filter: DEFAULT_FILTER })
  const setMonth = (next: string) => navigate({ ...route, month: next })

  const drillDown = useCallback(
    (target: DrillDown) => {
      navigate({
        page: "transactions",
        month: target.month ?? route.month,
        filter: {
          scope: target.month ? "month" : "all",
          group: target.group ?? ALL,
          category: target.category ?? ALL,
          search: "",
        },
      })
      window.scrollTo({ top: 0 })
    },
    [navigate, route.month],
  )

  if (error) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <ErrorState error={error} />
      </div>
    )
  }
  if (!meta) return <EmptyState>Loading...</EmptyState>
  if (!month) return <EmptyState>No transactions found. Put CSV exports into the data/ directory and reload.</EmptyState>

  return (
    <DrillDownContext.Provider value={drillDown}>
      <div className="flex min-h-screen flex-col md:flex-row">
        <Sidebar meta={meta} month={month} onMonth={setMonth} />
        <div className="min-w-0 flex-1">
          <Header month={month} page={page} onPage={setPage} uncategorized={summary?.uncategorized_count ?? 0} />
          <main className="mx-auto max-w-6xl p-4 md:p-8">
            {page === "overview" && <Overview month={month} meta={meta} onOpenBudgets={() => setPage("budgets")} />}
            {page === "uncategorized" && <Uncategorized month={month} meta={meta} />}
            {page === "trend" && <Trend selectedMonth={month} />}
            {page === "budgets" && <Budgets month={month} meta={meta} />}
            {page === "plan" && <Plan month={month} meta={meta} />}
            {page === "rules" && <Rules meta={meta} />}
            {page === "transactions" && (
              <Transactions
                month={month}
                meta={meta}
                filter={filter}
                onFilter={(next) => navigate({ ...route, filter: next }, "replace")}
              />
            )}
          </main>
        </div>
      </div>
    </DrillDownContext.Provider>
  )
}
