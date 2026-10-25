import { Lock } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import type { Group, MatchField, Sign, Transaction } from "@/lib/api"
import { GROUP_COLORS, GROUP_LABELS, formatMoney, humanize } from "@/lib/format"
import { cn } from "@/lib/utils"

export function Amount({ value, className }: { value: number; className?: string }) {
  return (
    <span
      className={cn(
        "tabular-nums whitespace-nowrap",
        value > 0 ? "text-income" : value < 0 ? "text-expense" : "text-muted-foreground",
        className,
      )}
    >
      {formatMoney(value)}
    </span>
  )
}

export function GroupDot({ group }: { group: Group }) {
  return <span className="inline-block size-2 shrink-0 rounded-full" style={{ background: GROUP_COLORS[group] }} />
}

export function CategoryBadge({ category, group }: { category: string | null; group: Group | null }) {
  if (!category || !group) {
    return (
      <Badge variant="outline" className="border-dashed text-muted-foreground">
        Uncategorized
      </Badge>
    )
  }
  return (
    <Badge variant="secondary" className="gap-1.5" title={GROUP_LABELS[group]}>
      <GroupDot group={group} />
      {humanize(category)}
    </Badge>
  )
}

export function Counterparty({ tx }: { tx: Transaction }) {
  if (tx.is_private) {
    return (
      <span className="inline-flex items-center gap-1.5 italic text-muted-foreground">
        <Lock className="size-3.5" />
        Private
      </span>
    )
  }
  return <span className="font-medium">{tx.counterparty || <span className="text-muted-foreground">(none)</span>}</span>
}

export function TxDetail({ tx }: { tx: Transaction }) {
  return (
    <div className="min-w-0">
      <Counterparty tx={tx} />
      <div className="truncate text-xs text-muted-foreground" title={tx.is_private ? undefined : tx.message}>
        {tx.raw_category}
        {!tx.is_private && tx.message ? ` \u00b7 ${tx.message}` : ""}
      </div>
    </div>
  )
}

export function EmptyState({ children }: { children: React.ReactNode }) {
  return <div className="py-12 text-center text-sm text-muted-foreground">{children}</div>
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
      {error instanceof Error ? error.message : String(error)}
    </div>
  )
}

const FIELD_NAMES: Record<MatchField, string> = {
  counterparty: "counterparty",
  message: "message",
  raw_category: "type",
}

/** Conditions of a rule as small monospace chips, e.g. [counterparty: lidl|tesco] [outgoing]. */
export function MatchChips({ match, sign }: { match: Partial<Record<MatchField, string>>; sign: Sign | null }) {
  const chip = "rounded bg-muted px-1.5 py-0.5 font-mono text-xs break-all"
  return (
    <div className="flex flex-wrap gap-1">
      {(Object.keys(FIELD_NAMES) as MatchField[])
        .filter((field) => match[field])
        .map((field) => (
          <span key={field} className={chip}>
            <span className="text-muted-foreground">{FIELD_NAMES[field]}: </span>
            {match[field]}
          </span>
        ))}
      {sign && <span className={chip}>{sign === "negative" ? "outgoing" : "incoming"}</span>}
    </div>
  )
}
