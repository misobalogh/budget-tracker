// Typed client for the local FastAPI backend (budget/api.py).

export type Group = "income" | "fixed" | "variable" | "transfer"
export type MatchField = "counterparty" | "message" | "raw_category"
export type Sign = "positive" | "negative"

export interface MonthInfo {
  month: string
  count: number
  partial: boolean
  income: number
  expenses: number
}

export interface Meta {
  count: number
  date_from: string | null
  date_to: string | null
  months: MonthInfo[]
  groups: Group[]
  categories: { name: string; group: Group }[]
}

export interface Summary {
  month: string
  income: number
  fixed: number
  variable: number
  transfer: number
  balance: number
  partial: boolean
  by_category: { category: string; group: Group; amount: number }[]
  uncategorized_count: number
  uncategorized_income: number
  uncategorized_expenses: number
}

export interface TrendMonth {
  month: string
  income: number
  fixed: number
  variable: number
  transfer: number
  balance: number
  partial: boolean
}

export interface Trend {
  months: TrendMonth[]
  categories: { month: string; category: string; group: Group; amount: number }[]
}

export interface Transaction {
  id: number
  date: string
  amount: number
  currency: string
  counterparty: string
  message: string
  raw_category: string
  category: string | null
  group: Group | null
  effective_group: Group
  is_private: boolean
  rule_index: number | null
  suggested_pattern?: string | null
  new_category?: string | null
}

export interface TransactionList {
  items: Transaction[]
  total: number
  count: number
}

export interface TransactionFilter {
  month?: string
  group?: string
  category?: string
  uncategorized?: boolean
  q?: string
}

/** Conditions of a rule; empty strings mean "not used". All given patterns must match. */
export interface RuleDraft {
  counterparty: string
  message: string
  raw_category: string
  sign: Sign | null
}

export interface Rule {
  index: number
  category: string
  group: Group
  match: Partial<Record<MatchField, string>>
  sign: Sign | null
  wins: number // transactions this rule categorizes
  matches: number // transactions it matches, including those won by an earlier rule
}

export interface RulePreviewBody extends RuleDraft {
  category?: string
  new_group?: Group | null
  replace_index?: number | null
}

export interface RuleWriteBody extends RuleDraft {
  category: string
  new_group: Group | null
}

export interface RulePreview {
  count: number
  changed: number
  moves: { from: string | null; to: string | null; count: number }[]
  sample: Transaction[]
}

export type BudgetKind = "total" | "group" | "category"

export interface BudgetItem {
  kind: BudgetKind
  key: string | null // group or category name, null for the total
  limit: number
  spent: number
  remaining: number // negative when over the limit
  ratio: number
  status: "ok" | "warning" | "over"
  known: boolean // false when the category no longer exists in rules.yaml
}

export interface BudgetConfig {
  total: number | null
  groups: Record<string, number>
  categories: Record<string, number>
}

export interface BudgetsResponse {
  month: string
  config: BudgetConfig
  items: BudgetItem[]
}

export interface PlanConfig {
  income: number | null // expected monthly net income (optional, only for projections)
  savings: number | null // how much the goal rises every month
  min_balance: number | null // the account balance should stay above this
  balance: number | null // a known balance ...
  balance_date: string | null // ... at the end of this day (YYYY-MM-DD)
  start_month: string | null // planning starts here (YYYY-MM); earlier months are not used
  goals: Record<string, number> // month (YYYY-MM) -> balance wanted at its end, replaces the default
}

/** What the settings form saves; the goals are changed separately and kept as they are. */
export type PlanInput = Omit<PlanConfig, "goals">

export interface MonthGoal {
  goal: number // balance to end the month with
  source: "default" | "custom"
  opening: number // balance at the start of the month
  default: number | null // the ladder: the minimum balance plus savings, then the previous goal plus savings
  from_opening: number | null // alternative: where the month began (at least the minimum) plus the savings
}

