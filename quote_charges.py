"""Conservative monetary evidence for freight quotes, independent of model output."""
import re
from decimal import Decimal

NUMBER = r"\d+(?:,\d{3})*(?:\.\d{1,2})?"
MONEY = re.compile(rf"(?P<code>USD|EUR|GBP|NGN|CNY|US\$|[$€£₦])\s*(?P<amount>{NUMBER})|(?P<after>{NUMBER})\s*(?P<suffix>USD|EUR|GBP|NGN|CNY|naira|dollars?)\b", re.I)
CONDITIONAL = re.compile(r"\b(if|unless|optional|conditional|maybe|may apply|might|subject to|upon request|when required|if applicable|not included|excluded|at cost|at actuals?|tarp(?:ing|ed)?)\b", re.I)
ROLLUP = re.compile(r"\b(subtotal|grand total|total local|total amount due|customs/tax|official/mid|parallel|platform fee|duty finance)\b", re.I)
RATE = re.compile(r"(?:\bper\s+|/\s*)(day|hour|kg|cbm|container|shipment)s?\b", re.I)


def currency(match):
    code = (match['code'] or match['suffix']).upper()
    return {'$': 'USD', 'US$': 'USD', 'DOLLAR': 'USD', 'DOLLARS': 'USD', 'NAIRA': 'NGN', '₦': 'NGN', '€': 'EUR', '£': 'GBP'}.get(code, code)


def charge_key(description):
    text = description.lower()
    if re.fullmatch(r'(?:base )?ocean freight', text.strip()) or (re.search(r'\b40\s*(?:hq|hc)\b', text) and not re.search(r'handling|doc|truck|chassis|surcharge', text)):
        return 'ocean freight'
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def extract_charges(text):
    items, flags = [], []
    # Decimal points and comma-separated amounts are never sentence delimiters.
    clauses = re.split(r'\n|;|(?<=[.!?])\s+(?=[A-Za-z])|,\s*(?=unless\b)', text, flags=re.I)
    for clause in clauses:
        clause = clause.strip().lstrip('-•').strip()
        matches = list(MONEY.finditer(clause))
        if re.search(r'\d+(?:\.\d+)?\s*%', clause):
            flags.append(f"Percentage term requires review; not added to baseline: {clause}")
        if not matches:
            continue
        if ROLLUP.search(clause[:matches[0].start()]):
            flags.append(f"Skipped rollup '{clause}' so it is not added on top of the detail lines.")
            continue
        if CONDITIONAL.search(clause):
            flags.append(f"Left optional charge or conditional term out of baseline: {clause}")
            continue
        if len(matches) != 1:
            flags.append(f"Multiple amounts need review; not added to baseline: {clause}")
            continue
        match = matches[0]
        description = clause[:match.start()].strip(' :-,')
        if len(description) < 3 or not re.search('[A-Za-z]', description):
            flags.append(f"Unlabeled amount needs review; not added to baseline: {clause}")
            continue
        if not re.search(r'[:=]|\b(freight|haulage|logistics|handling|doc(?:umentation)?|fee|charge|AMS|ISF|telex|customs|duty|duties|levy|VAT|tax|messenger|chassis|drayage|truck(?:ing)?|THC|DTHC|OTHC|BAF|LSS|brokerage|clearance|release|surcharge|insurance|40\s*(?:HQ|HC))\b', description, re.I):
            flags.append(f"Conversational amount needs review; not added to baseline: {clause}")
            continue
        if re.search(r'\b(discount|rebate|credit)\b', description, re.I):
            flags.append(f"Adjustment needs review; not added to baseline: {clause}")
            continue
        amount = Decimal((match['amount'] or match['after']).replace(',', ''))
        tail = clause[match.end():]
        unit = None
        if re.match(r'\s*[-–]\s*\d', tail):
            flags.append(f"Price range needs review; not added to baseline: {clause}")
            continue
        rate = RATE.search(tail)
        if rate:
            basis = rate.group(1).lower()
            minimum = re.search(rf'\bmin(?:imum)?\.?\s*(\d+)\s*{basis}s?\b', tail, re.I)
            if minimum:
                count = int(minimum[1]); amount *= count
                unit = f"{count} {basis}s minimum at {match.group(0)}/{basis}"
                flags.append(f"Minimum charge only; extra usage excluded: {clause}")
            elif basis in {'container', 'shipment'}:
                # One shipment is not evidence for the number of containers.
                if basis == 'container':
                    flags.append(f"Rate without confirmed quantity; not added to baseline: {clause}")
                    continue
                unit = 'per shipment'
            else:
                flags.append(f"Rate without confirmed quantity; not added to baseline: {clause}")
                continue
        if re.search(r'\beach\b', tail, re.I):
            if re.search(r'\bAMS\s*(?:/|&|and)\s*ISF\b', description, re.I):
                amount *= 2; unit = '2 filings at ' + match.group(0) + ' each'
            else:
                flags.append(f"Unit price without confirmed quantity; not added to baseline: {clause}")
                continue
        key = (charge_key(description), currency(match), amount)
        if any(item['_key'] == key for item in items):
            flags.append(f"Possible repeated charge counted once; review source: {clause}")
            continue
        items.append({'description': description, 'amount': float(amount), 'currency': currency(match), 'unit': unit, 'source_text': clause, '_key': key})
    return [{k: v for k, v in item.items() if k != '_key'} for item in items], flags
