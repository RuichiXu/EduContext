"""Synthetic teaching tasks. Gold is calculated from source, never sent to models."""
from statistics import mean


def dataset():
    rows = []
    common = "School policy: assessment records are internal teaching data. " * 7
    for student in range(120):
        for exam in range(6):
            score = 60 + (student * 7 + exam * 3) % 41
            if student == 119:
                score = [88, 89, 90, 87, 25, 91][exam]
            rows.append({
                "student_id": f"S{student:03d}", "student_name": f"学生{student:03d}",
                "class_name": "甲班" if student < 60 else "乙班",
                "course_name": "数学", "exam_date": f"2026-0{exam + 1}-15",
                "score": score, "status": "异常" if score < 30 else "正常",
                "important": student == 119 and exam == 4, "policy": common,
            })
    return {"scope": "2026年上半年数学考试。每行是一次学生考试记录，允许同一学生重复出现。",
            "score_unit": "分", "rows": rows}


def cases(data):
    rows = data["rows"]
    a = [r for r in rows if r["class_name"] == "甲班"]
    b = [r for r in rows if r["class_name"] == "乙班"]
    target = [r for r in rows if r["student_id"] == "S119"]
    return [
        {"id": "overall", "task": "生成整体学情报告，统计考试记录总数、成绩总和、按考试记录计算的平均分、最低分、最高分、异常状态记录数，并说明统计单位。",
         "schema": {"record_count": "整数", "score_sum": "数字", "score_mean": "数字", "min_score": "数字", "max_score": "数字", "abnormal_count": "整数", "unit": "填写考试记录"},
         "gold": {"record_count": len(rows), "score_sum": sum(r["score"] for r in rows), "score_mean": mean(r["score"] for r in rows), "min_score": min(r["score"] for r in rows), "max_score": max(r["score"] for r in rows), "abnormal_count": sum(r["status"] == "异常" for r in rows), "unit": "考试记录"},
         "numeric": ["record_count", "score_sum", "score_mean", "min_score", "max_score", "abnormal_count"]},
        {"id": "student", "task": "分析学号 S119 的成绩异常，保留该学生六次考试按日期排序的成绩、日期及状态，给出异常日期和异常成绩。只回答已标记的异常。",
         "schema": {"student_id": "字符串", "scores": "按日期升序的数字数组", "dates": "日期数组", "statuses": "对应状态数组", "abnormal_date": "字符串", "abnormal_score": "数字"},
         "gold": {"student_id": "S119", "scores": [r["score"] for r in target], "dates": [r["exam_date"] for r in target], "statuses": [r["status"] for r in target], "abnormal_date": target[4]["exam_date"], "abnormal_score": 25},
         "numeric": ["scores", "abnormal_score"]},
        {"id": "compare", "task": "对比甲班和乙班的数学考试情况。分别列出各班考试记录数、成绩总和、平均分，并指出平均分更高的班级。平均分按考试记录计算。",
         "schema": {"a_count": "甲班考试记录数（整数）", "b_count": "乙班考试记录数（整数）", "a_sum": "甲班成绩总和（数字）", "b_sum": "乙班成绩总和（数字）", "a_mean": "甲班平均分（数字）", "b_mean": "乙班平均分（数字）", "higher_class": "班级名称", "unit": "填写考试记录"},
         "gold": {"a_count": len(a), "b_count": len(b), "a_sum": sum(r["score"] for r in a), "b_sum": sum(r["score"] for r in b), "a_mean": mean(r["score"] for r in a), "b_mean": mean(r["score"] for r in b), "higher_class": "甲班" if mean(r["score"] for r in a) > mean(r["score"] for r in b) else "乙班", "unit": "考试记录"},
         "numeric": ["a_count", "b_count", "a_sum", "b_sum", "a_mean", "b_mean"]},
    ]
