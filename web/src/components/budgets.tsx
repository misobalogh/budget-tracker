import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Check, Pencil, Plus, Trash2, X } from "lucide-react"
import { useState } from "react"

import { EmptyState, ErrorState } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, type BudgetConfig, type BudgetItem, type Meta } from "@/lib/api"
import { budgetLabel, formatMoney, formatMonth, humanize } from "@/lib/format"
import { withLimit } from "@/lib/budgets"
import { useDrillDown } from "@/lib/navigation"
import { cn } from "@/lib/utils"

const BAR_COLORS: Record<BudgetItem["status"], string> = {
  ok: "bg-income",
  warning: "bg-amber-500",
  over: "bg-expense",
}

/** Progress bar of one budget: how much of the monthly limit is used. */
export function BudgetBar({ item, onClick, label }: { item: BudgetItem; onClick?: () => void; label?: string }) {
  const over = item.remaining < 0
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <button
          type="button"
          onClick={onClick}
          disabled={!onClick}
          className={cn("truncate text-left font-medium", onClick && "hover:underline")}
        >
          {label ?? budgetLabel(item)}
        </button>
        <span className="shrink-0 tabular-nums text-muted-foreground">
          {formatMoney(item.spent)} / {formatMoney(item.limit)}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={Math.round(item.ratio * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={cn("h-full rounded-full transition-all", BAR_COLORS[item.status])}
          style={{ width: `${Math.min(item.ratio, 1) * 100}%` }}
        />
      </div>
      <div className="flex justify-between text-xs tabular-nums">
        <span className={cn(over ? "text-expense" : "text-muted-foreground")}>
          {over ? `${formatMoney(-item.remaining)} over` : `${formatMoney(item.remaining)} left`}
        </span>
        <span className="text-muted-foreground">{Math.round(item.ratio * 100)} %</span>
      </div>
    </div>
  )
}

function BudgetRow({
  item,
  disabled,
  onSave,
  onOpen,
}: {
  item: BudgetItem
  disabled: boolean
  onSave: (limit: number | null) => void
  onOpen?: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(String(item.limit))
  const parsed = Number(value.replace(",", "."))
  const valid = value.trim() !== "" && Number.isFinite(parsed) && parsed > 0

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <BudgetBar item={item} onClick={onOpen} />
        </div>
        <div className="flex shrink-0 gap-0.5">
          <Button
            variant="ghost"
            size="icon-sm"
            title="Change limit"
            disabled={disabled}
            onClick={() => {
              setValue(String(item.limit))
              setEditing(!editing)
            }}
          >
            <Pencil />
          </Button>
          <Button variant="ghost" size="icon-sm" title="Remove budget" disabled={disabled} onClick={() => onSave(null)}>
            <Trash2 />
          </Button>
        </div>
      </div>
      {!item.known && (
        <Badge variant="outline" className="text-amber-600 dark:text-amber-400">
          category no longer exists in rules.yaml
        </Badge>
      )}
      {editing && (
        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (!valid) return
            onSave(parsed)
            setEditing(false)
          }}
        >
          <Input
            type="number"
            inputMode="decimal"
            min="1"
            step="any"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-32"
            autoFocus
          />
          <span className="text-sm text-muted-foreground">EUR / month</span>
          <Button type="submit" size="icon-sm" disabled={!valid || disabled} title="Save">
            <Check />
          </Button>
          <Button type="button" variant="ghost" size="icon-sm" onClick={() => setEditing(false)} title="Cancel">
            <X />
          </Button>
        </form>
      )}
    </div>
  )
}

const TOTAL = "__total__"

