"""Reproducible local business-data audit; optional paid model calls are opt-in.

Outputs can contain source text and identifiers. Keep output under the ignored
private_business_* directory; do not publish raw inputs, contexts, or caches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path
from time import perf_counter

from edu_context import compress, compress_lms, recover_json, restore_lms, unpack_lms_table
from edu_context.compressor import dumps
from edu_context.lms import flatten_record
from edu_context.recovery import strict_loads
from edu_context.text import EvidenceTextCompressor, visible_text
from edu_context.model_client import JSONModelClient
from .counters import cl100k, o200k


NUMERIC_TASK = "统计当前收到记录的成绩总和、均分、最高最低分、得分率和状态分布"
TEXT_TASK = "基于当前收到记录的教师评语，总结AI工具应用和视觉设计方面的优点与改进建议，并提供原文证据。不要推断未返回学生或完整活动的情况。"


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj), encoding="utf-8")


def credentials(path):
    # Parse only literal KEY=value lines; never execute shell syntax or interpolate.
    values = {}
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def independent_check(original, result):
    env = strict_loads(result.context)
    if env.get("format") != "lms-context/1":
        if not result.triggered and "format" not in env:
            assert env == original
            return {"passthrough_equal": True}
        raise AssertionError("Unexpected output protocol")
    cells, metrics = 0, 0
    for table in env['tables']:
        original_rows = original['data'][table['path'].split('/')[-1]]
        restored = unpack_lms_table(table)
        assert len(restored) == len(original_rows) == table['row_count']
        comment = table['comment_inventory']['path']
        omitted = set(table['comment_inventory']['omitted_source_indices'])
        for index, (source, out) in enumerate(zip(original_rows, restored)):
            expected = flatten_record(source)
            if index in omitted:
                del expected[comment]
            assert flatten_record(out) == expected
            cells += len(expected)
        for field, stat in table['fields'].items():
            all_flat = [flatten_record(r) for r in original_rows]
            values = [r[field] for r in all_flat if field in r]
            assert stat['present'] == len(values)
            assert stat['missing'] == len(original_rows) - len(values)
            assert stat['null'] == sum(v is None for v in values)
            if 'numeric_count' in stat:
                nums = [Fraction(str(v)) for v in values if not isinstance(v, (bool, str, list, dict)) and v is not None]
                assert stat['numeric_count'] == len(nums)
                if nums:
                    assert Fraction(str(stat['sum'])) == sum(nums)
                    mean = stat['mean_exact']
                    assert Fraction(mean['numerator'], mean['denominator']) == sum(nums)/len(nums)
                    assert Fraction(str(stat['min'])) == min(nums)
                    assert Fraction(str(stat['max'])) == max(nums)
                metrics += 1
            if 'value_counts' in stat:
                assert {dumps(v): n for v, n in stat['value_counts']} == dict(Counter(dumps(v) for v in values))
        if not omitted:
            assert restored == original_rows
    return {"checked_retained_cells": cells, "checked_numeric_columns": metrics,
            "all_received_structured_rows_exact": True,
            "all_summaries_match_independent_oracle": True}


def metadata(result):
    return {k: v for k, v in vars(result).items() if k != 'context'}


def audit_files(paths, output):
    records = []
    for file_no, path in enumerate(paths):
        raw = path.read_text(encoding='utf-8-sig')
        original = strict_loads(raw)
        rows = next(v for k, v in original['data'].items() if k in ('studentList','activityList'))
        declared_complete = False if file_no == 0 else None
        target_uid = rows[-1]['studentUid']
        for counter in (cl100k, o200k):
            baseline = compress(NUMERIC_TASK, raw, token_counter=counter)
            records.append({'file': path.name, 'variant': 'old_core', 'counter': counter.__name__, **metadata(baseline)})
            cases = [('numeric', NUMERIC_TASK, {}),
                     ('target', f'分析学号 {target_uid} 的成绩及教师评语', {'student_uids': [target_uid]}),
                     ('full_text', '完整保留所有教师评语和明细', {'comment_scope': 'all'})]
            if len(raw) <= 420000:
                cases = [('production_passthrough', NUMERIC_TASK, {}),
                         ('forced_structural', '完整保留所有教师评语和明细', {'force': True})]
            for name, task, kw in cases:
                started = perf_counter()
                r = compress_lms(task, raw, token_counter=counter,
                                 source_complete=declared_complete, **kw)
                check = independent_check(original, r)
                row = {'file': path.name, 'variant': name, 'counter': counter.__name__,
                       'seconds': round(perf_counter()-started, 4), **metadata(r), 'integrity': check}
                records.append(row)
                (output/f'{file_no}.{name}.{counter.__name__}.context.json').write_text(r.context, encoding='utf-8')
        # Multiple artificial cuts in this actual file, no synthetic duplicated rows.
        cuts = []
        needle = '"studentUid"'
        positions = [raw.rfind(needle), max(1, len(raw)-100), max(1, len(raw)-1000), len(raw)-2]
        for position in positions:
            recovered = recover_json(raw[:position], allow_truncated=True)
            recovered_rows = recovered.value.get('data',{}).get('studentList', recovered.value.get('data',{}).get('activityList', []))
            assert recovered_rows == rows[:len(recovered_rows)]
            assert recovered.metadata['source_complete'] is False
            cuts.append({'cut_chars': position, 'complete_rows_recovered': len(recovered_rows),
                         'exact_prefix': True, 'events': recovered.metadata['recovery_events']})
        save(output/f'{file_no}.recovery_checks.json', cuts)
    return records


def model_summary(path, output, client):
    raw = path.read_text(encoding='utf-8-sig')
    original = strict_loads(raw)
    compressor = EvidenceTextCompressor(client)
    result = compress_lms(TEXT_TASK, raw, token_counter=o200k, source_complete=False,
                          comment_scope='summarize', text_compressor=compressor)
    (output/'large.semantic.context.json').write_text(result.context, encoding='utf-8')
    save(output/'semantic_audit_inputs.json', compressor.audit_batches)
    check = independent_check(original, result)
    report = {**metadata(result), 'integrity': check, 'model_calls': client.calls,
              'api_network_calls_this_run': client.network_calls,
              'encodings_of_same_context': {name: {'original': counter(raw), 'compressed': counter(result.context),
                                                   'ratio': counter(raw)/counter(result.context)}
                                             for name, counter in [('cl100k',cl100k),('o200k',o200k)]}}
    save(output/'semantic_report.json', report)
    return report


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--files', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('evaluation/private_business_20261012'))
    parser.add_argument('--model', action='store_true')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--only-model', action='store_true')
    parser.add_argument('--answer-eval', action='store_true')
    parser.add_argument('--judge', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not args.only_model:
        report = audit_files(args.files, args.output)
        save(args.output/'deterministic_report.json', report)
        print(json.dumps([{'file':r['file'],'variant':r['variant'],'counter':r['counter'],
                           'ratio':r['original_tokens']/max(1,r['compressed_tokens']),
                           'triggered':r['triggered'],'within_budget':r['within_budget']} for r in report],ensure_ascii=False))
    if args.model or args.answer_eval or args.judge:
        if not args.env_file:
            parser.error('--model requires an explicitly authorized --env-file')
        env = credentials(args.env_file)
        client = JSONModelClient(api_key=env['TENCENT_API_KEY'],base_url=env['TENCENT_BASE_URL'],
                                 model='deepseek/deepseek-flash', cache_dir=args.output/'model_cache',
                                 max_calls=24, timeout=300, extra_body={'thinking': {'type': 'disabled'}})
        if args.model:
            report = model_summary(args.files[0],args.output,client)
            print(json.dumps({'semantic_ratio':report['stats']['token_ratio'],
                          'within_budget':report['within_budget'],
                          'network_calls':client.network_calls,
                          'omitted_comments':report['stats']['omitted_comments']},ensure_ascii=False))
        if args.answer_eval:
            from .lms_model_eval import paired_answers
            report = paired_answers(args.files,args.output,client)
            print(dumps([{k:r[k] for k in ('file_index','variant','passed','total')} for r in report]))
        if args.judge:
            from .lms_model_eval import judge_summaries
            report = judge_summaries(args.output,client)
            print(dumps({'judge_supported':sum(sum(r['supported']) for r in report),
                         'judge_total':sum(len(r['supported']) for r in report)}))


if __name__ == '__main__':
    main()
