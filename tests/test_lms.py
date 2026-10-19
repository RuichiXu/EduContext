import json
import unittest
from decimal import Decimal

from edu_context import Config, compress, compress_lms, recover_json, restore_lms, unpack_lms_table
from edu_context.compressor import dumps
from edu_context.lms import flatten_record, unflatten_record
from edu_context.recovery import strict_loads
from edu_context.text import EvidenceTextCompressor, visible_text


def fixture():
    return {"ok": True, "data": {"studentList": [
        {"studentUid": i, "studentName": "同学" + str(i), "activityId": 12,
         "studentScore": Decimal("80.125") + i, "studentRate": Decimal("0.81"),
         "status": "完成", "extra": {"stuHomeworkTeacherComment": "建议补充具体实例并清晰解释关键操作步骤。" * 3,
                                      "stuHomeworkIsRevised": "是", "stuHomeworkRefTime": 123400 + i}}
        for i in range(4)]}, "meta": {"has_more": True}}


class RecoveryTests(unittest.TestCase):
    def test_core_api_opt_in_recovery_reaches_downstream(self):
        text = '{"rows":[{"score":85},{"score":9'
        for forced in (True, False):
            r = compress('统计成绩', text, recover_truncated=True, force=forced)
            env = strict_loads(r.context)
            self.assertFalse(env['data_quality']['source_complete'])
            if forced:
                self.assertEqual(env['tables'][0]['row_count'], 1)
            else:
                self.assertEqual(env['source']['rows'], [{'score': 85}])

    def test_valid_source_completeness_is_separate(self):
        r = recover_json('{"x":1}', source_complete=False)
        self.assertFalse(r.metadata['syntax_recovered'])
        self.assertFalse(r.metadata['source_complete'])
        self.assertIsNone(recover_json('{"x":1}').metadata['source_complete'])

    def test_cut_tail_keeps_only_complete_records(self):
        text = '{"ok":true,"data":{"studentList":[{"id":1},{"id":2,"score":8'
        r = recover_json(text, allow_truncated=True)
        self.assertEqual(r.value['data']['studentList'], [{'id': 1}])
        self.assertTrue(r.metadata['syntax_recovered'])
        self.assertFalse(r.metadata['source_complete'])
        self.assertTrue(any(e['kind'] == 'discarded_incomplete_array_item' for e in r.metadata['recovery_events']))

    def test_missing_closing_brackets_keeps_closed_row(self):
        r = recover_json('{"data":{"studentList":[{"id":1}', allow_truncated=True)
        self.assertEqual(r.value['data']['studentList'], [{'id': 1}])

    def test_cut_number_is_not_a_smaller_valid_number(self):
        r = recover_json('{"rows":[{"a":1}],"total":12', allow_truncated=True)
        self.assertNotIn('total', r.value)
        self.assertEqual(r.value['rows'], [{'a': 1}])

    def test_strings_escapes_braces_and_partial_unicode(self):
        r = recover_json('{"rows":[{"s":"a} ] \\\" b"},{"s":"abc\\u4e', allow_truncated=True)
        self.assertEqual(r.value['rows'], [{'s': 'a} ] " b'}])

    def test_interior_errors_duplicates_nonfinite_rejected(self):
        for s in ['{"x":1 "y":2}', '{"a":1,"a":2', '{"x":NaN}',
                  '{"x":[1,]}', '{"x":01', '{"x":truX', '{"x":"bad\\z',
                  '{"a":1} garbage', '{"x":[{]', '{"x":-.', '{"x":1.e']:
            with self.subTest(s=s), self.assertRaises(ValueError):
                recover_json(s, allow_truncated=True)

    def test_strict_default_rejects_truncation(self):
        with self.assertRaises(ValueError):
            recover_json('{"rows":[')

    def test_every_cut_has_only_complete_prefix_records(self):
        rows = [{'id': i, 's': '引号"反斜杠\\花括号{}', 'v': Decimal('85.25')} for i in range(8)]
        raw = dumps({'data': {'studentList': rows}, 'total': 8})
        for cut in range(1, len(raw)):
            r = recover_json(raw[:cut], allow_truncated=True)
            recovered = r.value.get('data', {}).get('studentList', [])
            self.assertEqual(recovered, rows[:len(recovered)])


