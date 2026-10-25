import { useQuery } from "@tanstack/react-query"
import { Lock } from "lucide-react"
import { useState } from "react"

import { Amount, EmptyState, ErrorState, TxDetail } from "@/components/common"
import { RuleSheet, type RuleTarget } from "@/components/rule-editor"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { api, type Meta } from "@/lib/api"
import { formatDate } from "@/lib/format"

export function Uncategorized({ month, meta }: { month: string; meta: Meta }) {
  const [target, setTarget] = useState<RuleTarget | null>(null)
  const { data, error, isPending } = useQuery({
    queryKey: ["transactions", { month, uncategorized: true }],
    queryFn: () => api.transactions({ month, uncategorized: true }),
  })

  if (error) return <ErrorState error={error} />
  if (isPending || !data) return <EmptyState>Loading...</EmptyState>

  return (
    <Card>
      <CardHeader>
        <CardTitle>Uncategorized transactions</CardTitle>
        <CardDescription>
          {data.count === 0
            ? "Everything in this month is categorized."
            : "Click a transaction to create a rule for it and every similar one."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {data.count > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-28">Date</TableHead>
                <TableHead>Transaction</TableHead>
                <TableHead className="text-right">Amount</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((tx) => (
                <TableRow
                  key={tx.id}
                  className={tx.is_private ? "opacity-70" : "cursor-pointer"}
                  onClick={() => !tx.is_private && setTarget({ kind: "create", tx })}
                  title={tx.is_private ? "Private transactions cannot be used for rules" : undefined}
                >
                  <TableCell className="text-muted-foreground">{formatDate(tx.date)}</TableCell>
                  <TableCell className="max-w-0 w-full">
                    <div className="flex items-center gap-2">
                      <TxDetail tx={tx} />
                      {tx.is_private && <Lock className="ml-auto size-3.5 shrink-0 text-muted-foreground" />}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <Amount value={tx.amount} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <RuleSheet target={target} meta={meta} onTarget={setTarget} />
    </Card>
  )
}
