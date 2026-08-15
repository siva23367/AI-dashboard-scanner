"""
Revenue Impact Estimator
-------------------------
The #1 thing that gets a founder's attention is not "your CSP header is
missing" -- it's "this is costing you an estimated $X/month". This module
turns the scanner's category scores into a directional revenue-at-risk
number, grounded in published, citable industry benchmarks (not invented
multipliers).

Benchmarks used (all publicly published, checked August 2026):
  - Speed: each additional second of load time reduces conversion by
    roughly 7% (Reboot Online / Kanuka Digital 2025 aggregate), and mobile
    abandonment jumps sharply past a 3s load (Google / SiteBuilder Report).
  - Trust/security signals: checkout forms that display trust badges see
    up to a 42% conversion lift (Baymard-referenced industry aggregate);
    Visa/Stanford Digital Trust Lab (2026) found security-related checkout
    abandonment falls from 25.4% to 11.8% (a 53.5% relative reduction) when
    SSL badges, recognizable payment logos and a money-back guarantee are
    all present.
  - Checkout friction / missing structured purchase signals: Baymard
    Institute's meta-analysis of checkout usability studies finds the
    average large e-commerce site can recover ~35% more conversions by
    fixing solvable checkout-usability issues; the global cart abandonment
    rate is ~70% as of 2026.
  - SEO/structured data: incomplete Product schema and metadata primarily
    cost *organic visibility* (impressions/rankings), not conversion --
    modeled separately as an "organic reach" risk, not stacked into the
    conversion multiplier, to avoid double-counting.

IMPORTANT / product-honesty note (surface this to the user, do not hide it):
This is a DIRECTIONAL estimate built from category health scores and public
industry benchmarks. It is not a guarantee, an audit finding of actual lost
revenue, or financial/investment advice. Treat it as "here is the size of
the opportunity if industry-average elasticities hold for your funnel" --
useful for prioritization and for a founder conversation, not for a
board-deck commitment without your own A/B validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Max plausible conversion-rate uplift attributable to each lever, capped
# conservatively below the headline stats above so the model doesn't imply
# an unrealistic stacked total (industry studies measure these levers in
# isolation, not simultaneously).
MAX_UPLIFT_PP = {
    "performance": 0.12,   # speed: up to ~12 percentage-point relative uplift
    "conversion": 0.15,    # CTA/price/trust/urgency clarity on the PDP itself
    "security": 0.08,      # perceived-security / trust-badge effect
    "accessibility": 0.03, # WCAG fixes widen addressable audience slightly
}

DEFAULT_CONVERSION_RATE = 0.025  # 2.5%, mid-point of commonly cited 2-4% ecommerce range


@dataclass
class RevenueImpact:
    monthly_visitors: int
    aov: float
    baseline_conversion_rate: float
    baseline_monthly_orders: float
    baseline_monthly_revenue: float
    category_gap_pp: Dict[str, float]  # relative-uplift % per lever, not additive conversion-rate points
    total_recoverable_uplift_pp: float  # relative % uplift on baseline conversions, not additive conversion-rate points
    recoverable_monthly_orders: float
    estimated_monthly_revenue_at_risk: float
    estimated_annual_revenue_at_risk: float
    top_levers: List[str]
    disclaimer: str


def estimate(scores: Dict[str, float], *, monthly_visitors: int, aov: float,
             conversion_rate: Optional[float] = None) -> RevenueImpact:
    """
    scores: the ProReport.scores dict (0-100 per category).
    monthly_visitors: estimated/actual monthly PDP or site traffic.
    aov: average order value in the store's currency.
    conversion_rate: current baseline conversion rate as a fraction (e.g. 0.025).
                      Defaults to the commonly cited ecommerce mid-point (2.5%).
    """
    cr = conversion_rate if conversion_rate is not None else DEFAULT_CONVERSION_RATE
    baseline_orders = monthly_visitors * cr
    baseline_revenue = baseline_orders * aov

    category_gap_pp = {}
    total_uplift = 0.0
    for cat, max_pp in MAX_UPLIFT_PP.items():
        score = scores.get(cat)
        if score is None:
            continue
        gap_fraction = max(0.0, (100 - score) / 100)  # 0 (perfect) .. 1 (worst)
        lever_uplift = gap_fraction * max_pp
        category_gap_pp[cat] = round(lever_uplift * 100, 2)  # relative-uplift % contributed by this lever (NOT additive percentage points of conversion rate)
        total_uplift += lever_uplift

    # Diminishing returns when stacking multiple simultaneous levers --
    # apply a 0.7 co-occurrence discount so the total isn't a naive sum
    # (fixing 4 things at once rarely yields 4x the isolated lift of each).
    total_uplift_adjusted = total_uplift * 0.7

    recoverable_orders = baseline_orders * total_uplift_adjusted
    revenue_at_risk = recoverable_orders * aov

    top_levers = sorted(category_gap_pp, key=category_gap_pp.get, reverse=True)[:3]

    disclaimer = ("Directional estimate from category health scores and published industry "
                  "conversion-rate benchmarks (Google/Deloitte, Baymard Institute, Visa/Stanford "
                  "Digital Trust Lab -- see FEATURES.md for sources). Not a guarantee of results "
                  "and not financial advice; validate with your own analytics/A-B tests before "
                  "committing budget or making projections to investors.")

    return RevenueImpact(
        monthly_visitors=monthly_visitors,
        aov=round(aov, 2),
        baseline_conversion_rate=cr,
        baseline_monthly_orders=round(baseline_orders, 1),
        baseline_monthly_revenue=round(baseline_revenue, 2),
        category_gap_pp=category_gap_pp,
        total_recoverable_uplift_pp=round(total_uplift_adjusted * 100, 2),
        recoverable_monthly_orders=round(recoverable_orders, 1),
        estimated_monthly_revenue_at_risk=round(revenue_at_risk, 2),
        estimated_annual_revenue_at_risk=round(revenue_at_risk * 12, 2),
        top_levers=top_levers,
        disclaimer=disclaimer,
    )


def narrative(ri: RevenueImpact, currency: str = "$") -> List[str]:
    """Founder-facing bullet points (short, no jargon)."""
    lever_labels = {"performance": "page speed", "conversion": "PDP conversion clarity",
                     "security": "checkout trust signals", "accessibility": "accessibility reach"}
    lines = [
        f"At {ri.monthly_visitors:,} monthly visitors and {currency}{ri.aov:,.2f} AOV, "
        f"the current funnel is estimated at ~{ri.baseline_monthly_orders:,.0f} orders/mo "
        f"({currency}{ri.baseline_monthly_revenue:,.0f}/mo) at a {ri.baseline_conversion_rate*100:.1f}% conversion rate.",
        f"Closing the gaps this scan found is a directional ~{currency}{ri.estimated_monthly_revenue_at_risk:,.0f}/mo "
        f"({currency}{ri.estimated_annual_revenue_at_risk:,.0f}/yr) opportunity -- "
        f"roughly a {ri.total_recoverable_uplift_pp:.1f}% relative lift in conversions "
        f"(i.e. conversion rate moving from {ri.baseline_conversion_rate*100:.2f}% toward "
        f"~{ri.baseline_conversion_rate*100*(1+ri.total_recoverable_uplift_pp/100):.2f}%), not an additive percentage-point jump.",
    ]
    if ri.top_levers:
        pretty = ", ".join(lever_labels.get(l, l) for l in ri.top_levers)
        lines.append(f"Biggest levers, in order: {pretty}.")
    return lines
