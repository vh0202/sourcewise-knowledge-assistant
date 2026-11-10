import { ChartColumn, CircleHelp, Table2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { Page } from "../components/AppShell";
import { AllAnsweredArt, NoDataArt } from "../components/illustrations";
import { Floating } from "../components/overlays";
import { Badge, Card, CardHeader, EmptyState, ErrorNotice, IconButton, Segmented, Skeleton } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { classNames, formatDay, formatDayLong, formatDuration, formatNumber, formatPercent, formatRelative } from "../lib/format";
import { useCountUp } from "../lib/hooks";
import type { CitedDocument, DayCount, Insights, KnowledgeGap } from "../lib/types";

const RANGES = [7, 14, 30] as const;
const REASON: Record<string, string> = {
  weak_retrieval: "No matching passage",
  unsupported: "Passage did not answer it",
  refused: "Declined by the model",
};

// The two series of this page. Violet is "answered", teal is "abstained"; the pair is validated
// for colour-vision deficiency and for contrast against the card surface in both themes.
const SERIES = {
  answered: { name: "Answered", fill: "bg-series-1" },
  abstained: { name: "Abstained", fill: "bg-series-2" },
};

// -- stat tiles --------------------------------------------------------------------------------
/** A figure that counts up to its value; `format` turns the running number into text. */
function CountUp({ value, format }: { value: number; format: (value: number) => string }) {
  return <>{format(useCountUp(value))}</>;
}

/** Daily totals as a small line; the latest day carries the accent dot. */
function Sparkline({ values, label }: { values: number[]; label: string }) {
  const width = 88;
  const height = 28;
  const pad = 4;
  const max = Math.max(...values, 1);
  const step = values.length > 1 ? (width - pad * 2) / (values.length - 1) : 0;
  const points = values.map((value, index) => [pad + index * step, height - pad - (value / max) * (height - pad * 2)] as const);
  const line = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  if (!last) return null;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-7 w-[5.5rem] shrink-0 overflow-visible" role="img" aria-label={label}>
      <polygon points={`${pad},${height - pad} ${line} ${last[0].toFixed(1)},${height - pad}`} className="fill-series-1" opacity="0.1" />
      <polyline points={line} fill="none" className="stroke-series-1" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.55" />
      <circle cx={last[0]} cy={last[1]} r="3.5" className="fill-series-1 stroke-card" strokeWidth="2" />
    </svg>
  );
}

/** A share of a whole: the fill is the accent, the track a lighter step of the same hue. */
function Meter({ share, label }: { share: number; label: string }) {
  return (
    <div role="img" aria-label={label} className="mt-2.5 h-1.5 w-[5.5rem] shrink-0 overflow-hidden rounded-full bg-series-1-soft">
      <div className="h-full origin-left animate-grow-x rounded-full bg-series-1" style={{ width: `${Math.min(Math.max(share, 0), 1) * 100}%` }} />
    </div>
  );
}

/** Label and a small visual on the first line, then the figure, then what it is made of. */
function StatTile({ label, value, detail, visual }: { label: string; value: ReactNode; detail: string; visual?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-card px-4 py-4 shadow-xs sm:px-5">
      <div className="flex min-h-7 items-start justify-between gap-3">
        <p className="text-sm text-fg-muted">{label}</p>
        {visual && <div className="hidden shrink-0 sm:block">{visual}</div>}
      </div>
      <p className="mt-1.5 text-3xl font-semibold tracking-tighter text-fg">{value}</p>
      <p className="mt-1.5 text-xs text-fg-subtle">{detail}</p>
    </div>
  );
}

// -- questions per day -------------------------------------------------------------------------
function niceCeiling(value: number): number {
  // An even, round axis maximum, so that the middle tick of a count axis is a whole number.
  if (value <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 4, 6, 8, 10]) {
    const candidate = step * magnitude;
    if (candidate >= value && candidate % 2 === 0) return candidate;
  }
  return 10 * magnitude;
}

function rateOf(day: DayCount): number | null {
  const total = day.answered + day.abstained;
  return total ? day.answered / total : null;
}

type ChartMode = "count" | "share";

const PLOT_HEIGHT = 184; // px

