import { CheckCircle2, AlertTriangle, XCircle, ExternalLink, Sparkles } from "lucide-react";
import { Card, KpiCard, Badge, EmptyState } from "./ui";

export function HealthGauge({ score }) {
  const s = Math.round(score ?? 0);
  const tone = s >= 75 ? "good" : s >= 50 ? "warn" : "bad";
  const ring = { good: "#17b884", warn: "#e08a1e", bad: "#e0473f" }[tone];
  const pct = Math.max(0, Math.min(100, s));
  return (
    <div className="relative w-24 h-24 shrink-0">
      <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
        <circle cx="50" cy="50" r="42" fill="none" stroke="#e5e9f0" strokeWidth="10" />
        <circle
          cx="50"
          cy="50"
          r="42"
          fill="none"
          stroke={ring}
          strokeWidth="10"
          strokeDasharray={`${(pct / 100) * 264} 264`}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="kpi-readout text-[22px] font-semibold text-ink">{s}</span>
        <span className="text-[9.5px] text-muted -mt-0.5">/ 100</span>
      </div>
    </div>
  );
}

export function ScoreBreakdown({ scores }) {
  const entries = Object.entries(scores || {}).filter(([k]) => k !== "overall_health_score");
  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
      {entries.map(([key, val]) => (
        <KpiCard key={key} label={key.replace(/_/g, " ")} value={Math.round(val)} />
      ))}
    </div>
  );
}

const SEVERITY_CFG = {
  error: { icon: XCircle, tone: "coral", label: "Errors" },
  warning: { icon: AlertTriangle, tone: "amber", label: "Warnings" },
  info: { icon: CheckCircle2, tone: "blue", label: "Info" },
};

export function SeveritySummary({ summary }) {
  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(summary || {}).map(([sev, count]) => {
        const cfg = SEVERITY_CFG[sev] || SEVERITY_CFG.info;
        const Icon = cfg.icon;
        return (
          <Badge key={sev} tone={cfg.tone}>
            <Icon size={12} /> {count} {cfg.label}
          </Badge>
        );
      })}
    </div>
  );
}

const SEVERITY_ICON_COLOR = {
  error: "text-red-500",
  warning: "text-amber-500",
  info: "text-blue-500",
};

