"""Create de-identified production-derived fixtures from explicit local inputs.

No input paths or identifier lookup tables are written to the public output.
This script is tailored to the two reviewed export schemas, not a general PII
detector. New datasets require a separate privacy review before publication.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime, timezone, timedelta
from fractions import Fraction
from pathlib import Path

from edu_context.compressor import dumps
from edu_context.recovery import strict_loads


CONTACT_PATTERNS = [
    (r'https?://[^\s<>"\']+', '[URL_REDACTED]'),
    (r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[EMAIL_REDACTED]'),
    (r'(?<!\d)1[3-9]\d{9}(?!\d)', '[PHONE_REDACTED]'),
    (r'(?<!\d)\d{17}[\dXx](?!\d)', '[ID_REDACTED]'),
]
ACCOUNT_LABEL = re.compile(r'【[^】]{1,80}】(?=.{0,12}账号)')
COMMENT = 'stuHomeworkTeacherComment'
IDENTITY_KEYS = {'studentUid', 'studentName', 'activityId', 'stuHomeworkThUID', 'stuHomeworkThName'}
TIME_KEYS = {'stuHomeworkRefTime', 'stuHomeworkRefTimeBeijingFormat'}
ROW_KEYS = {'activityId','activityName','processFlag','activityBizType','studentUid',
            'studentName','studentScore','studentRate','status','extra','activityExtra'}
EXTRA_KEYS = TIME_KEYS | {COMMENT,'stuHomeworkIsRevised','stuHomeworkReadover',
             'stuHomeworkIsReform','stuHomeworkEmend','stuHomeworkCorrect','stuHomeworkWrong',
             'stuHomeworkAdmire','stuHomeworkIsCream','stuHomeworkThUID','stuHomeworkThName'}


def get_rows(data):
    keys = [k for k in ('studentList','activityList') if k in data.get('data',{})]
    if len(keys) != 1 or set(data['data']) != set(keys):
        raise ValueError('Only the two reviewed export schemas may be released')
    if set(data) - {'ok','data','error','meta'} or data.get('meta',{}) or data.get('error') is not None:
        raise ValueError('New metadata requires a manual privacy review')
    rows = data['data'][keys[0]]
    for row in rows:
        if set(row)-ROW_KEYS:
            raise ValueError('Unknown row field requires privacy review')
        extra = row.get('extra',row.get('activityExtra',{}))
        if set(extra)-EXTRA_KEYS:
            raise ValueError('Unknown nested field requires privacy review')
    return rows


def release(inputs, output):
    source = [strict_loads(p.read_text(encoding='utf-8-sig')) for p in inputs]
    all_rows = [row for data in source for row in get_rows(data)]
    students, activities, teachers, names = {}, {}, {}, {}
    original_ids, original_names = set(), set()
    timestamps = []
    for row in all_rows:
        sid = row['studentUid']
        students.setdefault(sid,900000001+len(students))
        activities.setdefault(row['activityId'],800000001+len(activities))
        if row.get('studentName'):
            original_names.add(row['studentName'])
            names[row['studentName']] = f"学生{students[sid]-900000000:04d}"
        extra = row.get('extra',row.get('activityExtra',{}))
        tid = extra.get('stuHomeworkThUID')
        if tid is not None:
            teachers.setdefault(tid,700000001+len(teachers))
        if extra.get('stuHomeworkThName'):
            original_names.add(extra['stuHomeworkThName'])
            names[extra['stuHomeworkThName']] = '教师已脱敏'
        for value in [sid,row['activityId'],tid]:
            if value is not None and len(str(value))>=5:
                original_ids.add(str(value))
        timestamp = extra.get('stuHomeworkRefTime',0)
        if timestamp:
            timestamps.append(timestamp / (1000 if timestamp>100000000000 else 1))
    # Move all absolute timestamps onto a synthetic timeline; preserve intervals.
    shift = int(datetime(2020,1,1,tzinfo=timezone.utc).timestamp()-min(timestamps))
    substitutions = {'known_names':0,'embedded_ids':0,'account_labels':0,'contacts':0,'text_dates':0}

    def clean(text):
        for name in sorted(names,key=len,reverse=True):
            substitutions['known_names'] += text.count(name)
            text = text.replace(name,names[name])
        for identifier in sorted(original_ids,key=len,reverse=True):
            text,count = re.subn(r'(?<!\d)'+re.escape(identifier)+r'(?!\d)','[ID_REDACTED]',text)
            substitutions['embedded_ids'] += count
        text,count = ACCOUNT_LABEL.subn('【账号已脱敏】',text)
        substitutions['account_labels'] += count
        for pattern,replacement in CONTACT_PATTERNS:
            text,count = re.subn(pattern,replacement,text)
            substitutions['contacts'] += count
        text,count = re.subn(r'20\d{2}[-年/.]\d{1,2}[-月/.]\d{1,2}日?', '[日期已脱敏]',text)
        substitutions['text_dates'] += count
        return text

    output.mkdir(parents=True,exist_ok=True)
    manifest = {'version':1,'source_kind':'production-derived de-identified exports',
                'release_date':'2026-10-19','original_inputs_published':False,
                'identifier_mapping_published':False,'time_policy':'Common shift to a synthetic timeline; relative intervals preserved.',
                'text_policy':'Original comments with identifying spans redacted; not model-generated replacements.',
                'files':[]}
    for file_no,data in enumerate(source):
        rows = get_rows(data)
        for row in rows:
            sid = row['studentUid']
            row['studentUid'] = students[sid]
            row['activityId'] = activities[row['activityId']]
            if 'studentName' in row:
                row['studentName'] = f"学生{students[sid]-900000000:04d}"
            extra = row.get('extra',row.get('activityExtra',{}))
            if 'stuHomeworkThUID' in extra:
                extra['stuHomeworkThUID'] = teachers[extra['stuHomeworkThUID']]
            if 'stuHomeworkThName' in extra:
                extra['stuHomeworkThName'] = '教师已脱敏'
            timestamp = extra.get('stuHomeworkRefTime',0)
            if timestamp:
                extra['stuHomeworkRefTime'] += shift*(1000 if timestamp>100000000000 else 1)
            formatted = extra.get('stuHomeworkRefTimeBeijingFormat','')
            if formatted:
                extra['stuHomeworkRefTimeBeijingFormat'] = (
                    datetime.strptime(formatted,'%Y-%m-%d %H:%M:%S')+timedelta(seconds=shift)
                ).strftime('%Y-%m-%d %H:%M:%S')
            for obj in (row,extra):
                for key,value in list(obj.items()):
                    if isinstance(value,str) and key not in IDENTITY_KEYS|TIME_KEYS:
                        obj[key] = clean(value)
        encoded = dumps(data)
        # Detect a known identifier surviving outside its original structured field.
        if any(name in encoded for name in original_names):
            raise ValueError('A known personal name survived redaction')
        if any(re.search(r'(?<!\d)'+re.escape(i)+r'(?!\d)',encoded) for i in original_ids):
            raise ValueError('An original business identifier survived redaction')
        filename = 'student_list.json' if file_no==0 else 'student_activities.json'
        (output/filename).write_text(encoded,encoding='utf-8')
        scores = [Fraction(str(row['studentScore'])) for row in rows]
        rates = [Fraction(str(row['studentRate'])) for row in rows]
        nested = 'extra' if file_no==0 else 'activityExtra'
        manifest['files'].append({'path':filename,'sha256':hashlib.sha256(encoded.encode()).hexdigest(),
                    'chars':len(encoded),'records':len(rows),'source_complete':False if file_no==0 else None,
                    'nonempty_comments':sum(bool(r[nested].get(COMMENT)) for r in rows),
                    'score_sum_exact':str(sum(scores)),'rate_sum_exact':str(sum(rates)),
                    'score_min':str(min(scores)),'score_max':str(max(scores))})
    manifest['text_redactions'] = substitutions
    (output/'manifest.json').write_text(dumps(manifest),encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--files',type=Path,nargs=2,required=True)
    parser.add_argument('--output',type=Path,default=Path('datasets/production_deidentified'))
    args = parser.parse_args()
    result = release(args.files,args.output)
    print(dumps({'files':[{k:r[k] for k in ('path','records','chars')} for r in result['files']],
                 'text_redactions':result['text_redactions']}))


if __name__ == '__main__':
    main()