/**
 * Stacked columns: answered (bottom) and abstained (top) per day, as counts or as shares of the
 * day's questions. Columns are capped at 24px, rounded only at the data end and separated by
 * a 2px gap in the surface colour. Each day is one hover target with a tooltip that lists both
 * series; the arrow keys move between days, and the same figures are available as a table.
 */
function DailyChart({ days, mode }: { days: DayCount[]; mode: ChartMode }) {
  const [active, setActive] = useState<number | null>(null);
  const [focusIndex, setFocusIndex] = useState(days.length - 1);
  const plot = useRef<HTMLDivElement>(null);

  const totals = days.map((day) => day.answered + day.abstained);
  const peak = Math.max(...totals, 1);
  const top = mode === "count" ? niceCeiling(peak) : 1;
  const ticks = [top, top / 2, 0];
  const labelEvery = days.length > 16 ? 5 : days.length > 8 ? 2 : 1;
  // Direct labels are sparing: the busiest day and the latest one.
  const labelled = new Set([totals.indexOf(peak), days.length - 1]);

  const dayElement = (index: number) => plot.current?.querySelectorAll<HTMLElement>("[data-day]")[index];

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>, index: number) => {
    let next = index;
    if (event.key === "ArrowRight") next = Math.min(index + 1, days.length - 1);
    else if (event.key === "ArrowLeft") next = Math.max(index - 1, 0);
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = days.length - 1;
    else if (event.key === "Escape") {
      setActive(null);
      return;
    } else return;
    event.preventDefault();
    dayElement(next)?.focus();
  };

  const activeDay = active != null ? days[active] : undefined;
  const activeRate = activeDay ? rateOf(activeDay) : null;

  return (
    <div className="flex gap-3">
      <div className="relative w-7 shrink-0 text-right text-2xs text-fg-subtle tabular-nums" style={{ height: PLOT_HEIGHT }} aria-hidden>
        {ticks.map((tick) => (
          <span key={tick} className="absolute right-0 -translate-y-1/2" style={{ top: `${(1 - tick / top) * 100}%` }}>
            {mode === "count" ? tick : formatPercent(tick)}
          </span>
        ))}
      </div>

      <div className="min-w-0 flex-1">
        <div ref={plot} className="relative" style={{ height: PLOT_HEIGHT }}>
          {ticks.map((tick) => (
            <span
              key={tick}
              aria-hidden
              className={classNames("absolute inset-x-0 h-px", tick === 0 ? "bg-chart-axis" : "bg-chart-grid")}
              style={{ top: `${(1 - tick / top) * 100}%` }}
            />
          ))}
          <div className="absolute inset-0 flex items-stretch">
            {days.map((day, index) => {
              const total = day.answered + day.abstained;
              const rate = rateOf(day);
              const height = mode === "count" ? (total / top) * 100 : total ? 100 : 0;
              const label = `${formatDayLong(day.date)}: ${day.answered} answered, ${day.abstained} abstained${rate != null ? `, answer rate ${formatPercent(rate)}` : ""}`;
              return (
                <div
                  key={day.date}
                  data-day={day.date}
                  tabIndex={index === focusIndex ? 0 : -1}
                  role="img"
                  aria-label={label}
                  onPointerEnter={() => setActive(index)}
                  onPointerLeave={() => setActive((current) => (current === index ? null : current))}
                  onFocus={() => {
                    setActive(index);
                    setFocusIndex(index);
                  }}
                  onBlur={() => setActive((current) => (current === index ? null : current))}
                  onKeyDown={(event) => onKeyDown(event, index)}
                  className={classNames(
                    "relative flex min-w-0 flex-1 flex-col items-center justify-end rounded-sm outline-offset-[-2px] transition-colors duration-150 ease-standard",
                    active === index && "bg-wash-strong",
                  )}
                >
                  <div data-stack className="relative flex w-full max-w-6 origin-bottom animate-grow-y flex-col justify-end gap-0.5 px-px" style={{ height: `${height}%` }}>
                    {mode === "count" && total > 0 && labelled.has(index) && active == null && (
                      <span aria-hidden className="absolute bottom-full left-1/2 mb-1 -translate-x-1/2 text-2xs font-medium text-fg-muted tabular-nums">
                        {total}
                      </span>
                    )}
                    {day.abstained > 0 && <div className={classNames("w-full rounded-t-[4px]", SERIES.abstained.fill)} style={{ flexGrow: day.abstained, flexBasis: 0 }} />}
                    {day.answered > 0 && (
                      <div className={classNames("w-full", SERIES.answered.fill, day.abstained === 0 && "rounded-t-[4px]")} style={{ flexGrow: day.answered, flexBasis: 0 }} />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="mt-2 flex text-2xs text-fg-subtle tabular-nums" aria-hidden>
          {days.map((day, index) => (
            <span key={day.date} className="min-w-0 flex-1 text-center whitespace-nowrap">
              {(days.length - 1 - index) % labelEvery === 0 ? formatDay(day.date) : ""}
            </span>
          ))}
        </div>
      </div>

      <Floating
        open={activeDay != null}
        anchor={() => (active != null ? (dayElement(active)?.querySelector("[data-stack]") ?? dayElement(active)) : null)}
        side="top"
        gap={10}
        className="pointer-events-none"
      >
        {activeDay && (
          <div role="tooltip" className="w-44 rounded-lg border border-line bg-raised p-3 shadow-lg">
            <p className="text-xs font-medium text-fg-muted">{formatDayLong(activeDay.date)}</p>
            <dl className="mt-2 space-y-1.5">
              {(["answered", "abstained"] as const).map((key) => (
                <div key={key} className="flex items-center justify-between gap-3">
                  <dt className="flex items-center gap-2 text-xs text-fg-muted">
                    <span aria-hidden className={classNames("h-0.5 w-3 rounded-full", SERIES[key].fill)} />
                    {SERIES[key].name}
                  </dt>
                  <dd className="text-sm font-semibold text-fg tabular-nums">{activeDay[key]}</dd>
                </div>
              ))}
              <div className="flex items-center justify-between gap-3 border-t border-line-faint pt-1.5">
                <dt className="text-xs text-fg-muted">Answer rate</dt>
                <dd className="text-sm font-semibold text-fg tabular-nums">{activeRate != null ? formatPercent(activeRate) : "–"}</dd>
              </div>
            </dl>
          </div>
        )}
      </Floating>
    </div>
  );
}

/** The same figures as the chart, for people who would rather read them. */
function DailyTable({ days }: { days: DayCount[] }) {
  const cell = "border-b border-line-faint py-1.5";
  return (
    <div className="overflow-y-auto" style={{ height: PLOT_HEIGHT + 24 }}>
      <table className="w-full border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">Answered and abstained questions per day</caption>
        <thead>
          <tr className="text-2xs tracking-caps text-fg-subtle uppercase">
            <th scope="col" className="sticky top-0 border-b border-line bg-card py-1.5 pr-4 font-medium">
              Day
            </th>
            <th scope="col" className="sticky top-0 border-b border-line bg-card px-4 py-1.5 text-right font-medium">
              Answered
            </th>
            <th scope="col" className="sticky top-0 border-b border-line bg-card px-4 py-1.5 text-right font-medium">
              Abstained
            </th>
            <th scope="col" className="sticky top-0 border-b border-line bg-card py-1.5 pl-4 text-right font-medium">
              Answer rate
            </th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {days.map((day) => {
            const rate = rateOf(day);
            return (
              <tr key={day.date}>
                <th scope="row" className={classNames(cell, "pr-4 font-normal text-fg-muted")}>
                  {formatDayLong(day.date)}
                </th>
                <td className={classNames(cell, "px-4 text-right text-fg")}>{day.answered}</td>
                <td className={classNames(cell, "px-4 text-right text-fg")}>{day.abstained}</td>
                <td className={classNames(cell, "pl-4 text-right text-fg-muted")}>{rate != null ? formatPercent(rate) : "–"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex items-center gap-4 text-xs text-fg-muted">
      {(["answered", "abstained"] as const).map((key) => (
        <li key={key} className="flex items-center gap-1.5">
          <span aria-hidden className={classNames("size-2.5 rounded-[3px]", SERIES[key].fill)} />
          {SERIES[key].name}
        </li>
      ))}
    </ul>
  );
}

// -- answered vs abstained ---------------------------------------------------------------------
/** One whole split in two: a thin segmented bar above the rows that give each part's figures. */
function OutcomeSplit({ answered, abstained }: { answered: number; abstained: number }) {
  const total = answered + abstained;
  if (total === 0) return <p className="text-sm text-fg-muted">No questions in this period.</p>;
  const parts = [
    { ...SERIES.answered, count: answered },
    { ...SERIES.abstained, count: abstained },
  ];
  return (
    <div>
      <div
        className="flex h-2 w-full gap-0.5"
        role="img"
        aria-label={parts.map((part) => `${part.name}: ${part.count} (${formatPercent(part.count / total)})`).join(", ")}
      >
        {parts
          .filter((part) => part.count > 0)
          .map((part) => (
            <div key={part.name} style={{ flexGrow: part.count, flexBasis: 0 }} className={classNames("min-w-1 rounded-full", part.fill)} />
          ))}
      </div>
      <dl className="mt-4 space-y-2 text-sm">
        {parts.map((part) => (
          <div key={part.name} className="flex items-center justify-between gap-3">
            <dt className="inline-flex items-center gap-2 text-fg-muted">
              <span className={classNames("size-2.5 rounded-[3px]", part.fill)} aria-hidden />
              {part.name}
            </dt>
            <dd className="text-fg tabular-nums">
              <span className="font-semibold">{formatNumber(part.count)}</span>
              <span className="ml-2 inline-block w-9 text-right text-fg-muted">{formatPercent(part.count / total)}</span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// -- most cited documents ----------------------------------------------------------------------
/** Ranked horizontal bars in one hue: the documents are one series, so the title names it. */
function CitedDocuments({ documents }: { documents: CitedDocument[] }) {
  const max = Math.max(...documents.map((document) => document.citations), 1);
  return (
    <ol className="space-y-4">
      {documents.map((document) => (
        <li key={`${document.document_id}-${document.title}`}>
          <div className="flex items-baseline justify-between gap-3">
            <p className="min-w-0 truncate text-sm font-medium text-fg">
              {document.in_knowledge_base && document.document_id != null ? (
                <Link to={`/knowledge/documents/${document.document_id}`} className="rounded-xs transition-colors duration-150 hover:text-accent-fg">
                  {document.title}
                </Link>
              ) : (
                document.title
              )}
              {!document.in_knowledge_base && <Badge className="ml-2 align-middle">Removed</Badge>}
            </p>
            <p className="hidden shrink-0 text-xs text-fg-subtle sm:block">{document.collection}</p>
          </div>
          <div className="mt-1.5 flex items-center gap-2.5">
            <div
              role="img"
              aria-label={`${document.citations} ${document.citations === 1 ? "citation" : "citations"}`}
              className="h-2 min-w-1 origin-left animate-grow-x rounded-r-[4px] bg-series-1"
              style={{ width: `calc((100% - 7.5rem) * ${document.citations / max})` }}
            />
            <p className="shrink-0 text-xs text-fg-subtle tabular-nums">
              <span className="text-sm font-semibold text-fg">{document.citations}</span>
              <span className="ml-1.5">
                in {document.answers} {document.answers === 1 ? "answer" : "answers"}
              </span>
            </p>
          </div>
        </li>
      ))}
    </ol>
  );
}

// -- knowledge gaps ----------------------------------------------------------------------------
const GAP_TH = "sticky top-14 z-10 border-y border-line bg-card/95 py-2.5 text-2xs font-medium tracking-caps whitespace-nowrap text-fg-subtle uppercase backdrop-blur-sm";

function Gaps({ gaps }: { gaps: KnowledgeGap[] }) {
  return (
    <table className="w-full border-separate border-spacing-0 text-left text-sm">
      <thead>
        <tr>
          <th scope="col" className={classNames(GAP_TH, "pr-3 pl-5")}>
            Question
          </th>
          <th scope="col" className={classNames(GAP_TH, "hidden px-3 md:table-cell")}>
            Reason
          </th>
          <th scope="col" className={classNames(GAP_TH, "px-3 text-right")}>
            Asked
          </th>
          <th scope="col" className={classNames(GAP_TH, "hidden pr-5 pl-3 sm:table-cell")}>
            Last asked
          </th>
        </tr>
      </thead>
      <tbody>
        {gaps.map((gap, index) => {
          const last = index === gaps.length - 1;
          const cell = classNames("border-line-faint py-3 align-top transition-colors duration-150 ease-standard group-hover/row:bg-wash", !last && "border-b");
          return (
            <tr key={gap.question} className="group/row">
              <td className={classNames(cell, "pr-3 pl-5 font-medium text-fg", last && "rounded-bl-xl")}>
                {gap.question}
                <span className="mt-0.5 block text-xs font-normal text-fg-muted md:hidden">{REASON[gap.reason] ?? gap.reason}</span>
              </td>
              <td className={classNames(cell, "hidden px-3 whitespace-nowrap text-fg-muted md:table-cell")}>{REASON[gap.reason] ?? gap.reason}</td>
              <td className={classNames(cell, "px-3 text-right text-fg tabular-nums", last && "max-sm:rounded-br-xl")}>{gap.count}&times;</td>
              <td className={classNames(cell, "hidden pr-5 pl-3 whitespace-nowrap text-fg-muted sm:table-cell", last && "rounded-br-xl")}>{formatRelative(gap.last_asked)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function InsightsSkeleton() {
  return (
    <Page title="Insights">
      <div role="status" aria-label="Loading insights">
        <Skeleton className="h-8 w-64 rounded-lg" />
        <div className="mt-5 grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          {[0, 1, 2, 3].map((tile) => (
            <Skeleton key={tile} className="h-[8.25rem] rounded-xl" />
          ))}
        </div>
        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Skeleton className="h-80 rounded-xl" />
          <Skeleton className="h-80 rounded-xl" />
        </div>
      </div>
    </Page>
  );
}

// -- page --------------------------------------------------------------------------------------
export function InsightsPage() {
  const [days, setDays] = useState<number>(14);
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [mode, setMode] = useState<ChartMode>("count");
  const [asTable, setAsTable] = useState(false);

  const load = useCallback(async (range: number) => {
    setRefreshing(true);
    try {
      setData(await api.insights(range));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Insights could not be loaded.");
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  if (error && !data) {
    return (
      <Page title="Insights">
        <ErrorNotice message={error} onRetry={() => void load(days)} />
      </Page>
    );
  }
  if (!data) return <InsightsSkeleton />;

  const feedback = data.helpful + data.not_helpful;
  const dailyTotals = data.daily.map((day) => day.answered + day.abstained);

  return (
    <Page
      title="Insights"
      description="How the assistant is being used, which documents its answers rely on, and which questions the knowledge base could not answer."
    >
      {error && <ErrorNotice message={error} className="mb-4" />}

      {/* One filter row above everything it scopes. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Segmented label="Period" value={days} onChange={setDays} options={RANGES.map((range) => ({ value: range, label: `${range} days` }))} />
        <p className="text-sm text-fg-subtle">Every figure below covers the last {data.days} days, by UTC day.</p>
      </div>

      {/* While a new period loads, the previous render stays in place at reduced opacity. */}
      <div className={classNames("mt-5 transition-opacity duration-200 ease-standard", refreshing && "opacity-60")}>
        <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
          <StatTile
            label="Questions asked"
            value={<CountUp value={data.questions} format={(value) => formatNumber(Math.round(value))} />}
            detail={`in the last ${data.days} days`}
            visual={data.questions > 0 ? <Sparkline values={dailyTotals} label={`Questions per day over the last ${data.days} days`} /> : undefined}
          />
          <StatTile
            label="Answer rate"
            value={data.answer_rate != null ? <CountUp value={data.answer_rate} format={(value) => formatPercent(value)} /> : "–"}
            visual={data.answer_rate != null ? <Meter share={data.answer_rate} label={`${formatPercent(data.answer_rate)} of questions were answered`} /> : undefined}
            detail={`${formatNumber(data.answered)} answered, ${formatNumber(data.abstained)} abstained`}
          />
          <StatTile
            label="Helpful ratings"
            value={feedback ? <CountUp value={data.helpful / feedback} format={(value) => formatPercent(value)} /> : "–"}
            visual={feedback ? <Meter share={data.helpful / feedback} label={`${formatPercent(data.helpful / feedback)} of rated answers were marked helpful`} /> : undefined}
            detail={feedback ? `${data.helpful} of ${feedback} rated answers` : "No answers rated yet"}
          />
          <StatTile
            label="Median response time"
            value={data.median_latency_ms != null ? <CountUp value={data.median_latency_ms} format={(value) => formatDuration(value)} /> : "–"}
            detail="for answered questions"
          />
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Card>
            <CardHeader
              title="Answered and abstained, per day"
              description={mode === "count" ? "Number of questions by outcome." : "Share of each day's questions by outcome."}
              action={
                data.questions > 0 ? (
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Segmented
                      label="Measure"
                      value={mode}
                      onChange={setMode}
                      options={[
                        { value: "count", label: "Count" },
                        { value: "share", label: "Share" },
                      ]}
                    />
                    <IconButton label={asTable ? "Show as chart" : "Show as table"} aria-pressed={asTable} active={asTable} onClick={() => setAsTable((shown) => !shown)}>
                      {asTable ? <ChartColumn className="size-4" aria-hidden /> : <Table2 className="size-4" aria-hidden />}
                    </IconButton>
                  </div>
                ) : undefined
              }
            />
            <div className="px-5 pt-1 pb-5">
              {data.questions > 0 ? (
                <figure>
                  <Legend />
                  <div className="mt-6">{asTable ? <DailyTable days={data.daily} /> : <DailyChart key={`${data.days}-${mode}`} days={data.daily} mode={mode} />}</div>
                </figure>
              ) : (
                <EmptyState illustration={<NoDataArt />} title="No questions in this period">
                  Once people start asking questions, daily volumes will appear here.
                </EmptyState>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="Outcome" description="Abstaining is the assistant saying that the documents do not cover a question." />
            <div className="px-5 pt-2 pb-5">
              <OutcomeSplit answered={data.answered} abstained={data.abstained} />
              <dl className="mt-5 space-y-2 border-t border-line-faint pt-4 text-sm">
                {Object.entries(data.engines).map(([engine, count]) => (
                  <div key={engine} className="flex items-center justify-between gap-3">
                    <dt className="text-fg-muted">{engine === "claude" ? "Answered by Claude" : "Extractive (offline) mode"}</dt>
                    <dd className="font-semibold text-fg tabular-nums">{formatNumber(count)}</dd>
                  </div>
                ))}
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-fg-muted">Knowledge base</dt>
                  <dd className="text-right text-fg tabular-nums">
                    {formatNumber(data.knowledge_base.documents)} documents, {formatNumber(data.knowledge_base.chunks)} chunks
                  </dd>
                </div>
              </dl>
            </div>
          </Card>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
          <Card>
            <CardHeader title="Most-cited documents" description="Number of citations in answers." />
            <div className="px-5 pt-2 pb-5">
              {data.most_cited.length > 0 ? (
                <CitedDocuments documents={data.most_cited} />
              ) : (
                <EmptyState illustration={<NoDataArt />} title="No citations yet" className="py-8">
                  Documents appear here once answers start citing them.
                </EmptyState>
              )}
            </div>
          </Card>

          <Card className="min-w-0">
            <CardHeader
              title="Knowledge gaps"
              description="Questions that were declined. Each one is a candidate for a new or better document."
              action={data.gaps.length > 0 ? <Badge tone="accent">{data.gaps.length} open</Badge> : undefined}
            />
            {data.gaps.length > 0 ? (
              <Gaps gaps={data.gaps} />
            ) : (
              <EmptyState illustration={<AllAnsweredArt />} title="No unanswered questions" className="py-8">
                Every question in this period was answered from the knowledge base.
              </EmptyState>
            )}
          </Card>
        </div>

        <p className="mt-6 flex items-start gap-2 text-xs text-fg-subtle">
          <CircleHelp className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Greetings and other messages with nothing to search for are not counted as questions.
        </p>
      </div>
    </Page>
  );
}
