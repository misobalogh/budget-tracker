import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Search, X } from "lucide-react"
import { useMemo, useState } from "react"

import { Amount, CategoryBadge, EmptyState, ErrorState, TxDetail } from "@/components/common"
import { RuleSheet, type RuleTarget } from "@/components/rule-editor"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableFooter, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { useDebounced } from "@/hooks/use-debounced"
import { api, type Meta, type Transaction } from "@/lib/api"
import { GROUP_LABELS, formatDate, formatMoney, formatMonth, humanize } from "@/lib/format"
import { ALL, DEFAULT_FILTER, UNCATEGORIZED, type TxFilter } from "@/lib/navigation"
import { cn } from "@/lib/utils"

type SortKey = "date" | "amount"

function sortItems(items: Transaction[], key: SortKey, desc: boolean): Transaction[] {
  const sorted = [...items].sort((a, b) =>
    key === "date" ? a.date.localeCompare(b.date) || a.id - b.id : a.amount - b.amount,
  )
  return desc ? sorted.reverse() : sorted
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
  className,
}: {
  label: string
  column: SortKey
  sort: { key: SortKey; desc: boolean }
  onSort: (key: SortKey) => void
  className?: string
}) {
  const Icon = sort.desc ? ArrowDown : ArrowUp
  return (
    <TableHead className={className}>
      <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => onSort(column)}>
        {label}
        {sort.key === column && <Icon className="size-3.5" />}
      </button>
    </TableHead>
  )
}

/** Share of a row within its own sign: incomes vs. all incomes, expenses vs. all expenses. */
function Share({ amount, totals }: { amount: number; totals: { income: number; expenses: number } }) {
  const whole = amount >= 0 ? totals.income : -totals.expenses
  const share = whole > 0 ? Math.abs(amount) / whole : 0
  return (
    <div className="flex items-center gap-2" title={`${(share * 100).toFixed(2)} % of ${amount >= 0 ? "incoming" : "outgoing"}`}>
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", amount >= 0 ? "bg-income" : "bg-expense")}
          style={{ width: `${Math.max(share * 100, share > 0 ? 2 : 0)}%` }}
        />
      </div>
      <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
        {share >= 0.1 ? (share * 100).toFixed(0) : (share * 100).toFixed(1)} %
      </span>
    </div>
  )
}

export function Transactions({
  month,
  meta,
  filter: state,
  onFilter,
}: {
  month: string
  meta: Meta
  filter: TxFilter
  onFilter: (filter: TxFilter) => void
}) {
  const { scope, group, category, search } = state
  const set = (patch: Partial<TxFilter>) => onFilter({ ...state, ...patch })
  const [target, setTarget] = useState<RuleTarget | null>(null)
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "date", desc: true })
  const q = useDebounced(search.trim())

  const filter = {
    month: scope === "month" ? month : undefined,
    group: group === ALL ? undefined : group,
    category: category === ALL || category === UNCATEGORIZED ? undefined : category,
    uncategorized: category === UNCATEGORIZED,
    q: q || undefined,
  }
  const { data, error, isPending } = useQuery({
    queryKey: ["transactions", filter],
    queryFn: () => api.transactions(filter),
    placeholderData: keepPreviousData,
  })
  const items = useMemo(() => sortItems(data?.items ?? [], sort.key, sort.desc), [data, sort])
  const totals = useMemo(() => {
    let income = 0
    let expenses = 0
    for (const tx of data?.items ?? []) {
      if (tx.amount >= 0) income += tx.amount
      else expenses += tx.amount
    }
    return { income, expenses }
  }, [data])

  const onSort = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key === "date" }))

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search counterparty or message"
              value={search}
              onChange={(e) => set({ search: e.target.value })}
              className="pl-8"
            />
          </div>
          <Select value={scope} onValueChange={(v) => set({ scope: v as "month" | "all" })}>
            <SelectTrigger className="w-40">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="month">{formatMonth(month)}</SelectItem>
              <SelectItem value="all">All months</SelectItem>
            </SelectContent>
          </Select>
          <Select value={group} onValueChange={(v) => set({ group: v })}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All groups</SelectItem>
              {meta.groups.map((g) => (
                <SelectItem key={g} value={g}>
                  {GROUP_LABELS[g]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={category} onValueChange={(v) => set({ category: v })}>
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All categories</SelectItem>
              <SelectItem value={UNCATEGORIZED}>Uncategorized</SelectItem>
              {meta.categories.map((c) => (
                <SelectItem key={c.name} value={c.name}>
                  {humanize(c.name)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {(group !== ALL || category !== ALL || search !== "") && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onFilter({ ...DEFAULT_FILTER, scope })}
            >
              <X className="size-4" />
              Clear filters
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {error && <ErrorState error={error} />}
        {isPending && <EmptyState>Loading...</EmptyState>}
        {data && data.count === 0 && <EmptyState>No transactions match the filters.</EmptyState>}
        {data && data.count > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <SortHeader label="Date" column="date" sort={sort} onSort={onSort} className="w-28" />
                <TableHead>Transaction</TableHead>
                <TableHead className="w-40">Category</TableHead>
                <SortHeader label="Amount" column="amount" sort={sort} onSort={onSort} className="text-right" />
                <TableHead className="w-36">Share</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((tx) => (
                <TableRow
                  key={tx.id}
                  className={tx.is_private ? undefined : "cursor-pointer"}
                  onClick={() => !tx.is_private && setTarget({ kind: "create", tx })}
                  title={tx.is_private ? "Private transactions cannot be used for rules" : "Click to change the category"}
                >
                  <TableCell className="text-muted-foreground">{formatDate(tx.date)}</TableCell>
                  <TableCell className="max-w-0 w-full">
                    <TxDetail tx={tx} />
                  </TableCell>
                  <TableCell>
                    <CategoryBadge category={tx.category} group={tx.group} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Amount value={tx.amount} />
                  </TableCell>
                  <TableCell>
                    <Share amount={tx.amount} totals={totals} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            <TableFooter>
              <TableRow>
                <TableCell colSpan={3}>
                  {data.count} transactions
                  <span className="ml-3 text-xs font-normal text-muted-foreground">
                    in <span className="text-income">{formatMoney(totals.income)}</span>, out{" "}
                    <span className="text-expense">{formatMoney(totals.expenses)}</span>
                  </span>
                </TableCell>
                <TableCell className="text-right">
                  <Amount value={data.total} className="font-semibold" />
                </TableCell>
                <TableCell />
              </TableRow>
            </TableFooter>
          </Table>
        )}
      </CardContent>
      <RuleSheet target={target} meta={meta} onTarget={setTarget} />
    </Card>
  )
}