export function IssueList({ issues }) {
  if (!issues || issues.length === 0) {
    return <EmptyState title="No issues found" subtitle="This page came back clean on every category we checked." />;
  }
  const sorted = [...issues].sort((a, b) => {
    const rank = { error: 2, warning: 1, info: 0 };
    return (rank[b.severity] ?? 0) - (rank[a.severity] ?? 0);
  });
  return (
    <div className="divide-y divide-line">
      {sorted.slice(0, 40).map((issue, i) => {
        const cfg = SEVERITY_CFG[issue.severity] || SEVERITY_CFG.info;
        const Icon = cfg.icon;
        return (
          <div key={i} className="py-3 flex items-start gap-3">
            <Icon size={16} className={`mt-0.5 shrink-0 ${SEVERITY_ICON_COLOR[issue.severity] || SEVERITY_ICON_COLOR.info}`} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="gray">{issue.category}</Badge>
                {issue.count > 1 && <span className="text-[11.5px] text-muted">×{issue.count}</span>}
              </div>
              <p className="text-[13.5px] text-ink mt-1">{issue.message}</p>
              {issue.location && <p className="text-[12px] text-muted mt-0.5 font-mono truncate">{issue.location}</p>}
              {issue.remediation && <p className="text-[12.5px] text-signal-blue mt-1">→ {issue.remediation}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function BulletList({ items, empty }) {
  if (!items || items.length === 0) return empty ? <p className="text-[13px] text-muted">{empty}</p> : null;
  return (
    <ul className="space-y-2">
      {items.map((x, i) => (
        <li key={i} className="text-[13.5px] text-ink flex gap-2">
          <span className="text-signal-blue mt-1.5">•</span>
          <span>{x}</span>
        </li>
      ))}
    </ul>
  );
}

const BUCKET_CFG = {
  retailer_listing: { tone: "blue", label: "Retailer listing" },
  review_or_comparison: { tone: "mint", label: "Review / comparison" },
  video: { tone: "coral", label: "Video" },
  forum_or_community: { tone: "amber", label: "Forum / community" },
  other_mention: { tone: "gray", label: "Other mention" },
};

export function ResearchHits({ hits }) {
  if (!hits || hits.length === 0) {
    return <EmptyState title="No web references found" subtitle="Try a different product name, or add extra terms like a model number." />;
  }
  return (
    <div className="divide-y divide-line">
      {hits.map((h, i) => {
        const cfg = BUCKET_CFG[h.bucket] || BUCKET_CFG.other_mention;
        return (
          <a
            key={i}
            href={h.url}
            target="_blank"
            rel="noopener noreferrer"
            className="py-3 flex items-start gap-3 group"
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 mb-1">
                <Badge tone={cfg.tone}>{cfg.label}</Badge>
                <span className="text-[11.5px] text-muted">{h.domain}</span>
              </div>
              <p className="text-[13.5px] text-ink font-medium group-hover:text-signal-blue transition-colors flex items-center gap-1.5">
                {h.title}
                <ExternalLink size={12} className="opacity-0 group-hover:opacity-60 transition-opacity shrink-0" />
              </p>
              {h.snippet && <p className="text-[12.5px] text-muted mt-0.5 line-clamp-2">{h.snippet}</p>}
              {h.prices_found?.length > 0 && (
                <div className="flex gap-1.5 mt-1.5 flex-wrap">
                  {h.prices_found.map((p, j) => (
                    <Badge key={j} tone="mint">
                      {p}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          </a>
        );
      })}
    </div>
  );
}

export function AskResultPanel({ result }) {
  if (!result) return null;
  const { matched_chunks = [], surrounding_chunks = [], dashboards_hit = [], all_metrics_found = [], ai_answer, ai_answer_available } = result;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Dashboards hit" value={dashboards_hit.length} />
        <KpiCard label="Matched chunks" value={matched_chunks.length} />
        <KpiCard label="Surrounding data" value={surrounding_chunks.length} />
        <KpiCard label="Metrics found" value={all_metrics_found.length} />
      </div>

      {ai_answer_available && (
        <Card accent>
          <div className="flex items-center gap-2 mb-2">
            <Sparkles size={16} className="text-signal-blue" />
            <h3 className="font-semibold text-[14.5px]">AI answer</h3>
          </div>
          <p className="text-[13.5px] text-ink leading-relaxed">{ai_answer}</p>
        </Card>
      )}

      {matched_chunks.length === 0 ? (
        <EmptyState title="No matches" subtitle="Try a different phrase, or ingest more dashboards from the Dashboard PDF page." />
      ) : (
        <Card>
          <h3 className="font-semibold text-[14.5px] mb-3">Matched text</h3>
          <div className="divide-y divide-line">
            {matched_chunks.map((m, i) => (
              <div key={i} className="py-3">
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <Badge tone="blue">{m.dashboard_name}</Badge>
                  <span className="text-[11.5px] text-muted">page {m.page}</span>
                  <span className="text-[11px] text-muted font-mono">
                    {m.match_type}
                    {m.match_type === "semantic" ? ` ${m.score.toFixed(2)}` : ""}
                  </span>
                </div>
                <p className="text-[13.5px] text-ink">{m.text}</p>
                {m.metrics_found?.length > 0 && (
                  <p className="text-[12px] text-muted mt-1">Metrics: {m.metrics_found.join(", ")}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {surrounding_chunks.length > 0 && (
        <Card>
          <h3 className="font-semibold text-[14.5px] mb-3">Surrounding data on the same card / table</h3>
          <div className="divide-y divide-line">
            {surrounding_chunks.map((s, i) => (
              <div key={i} className="py-2.5 flex items-start gap-3">
                <Badge tone="gray">{s.dashboard_name}</Badge>
                <p className="text-[13.5px] text-ink flex-1">{s.text}</p>
              </div>
            ))}
          </div>
        </Card>
      )}

      {all_metrics_found.length > 0 && (
        <Card>
          <h3 className="font-semibold text-[14.5px] mb-3">All numeric / metric values found</h3>
          <div className="flex flex-wrap gap-2">
            {all_metrics_found.map((m, i) => (
              <Badge key={i} tone="mint">
                {m}
              </Badge>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
