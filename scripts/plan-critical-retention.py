#!/usr/bin/env python3
"""Filter a fixed-policy dry run; fail closed and protect known recovery points."""
import datetime as dt
import json
import re
import sys

PROTECTED = {
    '71c54e35ee092833307f2441248d20bda428a18fe4a7b0b957d556dec0d8c303',
    '5c5b3018c70edb5d4bf7339a98c66866abe0d69bb54dd8e530b6a9d9dae6f774',
}


def candidates(snapshots, policy, now):
    if not isinstance(snapshots, list) or not isinstance(policy, list):
        raise ValueError('Expected snapshot and policy arrays')
    by_id = {}
    times = {}
    for snapshot in snapshots:
        identifier = snapshot['id']
        if not re.fullmatch(r'[0-9a-f]{64}', identifier) or identifier in by_id:
            raise ValueError('Invalid/duplicate snapshot ID')
        by_id[identifier] = snapshot
        if snapshot.get('hostname') == 'blade' and 'blade-critical-v1' in (snapshot.get('tags') or []):
            time = dt.datetime.fromisoformat(snapshot['time'].replace('Z', '+00:00'))
            if time.tzinfo is None or time > now + dt.timedelta(minutes=5):
                raise ValueError('Invalid/future snapshot timestamp; manual review required')
            times[identifier] = time
    if not PROTECTED.issubset(by_id):
        raise ValueError('A protected recovery point is missing; manual review required')
    selected = set()
    for group in policy:
        for snapshot in group.get('remove', []) or []:
            identifier = snapshot['id']
            if identifier not in by_id:
                raise ValueError('Policy references an unknown snapshot')
            actual = by_id[identifier]
            if actual.get('hostname') != 'blade' or 'blade-critical-v1' not in (actual.get('tags') or []):
                raise ValueError('Policy references a snapshot outside the critical scope')
            if identifier not in PROTECTED and times[identifier] < now - dt.timedelta(days=14):
                selected.add(identifier)
    return sorted(selected)


def main():
    if len(sys.argv) != 3:
        raise ValueError('Expected snapshot JSON and policy JSON paths')
    with open(sys.argv[1]) as source:
        snapshots = json.load(source)
    with open(sys.argv[2]) as source:
        policy = json.load(source)
    result = candidates(snapshots, policy, dt.datetime.now(dt.timezone.utc))
    for identifier in result:
        print(identifier)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f'Retention plan refused: {error}', file=sys.stderr)
        sys.exit(1)
