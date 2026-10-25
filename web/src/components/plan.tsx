import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Pencil } from "lucide-react"
import { useState } from "react"
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts"

import { BudgetBar } from "@/components/budgets"
import { Amount, EmptyState, ErrorState } from "@/components/common"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, type ChartConfig } from "@/components/ui/chart"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  api,
  type BalanceSeries,
  type BudgetItem,
  type Meta,
  type MonthPlan,
  type PlanInput,
  type PlanForecast,
  type PlanProgress,
  type SavingsMonth,
  type TypicalItem,
  type TypicalSpending,
} from "@/lib/api"
import { withLimit } from "@/lib/budgets"
import { formatDate, formatMoney, formatMonth, humanize } from "@/lib/format"
import { UNCATEGORIZED, useDrillDown } from "@/lib/navigation"
import { cn } from "@/lib/utils"

const tickDate = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" })

function parseNumber(text: string): number | null {
  const value = text.trim() === "" ? null : Number(text.replace(",", "."))
  return value !== null && Number.isFinite(value) ? value : null
}

const toText = (value: number | null) => (value === null ? "" : String(value))

function NumberField({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string
  label: string
  hint: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          step="any"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <span className="text-sm text-muted-foreground">EUR</span>
      </div>
      <p className="text-xs text-muted-foreground">{hint}</p>
    </div>
  )
}

