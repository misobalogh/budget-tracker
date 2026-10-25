import { useQuery } from "@tanstack/react-query"
import { useMemo, useState } from "react"
import { Bar, CartesianGrid, ComposedChart, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts"

import { Amount, EmptyState, ErrorState } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Group } from "@/lib/api"
import { formatMoney, formatMonth, humanize } from "@/lib/format"
import { useDrillDown } from "@/lib/navigation"
import { cn } from "@/lib/utils"

const overviewConfig = {
  income: { label: "Income", color: "var(--chart-1)" },
  fixed: { label: "Fixed", color: "var(--chart-2)" },
  variable: { label: "Variable", color: "var(--chart-3)" },
  balance: { label: "Balance", color: "var(--foreground)" },
} satisfies ChartConfig

const SERIES_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-5)", "var(--expense)"]
const MAX_SELECTED = SERIES_COLORS.length

function compactMoney(value: number): string {
  return new Intl.NumberFormat("sk-SK", { notation: "compact", maximumFractionDigits: 1 }).format(value)
}

const moneyTooltip = (
  <ChartTooltipContent
    formatter={(value, name, item) => (
      <div className="flex w-full items-center justify-between gap-4">
        <span className="flex items-center gap-2">
          <span className="size-2 rounded-full" style={{ background: item.color }} />
          {overviewConfig[name as keyof typeof overviewConfig]?.label ?? humanize(String(name))}
        </span>
        <span className="font-mono tabular-nums">{formatMoney(Number(value))}</span>
      </div>
    )}
  />
)

interface DotProps {
  cx?: number
  cy?: number
  stroke?: string
  payload?: { month: string }
}

/** Line dot that drills down to the transactions of its month. */
function ClickableDot({ cx, cy, stroke, payload, onPick }: DotProps & { onPick: (month: string) => void }) {
  if (cx === undefined || cy === undefined || !payload) return null
  return (
    <circle
      cx={cx}
      cy={cy}
      r={4}
      fill={stroke}
      stroke="var(--card)"
      strokeWidth={1.5}
      className="cursor-pointer"
      onClick={() => onPick(payload.month)}
    />
  )
}

function GroupCell({ month, group, value }: { month: string; group: Group; value: number }) {
  const drillDown = useDrillDown()
  return (
    <TableCell className="text-right">
      <button type="button" className="rounded px-1 hover:bg-muted" onClick={() => drillDown({ month, group })}>
        <Amount value={value} />
      </button>
    </TableCell>
  )
}

