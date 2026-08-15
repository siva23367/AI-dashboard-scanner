import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Link2, FileText, Search, Compass, ArrowUpRight, Satellite, Radar } from "lucide-react";
import { PageHero, Card, KpiCard, EmptyState } from "../components/ui";
import { TypeBadge } from "../components/ui";
import { useAuth } from "../AuthContext";
import { useToast } from "../ToastContext";
import { api } from "../api";

const ACTIONS = [
  {
    to: "/website",
    icon: Link2,
    title: "Website Link",
    desc: "Full PDP audit — SEO, accessibility, security, performance & conversion",
  },
  {
    to: "/pdf",
    icon: FileText,
    title: "Dashboard PDF",
    desc: "Upload a dashboard PDF/image, extract text & metrics via OCR",
  },
  {
    to: "/research",
    icon: Search,
    title: "Product Research",
    desc: "Live web search for reviews, other listings & mentions of a product",
  },
  {
    to: "/ask",
    icon: Compass,
    title: "Ask Your Dashboards",
    desc: "Search everything you've ingested and get the surrounding data",
  },
];

function formatDate(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

export default function Home() {
  const { username } = useAuth();
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

  const total = entries.length;

  return (
    <div>
      <PageHero
        eyebrow="⚡ Web Intelligence Suite"
        title={`Welcome back, ${username || "there"}`}
        subtitle="Audit a product page, ingest a dashboard PDF, or research where a product shows up across the web — pick a starting point below."
        right={
          <div className="hidden md:flex items-center gap-2 bg-white/10 border border-white/15 rounded-full px-3.5 py-1.5 text-[12px] text-white/70">
            <Radar size={13} className="text-signal-blue" />
            <span className="live-dot animate-pulseDot" /> Live corpus &amp; report index
          </div>
        }
      />

      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-7">
        {ACTIONS.map(({ to, icon: Icon, title, desc }) => (
          <Link
            key={to}
            to={to}
            className="viewfinder group bg-white border border-line rounded-xl2 p-5 shadow-card hover:shadow-lift hover:-translate-y-0.5 transition-all"
          >
            <div className="vf-tr" />
            <div className="vf-br" />
            <div className="w-10 h-10 rounded-lg bg-signal-blue/10 flex items-center justify-center mb-4 group-hover:bg-signal-blue/15 transition-colors">
              <Icon size={19} className="text-signal-blue" />
            </div>
            <div className="flex items-center gap-1.5 mb-1">
              <h3 className="font-semibold text-[14.5px] text-ink">{title}</h3>
              <ArrowUpRight size={14} className="text-muted opacity-0 group-hover:opacity-100 transition-opacity" />
            </div>
            <p className="text-[12.5px] text-muted leading-relaxed">{desc}</p>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-7">
        <KpiCard label="Total reports" value={total} />
        <KpiCard label="Website scans" value={counts.website} />
        <KpiCard label="PDF ingests" value={counts.pdf} />
        <KpiCard label="Product research" value={counts.research} />
      </div>

      <Card>
        <div className="flex items-center justify-between mb-1">
          <h3 className="font-semibold text-[14.5px]">Recent activity</h3>
          <Link to="/reports" className="text-[12.5px] text-signal-blue hover:underline flex items-center gap-1">
            View all <ArrowUpRight size={12} />
          </Link>
        </div>
        {loading ? (
          <p className="text-[13.5px] text-muted py-6 text-center">Loading…</p>
        ) : entries.length === 0 ? (
          <EmptyState
            icon={Satellite}
            title="Nothing scanned yet"
            subtitle="Run your first website scan, dashboard ingest, or product research above to see activity here."
          />
        ) : (
          <div className="divide-y divide-line -mx-6 mt-2">
            {entries.slice(0, 6).map((e, i) => (
              <a
                key={i}
                href={e.html_url}
                target="_blank"
                rel="noopener noreferrer"
                className="px-6 py-3 flex items-center gap-3 hover:bg-slate-50/80 transition-colors"
              >
                <div className="w-24 text-[11.5px] text-muted shrink-0">{formatDate(e.created_at)}</div>
                <TypeBadge type={e.type} />
                <div className="flex-1 min-w-0 text-[13.5px] text-ink truncate">{e.target}</div>
                <ArrowUpRight size={13} className="text-muted shrink-0" />
              </a>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
