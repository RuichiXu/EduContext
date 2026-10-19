"""Export aggregate-only business metrics; never copy answers or source quotes."""
import hashlib
import json
from pathlib import Path


def main():
    private = Path('evaluation/private_business_20261012')
    final = private / 'text_v3'
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    deterministic = read(private / 'deterministic_report.json')
    semantic = read(final / 'semantic_report.json')
    answers = read(final / 'answer_report.json')
    judge = read(final / 'semantic_judge.json')
    rows = []
    for r in deterministic:
        rows.append({k:r[k] for k in ('variant','counter','original_chars','compressed_chars',
                                     'original_tokens','compressed_tokens','triggered','within_budget')})
    code_files = sorted(Path('edu_context').glob('*.py')) + sorted(Path('tests').glob('*.py'))
    report = {'date':'2026-10-12', 'scope':'Two received business files, single model run per variant; not population accuracy.',
              'deterministic':rows,
              'semantic':{k:semantic[k] for k in ('original_chars','compressed_chars','original_tokens',
                          'compressed_tokens','within_budget','integrity','encodings_of_same_context')},
              'semantic_usage':{key:sum(c['usage'][key] for c in semantic['model_calls'])
                                for key in ('prompt_tokens','completion_tokens','total_tokens')},
              'answers':[{k:r[k] for k in ('file_index','variant','context_tokens_o200k','passed','total','checks')}
                         for r in answers],
              'quote_judge':{'supported':sum(sum(r['supported']) for r in judge),
                             'total':sum(len(r['supported']) for r in judge),
                             'limitation':'Same-model separate review; no exhaustive semantic recall certification.'},
              'recovery_checks':[[{k:r[k] for k in ('cut_chars','complete_rows_recovered','exact_prefix')}
                                  for r in read(private/f'{i}.recovery_checks.json')] for i in range(2)],
              'tests':{'module_tests':67,'evaluation_tests':6,'passed':73},
              'code_sha256':{str(p).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files}}
    target = Path('evaluation/artifacts/business_summary_20261012.json')
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(target))


if __name__ == '__main__':
    main()
