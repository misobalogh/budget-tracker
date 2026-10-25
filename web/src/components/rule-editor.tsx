import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { Amount, CategoryBadge, ErrorState, MatchChips, TxDetail } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useDebounced } from "@/hooks/use-debounced"
import {
  api,
  type Group,
  type MatchField,
  type Meta,
  type Rule,
  type RuleDraft,
  type Sign,
  type Transaction,
} from "@/lib/api"
import { GROUP_LABELS, formatDate, humanize } from "@/lib/format"

const NEW_CATEGORY = "__new__"
const ANY_SIGN = "any"
const NEW_NAME_RE = /^[a-z][a-z0-9_]*$/

/** What the sheet edits: a new rule seeded from a transaction, or an existing rule. */
export type RuleTarget = { kind: "create"; tx: Transaction } | { kind: "edit"; rule: Rule }

const FIELDS: { field: MatchField; label: string; hint: string }[] = [
  { field: "counterparty", label: "Counterparty", hint: "merchant or person" },
  { field: "message", label: "Message", hint: "text for the recipient" },
  { field: "raw_category", label: "Transaction type", hint: "e.g. platba kartou" },
]

function initialDraft(target: RuleTarget): RuleDraft {
  if (target.kind === "edit") {
    const { match, sign } = target.rule
    return {
      counterparty: match.counterparty ?? "",
      message: match.message ?? "",
      raw_category: match.raw_category ?? "",
      sign,
    }
  }
  const { tx } = target
  const counterparty = tx.suggested_pattern ?? ""
  // without a counterparty (e.g. cash withdrawal) fall back to the transaction type
  return { counterparty, message: "", raw_category: counterparty ? "" : tx.raw_category.toLowerCase(), sign: null }
}

