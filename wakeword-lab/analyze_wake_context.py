"""Offline diagnosis of the CURRENT name-only wake policy; never updates the app.

Input caches must come from the same ordered corpus. Original name-only negatives
were created when 'Ei Emily' was mandatory and are positives under today's policy.
General English ASR confirmation is experimental: it must preserve personal calls
and demonstrate useful discrimination before being considered for production.
"""
import argparse
import json
import math
from pathlib import Path


def is_current_call(row):
    return bool(row['positive']) or row['text'].strip().lower() == 'emily.'


def accepted_segment(segment):
    words = segment.get('result', [])
    if not words:
        return False
    prefix = words[0]['word'].lower() == 'hey'
    index = 1 if prefix else 0
    if len(words) != index + 1 or words[index]['word'].lower() != 'emily':
        return False
    for word in words:
        if any(not math.isfinite(word[k]) for k in ('conf', 'start', 'end')):
            return False
        if word['start'] < 0 or word['end'] <= word['start'] or word['conf'] < .70:
            return False
    name = words[index]
    if name['end'] - name['start'] < .18:
        return False
    if prefix:
        first = words[0]
        if first['end'] - first['start'] < .05:
            return False
        if not -.06 <= name['start'] - first['end'] <= .45:
            return False
    return True


def full_confirmation(segment, full_segments):
    """Experimental independent recognition must agree on the name/time span."""
    name = segment['result'][-1]
    return any(
        w['word'].lower() == 'emily' and w.get('conf', 0) >= .70
        and min(w['end'], name['end']) > max(w['start'], name['start'])
        for s in full_segments for w in s.get('result', [])
    )


def analyze(baseline, full):
    if len(baseline) != len(full):
        raise ValueError('Corpus lengths differ')
    results = []
    for a, b in zip(baseline, full):
        identity = ('path', 'group', 'text', 'kind')
        if any(a.get(k) != b.get(k) for k in identity):
            raise ValueError('Corpus identities differ')
        segments = [s for s in a['segments'] if accepted_segment(s)]
        results.append(dict(group=a['group'], kind=a.get('kind'), text=a['text'],
            positive=is_current_call(a), baseline=bool(segments),
            confirmed=any(full_confirmation(s, b['full']) for s in segments),
            general_text=' / '.join(s['text'] for s in b['full'] if s['text'])))
    def summary(items):
        return {label: { 'total':sum(r['positive']==positive for r in items),
            'baseline_accepted':sum(r['positive']==positive and r['baseline'] for r in items),
            'confirmed_accepted':sum(r['positive']==positive and r['confirmed'] for r in items)}
            for label,positive in [('calls',True),('non_calls',False)]}
    return dict(summary=summary(results), private=[r for r in results if r['group']=='private'],
        lost_calls=[r for r in results if r['positive'] and r['baseline'] and not r['confirmed']],
        rejected_non_calls=[r for r in results if not r['positive'] and r['baseline'] and not r['confirmed']],
        limits=['Synthetic recordings do not measure false activations per hour.',
                'Only three private calls, all recorded as Ei Emily, are available.',
                'No spontaneous conversation causing the reported issue is available.',
                'PC replay does not measure Android battery or microphone behavior.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--full', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(json.loads(args.baseline.read_text()), json.loads(args.full.read_text()))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('lost_calls','rejected_non_calls')},ensure_ascii=False,indent=2))
