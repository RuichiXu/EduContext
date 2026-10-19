import tempfile
import unittest
from pathlib import Path

from edu_context.compressor import dumps
from edu_context.recovery import strict_loads
from scripts.prepare_public_data import release, get_rows


class PublicReleaseTests(unittest.TestCase):
    def test_redaction_preserves_metrics_and_cross_file_links(self):
        def record(score):
            return {'studentUid':222222221,'studentName':'虚构甲','activityId':333333331,
                    'studentScore':score,'studentRate':0.8,'extra':{
                        'stuHomeworkThUID':444444441,'stuHomeworkThName':'虚构乙',
                        'stuHomeworkRefTime':1700000000,
                        'stuHomeworkRefTimeBeijingFormat':'2023-11-15 06:13:20',
                        'stuHomeworkTeacherComment':'虚构甲建议补充操作步骤。为【虚构个人】视频账号制作内容。联系user@example.com。'}}
        first = {'ok':True,'data':{'studentList':[record(80)]}}
        other = record(90)
        other['activityExtra'] = other.pop('extra')
        second = {'ok':True,'data':{'activityList':[other]},'error':None,'meta':{}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = [root/'a.json',root/'b.json']
            for path,data in zip(inputs,[first,second]):
                path.write_text(dumps(data),encoding='utf-8')
            out = root/'release'
            manifest = release(inputs,out)
            a = strict_loads((out/'student_list.json').read_text(encoding='utf-8'))['data']['studentList'][0]
            b = strict_loads((out/'student_activities.json').read_text(encoding='utf-8'))['data']['activityList'][0]
            self.assertEqual(a['studentUid'],b['studentUid'])
            self.assertEqual(a['activityId'],b['activityId'])
            self.assertEqual(a['studentScore'],80)
            self.assertEqual(b['studentScore'],90)
            self.assertEqual(a['extra']['stuHomeworkRefTime'],1577836800)
            self.assertEqual(a['extra']['stuHomeworkRefTimeBeijingFormat'],'2020-01-01 08:00:00')
            content = ''.join(p.read_text(encoding='utf-8') for p in out.glob('*.json'))
            for value in ['虚构甲','虚构乙','虚构个人','user@example.com','222222221','333333331','444444441']:
                self.assertNotIn(value,content)
            self.assertFalse(manifest['identifier_mapping_published'])
            self.assertNotIn(str(inputs[0]),content)

    def test_unreviewed_fields_are_rejected(self):
        for data in [{'data':{'studentList':[]},'meta':{'school':'unknown'}},
                     {'data':{'studentList':[{'unreviewedPersonalField':'value'}]}}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                get_rows(data)


if __name__ == '__main__':
    unittest.main()