export function Trend({ selectedMonth }: { selectedMonth: string }) {
  const drillDown = useDrillDown()
  const { data, error, isPending } = useQuery({ queryKey: ["trend"], queryFn: api.trend })

  const spending = useMemo(() => {
    const totals = new Map<string, number>()
    for (const row of data?.categories ?? []) {
      if (row.group === "fixed" || row.group === "variable") {
        totals.set(row.category, (totals.get(row.category) ?? 0) - row.amount)
      }
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name)
  }, [data])

  const [picked, setPicked] = useState<string[] | null>(null)
  const selected = picked ?? spending.slice(0, 3)

  if (error) return <ErrorState error={error} />
  if (isPending || !data) return <EmptyState>Loading...</EmptyState>
  if (data.months.length === 0) return <EmptyState>No data.</EmptyState>

  const months = data.months.map((m) => ({ ...m, label: formatMonth(m.month, true) }))
  const categoryRows = months.map((m) => {
    const row: Record<string, number | string> = { label: m.label, month: m.month }
    for (const name of selected) {
      const hit = data.categories.find((c) => c.month === m.month && c.category === name)
      row[name] = hit ? -hit.amount : 0
    }
    return row
  })
  const categoryConfig = Object.fromEntries(
    selected.map((name, i) => [name, { label: humanize(name), color: SERIES_COLORS[i] }]),
  ) satisfies ChartConfig

  const toggle = (name: string) => {
    const next = selected.includes(name) ? selected.filter((n) => n !== name) : [...selected, name]
    setPicked(next.slice(-MAX_SELECTED))
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Income and expenses by month</CardTitle>
          <CardDescription>
            Expenses are shown below zero. Click a bar to see its transactions.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ChartContainer config={overviewConfig} className="aspect-auto h-80 w-full">
            <ComposedChart data={months} stackOffset="sign" margin={{ left: 8, right: 8 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} tickFormatter={compactMoney} width={48} />
              <ReferenceLine y={0} stroke="var(--border)" />
              <ChartTooltip content={moneyTooltip} />
              <ChartLegend content={<ChartLegendContent />} />
              <Bar
                dataKey="income"
                stackId="a"
                fill="var(--color-income)" radius={[4, 4, 0, 0]}
                className="cursor-pointer"
                onClick={(entry) => drillDown({ month: (entry.payload as { month: string }).month, group: "income" })}
              />
              <Bar
                dataKey="fixed"
                stackId="a"
                fill="var(--color-fixed)"
                className="cursor-pointer"
                onClick={(entry) => drillDown({ month: (entry.payload as { month: string }).month, group: "fixed" })}
              />
              <Bar
                dataKey="variable"
                stackId="a"
                fill="var(--color-variable)" radius={[0, 0, 4, 4]}
                className="cursor-pointer"
                onClick={(entry) => drillDown({ month: (entry.payload as { month: string }).month, group: "variable" })}
              />
              <Line dataKey="balance" stroke="var(--color-balance)" strokeWidth={2} dot={{ r: 3 }} />
            </ComposedChart>
          </ChartContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Spending by category over time</CardTitle>
          <CardDescription>
            Pick up to {MAX_SELECTED} categories to compare. Click a point to see its transactions.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-1.5">
            {spending.map((name) => {
              const index = selected.indexOf(name)
              return (
                <button key={name} type="button" onClick={() => toggle(name)}>
                  <Badge
                    variant={index >= 0 ? "default" : "outline"}
                    className={cn("cursor-pointer gap-1.5", index < 0 && "text-muted-foreground")}
                  >
                    {index >= 0 && <span className="size-2 rounded-full" style={{ background: SERIES_COLORS[index] }} />}
                    {humanize(name)}
                  </Badge>
                </button>
              )
            })}
          </div>
          {selected.length === 0 ? (
            <EmptyState>Select a category above.</EmptyState>
          ) : (
            <ChartContainer config={categoryConfig} className="aspect-auto h-64 w-full">
              <LineChart data={categoryRows} margin={{ left: 8, right: 8 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="label" tickLine={false} axisLine={false} />
                <YAxis tickLine={false} axisLine={false} tickFormatter={compactMoney} width={48} />
                <ChartTooltip content={moneyTooltip} />
                {selected.map((name) => (
                  <Line
                    key={name}
                    dataKey={name}
                    stroke={`var(--color-${name})`}
                    strokeWidth={2}
                    dot={(props) => (
                      <ClickableDot
                        key={`${name}-${props.index}`}
                        cx={props.cx}
                        cy={props.cy}
                        stroke={props.stroke}
                        payload={props.payload as { month: string }}
                        onPick={(month) => drillDown({ month, category: name })}
                      />
                    )}
                    activeDot={false}
                  />
                ))}
              </LineChart>
            </ChartContainer>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Monthly totals</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Month</TableHead>
                <TableHead className="text-right">Income</TableHead>
                <TableHead className="text-right">Fixed</TableHead>
                <TableHead className="text-right">Variable</TableHead>
                <TableHead className="text-right">Balance</TableHead>
                <TableHead className="text-right">Transfer</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {months.map((m) => (
                <TableRow key={m.month} className={cn(m.month === selectedMonth && "bg-muted/50")}>
                  <TableCell className="font-medium">
                    {formatMonth(m.month)}
                  </TableCell>
                  <GroupCell month={m.month} group="income" value={m.income} />
                  <GroupCell month={m.month} group="fixed" value={m.fixed} />
                  <GroupCell month={m.month} group="variable" value={m.variable} />
                  <TableCell className="text-right font-semibold"><Amount value={m.balance} /></TableCell>
                  <TableCell className="text-right text-muted-foreground">
                    <button
                      type="button"
                      className="rounded px-1 hover:bg-muted"
                      onClick={() => drillDown({ month: m.month, group: "transfer" })}
                    >
                      {formatMoney(m.transfer)}
                    </button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}
