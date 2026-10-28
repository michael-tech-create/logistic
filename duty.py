"""Duty estimates require explicit valuation and a reviewed tariff profile."""
from shipment_costs import source_hints


def estimate_duty(text: str, record: dict) -> dict:
    saved = record.get('customs_assessment')
    if saved and saved.get('status') == 'calculated':
        return saved
    hints = source_hints(text or '')
    return {'status': 'needs_inputs', 'hs_code': hints['hs_code'], 'label': 'Customs valuation required', 'reason': 'Open Customs calculation to confirm the HS code, goods value, freight, insurance, dated customs exchange rate, and sourced tariff rates. No duty rate has been assumed.'}
