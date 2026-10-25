import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDown, ArrowUp, Pencil, Search, Trash2 } from "lucide-react"
import { useState } from "react"

import { CategoryBadge, EmptyState, ErrorState, MatchChips } from "@/components/common"
import { RuleSheet, type RuleTarget } from "@/components/rule-editor"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Meta, type Rule } from "@/lib/api"
import { humanize } from "@/lib/format"
import { useDrillDown } from "@/lib/navigation"

function matchesSearch(rule: Rule, needle: string): boolean {
  const haystack = [rule.category, humanize(rule.category), ...Object.values(rule.match)].join(" ").toLowerCase()
  return haystack.includes(needle)
}

export function Rules({ meta }: { meta: Meta }) {
  const queryClient = useQueryClient()
  const drillDown = useDrillDown()
  const [target, setTarget] = useState<RuleTarget | null>(null)
  const [search, setSearch] = useState("")
  const [confirming, setConfirming] = useState<number | null>(null)
  const { data, error, isPending } = useQuery({ queryKey: ["rules"], queryFn: api.rules })

  const change = useMutation({
    mutationFn: (action: () => Promise<unknown>) => action(),
    onSuccess: () => queryClient.invalidateQueries(),
    onSettled: () => setConfirming(null),
  })

  if (error) return <ErrorState error={error} />
  if (isPending || !data) return <EmptyState>Loading...</EmptyState>

  const needle = search.trim().toLowerCase()
  const rules = data.rules
  const visible = needle ? rules.filter((r) => matchesSearch(r, needle)) : rules
  const last = rules.length - 1

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rules</CardTitle>
        <CardDescription>
          Rules are checked from top to bottom and the first match wins, so order matters. Changes are saved to
          rules.yaml and apply to all months at once.
        </CardDescription>
        <div className="relative max-w-sm pt-2">
          <Search className="absolute top-1/2 left-2.5 size-4 translate-y-[-30%] text-muted-foreground" />
          <Input
            placeholder="Search category or pattern"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-8"
          />
        </div>
      </CardHeader>
      <CardContent>
        {change.isError && (
          <div className="mb-3">
            <ErrorState error={change.error} />
          </div>
        )}
        {visible.length === 0 ? (
          <EmptyState>No rules match the search.</EmptyState>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10">#</TableHead>
                <TableHead className="w-44">Category</TableHead>
                <TableHead>Match</TableHead>
                <TableHead className="w-28 text-right">Transactions</TableHead>
                <TableHead className="w-44" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((rule) => {
                const shadowed = rule.matches > 0 && rule.wins === 0
                return (
                  <TableRow key={rule.index}>
                    <TableCell className="text-muted-foreground tabular-nums">{rule.index + 1}</TableCell>
                    <TableCell>
                      <button
                        type="button"
                        title="Show transactions of this category"
                        onClick={() => drillDown({ category: rule.category })}
                      >
                        <CategoryBadge category={rule.category} group={rule.group} />
                      </button>
                    </TableCell>
                    <TableCell className="max-w-0 w-full whitespace-normal">
                      <MatchChips match={rule.match} sign={rule.sign} />
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="tabular-nums">{rule.wins}</div>
                      {shadowed ? (
                        <Badge
                          variant="outline"
                          className="text-[10px] text-amber-600 dark:text-amber-400"
                          title="Every transaction matching this rule is already caught by a rule above it"
                        >
                          never used
                        </Badge>
                      ) : rule.matches === 0 ? (
                        <span className="text-[10px] text-muted-foreground">no matches</span>
                      ) : rule.matches > rule.wins ? (
                        <span
                          className="text-[10px] text-muted-foreground"
                          title="Matches that are caught by a rule above"
                        >
                          {rule.matches - rule.wins} overridden
                        </span>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-0.5">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Move up"
                          disabled={rule.index === 0 || change.isPending || needle !== ""}
                          onClick={() => change.mutate(() => api.moveRule(rule.index, "up"))}
                        >
                          <ArrowUp />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Move down"
                          disabled={rule.index === last || change.isPending || needle !== ""}
                          onClick={() => change.mutate(() => api.moveRule(rule.index, "down"))}
                        >
                          <ArrowDown />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          title="Edit rule"
                          onClick={() => setTarget({ kind: "edit", rule })}
                        >
                          <Pencil />
                        </Button>
                        {confirming === rule.index ? (
                          <Button
                            variant="destructive"
                            size="sm"
                            disabled={change.isPending}
                            onClick={() => change.mutate(() => api.deleteRule(rule.index))}
                            onBlur={() => setConfirming(null)}
                            autoFocus
                          >
                            Delete?
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            title={
                              rule.wins > 0
                                ? `Delete rule (${rule.wins} transactions lose this category)`
                                : "Delete rule"
                            }
                            onClick={() => setConfirming(rule.index)}
                          >
                            <Trash2 />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
        {needle !== "" && visible.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">Reordering is disabled while a search is active.</p>
        )}
      </CardContent>
      <RuleSheet target={target} meta={meta} onTarget={setTarget} />
    </Card>
  )
}