export interface MonthPlan {
  mode: "balance" | "income" // "balance": based on the balance goal, "income": income minus savings
  goal: MonthGoal | null
  opening_balance: number | null
  transfers_out: number // money moved out of the account this month (savings, investments)
  income: number // the income that actually arrived in the month
  expected_income: number | null // optional setting, only a fallback for projections
  income_pending: number | null // expected income not received yet, for a month in progress
  savings: number | null
  available: number | null // income minus the savings target
  allocated: number // sum of the category budgets
  unallocated: number | null
  total_budget: number | null
  total_over_available: number | null
  spent: number
  remaining: number | null
  outside_budgets: number // spending not covered by a category budget, plus overspend of budgeted categories
  free_remaining: number | null // unallocated money still unused; negative once it is used up
  budget_reserved: number | null // the unused part of the category budgets, kept free for them
}

export interface SavingsMonth {
  month: string
  income: number
  expenses: number
  saved: number
  target: number | null
  difference: number | null
  met: boolean | null
}

export interface BalanceSeries {
  points: { date: string; balance: number }[]
  current: number
  current_date: string
  min_balance: number | null
  headroom: number | null
  lowest: { date: string; balance: number }
  days_below: number | null
}

/** Only present while the month is in progress, judged by the newest transaction in the data. */
export interface PlanProgress {
  as_of: string
  elapsed: number
  days_in_month: number
  days_left: number
  per_day: number | null // what can be spent per remaining day; negative when over
}

export interface PlanForecast {
  spent: number
  projected_spend: number
  projected_income: number
  projected_saved: number
  saved_vs_target: number | null
  projected_balance: number | null
  balance_vs_floor: number | null
  balance_vs_goal?: number | null
}

export interface TypicalItem {
  category: string | null // null = uncategorized
  group: Group
  average: number // per month, over the last full months
  suggested: number // average rounded to a multiple of 5
  this_month: number
  budget: number | null
}

export interface TypicalSpending {
  months: string[]
  items: TypicalItem[]
}

export interface PlanResponse {
  plan: PlanConfig
  month: MonthPlan
  progress: PlanProgress | null
  forecast: PlanForecast | null
  typical: TypicalSpending
  savings: SavingsMonth[]
  balance: BalanceSeries | null
}

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  })
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`
    try {
      const body = await resp.json()
      if (typeof body.detail === "string") detail = body.detail
    } catch {
      // keep the status text
    }
    throw new ApiError(detail)
  }
  return resp.json() as Promise<T>
}

function query(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && value !== false) search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ""
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  summary: (month: string) => request<Summary>(`/api/summary${query({ month })}`),
  trend: () => request<Trend>("/api/trend"),
  transactions: (filter: TransactionFilter) =>
    request<TransactionList>(`/api/transactions${query({ ...filter })}`),
  budgets: (month: string) => request<BudgetsResponse>(`/api/budgets${query({ month })}`),
  saveBudgets: (config: BudgetConfig) =>
    request<{ ok: boolean }>("/api/budgets", { method: "PUT", body: JSON.stringify(config) }),
  plan: (month: string) => request<PlanResponse>(`/api/plan${query({ month })}`),
  savePlan: (plan: PlanInput) =>
    request<{ ok: boolean }>("/api/plan", { method: "PUT", body: JSON.stringify(plan) }),
  setGoal: (month: string, goal: number | null) =>
    request<{ ok: boolean }>("/api/plan/goal", { method: "PUT", body: JSON.stringify({ month, goal }) }),
  rules: () => request<{ rules: Rule[] }>("/api/rules"),
  previewRule: (body: RulePreviewBody) =>
    request<RulePreview>("/api/rules/preview", { method: "POST", body: JSON.stringify(body) }),
  createRule: (body: RuleWriteBody) =>
    request<{ ok: boolean }>("/api/rules", { method: "POST", body: JSON.stringify(body) }),
  updateRule: (index: number, body: RuleWriteBody) =>
    request<{ ok: boolean }>(`/api/rules/${index}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteRule: (index: number) => request<{ ok: boolean }>(`/api/rules/${index}`, { method: "DELETE" }),
  moveRule: (index: number, direction: "up" | "down") =>
    request<{ ok: boolean }>(`/api/rules/${index}/move`, { method: "POST", body: JSON.stringify({ direction }) }),
  reload: () => request<{ ok: boolean; count: number }>("/api/reload", { method: "POST" }),
}