function AddBudget({
  config,
  meta,
  disabled,
  onAdd,
}: {
  config: BudgetConfig
  meta: Meta
  disabled: boolean
  onAdd: (item: Pick<BudgetItem, "kind" | "key">, limit: number) => void
}) {
  const [target, setTarget] = useState("")
  const [value, setValue] = useState("")
  const parsed = Number(value.replace(",", "."))
  const valid = target !== "" && value.trim() !== "" && Number.isFinite(parsed) && parsed > 0

  const options: { value: string; label: string; item: Pick<BudgetItem, "kind" | "key"> }[] = []
  if (config.total === null) options.push({ value: TOTAL, label: "All expenses", item: { kind: "total", key: null } })
  for (const group of ["fixed", "variable"] as const) {
    if (!(group in config.groups)) {
      options.push({
        value: `group:${group}`,
        label: `${humanize(group)} expenses (group)`,
        item: { kind: "group", key: group },
      })
    }
  }
  for (const c of meta.categories) {
    if ((c.group === "fixed" || c.group === "variable") && !(c.name in config.categories)) {
      options.push({ value: `category:${c.name}`, label: humanize(c.name), item: { kind: "category", key: c.name } })
    }
  }
  const chosen = options.find((o) => o.value === target)

  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid && chosen) {
          onAdd(chosen.item, parsed)
          setTarget("")
          setValue("")
        }
      }}
    >
      <Select value={target} onValueChange={setTarget}>
        <SelectTrigger className="w-56">
          <SelectValue placeholder="Choose what to limit" />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        type="number"
        inputMode="decimal"
        min="1"
        step="any"
        placeholder="Limit"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="w-28"
      />
      <span className="text-sm text-muted-foreground">EUR / month</span>
      <Button type="submit" disabled={!valid || disabled}>
        <Plus />
        Add budget
      </Button>
    </form>
  )
}

export function Budgets({ month, meta }: { month: string; meta: Meta }) {
  const queryClient = useQueryClient()
  const drillDown = useDrillDown()
  const { data, error, isPending } = useQuery({ queryKey: ["budgets", month], queryFn: () => api.budgets(month) })
  const save = useMutation({
    mutationFn: (config: BudgetConfig) => api.saveBudgets(config),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["budgets"] }),
  })

  if (error) return <ErrorState error={error} />
  if (isPending || !data) return <EmptyState>Loading...</EmptyState>

  const { config, items } = data
  const overall = items.filter((i) => i.kind !== "category")
  const categories = items.filter((i) => i.kind === "category")
  const over = items.filter((i) => i.status === "over").length
  const open = (item: BudgetItem) =>
    item.kind === "total"
      ? undefined
      : () => drillDown(item.kind === "group" ? { month, group: item.key as "fixed" | "variable" } : { month, category: item.key! })
  const row = (item: BudgetItem) => (
    <BudgetRow
      key={`${item.kind}:${item.key}`}
      item={item}
      disabled={save.isPending}
      onSave={(limit) => save.mutate(withLimit(config, item, limit))}
      onOpen={open(item)}
    />
  )

  return (
    <div className="space-y-4">
      {save.isError && <ErrorState error={save.error} />}

      {items.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState>
              No budgets yet. Set a monthly limit for all expenses, a group or a category below.
            </EmptyState>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          {overall.length > 0 && (
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>{formatMonth(month)}</CardTitle>
                <CardDescription>
                  {over === 0 ? "All budgets are within their limits." : `${over} of ${items.length} budgets are over the limit.`}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-6 md:grid-cols-2">{overall.map(row)}</CardContent>
            </Card>
          )}
          {categories.length > 0 && (
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Categories</CardTitle>
              </CardHeader>
              <CardContent className="grid gap-6 md:grid-cols-2">{categories.map(row)}</CardContent>
            </Card>
          )}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Add a budget</CardTitle>
          <CardDescription>
            Limits apply to every month separately and do not carry over. Spending is net, so refunds reduce it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AddBudget
            config={config}
            meta={meta}
            disabled={save.isPending}
            onAdd={(item, limit) => save.mutate(withLimit(config, item, limit))}
          />
        </CardContent>
      </Card>
    </div>
  )
}
