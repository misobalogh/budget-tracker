import { useQuery } from "@tanstack/react-query"
import { ArrowRight } from "lucide-react"
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, XAxis, YAxis } from "recharts"

import { BudgetBar } from "@/components/budgets"
import { Amount, EmptyState, ErrorState, GroupDot } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart"
import { api, type Group, type Meta, type Summary } from "@/lib/api"
import {
  GROUP_COLORS,
  GROUP_LABELS,
  UNCATEGORIZED_COLOR,
  categoryColor,
  formatMoney,
  humanize,
} from "@/lib/format"
import { UNCATEGORIZED, useDrillDown } from "@/lib/navigation"
import { cn } from "@/lib/utils"

const chartConfig = { amount: { label: "Spent" } } satisfies ChartConfig

interface Slice {
  key: string // category name or UNCATEGORIZED
  name: string
  group: Group | null
  amount: number // positive = spent
  color: string
}

/** Expense slices of the month, largest first, uncategorized last. */
function expenseSlices(summary: Summary, meta: Meta): Slice[] {
  const order = meta.categories.map((c) => c.name)
  const slices: Slice[] = summary.by_category
    .filter((c) => c.amount < 0 && (c.group === "fixed" || c.group === "variable"))
    .map((c) => ({
      key: c.category,
      name: humanize(c.category),
      group: c.group,
      amount: -c.amount,
      color: categoryColor(order.indexOf(c.category)),
    }))
    .sort((a, b) => b.amount - a.amount)
  if (summary.uncategorized_expenses < 0) {
    slices.push({
      key: UNCATEGORIZED,
      name: "Uncategorized",
      group: null,
      amount: -summary.uncategorized_expenses,
      color: UNCATEGORIZED_COLOR,
    })
  }
  return slices
}

function SliceTooltip({ slice, total }: { slice: Slice; total: number }) {
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
      <div className="font-medium">{slice.name}</div>
      <div className="text-muted-foreground">
        {slice.group ? GROUP_LABELS[slice.group] : "No rule yet"} &middot; {formatMoney(-slice.amount)} &middot;{" "}
        {((slice.amount / total) * 100).toFixed(1)} %
      </div>
      <div className="mt-1 text-muted-foreground">Click to see transactions</div>
    </div>
  )
}

function StatCard({
  label,
  value,
  hint,
  group,
  month,
}: {
  label: string
  value: number
  hint?: string
  group?: Group
  month: string
}) {
  const drillDown = useDrillDown()
  const clickable = group !== undefined
  return (
    <Card
      className={cn("gap-1 py-4", clickable && "cursor-pointer transition-colors hover:bg-muted/50")}
      onClick={clickable ? () => drillDown({ month, group }) : undefined}
    >
      <CardHeader className="px-4">
        <CardDescription className="flex items-center gap-2">
          {group && <GroupDot group={group} />}
          {label}
        </CardDescription>
      </CardHeader>
      <CardContent className="px-4">
        <Amount value={value} className="text-2xl font-semibold tracking-tight" />
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  )
}

function SpendingBars({ slices, total, onPick }: { slices: Slice[]; total: number; onPick: (s: Slice) => void }) {
  return (
    <ChartContainer config={chartConfig} className="aspect-auto w-full" style={{ height: slices.length * 36 + 16 }}>
      <BarChart data={slices} layout="vertical" margin={{ left: 8, right: 96 }}>
        <XAxis type="number" hide />
        <YAxis type="category" dataKey="name" width={120} tickLine={false} axisLine={false} />
        <ChartTooltip
          cursor={{ fill: "var(--muted)" }}
          content={({ payload }) => {
            const slice = payload?.[0]?.payload as Slice | undefined
            return slice ? <SliceTooltip slice={slice} total={total} /> : null
          }}
        />
        <Bar dataKey="amount" radius={4} barSize={22} className="cursor-pointer" onClick={(entry) => onPick(entry.payload as Slice)}>
          {slices.map((s) => (
            <Cell key={s.key} fill={s.group ? GROUP_COLORS[s.group] : UNCATEGORIZED_COLOR} />
          ))}
          <LabelList
            dataKey="amount"
            position="right"
            className="fill-foreground text-xs tabular-nums"
            formatter={(v) => formatMoney(-Number(v))}
          />
        </Bar>
      </BarChart>
    </ChartContainer>
  )
}

