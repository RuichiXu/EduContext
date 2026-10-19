"""Verify the released fixtures and compression locally, without any model API."""
from __future__ import annotations

import argparse
import hashlib
from fractions import Fraction
from pathlib import Path

from edu_context import compress_lms, recover_json, restore_lms, unpack_lms_table
from edu_context.compressor import dumps
from edu_context.lms import flatten_record
from edu_context.recovery import strict_loads


def verify(directory, counter=None):
    manifest = strict_loads((directory/'manifest.json').read_text(encoding='utf-8'))
    results = []
    for info in manifest['files']:
        raw = (directory/info['path']).read_text(encoding='utf-8')
        assert hashlib.sha256(raw.encode()).hexdigest()==info['sha256']
        source = strict_loads(raw)
        key = 'studentList' if 'studentList' in source['data'] else 'activityList'
        rows = source['data'][key]
        assert len(rows)==info['records']
        for field,expected in [('studentScore','score_sum_exact'),('studentRate','rate_sum_exact')]:
            assert sum(Fraction(str(r[field])) for r in rows)==Fraction(info[expected])
        cases = [('numeric','统计成绩总和均分与状态分布',{}),
                 ('target','分析指定学生成绩和评语',{'student_uids':[rows[-1]['studentUid']]}),
                 ('full_text','完整保留所有评语',{'comment_scope':'all'})]
        for name,task,kwargs in cases:
            result = compress_lms(task,raw,source_complete=info['source_complete'],
                                  token_counter=counter,**kwargs)
            if not result.triggered:
                assert result.context==raw
            else:
                envelope = strict_loads(result.context)
                table = envelope['tables'][0]
                reconstructed = unpack_lms_table(table)
                omitted = set(table['comment_inventory']['omitted_source_indices'])
                comment_path = table['comment_inventory']['path']
                assert len(reconstructed)==len(rows)
                for index,(original,restored) in enumerate(zip(rows,reconstructed)):
                    expected = flatten_record(original)
                    if index in omitted:
                        del expected[comment_path]
                    assert flatten_record(restored)==expected
                if name=='target':
                    assert reconstructed[-1]==rows[-1]
                if name=='full_text':
                    assert restore_lms(envelope)==source
                stat = table['fields']['/studentScore']
                assert Fraction(str(stat['sum']))==Fraction(info['score_sum_exact'])
            results.append({'file':info['path'],'variant':name,'triggered':result.triggered,
                            'original_tokens':result.original_tokens,'compressed_tokens':result.compressed_tokens,
                            'within_budget':result.within_budget,'records_exact':True})
        recovered = recover_json(raw[:-100],allow_truncated=True)
        recovered_rows = recovered.value['data'][key]
        assert recovered_rows==rows[:len(recovered_rows)]
        assert recovered.metadata['source_complete'] is False
    return results


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--directory',type=Path,default=Path('datasets/production_deidentified'))
    parser.add_argument('--counter',choices=['estimated','o200k','cl100k'],default='estimated')
    args = parser.parse_args()
    counter = None
    if args.counter!='estimated':
        from evaluation import counters
        counter = getattr(counters,args.counter)
    print(dumps({'counter':args.counter,'checks':verify(args.directory,counter)}))


if __name__ == '__main__':
    main()