class LMSAdapterTests(unittest.TestCase):
    def test_small_string_is_exact_passthrough(self):
        raw = dumps(fixture())
        r = compress_lms('评语分析', raw)
        self.assertFalse(r.triggered)
        self.assertEqual(r.context, raw)

    def test_full_comment_nested_roundtrip(self):
        data = fixture()
        data['data']['studentList'][0]['extra']['custom'] = {'x/y': None, '~': [], 'empty': {}}
        r = compress_lms('生成学情报告', data, force=True)
        self.assertEqual(restore_lms(strict_loads(r.context)), data)

    def test_pointer_escaping_and_empty_values(self):
        row = {'x/y': {'~a': None, '': []}, '': {'v': '0'}, 'empty': {}}
        self.assertEqual(unflatten_record(flatten_record(row)), row)

    def test_numeric_projection_preserves_every_scalar(self):
        original = fixture()
        r = compress_lms('统计作业成绩和状态', original, force=True)
        env = strict_loads(r.context)
        table = env['tables'][0]
        reconstructed = unpack_lms_table(table)
        for i, row in enumerate(reconstructed):
            expected = original['data']['studentList'][i]
            for key, value in flatten_record(expected).items():
                if key.endswith('/stuHomeworkTeacherComment'):
                    continue
                self.assertEqual(flatten_record(row)[key], value)
        self.assertEqual(table['fields']['/studentScore']['sum'], Decimal('326.500'))
        self.assertEqual(table['comment_inventory']['omitted_nonempty'], 4)
        with self.assertRaises(ValueError):
            restore_lms(env)

    def test_target_comment_remains_verbatim_even_with_none_policy(self):
        data = fixture()
        r = compress_lms('统计成绩', data, student_uids=[2], comment_scope='none', force=True)
        table = strict_loads(r.context)['tables'][0]
        self.assertEqual(table['target_indices'], [2])
        self.assertEqual(unpack_lms_table(table)[2], data['data']['studentList'][2])
        self.assertEqual(table['comment_inventory']['omitted_nonempty'], 3)

    def test_inferred_uid_and_name_targets(self):
        for task in ['分析学号 2 的评语', '分析同学2的评语']:
            r = compress_lms(task, fixture(), force=True)
            table = strict_loads(r.context)['tables'][0]
            self.assertEqual(table['target_indices'], [2])
            self.assertEqual(table['comments']['indices'], [2])

    def test_unresolved_uid_is_conservative(self):
        for kwargs in [{'student_uids': [999]}, {}]:
            r = compress_lms('统计学号 999 的成绩', fixture(), force=True, **kwargs)
            self.assertEqual(restore_lms(strict_loads(r.context)), fixture())

    def test_missing_empty_null_comment_distinctions(self):
        data = fixture()
        del data['data']['studentList'][0]['extra']['stuHomeworkTeacherComment']
        data['data']['studentList'][1]['extra']['stuHomeworkTeacherComment'] = None
        data['data']['studentList'][2]['extra']['stuHomeworkTeacherComment'] = ''
        r = compress_lms('统计成绩', data, force=True)
        inventory = strict_loads(r.context)['tables'][0]['comment_inventory']
        self.assertEqual((inventory['missing'], inventory['null'], inventory['empty'], inventory['omitted_nonempty']), (1, 1, 1, 1))

    def test_small_truncated_input_recovered_without_forcing_compression(self):
        raw = '{"ok":true,"data":{"studentList":[{"studentUid":1},{"studentUid":'
        r = compress_lms('统计成绩', raw, recover_truncated=True)
        self.assertFalse(r.triggered)
        env = strict_loads(r.context)
        self.assertEqual(env['source']['data']['studentList'], [{'studentUid': 1}])
        self.assertFalse(env['data_quality']['source_complete'])

    def test_incomplete_valid_source_flag_reaches_model(self):
        r = compress_lms('统计成绩', fixture(), source_complete=False)
        self.assertEqual(strict_loads(r.context)['data_quality']['source_complete'], False)

    def test_budget_is_final_counter_and_preserves_all_rows(self):
        r = compress_lms('报告', fixture(), force=True, token_counter=len, config=Config(max_tokens=2))
        self.assertEqual(r.compressed_tokens, len(r.context))
        self.assertFalse(r.within_budget)
        self.assertEqual(restore_lms(strict_loads(r.context)), fixture())

    def test_model_failure_keeps_original_comments(self):
        def fail(**kwargs):
            raise RuntimeError('secret provider diagnostic must not appear')
        r = compress_lms('总结评语', fixture(), force=True, comment_scope='summarize',
                         text_compressor=fail)
        self.assertEqual(restore_lms(strict_loads(r.context)), fixture())
        self.assertNotIn('secret provider', r.context)


class TextCompressionTests(unittest.TestCase):
    def test_math_and_html_text_normalization(self):
        raw = '&lt;p&gt;若xy&amp;lt;0，则x&lt;sup&gt;2&lt;/sup&gt;大于0。&lt;/p&gt;'
        self.assertEqual(visible_text(raw), '若xy<0，则x^{2}大于0。')
        self.assertEqual(visible_text('x < 2 且 y > 3'), 'x < 2 且 y > 3')
        self.assertIn('href: https://example.com', visible_text('&lt;a href="https://example.com"&gt;例子&lt;/a&gt;'))

    def test_full_batch_coverage_and_quote_attribution(self):
        doc = {'index': 7, 'text': '建议补充具体实例并清晰解释关键操作步骤。'}
        good = {'reviewed_indices': [7], 'findings': [{'finding': '说明操作步骤',
                    'evidence': [{'index': 7, 'quote': doc['text']}]}]}
        self.assertEqual(EvidenceTextCompressor.validate(good, [doc])['findings'][0]['evidence'][0]['normalized_char_start'], 0)
        self.assertEqual(EvidenceTextCompressor.validate(good, [doc])['findings'][0]['finding'], doc['text'])
        for bad in [dict(good, reviewed_indices=[]), dict(good, reviewed_indices=[7, 7]),
                    {'reviewed_indices': [7], 'findings': [{'finding': '不实', 'evidence': [{'index': 7, 'quote': '并不存在于原文的引用或模型编造内容'}]}]}]:
            with self.assertRaises(ValueError):
                EvidenceTextCompressor.validate(bad, [doc])

    def test_oversized_document_is_not_silently_sliced(self):
        compressor = EvidenceTextCompressor(lambda **kw: {}, batch_chars=1000)
        with self.assertRaises(ValueError):
            compressor(task='总结', documents=[{'index': 0, 'text': '长' * 1001}], token_budget=1000)

    def test_model_is_opt_in(self):
        with self.assertRaises(ValueError):
            compress_lms('总结评语', fixture(), force=True, comment_scope='summarize')


if __name__ == '__main__':
    unittest.main()
