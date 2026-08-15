import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Compass } from "lucide-react";
import { PageHero, Card, Button, inputClass, ScanSweepPanel, EmptyState } from "../components/ui";
import { AskResultPanel } from "../components/results";
import { useToast } from "../ToastContext";
import { api } from "../api";

export default function AskDashboards() {
  const { push } = useToast();
  const [params] = useSearchParams();
  const initialSource = params.get("source") || "";
  const initialQ = params.get("q") || "";

  const [q, setQ] = useState(initialQ);
  const [scope, setScope] = useState(initialSource ? "this" : "all");
  const [summarize, setSummarize] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [searched, setSearched] = useState(false);

  const source = initialSource || null;
  const sourceLabel = source ? source.split("/").pop().split("_").slice(1).join("_") : null;

  const runSearch = async (query, sc) => {
    setLoading(true);
    setResult(null);
    try {
      const res = await api.ask({ q: query, source, scope: sc, summarize });
      setResult(res.result);
    } catch (err) {
      push(err.message, "error");
      setResult(null);
    } finally {
      setLoading(false);
      setSearched(true);
    }
  };

  useEffect(() => {
    if (initialQ.trim()) runSearch(initialQ.trim(), initialSource ? "this" : "all");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const submit = (e) => {
    e.preventDefault();
    if (!q.trim()) return;
    runSearch(q.trim(), scope);
  };

  return (
    <div>
      <PageHero
        eyebrow="🧭 Ask Your Dashboards"
        title="Search your ingested dashboards"
        subtitle="Exact + semantic search over everything you've uploaded on the Dashboard PDF page, with the surrounding label/value data pulled in from the same card or table."
      />

      <Card className="mb-6">
        <form onSubmit={submit} className="space-y-4">
          <input
            className={inputClass}
            placeholder='What do you want to know? e.g. "current DXI" or "Promocodeusagerate"'
            value={q}
            onChange={(e) => setQ(e.target.value)}
            autoFocus
            required
          />
          {source && (
            <label className="flex items-start gap-2.5 bg-slate-50 border border-line rounded-lg px-3.5 py-3 cursor-pointer">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={scope === "this"}
                onChange={(e) => setScope(e.target.checked ? "this" : "all")}
              />
              <span className="text-[13.5px]">
                Search only <b>{sourceLabel}</b>
                <span className="block text-[12px] text-muted">Untick to search every dashboard you've ever uploaded</span>
              </span>
            </label>
          )}
          <label className="flex items-start gap-2.5 bg-slate-50 border border-line rounded-lg px-3.5 py-3 cursor-pointer">
            <input type="checkbox" className="mt-0.5" checked={summarize} onChange={(e) => setSummarize(e.target.checked)} />
            <span className="text-[13.5px]">
              Write an AI answer from the matches
              <span className="block text-[12px] text-muted">Needs GEMINI_API_KEY in .env — silently skipped otherwise</span>
            </span>
          </label>
          <Button type="submit" disabled={loading}>
            {loading ? "Searching…" : "Search"}
          </Button>
        </form>
      </Card>

      {loading && <ScanSweepPanel label="Searching the corpus…" />}
      {!loading && result && <AskResultPanel result={result} />}
      {!loading && searched && !result && (
        <Card>
          <EmptyState
            icon={Compass}
            title="No dashboards ingested yet"
            subtitle='Upload one from the "Dashboard PDF" page first, then come back and ask it anything.'
          />
        </Card>
      )}
    </div>
  );
}