function SpendingPie({ slices, total, onPick }: { slices: Slice[]; total: number; onPick: (s: Slice) => void }) {
  return (
    <div className="space-y-4">
      <ChartContainer config={chartConfig} className="mx-auto aspect-square max-h-64">
        <PieChart>
          <ChartTooltip
            content={({ payload }) => {
              const slice = payload?.[0]?.payload as Slice | undefined
              return slice ? <SliceTooltip slice={slice} total={total} /> : null
            }}
          />
          <Pie
            data={slices}
            dataKey="amount"
            nameKey="name"
            innerRadius="55%"
            strokeWidth={2}
            stroke="var(--card)"
            className="cursor-pointer"
            onClick={(entry) => onPick(entry.payload as Slice)}
          >
            {slices.map((s) => (
              <Cell key={s.key} fill={s.color} />
            ))}
          </Pie>
        </PieChart>
      </ChartContainer>
      <div className="max-h-56 space-y-0.5 overflow-y-auto">
        {slices.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => onPick(s)}
            className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-muted"
          >
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: s.color }} />
            <span className="flex-1 truncate">{s.name}</span>
            <span className="text-xs tabular-nums text-muted-foreground">{((s.amount / total) * 100).toFixed(1)} %</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function BudgetsCard({ month, onOpen }: { month: string; onOpen: () => void }) {
  const drillDown = useDrillDown()
  const { data } = useQuery({ queryKey: ["budgets", month], queryFn: () => api.budgets(month) })
  if (!data || data.items.length === 0) return null

  const rank = { over: 0, warning: 1, ok: 2 }
  const shown = [...data.items].sort((a, b) => rank[a.status] - rank[b.status] || b.ratio - a.ratio).slice(0, 4)
  const over = data.items.filter((i) => i.status === "over").length

  return (
    <Card>
      <CardHeader>
        <CardTitle>Budgets</CardTitle>
        <CardDescription>
          {over === 0 ? "All within limits." : `${over} over the limit.`} Most used shown first.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {shown.map((item) => (
          <BudgetBar
            key={`${item.kind}:${item.key}`}
            item={item}
            onClick={
              item.kind === "total"
                ? undefined
                : () => drillDown(item.kind === "group" ? { month, group: item.key as "fixed" | "variable" } : { month, category: item.key! })
            }
          />
        ))}
        <Button variant="link" size="sm" className="h-auto px-0" onClick={onOpen}>
          All budgets
        </Button>
      </CardContent>
    </Card>
  )
}

export function Overview({ month, meta, onOpenBudgets }: { month: string; meta: Meta; onOpenBudgets: () => void }) {
  const drillDown = useDrillDown()
  const { data: summary, error, isPending } = useQuery({
    queryKey: ["summary", month],
    queryFn: () => api.summary(month),
  })

  if (error) return <ErrorState error={error} />
  if (isPending || !summary) return <EmptyState>Loading...</EmptyState>

  const slices = expenseSlices(summary, meta)
  const total = slices.reduce((sum, s) => sum + s.amount, 0)
  const pick = (s: Slice) => drillDown({ month, category: s.key })
  const income = summary.by_category.filter((c) => c.amount > 0)

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Income" value={summary.income} group="income" month={month} />
        <StatCard label="Fixed" value={summary.fixed} group="fixed" month={month} />
        <StatCard label="Variable" value={summary.variable} group="variable" month={month} />
        <StatCard
          label="Balance"
          value={summary.balance}
          month={month}
          hint={summary.transfer !== 0 ? `Transfers ${formatMoney(summary.transfer)} not counted` : undefined}
        />
      </div>

      {summary.uncategorized_count > 0 && (
        <button
          type="button"
          onClick={() => drillDown({ month, category: UNCATEGORIZED })}
          className="flex w-full items-center justify-between rounded-lg border border-dashed px-4 py-3 text-left text-sm transition-colors hover:bg-muted"
        >
          <span>
            <span className="font-medium">{summary.uncategorized_count} uncategorized transactions</span>
            <span className="text-muted-foreground"> are counted as variable expenses or income.</span>
          </span>
          <ArrowRight className="size-4 text-muted-foreground" />
        </button>
      )}

      {slices.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState>No expenses this month.</EmptyState>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Spending by category</CardTitle>
              <CardDescription>
                {formatMoney(-total)} in total, colored by group. Click a bar to see its transactions.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SpendingBars slices={slices} total={total} onPick={pick} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Share of spending</CardTitle>
              <CardDescription>Click a slice to see its transactions.</CardDescription>
            </CardHeader>
            <CardContent>
              <SpendingPie slices={slices} total={total} onPick={pick} />
            </CardContent>
          </Card>
        </div>
      )}

      <BudgetsCard month={month} onOpen={onOpenBudgets} />

      <Card>
        <CardHeader>
          <CardTitle>Income</CardTitle>
          <CardDescription>Including refunds in expense categories</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {income.length === 0 && summary.uncategorized_income === 0 && (
            <div className="text-sm text-muted-foreground">No income this month.</div>
          )}
          {income.map((c) => (
            <button
              key={c.category}
              type="button"
              onClick={() => drillDown({ month, category: c.category })}
              className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted"
            >
              <span className="flex items-center gap-2">
                <GroupDot group={c.group} />
                {humanize(c.category)}
              </span>
              <Amount value={c.amount} />
            </button>
          ))}
          {summary.uncategorized_income > 0 && (
            <button
              type="button"
              onClick={() => drillDown({ month, category: UNCATEGORIZED })}
              className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-sm hover:bg-muted"
            >
              <span className="text-muted-foreground">Uncategorized</span>
              <Amount value={summary.uncategorized_income} />
            </button>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
