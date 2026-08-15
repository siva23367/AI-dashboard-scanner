import { Link2, FileText, Search, Inbox } from "lucide-react";

export function PageHero({ eyebrow, title, subtitle, right }) {
  return (
    <div className="bg-gradient-to-br from-navy-700 via-navy-900 to-navy-950 text-white rounded-2xl px-7 py-8 shadow-hero mb-7 relative overflow-hidden">
      <div className="relative flex flex-col md:flex-row md:items-start md:justify-between gap-4">
        <div>
          {eyebrow && (
            <span className="inline-flex items-center gap-1.5 bg-white/10 border border-white/15 text-[11.5px] font-semibold px-3 py-1 rounded-full text-blue-100 mb-3">
              {eyebrow}
            </span>
          )}
          <h1 className="font-display text-[26px] font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="text-white/60 text-[13.5px] mt-1.5 max-w-xl leading-relaxed">{subtitle}</p>}
        </div>
        {right && <div className="shrink-0">{right}</div>}
      </div>
    </div>
  );
}

export function Card({ children, className = "", accent = false }) {
  return (
    <div
      className={`bg-white border border-line rounded-xl2 p-6 shadow-card ${
        accent ? "border-t-[3px] border-t-signal-blue" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function KpiCard({ label, value, sub, tone = "default" }) {
  const toneClass = {
    default: "text-ink",
    good: "text-emerald-600",
    warn: "text-amber-600",
    bad: "text-red-600",
  }[tone];
  return (
    <div className="bg-white border border-line rounded-xl p-4 border-t-[3px] border-t-signal-blue">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={`kpi-readout text-[26px] font-semibold mt-1 ${toneClass}`}>{value}</div>
      {sub && <div className="text-[11.5px] text-muted mt-0.5">{sub}</div>}
    </div>
  );
}

export function Badge({ tone = "blue", children }) {
  const styles = {
    blue: "bg-signal-blue/10 text-signal-blue",
    mint: "bg-signal-mint/10 text-emerald-700",
    amber: "bg-signal-amber/10 text-amber-700",
    coral: "bg-signal-coral/10 text-red-700",
    gray: "bg-slate-100 text-slate-600",
  }[tone];
  return <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11.5px] font-semibold ${styles}`}>{children}</span>;
}

export function TypeBadge({ type }) {
  const map = {
    website: { tone: "blue", icon: Link2, label: "Website" },
    pdf: { tone: "coral", icon: FileText, label: "PDF" },
    research: { tone: "mint", icon: Search, label: "Research" },
  };
  const cfg = map[type] || { tone: "gray", icon: Inbox, label: type };
  const Icon = cfg.icon;
  return (
    <Badge tone={cfg.tone}>
      <Icon size={11} /> {cfg.label}
    </Badge>
  );
}

export function EmptyState({ icon: Icon = Inbox, title, subtitle, action }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      <div className="w-12 h-12 rounded-xl bg-signal-blue/10 flex items-center justify-center mb-4">
        <Icon size={22} className="text-signal-blue" />
      </div>
      <div className="font-medium text-[15px] text-ink">{title}</div>
      {subtitle && <p className="text-[13px] text-muted mt-1.5 max-w-sm leading-relaxed">{subtitle}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** The signature "scan sweep" loading state -- a beam moving across a dark
 * track, used whenever the app is waiting on a scan/ingest/research/search
 * call so the wait itself reinforces what the product does. */
export function ScanSweep({ label = "Scanning…" }) {
  return (
    <div className="scan-sweep-track rounded-xl h-2 w-full">
      <div className="scan-sweep-beam h-full animate-sweep" />
    </div>
  );
}

export function ScanSweepPanel({ label = "Working…", detail }) {
  return (
    <Card className="flex flex-col items-center py-10 gap-4">
      <div className="w-full max-w-sm">
        <ScanSweep />
      </div>
      <div className="text-center">
        <div className="text-[14px] font-medium text-ink">{label}</div>
        {detail && <div className="text-[12.5px] text-muted mt-1">{detail}</div>}
      </div>
    </Card>
  );
}

export function Button({ children, variant = "primary", className = "", ...props }) {
  const base = "inline-flex items-center justify-center gap-2 rounded-lg text-[14px] font-semibold px-5 py-2.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed";
  const styles = {
    primary: "bg-signal-blue text-white hover:bg-signal-blueDark shadow-sm",
    ghost: "bg-white border border-line text-ink hover:border-signal-blue/50",
    subtle: "bg-signal-blue/8 text-signal-blue hover:bg-signal-blue/15",
  }[variant];
  return (
    <button className={`${base} ${styles} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function Field({ label, hint, children }) {
  return (
    <label className="block">
      <span className="block text-[13px] font-semibold text-ink mb-1.5">{label}</span>
      {children}
      {hint && <span className="block text-[12px] text-muted mt-1">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "w-full px-3.5 py-2.5 border border-line rounded-lg text-[14.5px] bg-slate-50/60 focus:bg-white focus:border-signal-blue outline-none transition-colors";
