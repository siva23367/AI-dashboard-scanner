import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, Download, FileJson, Compass, Inbox } from "lucide-react";
import { PageHero, Card, KpiCard, EmptyState } from "../components/ui";
import { TypeBadge } from "../components/ui";
import { useToast } from "../ToastContext";
import { api, resolveUrl } from "../api";

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function HealthPill({ score }) {
  if (score === null || score === undefined) return <span className="text-muted text-[13px]">—</span>;
  const s = Math.round(score);
  const tone = s >= 75 ? "text-emerald-600" : s >= 50 ? "text-amber-600" : "text-red-600";
  return <span className={`kpi-readout font-semibold ${tone}`}>{s}</span>;
}

export default function Reports() {
  const { push } = useToast();
  const [entries, setEntries] = useState([]);
  const [counts, setCounts] = useState({ website: 0, pdf: 0, research: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .reports()
      .then((res) => {
        setEntries(res.entries);
        setCounts(res.counts);
      })
      .catch((err) => push(err.message, "error"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <PageHero
        eyebrow="📊 All Reports"
        title="Dashboard"
        subtitle="Every report generated from Website Link, Dashboard PDF and Product Research, newest first."
      />

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
        <KpiCard label="Total reports" value={entries.length} />
        <KpiCard label="Website scans" value={counts.website} />
        <KpiCard label="PDF ingests" value={counts.pdf} />
        <KpiCard label="Product research" value={counts.research} />
      </div>

      <Card>
        {loading ? (
          <p className="text-[13.5px] text-muted py-6 text-center">Loading…</p>
        ) : entries.length === 0 ? (
          <EmptyState icon={Inbox} title="No reports yet" subtitle="Try Website Scan, Dashboard PDF or Product Research from the sidebar." />
        ) : (
          <div className="divide-y divide-line -mx-6">
            {entries.map((e, i) => (
              <div key={i} className="px-6 py-3.5 flex flex-wrap items-center gap-3">
                <div className="w-28 text-[12px] text-muted shrink-0">{formatDate(e.created_at)}</div>
                <div className="shrink-0">
                  <TypeBadge type={e.type} />
                </div>
                <div className="flex-1 min-w-[160px] text-[13.5px] text-ink truncate" title={e.target}>
                  {e.target}
                </div>
                <div className="w-14 text-right shrink-0">
                  <HealthPill score={e.overall_health} />
                </div>
                <div className="flex items-center gap-3 shrink-0 text-[12.5px]">
                  {e.html_url && (
                    <a href={resolveUrl(e.html_url)} target="_blank" rel="noopener noreferrer" className="text-signal-blue hover:underline flex items-center gap-1">
                      <ExternalLink size={12} /> HTML
                    </a>
                  )}
                  {e.pdf_url && (
                    <a href={resolveUrl(e.pdf_url)} target="_blank" rel="noopener noreferrer" className="text-signal-blue hover:underline flex items-center gap-1">
                      <Download size={12} /> PDF
                    </a>
                  )}
                  {e.json_url && (
                    <a href={resolveUrl(e.json_url)} target="_blank" rel="noopener noreferrer" className="text-signal-blue hover:underline flex items-center gap-1">
                      <FileJson size={12} /> JSON
                    </a>
                  )}
                  {e.type === "pdf" && e.source_file && (
                    <Link to={`/ask?source=${encodeURIComponent(e.source_file)}`} className="text-signal-blue hover:underline flex items-center gap-1">
                      <Compass size={12} /> Ask
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
