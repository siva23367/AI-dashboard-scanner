import { useState } from "react";
import { Search, ExternalLink, Download, RotateCcw } from "lucide-react";
import { PageHero, Card, KpiCard, Button, Field, inputClass, ScanSweepPanel } from "../components/ui";
import { ResearchHits, BulletList } from "../components/results";
import { useToast } from "../ToastContext";
import { api } from "../api";

export default function ProductResearch() {
  const { push } = useToast();
  const [productName, setProductName] = useState("");
  const [brand, setBrand] = useState("");
  const [extraTerms, setExtraTerms] = useState("");
  const [numResults, setNumResults] = useState(8);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);

  const submit = async (e) => {
    e.preventDefault();
    if (!productName.trim()) return;
    setLoading(true);
    setData(null);
    try {
      const res = await api.research({
        product_name: productName.trim(),
        brand: brand.trim() || undefined,
        extra_terms: extraTerms.trim() || undefined,
        num_results: numResults,
      });
      setData(res);
      push("Research complete.", "success");
    } catch (err) {
      push(err.message, "error");
    } finally {
      setLoading(false);
    }
  };

  const result = data?.result;

  return (
    <div>
      <PageHero
        eyebrow="🔎 Product Research"
        title="Research a product across the web"
        subtitle="Live web search for reviews, other retailer listings, comparison articles, forum/video mentions and any prices mentioned — for any product, not just one you've scanned a page for."
      />

      <Card className="mb-6">
        <form onSubmit={submit} className="space-y-4">
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Product name">
              <div className="relative">
                <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
                <input
                  className={`${inputClass} pl-10`}
                  placeholder="e.g. Realme 16T 5G"
                  value={productName}
                  onChange={(e) => setProductName(e.target.value)}
                  required
                />
              </div>
            </Field>
            <Field label="Brand" hint="optional">
              <input className={inputClass} placeholder="e.g. Realme" value={brand} onChange={(e) => setBrand(e.target.value)} />
            </Field>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Extra terms" hint="optional — e.g. review, 128GB">
              <input className={inputClass} value={extraTerms} onChange={(e) => setExtraTerms(e.target.value)} />
            </Field>
            <Field label="Max results">
              <input
                type="number"
                min={1}
                max={20}
                className={inputClass}
                value={numResults}
                onChange={(e) => setNumResults(Number(e.target.value))}
              />
            </Field>
          </div>
          <Button type="submit" disabled={loading}>
            {loading ? "Searching…" : "Search the web"}
          </Button>
        </form>
        <p className="text-[12.5px] text-muted mt-3">
          Runs a live web search and buckets results into retailer listings, reviews/comparisons, videos, forum mentions and other
          references — with any prices found in the snippets. Directional signal only, not a verified price feed.
        </p>
      </Card>

      {loading && <ScanSweepPanel label="Searching the web…" detail="Retailers · reviews · videos · forums" />}

      {result && (
        <div className="space-y-5 animate-fadeUp">
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 flex-1">
                <KpiCard label="Total references" value={result.hits?.length ?? 0} />
                <KpiCard label="Retailer listings" value={result.bucket_counts?.retailer_listing ?? 0} />
                <KpiCard label="Reviews / comparisons" value={result.bucket_counts?.review_or_comparison ?? 0} />
                <KpiCard label="Prices mentioned" value={result.all_prices_found?.length ?? 0} />
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

          {!result.available ? (
            <Card>
              <p className="text-[13.5px] text-muted">
                No results ({result.backend}): {result.error || "no hits"}
              </p>
            </Card>
          ) : (
            <>
              {result.reference_summary?.length > 0 && (
                <Card accent>
                  <h3 className="font-semibold text-[14.5px] mb-3">Summary</h3>
                  <BulletList items={result.reference_summary} />
                </Card>
              )}
              <Card>
                <h3 className="font-semibold text-[14.5px] mb-3">References</h3>
                <ResearchHits hits={result.hits} />
              </Card>
            </>
          )}

          <div className="flex justify-center">
            <Button
              variant="ghost"
              onClick={() => {
                setData(null);
                setProductName("");
                setBrand("");
                setExtraTerms("");
              }}
            >
              <RotateCcw size={14} /> Research another product
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
