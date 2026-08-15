import { useState } from "react";
import { Link2, ExternalLink, Download, RotateCcw } from "lucide-react";
import { PageHero, Card, Button, Field, inputClass, ScanSweepPanel } from "../components/ui";
import { HealthGauge, ScoreBreakdown, SeveritySummary, IssueList, BulletList } from "../components/results";
import { useToast } from "../ToastContext";
import { api } from "../api";

export default function WebsiteScan() {
  const { push } = useToast();
  const [url, setUrl] = useState("");
  const [useLlm, setUseLlm] = useState(false);
  const [research, setResearch] = useState(true);
  const [researchTerms, setResearchTerms] = useState("");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!url.trim()) return;
    setLoading(true);
    setData(null);
    try {
      const res = await api.scanWebsite({
        url: url.trim(),
        use_llm: useLlm,
        research,
        research_terms: researchTerms.trim() || undefined,
      });
      setData(res);
      if (res.research_note) push(res.research_note, "info");
      push("Scan complete.", "success");
    } catch (err) {
      push(err.message, "error");
    } finally {
      setLoading(false);
    }
  };

  const report = data?.report;

  return (
    <div>
      <PageHero
        eyebrow="🔗 Website Link"
        title="Scan a product page"
        subtitle="Runs the full audit — semantic issues, spelling, SEO, accessibility, security, performance and conversion — and can optionally research this exact product's footprint across the web in the same run."
      />

      <Card className="mb-6">
        <form onSubmit={submit} className="space-y-4">
          <Field label="Product page URL">
            <div className="relative">
              <Link2 size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
              <input
                className={`${inputClass} pl-10`}
                placeholder="https://example.com/product/abc"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
            </div>
          </Field>

          <label className="flex items-start gap-2.5 bg-slate-50 border border-line rounded-lg px-3.5 py-3 cursor-pointer">
            <input type="checkbox" className="mt-0.5" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            <span className="text-[13.5px]">
              Use LLM enrichment
              <span className="block text-[12px] text-muted">Needs an API key configured in .env</span>
            </span>
          </label>

          <label className="flex items-start gap-2.5 bg-slate-50 border border-line rounded-lg px-3.5 py-3 cursor-pointer">
            <input type="checkbox" className="mt-0.5" checked={research} onChange={(e) => setResearch(e.target.checked)} />
            <span className="text-[13.5px]">
              Also run Product Research
              <span className="block text-[12px] text-muted">
                Live web search for reviews, other retailer listings, forum &amp; video mentions of this product
              </span>
            </span>
          </label>

          {research && (
            <Field label="Extra research terms" hint="optional — e.g. 'review' or a model number">
              <input className={inputClass} value={researchTerms} onChange={(e) => setResearchTerms(e.target.value)} />
            </Field>
          )}

          <Button type="submit" disabled={loading}>
            {loading ? "Scanning…" : "Run scan"}
          </Button>
        </form>
      </Card>

      {loading && <ScanSweepPanel label="Auditing the page…" detail="SEO · accessibility · security · performance · conversion" />}

      {report && (
        <div className="space-y-5 animate-fadeUp">
          <Card>
            <div className="flex flex-wrap items-center gap-6">
              <HealthGauge score={report.scores?.overall_health_score} />
              <div className="flex-1 min-w-[200px]">
                <div className="text-[13px] text-muted mb-1 truncate">{report.url}</div>
                <SeveritySummary summary={Object.fromEntries(["error", "warning", "info"].map((s) => [s, (report.issues || []).filter((i) => i.severity === s).reduce((a, i) => a + i.count, 0)]))} />
              </div>
              <div className="flex gap-2">
                {data.html_url && (
                  <a href={data.html_url} target="_blank" rel="noopener noreferrer">
                    <Button variant="ghost">
                      <ExternalLink size={14} /> Full report
                    </Button>
                  </a>
                )}
                {data.pdf_url && (
                  <a href={data.pdf_url} target="_blank" rel="noopener noreferrer">
                    <Button variant="ghost">
                      <Download size={14} /> PDF
                    </Button>
                  </a>
                )}
              </div>
            </div>
          </Card>

          <ScoreBreakdown scores={report.scores} />

          {report.executive_summary?.length > 0 && (
            <Card>
              <h3 className="font-semibold text-[14.5px] mb-3">Executive summary</h3>
              <BulletList items={report.executive_summary} />
            </Card>
          )}

          {report.quick_wins?.length > 0 && (
            <Card accent>
              <h3 className="font-semibold text-[14.5px] mb-3">Quick wins</h3>
              <BulletList items={report.quick_wins} />
            </Card>
          )}

          <Card>
            <h3 className="font-semibold text-[14.5px] mb-1">Issues found</h3>
            <p className="text-[12.5px] text-muted mb-3">Highest severity first, top 40 shown — open the full report for everything.</p>
            <IssueList issues={report.issues} />
          </Card>

          <div className="flex justify-center">
            <Button
              variant="ghost"
              onClick={() => {
                setData(null);
                setUrl("");
              }}
            >
              <RotateCcw size={14} /> Scan another page
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
