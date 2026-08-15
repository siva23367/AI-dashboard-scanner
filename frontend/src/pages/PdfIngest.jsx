import { useRef, useState } from "react";
import { UploadCloud, FileText, ExternalLink, Download, RotateCcw, Search } from "lucide-react";
import { PageHero, Card, KpiCard, Button, Field, inputClass, ScanSweepPanel, EmptyState } from "../components/ui";
import { AskResultPanel } from "../components/results";
import { useToast } from "../ToastContext";
import { api } from "../api";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.bmp,.tiff";

export default function PdfIngest() {
  const { push } = useToast();
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  const [askQ, setAskQ] = useState("");
  const [askScope, setAskScope] = useState("this");
  const [askLoading, setAskLoading] = useState(false);
  const [askResult, setAskResult] = useState(null);

  const pickFile = (f) => {
    if (!f) return;
    setFile(f);
    setData(null);
    setAskResult(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!file) return;
    setLoading(true);
    setData(null);
    try {
      const res = await api.scanPdf(file);
      setData(res);
      push("Dashboard ingested.", "success");
    } catch (err) {
      push(err.message, "error");
    } finally {
      setLoading(false);
    }
  };

  const runAsk = async (e) => {
    e.preventDefault();
    if (!askQ.trim() || !data) return;
    setAskLoading(true);
    setAskResult(null);
    try {
      const res = await api.ask({ q: askQ.trim(), source: data.source_file, scope: askScope });
      setAskResult(res.result);
    } catch (err) {
      push(err.message, "error");
    } finally {
      setAskLoading(false);
    }
  };

  const result = data?.result;

  return (
    <div>
      <PageHero
        eyebrow="📄 Dashboard PDF"
        title="Upload a dashboard PDF"
        subtitle="Extracts text/metrics via the text-layer + OCR pipeline and adds it to the searchable corpus, then you can ask it questions right away."
      />

      <Card className="mb-6">
        <form onSubmit={submit} className="space-y-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              pickFile(e.dataTransfer.files?.[0]);
            }}
            onClick={() => inputRef.current?.click()}
            className={`viewfinder border-2 border-dashed rounded-xl px-6 py-10 text-center cursor-pointer transition-colors ${
              dragOver ? "border-signal-blue bg-signal-blue/5" : "border-line bg-slate-50/60"
            }`}
          >
            <div className="vf-tr" />
            <div className="vf-br" />
            <UploadCloud size={26} className="mx-auto text-signal-blue mb-2.5" />
            {file ? (
              <p className="text-[13.5px] text-ink font-medium flex items-center justify-center gap-1.5">
                <FileText size={14} /> {file.name}
              </p>
            ) : (
              <>
                <p className="text-[13.5px] text-ink font-medium">Drop a dashboard PDF or image here, or click to browse</p>
                <p className="text-[12px] text-muted mt-1">Accepts .pdf, .png, .jpg, .jpeg, .webp, .bmp, .tiff</p>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              onChange={(e) => pickFile(e.target.files?.[0])}
            />
          </div>
          <Button type="submit" disabled={loading || !file}>
            {loading ? "Ingesting…" : "Ingest & generate report"}
          </Button>
        </form>
      </Card>

      {loading && <ScanSweepPanel label="Reading the dashboard…" detail="Text layer + OCR extraction" />}

      {result && (
        <div className="space-y-5 animate-fadeUp">
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 flex-1">
                <KpiCard label="Pages" value={result.pages} />
                <KpiCard label="Chunks added" value={result.chunks_added} />
                <KpiCard label="Metrics found" value={data.metrics_found?.length ?? 0} />
                <KpiCard label="Corpus size (total)" value={data.corpus_size} />
              </div>
              <div className="flex gap-2 shrink-0">
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

          {result.warnings?.length > 0 && (
            <Card>
              <h3 className="font-semibold text-[14.5px] mb-2">Warnings</h3>
              <ul className="space-y-1.5">
                {result.warnings.map((w, i) => (
                  <li key={i} className="text-[13px] text-amber-700">
                    ⚠ {w}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card accent>
            <div className="flex items-center gap-2 mb-1">
              <Search size={16} className="text-signal-blue" />
              <h3 className="font-semibold text-[14.5px]">Ask about this dashboard</h3>
            </div>
            <p className="text-[12.5px] text-muted mb-3">Got a question about the data on this PDF? Search it directly.</p>
            <form onSubmit={runAsk} className="flex flex-wrap gap-2.5 items-start">
              <input
                className={`${inputClass} flex-1 min-w-[220px]`}
                placeholder='e.g. "current DXI" or "Promocodeusagerate"'
                value={askQ}
                onChange={(e) => setAskQ(e.target.value)}
                required
              />
              <select
                value={askScope}
                onChange={(e) => setAskScope(e.target.value)}
                className={`${inputClass} w-auto`}
              >
                <option value="this">This dashboard only</option>
                <option value="all">All dashboards</option>
              </select>
              <Button type="submit" disabled={askLoading}>
                {askLoading ? "Searching…" : "Ask"}
              </Button>
            </form>
          </Card>

          {askLoading && <ScanSweepPanel label="Searching the corpus…" />}
          {askResult && <AskResultPanel result={askResult} />}

          <div className="flex justify-center">
            <Button
              variant="ghost"
              onClick={() => {
                setData(null);
                setFile(null);
                setAskResult(null);
                setAskQ("");
              }}
            >
              <RotateCcw size={14} /> Ingest another dashboard
            </Button>
          </div>
        </div>
      )}

      {!result && !loading && (
        <Card>
          <EmptyState
            icon={FileText}
            title="No dashboard uploaded yet"
            subtitle="Upload a dashboard PDF or image above to extract its text and metrics, then ask it questions right on this page."
          />
        </Card>
      )}
    </div>
  );
}
