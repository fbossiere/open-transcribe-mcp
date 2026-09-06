from datetime import UTC, datetime

from open_transcribe.domain.capabilities import PricingDescriptor
from open_transcribe.domain.transcript import CostEstimate


def estimate_from_pricing(
    provider: str,
    model: str,
    duration_seconds: float,
    pricing: PricingDescriptor | None,
) -> CostEstimate:
    cost = duration_seconds / 3600 * pricing.price_usd if pricing else None
    warnings = [] if pricing else ["pricing_metadata_unavailable"]
    if pricing and pricing.valid_until and pricing.valid_until < datetime.now(UTC).date():
        warnings.append("pricing_metadata_expired")
    return CostEstimate(
        provider=provider,
        model=model,
        duration_seconds=duration_seconds,
        estimated_cost_usd=round(cost, 6) if cost is not None else None,
        pricing_valid_at=str(pricing.valid_from) if pricing else None,
        warnings=warnings,
    )
