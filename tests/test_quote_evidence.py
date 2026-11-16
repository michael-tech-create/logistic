"""Regressions reconstructed from reported clauses; not the original source email."""
import unittest
from unittest.mock import patch
from quote_agent import parse_freight_quote, parse_freight_quote_llm, SAMPLE_QUOTE

SPOT_QUOTE = '''40HQ from Shanghai (or Ningbo) to LAX / Long Beach.
40HQ: USD 3,450.00.
Ocean freight: USD 3,450.00.
Price changes if Ningbo, plus USD 150.00 maybe.
AMS/ISF, USD 35.00 each.
If we do, add USD 50.00.
Unless carrier announces GRI next week, then plus USD 400.00.
Chassis, USD 45.00 per day, min 3 days.
Origin doc fee: USD 95.00.
Destination handling: USD 85.00.
Telex release: USD 55.00.
Customs clearance: USD 125.00.
Messenger fee: USD 40.00.
Local drayage: USD 650.00.
Trucking fuel surcharge 38%.
Waiting time, USD 95.00 per hour after 1 hour free.
'''

class EvidenceTests(unittest.TestCase):
    def test_reconstructed_baseline_and_route(self):
        quote = parse_freight_quote(SPOT_QUOTE)
        self.assertEqual(quote.financials.total_amount, 4705)
        self.assertEqual(len(quote.financials.line_items), 9)
        items = {i.description: i for i in quote.financials.line_items}
        self.assertEqual(items['Chassis'].amount, 135)
        self.assertEqual(items['AMS/ISF'].amount, 70)
        self.assertTrue(all(i.source_text for i in items.values()))
        self.assertIsNone(quote.shipment_details.est_transit_days)
        self.assertIn('Shanghai', quote.shipment_details.origin.location_name)
        self.assertIn('Ningbo', quote.shipment_details.origin.location_name)
        self.assertIn('Long Beach', quote.shipment_details.destination.location_name)
        self.assertEqual(quote.shipment_details.destination.country, 'United States')
        notes = '\n'.join(quote.extraction_flags)
        for term in ['150.00', '50.00', '400.00', '95.00 per hour', '38%', 'alternatives']:
            self.assertIn(term, notes)

    def test_transit_requires_explicit_context(self):
        for source in ['Chassis USD 45/day, min 3 days.', 'Payment within 30 days.', 'Valid for 2 weeks.', '7 days free storage.']:
            self.assertIsNone(parse_freight_quote(source).shipment_details.est_transit_days)
        self.assertEqual(parse_freight_quote('Transit time: 14-24 days.').shipment_details.est_transit_days, 19)
        self.assertEqual(parse_freight_quote('Transit: 3-5 weeks.').shipment_details.est_transit_days, 28)

    def test_same_amount_different_charges_are_kept(self):
        q = parse_freight_quote('Origin handling: USD 95\nDestination handling: USD 95')
        self.assertEqual(q.financials.total_amount, 190)

    def test_ambiguous_multiple_amounts_and_conversation_not_billed(self):
        q = parse_freight_quote('Handling/doc fee, USD 85.00 at origin, USD 95.00\nWe discussed USD 150 yesterday.')
        self.assertEqual(q.financials.total_amount, 0)
        self.assertIn('Multiple amounts need review', '\n'.join(q.extraction_flags))

    def test_conditional_structured_lines_do_not_reinflate_stated_total(self):
        q = parse_freight_quote('Charges:\nFreight: USD 100\nGRI: USD 400 if announced\nWaiting: USD 95 per hour\nTotal Amount Due: USD 595')
        self.assertEqual(q.financials.total_amount, 100)
        self.assertFalse(any('matches the stated total' in f for f in q.extraction_flags))

    def test_llm_cannot_add_unsupported_money_or_rental_transit(self):
        payload = parse_freight_quote(SAMPLE_QUOTE).model_dump()
        payload['financials']['total_amount'] = 8725
        payload['shipment_details']['est_transit_days'] = 3
        import json
        with patch('quote_agent._gemini_keys', return_value=['fixture']), patch('quote_agent._next_key_index', return_value=0), patch('quote_agent._gemini_once', return_value=json.dumps(payload)):
            q = parse_freight_quote_llm(SPOT_QUOTE)
        self.assertEqual(q.financials.total_amount, 4705)
        self.assertIsNone(q.shipment_details.est_transit_days)
        self.assertEqual(q.shipment_details.destination.country, "United States")

    def test_percentage_alongside_base_is_flagged(self):
        q = parse_freight_quote('Drayage: USD 650 plus 38% fuel.')
        self.assertEqual(q.financials.total_amount, 650)
        self.assertIn('38%', '\n'.join(q.extraction_flags))

    def test_separate_ocean_legs_are_not_deduplicated(self):
        q = parse_freight_quote('Ocean freight Shanghai to LAX: USD 100\nOcean freight Ningbo to LAX: USD 100')
        self.assertEqual(q.financials.total_amount, 200)

    def test_currency_and_unquantified_rates(self):
        q = parse_freight_quote('Ocean freight: USD 100\nCustoms fee: NGN 5000\nStorage: EUR 10/day')
        self.assertEqual(q.financials.total_amount, 5000)
        self.assertEqual(len(q.financials.line_items), 2)

if __name__ == '__main__':
    unittest.main()