function SettingsCard({ plan, defaultDate }: { plan: PlanInput; defaultDate: string | null }) {
  const queryClient = useQueryClient()
  const [income, setIncome] = useState(toText(plan.income))
  const [savings, setSavings] = useState(toText(plan.savings))
  const [minBalance, setMinBalance] = useState(toText(plan.min_balance))
  const [balance, setBalance] = useState(toText(plan.balance))
  const [balanceDate, setBalanceDate] = useState(plan.balance_date ?? defaultDate ?? "")
  const [startMonth, setStartMonth] = useState(plan.start_month ?? "")

  const save = useMutation({
    mutationFn: (config: PlanInput) => api.savePlan(config),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plan"] }),
  })

  const config: PlanInput = {
    income: parseNumber(income),
    savings: parseNumber(savings),
    min_balance: parseNumber(minBalance),
    balance: parseNumber(balance),
    balance_date: parseNumber(balance) === null ? null : balanceDate || null,
    start_month: startMonth || null,
  }
  const needsDate = config.balance !== null && config.balance_date === null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your plan</CardTitle>
        <CardDescription>
          Leave a field empty to skip it. Saved to budgets.yaml and used for every month.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-5"
          onSubmit={(e) => {
            e.preventDefault()
            if (!needsDate) save.mutate(config)
          }}
        >
          <div className="grid gap-5 md:grid-cols-2">
            <NumberField
              id="plan-income"
              label="Expected monthly income (optional)"
              hint="The plan uses the income that really arrived in each month. This is only used to project the rest of a running month before the salary has arrived."
              value={income}
              onChange={setIncome}
            />
            <NumberField
              id="plan-savings"
              label="Monthly savings target"
              hint="The balance goal rises by this amount every month: the first month aims at the minimum balance plus this, the next one at that goal plus this again."
              value={savings}
              onChange={setSavings}
            />
            <div className="space-y-1.5">
              <Label htmlFor="plan-start">Start planning from</Label>
              <Input
                id="plan-start"
                type="month"
                value={startMonth}
                onChange={(e) => setStartMonth(e.target.value)}
                className="w-44"
              />
              <p className="text-xs text-muted-foreground">
                Earlier months are left out of the plan, the averages and the savings history. Needed for the balance goal.
              </p>
            </div>
            <NumberField
              id="plan-min"
              label="Keep the account balance above"
              hint="A floor for the balance; the chart warns when you go below it."
              value={minBalance}
              onChange={setMinBalance}
            />
            <div className="space-y-5">
              <NumberField
                id="plan-balance"
                label="Known account balance"
                hint="Enter it once from your bank app; the balance for other days is calculated from the transactions."
                value={balance}
                onChange={setBalance}
              />
              <div className="space-y-1.5">
                <Label htmlFor="plan-date">Balance as of the end of</Label>
                <Input
                  id="plan-date"
                  type="date"
                  value={balanceDate}
                  onChange={(e) => setBalanceDate(e.target.value)}
                  className="w-44"
                />
                <p className="text-xs text-muted-foreground">
                  Use the last day your CSV files cover, or later if nothing was booked since.
                </p>
              </div>
            </div>
          </div>
          {save.isError && <ErrorState error={save.error} />}
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={save.isPending || needsDate}>
              {save.isPending ? "Saving..." : "Save plan"}
            </Button>
            {save.isSuccess && !save.isPending && <span className="text-sm text-muted-foreground">Saved.</span>}
            {needsDate && <span className="text-sm text-expense">Choose the date of the balance.</span>}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function Row({ label, value, strong, hint }: { label: string; value: React.ReactNode; strong?: boolean; hint?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-1.5 text-sm", strong && "border-t font-semibold")}>
      <span className={cn(!strong && "text-muted-foreground")}>
        {label}
        {hint && <span className="ml-2 text-xs font-normal text-muted-foreground">{hint}</span>}
      </span>
      <span className="tabular-nums">{value}</span>
    </div>
  )
}

/** The balance goal of the month, with quick ways to change it. */
function GoalRow({ month, plan }: { month: string; plan: MonthPlan }) {
  const queryClient = useQueryClient()
  const goal = plan.goal!
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(String(goal.goal))
  const set = useMutation({
    mutationFn: (next: number | null) => api.setGoal(month, next),
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      setEditing(false)
    },
  })
  const parsed = parseNumber(value)
  const valid = parsed !== null && parsed > 0

  return (
    <div className="py-1.5 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-muted-foreground">
          Balance goal for the end of the month
          <span className="ml-2 text-xs">
            {goal.source === "custom"
              ? "set by you"
              : (plan.savings ?? 0) >= 0
                ? `${formatMoney(plan.savings ?? 0)} above the start`
                : `${formatMoney(-(plan.savings ?? 0))} below the start`}
          </span>
        </span>
        <span className="flex items-center gap-1 tabular-nums">
          {formatMoney(-goal.goal)}
          <Button
            variant="ghost"
            size="icon-sm"
            title="Change the goal"
            onClick={() => {
              setValue(String(goal.goal))
              setEditing(!editing)
            }}
          >
            <Pencil />
          </Button>
        </span>
      </div>
      {editing && (
        <div className="mt-1 space-y-2 rounded-lg border bg-muted/30 p-3">
          <form
            className="flex flex-wrap items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              if (valid) set.mutate(parsed)
            }}
          >
            <Input
              type="number"
              inputMode="decimal"
              step="any"
              min="1"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="h-8 w-32"
              autoFocus
              aria-label="Balance goal"
            />
            <span className="text-muted-foreground">EUR</span>
            <Button type="submit" size="sm" disabled={!valid || set.isPending}>
              Set goal
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </form>
          <div className="flex flex-wrap gap-2">
            {goal.source === "custom" && goal.default !== null && (
              <Button
                size="sm"
                variant="outline"
                disabled={set.isPending}
                title="The minimum balance plus the savings, then the previous goal plus the savings every month"
                onClick={() => set.mutate(null)}
              >
                Use the default {formatMoney(goal.default)}
              </Button>
            )}
            {goal.from_opening !== null && goal.from_opening !== goal.goal && (
              <Button
                size="sm"
                variant="outline"
                disabled={set.isPending}
                title="Where the month began (at least the minimum balance) plus the savings"
                onClick={() => set.mutate(goal.from_opening)}
              >
                From the opening balance: {formatMoney(goal.from_opening)}
              </Button>
            )}
          </div>
          {set.isError && <ErrorState error={set.error} />}
        </div>
      )}
    </div>
  )
}