function RuleForm({
  target,
  meta,
  onDone,
  onEditRule,
}: {
  target: RuleTarget
  meta: Meta
  onDone: () => void
  onEditRule: (rule: Rule) => void
}) {
  const queryClient = useQueryClient()
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules })
  const editing = target.kind === "edit" ? target.rule : null
  const tx = target.kind === "create" ? target.tx : null
  const currentRule = tx && tx.rule_index !== null ? rules.data?.rules[tx.rule_index] : undefined

  const [draft, setDraft] = useState<RuleDraft>(() => initialDraft(target))
  const [category, setCategory] = useState(editing?.category ?? "")
  const [newName, setNewName] = useState("")
  const [newGroup, setNewGroup] = useState<Group>(tx && tx.amount > 0 ? "income" : "variable")
  const setField = (field: MatchField, value: string) => setDraft((d) => ({ ...d, [field]: value }))

  const isNew = category === NEW_CATEGORY
  const chosen = isNew ? (NEW_NAME_RE.test(newName.trim()) ? newName.trim() : "") : category
  const hasPattern = FIELDS.some(({ field }) => draft[field].trim() !== "")
  const body = {
    ...draft,
    category: chosen || undefined,
    new_group: isNew ? newGroup : null,
    replace_index: editing ? editing.index : null,
  }
  const debouncedBody = useDebounced(JSON.stringify(body))
  const preview = useQuery({
    queryKey: ["rule-preview", debouncedBody],
    queryFn: () => api.previewRule(JSON.parse(debouncedBody)),
    enabled: hasPattern,
    retry: false,
  })

  const save = useMutation({
    mutationFn: () => {
      const write = { ...draft, category: chosen, new_group: isNew ? newGroup : null }
      return editing ? api.updateRule(editing.index, write) : api.createRule(write)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries()
      onDone()
    },
  })

  const canSave = hasPattern && chosen !== "" && !preview.isError
  const data = preview.data

  return (
    <form
      className="flex h-full flex-col"
      onSubmit={(e) => {
        e.preventDefault()
        if (canSave) save.mutate()
      }}
    >
      <div className="flex-1 space-y-5 overflow-y-auto px-4">
        {tx && (
          <div className="space-y-3">
            <div className="rounded-lg border bg-muted/40 p-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <TxDetail tx={tx} />
                <Amount value={tx.amount} className="font-medium" />
              </div>
              <div className="mt-1 text-xs text-muted-foreground">{formatDate(tx.date)}</div>
            </div>
            {tx.category && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Currently</span>
                <CategoryBadge category={tx.category} group={tx.group} />
                {currentRule ? (
                  <>
                    <span className="text-muted-foreground">by rule #{currentRule.index + 1}</span>
                    <Button type="button" variant="link" size="sm" className="h-auto px-0" onClick={() => onEditRule(currentRule)}>
                      Edit that rule instead
                    </Button>
                    <div className="w-full">
                      <MatchChips match={currentRule.match} sign={currentRule.sign} />
                    </div>
                  </>
                ) : null}
              </div>
            )}
          </div>
        )}

        <div className="space-y-3">
          {FIELDS.map(({ field, label, hint }) => (
            <div key={field} className="space-y-1.5">
              <Label htmlFor={`rule-${field}`}>
                {label} <span className="font-normal text-muted-foreground">({hint})</span>
              </Label>
              <Input
                id={`rule-${field}`}
                value={draft[field]}
                onChange={(e) => setField(field, e.target.value)}
                className="font-mono"
                spellCheck={false}
                autoFocus={field === "counterparty"}
              />
            </div>
          ))}
          <p className="text-xs text-muted-foreground">
            Case-insensitive regex matched anywhere in the text; use <code>|</code> for alternatives, e.g.{" "}
            <code>lidl|tesco</code>. When several fields are filled, all of them must match.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label>Amount</Label>
            <Select
              value={draft.sign ?? ANY_SIGN}
              onValueChange={(v) => setDraft((d) => ({ ...d, sign: v === ANY_SIGN ? null : (v as Sign) }))}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ANY_SIGN}>Any</SelectItem>
                <SelectItem value="negative">Outgoing only</SelectItem>
                <SelectItem value="positive">Incoming only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Category</Label>
            <Select value={category} onValueChange={setCategory}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Choose a category" />
              </SelectTrigger>
              <SelectContent>
                {meta.categories.map((c) => (
                  <SelectItem key={c.name} value={c.name}>
                    {humanize(c.name)} <span className="text-muted-foreground">({GROUP_LABELS[c.group]})</span>
                  </SelectItem>
                ))}
                <SelectItem value={NEW_CATEGORY}>+ New category...</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        {isNew && (
          <div className="grid grid-cols-2 gap-3">
            <Input
              placeholder="name, e.g. travel"
              value={newName}
              onChange={(e) => setNewName(e.target.value.toLowerCase().replace(/\s+/g, "_"))}
            />
            <Select value={newGroup} onValueChange={(v) => setNewGroup(v as Group)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {meta.groups.map((g) => (
                  <SelectItem key={g} value={g}>
                    {GROUP_LABELS[g]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="space-y-2">
          <div className="text-sm font-medium">Impact</div>
          {!hasPattern && <p className="text-sm text-muted-foreground">Fill in a pattern to see what it would change.</p>}
          {preview.isError && <ErrorState error={preview.error} />}
          {data && (
            <div className="rounded-lg border">
              <div className="space-y-1 border-b px-3 py-2 text-sm">
                <div>
                  Matches <span className="font-semibold">{data.count}</span> transactions across all months.
                </div>
                {chosen === "" ? (
                  <div className="text-muted-foreground">Choose a category to see which transactions would move.</div>
                ) : data.changed === 0 ? (
                  <div className="text-muted-foreground">No transaction would change its category.</div>
                ) : (
                  <div>
                    <span className="font-semibold">{data.changed}</span> would change category:
                    <ul className="mt-1 text-xs text-muted-foreground">
                      {data.moves.map((m) => (
                        <li key={`${m.from}-${m.to}`}>
                          {m.from ? humanize(m.from) : "Uncategorized"} &rarr; {m.to ? humanize(m.to) : "Uncategorized"}{" "}
                          <span className="tabular-nums">&times;{m.count}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
              {data.sample.length > 0 && (
                <div className="max-h-60 divide-y overflow-y-auto">
                  {data.sample.map((t) => (
                    <div key={t.id} className="flex items-center justify-between gap-3 px-3 py-1.5 text-xs">
                      <span className="w-20 shrink-0 text-muted-foreground">{t.date}</span>
                      <span className="min-w-0 flex-1 truncate">{t.counterparty}</span>
                      <span className="shrink-0 text-muted-foreground">
                        {t.category ? humanize(t.category) : "Uncategorized"} &rarr;{" "}
                        {t.new_category ? humanize(t.new_category) : "Uncategorized"}
                      </span>
                      <Amount value={t.amount} />
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {save.isError && <ErrorState error={save.error} />}
      </div>

      <SheetFooter className="border-t">
        <Button type="submit" disabled={!canSave || save.isPending}>
          {save.isPending ? "Saving..." : editing ? "Save changes" : "Save rule"}
        </Button>
        <p className="text-xs text-muted-foreground">
          {editing
            ? `Rule #${editing.index + 1} is changed in place in rules.yaml.`
            : "The rule is added to the top of rules.yaml, so it wins over existing rules. Past transactions are re-categorized too."}
        </p>
      </SheetFooter>
    </form>
  )
}

/** Side panel to create or edit a rule. Controlled: target null means closed. */
export function RuleSheet({
  target,
  meta,
  onTarget,
}: {
  target: RuleTarget | null
  meta: Meta
  onTarget: (target: RuleTarget | null) => void
}) {
  const key = !target ? "closed" : target.kind === "edit" ? `edit-${target.rule.index}` : `create-${target.tx.id}`
  const changing = target?.kind === "create" && target.tx.category !== null
  const title = !target ? "" : target.kind === "edit" ? `Edit rule #${target.rule.index + 1}` : changing ? "Change category" : "New rule"
  const description =
    target?.kind === "edit"
      ? "Changes apply to every transaction this rule matches, in all months."
      : "Categorize this transaction and every transaction that matches the pattern."

  return (
    <Sheet open={target !== null} onOpenChange={(open) => !open && onTarget(null)}>
      <SheetContent className="w-full gap-0 sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        {target && (
          <RuleForm
            key={key}
            target={target}
            meta={meta}
            onDone={() => onTarget(null)}
            onEditRule={(rule) => onTarget({ kind: "edit", rule })}
          />
        )}
      </SheetContent>
    </Sheet>
  )
}
