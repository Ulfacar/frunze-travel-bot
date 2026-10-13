"""Validate frozen acceptance definitions and print evidenced engineering points.

This reads local evidence only; points do not certify review or production use.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFINITION_SHA256 = '3a26373ae606cb6bba64adf1bd41fd8efb7a767663523d328cbd166aca219f4a'


def evaluate(document, root=ROOT):
    criteria = document['criteria']
    definitions = [{key: row[key] for key in ('id', 'weight', 'pdf', 'acceptance')} for row in criteria]
    digest = hashlib.sha256(json.dumps(definitions, ensure_ascii=False, sort_keys=True,
                                      separators=(',', ':')).encode()).hexdigest()
    if digest != DEFINITION_SHA256 or digest != document['definition_sha256']:
        raise ValueError('Acceptance definitions changed; do not silently recalculate the baseline')
    if len(criteria) != 50 or sum(row['weight'] for row in criteria) != 100:
        raise ValueError('Expected 50 criteria / 100 total points')
    points = 0
    review_pending = []
    for row in criteria:
        if row['status'] not in ('PASS', 'FAIL', 'UNKNOWN') or row['review'] not in ('PASS', 'FAIL', 'UNKNOWN'):
            raise ValueError('Invalid evidence status')
        if row['status'] != 'PASS':
            continue
        if not row['evidence']:
            raise ValueError(f"Missing evidence: {row['id']}")
        for evidence in row['evidence']:
            if evidence['result'] != 'PASS' or not re.fullmatch('[a-f0-9]{40}', evidence['revision']):
                raise ValueError(f"Missing exact passing revision: {row['id']}")
            if not evidence['command'] or not evidence['environment'] or not evidence['scope']:
                raise ValueError(f"Incomplete evidence: {row['id']}")
            artifact = (root / evidence['artifact']).resolve()
            if not artifact.is_relative_to(root.resolve()) or not artifact.is_file():
                raise ValueError(f"Missing local evidence artifact: {row['id']}")
        points += row['weight']
        if row['review'] != 'PASS':
            review_pending.append(row['id'])
    return dict(engineering_points=points, remaining_points=100-points,
                target_points=document['target_points'], total_points=100,
                independently_reviewed=False if review_pending else None,
                review_not_pass=review_pending, production_readiness='UNKNOWN')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--criteria', type=Path, default=ROOT/'docs/pdf-engineering-criteria.json')
    args = parser.parse_args()
    result = evaluate(json.loads(args.criteria.read_text(encoding='utf-8')))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