function MonthPlanCard({
  month,
  plan,
  progress,
  startMonth,
}: {
  month: string
  plan: MonthPlan
  progress: PlanProgress | null
  startMonth: string | null
}) {
  const { available, unallocated, free_remaining: free } = plan
  // The free money is what no category budget has reserved; only spending outside budgets uses it up.
  const item: BudgetItem | null =
    unallocated === null || free === null || unallocated <= 0
      ? null
      : {
          kind: "total",
          key: null,
          limit: unallocated,
          spent: Math.max(0, plan.outside_budgets),
          remaining: free,
          ratio: Math.max(0, plan.outside_budgets) / unallocated,
          status: plan.outside_budgets > unallocated ? "over" : plan.outside_budgets >= unallocated * 0.8 ? "warning" : "ok",
          known: true,
        }

  if (startMonth && month < startMonth) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{formatMonth(month)}</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState>Planning starts in {formatMonth(startMonth)}, earlier months are not planned.</EmptyState>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{formatMonth(month)}: what is left to spend</CardTitle>
        <CardDescription>
          {plan.mode === "balance"
            ? "What you can spend this month and still end it with the balance goal. Category budgets come out of it, the rest is free money."
            : "Savings come first, then the category budgets, the rest is free money. Enter a known balance and the month to start from to plan with a balance goal."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {available === null ? (
          <EmptyState>
            Set a monthly savings target to see how much is left to spend. With a known account balance it becomes a
            balance goal for the end of each month.
          </EmptyState>
        ) : (
          <div>
            {plan.mode === "balance" && plan.goal && (
              <Row label="Balance at the start of the month" value={formatMoney(plan.opening_balance!)} />
            )}
            <Row
              label="Income this month"
              value={formatMoney(plan.income)}
              hint={plan.income_pending !== null ? `${formatMoney(plan.income_pending)} still expected` : undefined}
            />
            {plan.mode === "balance" && plan.goal ? (
              <>
                {plan.transfers_out !== 0 && (
                  <Row
                    label="Moved out of the account"
                    hint="savings, investments"
                    value={formatMoney(-plan.transfers_out)}
                  />
                )}
                <GoalRow month={month} plan={plan} />
              </>
            ) : (
              <Row label="Savings target" value={formatMoney(-plan.savings!)} />
            )}
            <Row label="Available to spend" hint="the whole month" value={formatMoney(available)} strong />
            <Row label="Spent so far" value={formatMoney(-plan.spent)} />
            <Row
              label={progress ? "Left to spend now" : plan.mode === "balance" ? "Above the goal at the end of the month" : "Left over"}
              hint={progress && plan.mode === "balance" ? "balance now minus the goal" : undefined}
              value={<Amount value={plan.remaining ?? 0} />}
              strong
            />
            {plan.budget_reserved !== null && plan.allocated > 0 && (
              <Row
                label="Kept for unused category budgets"
                hint={`${formatMoney(plan.allocated)} budgeted, ${formatMoney(plan.allocated - plan.budget_reserved)} used`}
                value={formatMoney(-plan.budget_reserved)}
              />
            )}
            <Row
              label={progress ? "Free money left to spend" : "Free money left over"}
              value={<Amount value={plan.free_remaining ?? 0} />}
              strong
            />
          </div>
        )}
        {plan.total_over_available !== null && plan.total_over_available > 0 && (
          <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-700 dark:text-amber-400">
            Your total expense budget ({formatMoney(plan.total_budget!)}) is {formatMoney(plan.total_over_available)}{" "}
            more than what is left after saving, so the savings target would be missed if you spend all of it.
          </div>
        )}
        {unallocated !== null && free !== null && (
          <div className="space-y-2">
            <div>
              <div className="text-sm font-medium">Free money used this month</div>
              <p className="text-xs text-muted-foreground">
                Spending in categories without a budget, plus anything above a category&apos;s limit, compared with the{" "}
                {formatMoney(Math.max(0, unallocated))} that no budget has claimed. Money inside a budget is already
                reserved.
              </p>
            </div>
            {item ? (
              <BudgetBar item={item} label="Outside budgets" />
            ) : (
              <p className="text-sm text-muted-foreground">
                {unallocated < 0
                  ? "The category budgets already take more than what is available."
                  : "There is no free money: the category budgets use everything that is available."}{" "}
                {plan.outside_budgets > 0 && <>{formatMoney(plan.outside_budgets)} was spent outside budgets so far.</>}
              </p>
            )}
            {progress && progress.per_day !== null && (
              <div
                className={cn(
                  "rounded-lg border px-3 py-2 text-sm",
                  progress.per_day < 0 ? "border-expense/40 bg-expense/10" : "bg-muted/40",
                )}
              >
                {progress.per_day < 0 ? (
                  <>
                    The free money is used up, you are <span className="font-semibold">{formatMoney(-free)}</span> over.
                  </>
                ) : (
                  <>
                    Outside your budgets you can spend about{" "}
                    <span className="font-semibold">{formatMoney(progress.per_day)}</span> per day for the remaining{" "}
                    {progress.days_left} {progress.days_left === 1 ? "day" : "days"}.
                  </>
                )}
                <div className="text-xs text-muted-foreground">Based on data up to {formatDate(progress.as_of)}.</div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function OutlookCard({
  forecast,
  progress,
  balance,
}: {
  forecast: PlanForecast | null
  progress: PlanProgress | null
  balance: BalanceSeries | null
}) {
  const cushion = balance?.headroom ?? null
  if (!forecast && cushion === null) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Outlook</CardTitle>
        <CardDescription>
          {forecast && progress
            ? `If you keep spending at the pace of the first ${progress.elapsed} days of the month.`
            : "Where you stand against the minimum balance."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {forecast && (
          <div>
            <Row label="Spent so far" value={formatMoney(forecast.spent)} />
            <Row label="Projected spending" value={formatMoney(forecast.projected_spend)} />
            <Row label="Projected savings" value={<Amount value={forecast.projected_saved} />} strong />
            {forecast.saved_vs_target !== null && (
              <div className={cn("pb-1.5 text-right text-xs", forecast.saved_vs_target >= 0 ? "text-income" : "text-expense")}>
                {forecast.saved_vs_target >= 0
                  ? `${formatMoney(forecast.saved_vs_target)} above the savings target`
                  : `${formatMoney(-forecast.saved_vs_target)} short of the savings target`}
              </div>
            )}
            {forecast.projected_balance !== null && (
              <>
                <Row label="Balance at month end" value={formatMoney(forecast.projected_balance)} strong />
                {forecast.balance_vs_goal != null && (
                  <div className={cn("text-right text-xs", forecast.balance_vs_goal >= 0 ? "text-income" : "text-expense")}>
                    {formatMoney(Math.abs(forecast.balance_vs_goal))} {forecast.balance_vs_goal >= 0 ? "above" : "below"}{" "}
                    the goal for this month
                  </div>
                )}
                {forecast.balance_vs_floor !== null && (
                  <div className={cn("text-right text-xs", forecast.balance_vs_floor >= 0 ? "text-income" : "text-expense")}>
                    {formatMoney(Math.abs(forecast.balance_vs_floor))}{" "}
                    {forecast.balance_vs_floor >= 0 ? "above" : "below"} the minimum balance
                  </div>
                )}
              </>
            )}
            <p className="pt-3 text-xs text-muted-foreground">
              Variable spending is extrapolated, fixed budgets that are not paid yet are added, and transfers are not
              included.
            </p>
          </div>
        )}
        {cushion !== null && (
          <div className={cn("rounded-lg border px-3 py-2 text-sm", cushion < 0 && "border-expense/40 bg-expense/10")}>
            {cushion >= 0 ? (
              <>
                You can spend <span className="font-semibold">{formatMoney(cushion)}</span> more than you earn before the
                balance reaches the minimum.
              </>
            ) : (
              <>
                The balance is <span className="font-semibold">{formatMoney(-cushion)}</span> below the minimum.
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function BudgetSetter({ item, disabled, onSet }: { item: TypicalItem; disabled: boolean; onSet: (limit: number) => void }) {
  const [value, setValue] = useState(String(item.suggested))
  const parsed = parseNumber(value)
  const valid = parsed !== null && parsed > 0
  return (
    <form
      className="flex items-center justify-end gap-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid) onSet(parsed)
      }}
    >
      <Input
        type="number"
        inputMode="decimal"
        step="any"
        min="1"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="h-7 w-24"
        aria-label={`Budget for ${humanize(item.category ?? "")}`}
      />
      <Button type="submit" size="sm" variant="outline" disabled={!valid || disabled}>
        Set budget
      </Button>
    </form>
  )
}

function TypicalCard({ month, typical, plan }: { month: string; typical: TypicalSpending; plan: MonthPlan }) {
  const queryClient = useQueryClient()
  const drillDown = useDrillDown()
  const { data: budgets } = useQuery({ queryKey: ["budgets", month], queryFn: () => api.budgets(month) })
  const save = useMutation({
    mutationFn: (config: Parameters<typeof api.saveBudgets>[0]) => api.saveBudgets(config),
    onSuccess: () => queryClient.invalidateQueries(),
  })

  const { items } = typical
  const unbudgeted = items.filter((i) => i.category !== null && i.budget === null)
  const unbudgetedTotal = unbudgeted.reduce((sum, i) => sum + i.average, 0)
  const unallocated = plan.unallocated

  return (
    <Card>
      <CardHeader>
        <CardTitle>Where your money goes</CardTitle>
        <CardDescription>
          {items.length === 0
            ? "Needs at least one full month before the selected one."
            : `Average monthly spending in ${typical.months.map((m) => formatMonth(m, true)).join(", ")}. Use it to decide where the unallocated money should go.`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {unallocated !== null && items.length > 0 && (
          <div className="rounded-lg border bg-muted/40 px-3 py-2 text-sm">
            <span className="font-semibold">{formatMoney(unallocated)}</span> is not allocated to any budget.{" "}
            {unbudgeted.length > 0 && (
              <>
                Categories without a budget cost{" "}
                <span className="font-semibold">{formatMoney(unbudgetedTotal)}</span> a month on average
                {unbudgetedTotal > unallocated && unallocated >= 0 ? ", which is more than you have left to give out" : ""}.
              </>
            )}
          </div>
        )}
        {save.isError && <ErrorState error={save.error} />}
        {items.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Average</TableHead>
                <TableHead className="text-right">This month</TableHead>
                <TableHead className="w-52 text-right">Budget</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <TableRow key={item.category ?? "uncategorized"}>
                  <TableCell>
                    <button
                      type="button"
                      className="font-medium hover:underline"
                      onClick={() =>
                        drillDown({ month, category: item.category ?? UNCATEGORIZED })
                      }
                    >
                      {item.category ? humanize(item.category) : "Uncategorized"}
                    </button>
                    {item.group === "fixed" && <span className="ml-2 text-xs text-muted-foreground">fixed</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatMoney(item.average)}</TableCell>
                  <TableCell className="text-right tabular-nums text-muted-foreground">{formatMoney(item.this_month)}</TableCell>
                  <TableCell className="text-right">
                    {item.category === null ? (
                      <span className="text-xs text-muted-foreground">add rules to budget it</span>
                    ) : item.budget !== null ? (
                      <span className="tabular-nums">{formatMoney(item.budget)}</span>
                    ) : (
                      <BudgetSetter
                        item={item}
                        disabled={save.isPending || !budgets}
                        onSet={(limit) =>
                          budgets && save.mutate(withLimit(budgets.config, { kind: "category", key: item.category }, limit))
                        }
                      />
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function SavingsCard({ rows, selected }: { rows: SavingsMonth[]; selected: string }) {
  const hasTarget = rows.some((r) => r.target !== null)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Savings by month</CardTitle>
        <CardDescription>
          Saved = income minus expenses. Money moved to savings or investments is not an expense, so it counts as saved.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!hasTarget && (
          <p className="text-sm text-muted-foreground">Set a monthly savings target above to compare it with these.</p>
        )}
        {[...rows].reverse().map((row) => {
          const ratio = row.target ? Math.min(Math.max(row.saved, 0) / row.target, 1) : 0
          return (
            <div key={row.month} className={cn("space-y-1 rounded-md px-2 py-1.5", row.month === selected && "bg-muted/60")}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-medium">{formatMonth(row.month)}</span>
                <span className="tabular-nums text-muted-foreground">
                  <Amount value={row.saved} />
                  {row.target !== null && <> / {formatMoney(row.target)}</>}
                </span>
              </div>
              {row.target !== null && (
                <>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn("h-full rounded-full", row.met ? "bg-income" : "bg-expense")}
                      style={{ width: `${ratio * 100}%` }}
                    />
                  </div>
                  <div className={cn("text-xs tabular-nums", row.met ? "text-income" : "text-expense")}>
                    {row.met
                      ? `${formatMoney(row.difference!)} above the target`
                      : `${formatMoney(-row.difference!)} short of the target`}
                  </div>
                </>
              )}
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}

const balanceConfig = { balance: { label: "Balance", color: "var(--chart-2)" } } satisfies ChartConfig

function compact(value: number): string {
  return new Intl.NumberFormat("sk-SK", { notation: "compact", maximumFractionDigits: 1 }).format(value)
}

function BalanceCard({ series }: { series: BalanceSeries | null }) {
  if (!series) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Account balance</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState>Enter a known account balance above to see the balance over time.</EmptyState>
        </CardContent>
      </Card>
    )
  }
  const floor = series.min_balance
  const below = series.headroom !== null && series.headroom < 0

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account balance</CardTitle>
        <CardDescription>
          Calculated from one known balance and all transactions in the data, so it is only as complete as the exports.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <div>
            <div className="text-xs text-muted-foreground">Balance on {formatDate(series.current_date)}</div>
            <div className="text-xl font-semibold tabular-nums">{formatMoney(series.current)}</div>
          </div>
          {series.headroom !== null && floor !== null && (
            <div>
              <div className="text-xs text-muted-foreground">Compared to {formatMoney(floor)}</div>
              <div className={cn("text-xl font-semibold tabular-nums", below ? "text-expense" : "text-income")}>
                {formatMoney(Math.abs(series.headroom))} {below ? "below" : "above"}
              </div>
            </div>
          )}
          <div>
            <div className="text-xs text-muted-foreground">Lowest, {formatDate(series.lowest.date)}</div>
            <div className="text-xl font-semibold tabular-nums">{formatMoney(series.lowest.balance)}</div>
          </div>
          {series.days_below !== null && (
            <div>
              <div className="text-xs text-muted-foreground">Days below the minimum</div>
              <div className={cn("text-xl font-semibold tabular-nums", series.days_below > 0 && "text-expense")}>
                {series.days_below}
              </div>
            </div>
          )}
        </div>
        <ChartContainer config={balanceConfig} className="aspect-auto h-72 w-full">
          <LineChart data={series.points} margin={{ left: 8, right: 16, top: 8 }}>
            <CartesianGrid vertical={false} />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              minTickGap={48}
              tickFormatter={(d: string) => tickDate.format(new Date(`${d}T00:00:00`))}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              width={48}
              tickFormatter={compact}
              domain={[
                (min: number) => Math.floor(Math.min(min, floor ?? min) / 500) * 500,
                (max: number) => Math.ceil(Math.max(max, floor ?? max) / 500) * 500,
              ]}
            />
            {floor !== null && (
              <ReferenceLine
                y={floor}
                stroke="var(--expense)"
                strokeDasharray="6 4"
                label={{ value: `Minimum ${formatMoney(floor)}`, position: "insideBottomRight", fill: "var(--expense)", fontSize: 11 }}
              />
            )}
            <ChartTooltip
              content={({ payload }) => {
                const point = payload?.[0]?.payload as { date: string; balance: number } | undefined
                if (!point) return null
                return (
                  <div className="rounded-md border bg-popover px-3 py-2 text-xs shadow-md">
                    <div className="text-muted-foreground">{formatDate(point.date)}</div>
                    <div className="font-medium tabular-nums">{formatMoney(point.balance)}</div>
                  </div>
                )
              }}
            />
            <Line dataKey="balance" type="stepAfter" stroke="var(--color-balance)" strokeWidth={2} dot={false} />
          </LineChart>
        </ChartContainer>
      </CardContent>
    </Card>
  )
}

export function Plan({ month, meta }: { month: string; meta: Meta }) {
  const { data, error, isPending } = useQuery({ queryKey: ["plan", month], queryFn: () => api.plan(month) })

  if (error) return <ErrorState error={error} />
  if (isPending || !data) return <EmptyState>Loading...</EmptyState>

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <SettingsCard key={JSON.stringify(data.plan)} plan={data.plan} defaultDate={meta.date_to} />
        <MonthPlanCard month={month} plan={data.month} progress={data.progress} startMonth={data.plan.start_month} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <OutlookCard forecast={data.forecast} progress={data.progress} balance={data.balance} />
        <div className="lg:col-span-2">
          <TypicalCard month={month} typical={data.typical} plan={data.month} />
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <SavingsCard rows={data.savings} selected={month} />
        <div className="lg:col-span-2">
          <BalanceCard series={data.balance} />
        </div>
      </div>
    </div>
  )
}
