"""Bounded literal captures only; a parsed observation is never a decision."""
import hashlib
import re
import unicodedata

from app.domain.entry_storage import EntryStorageInvalid
from app.domain.entry_portal_policy import PARSER_VERSION, PortalPolicy, day

MAX_BYTES = 16384
MAX_LINES = 128
MAX_LINE = 512


def parse(text, policy):
    if not isinstance(policy, PortalPolicy) or type(text) is not str:
        raise EntryStorageInvalid('invalid_portal_input')
    try: raw = text.encode('utf-8')
    except UnicodeError: raise EntryStorageInvalid('invalid_portal_input') from None
    lines = text.replace('\r\n', '\n').split('\n')
    if (not 1 <= len(raw) <= MAX_BYTES or len(lines) > MAX_LINES or any(len(v) > MAX_LINE for v in lines) or
        any(unicodedata.category(c).startswith('C') and c not in '\r\n\t' for c in text)):
        raise EntryStorageInvalid('invalid_portal_input')
    references, kinds, dates, issues = [], [], [], set()
    labels = {label: kind for kind, label in policy.status_labels}
    for original in lines:
        line = original.strip()
        candidate = line.lstrip('>| ')
        quoted = candidate != line
        if '<' in line or '>' in line: issues.add('markup_or_quote')
        if candidate.startswith(policy.reference_label):
            value = candidate[len(policy.reference_label):]
            if re.fullmatch(r'[A-Z0-9]{8}', value): references.append(value)
            else: issues.add('invalid_reference')
            if quoted: issues.add('quoted_capture')
        if candidate.startswith(policy.date_label):
            value = candidate[len(policy.date_label):]
            try: day(value)
            except EntryStorageInvalid: issues.add('invalid_date')
            else: dates.append(value)
            if quoted: issues.add('quoted_capture')
        if candidate.startswith(policy.status_label):
            value = candidate[len(policy.status_label):]
            if value in labels: kinds.append(labels[value])
            else: issues.add('unknown_status')
            if quoted: issues.add('quoted_capture')
    # Duplicate captures, even identical ones, can be a quoted prior message.
    # Keep their bounded structured values, with an explicit ambiguity marker.
    if len(references) != 1: issues.add('reference_not_unique')
    if len(kinds) != 1: issues.add('status_not_unique')
    if len(dates) > 1: issues.add('date_not_unique')
    return {'parser_version': PARSER_VERSION, 'raw_sha256': hashlib.sha256(raw).hexdigest(),
            'raw_bytes': len(raw), 'references': sorted(set(references)), 'kinds': sorted(set(kinds)),
            'dates': sorted(set(dates)), 'issues': sorted(issues)}
