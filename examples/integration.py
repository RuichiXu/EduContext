"""Run from project root: python -m examples.integration"""
from edu_context import Config, compress


def build_context(user_request, tool_results, exact_counter=None):
    result = compress(
        user_request,
        tool_results,  # {"grades_api": json_payload, "attendance_api": json_payload}
        config=Config(
            field_roles={"studentId": "entity", "points": "metric"},
            bounds={"points": (0, 100)},
        ),
        token_counter=exact_counter,
    )
    if result.triggered and not result.within_budget:
        # The caller decides whether to narrow the API query, split tasks, or use
        # a larger context. Never silently truncate result.context again.
        return {"needs_more_capacity": True, "result": result}
    return {"needs_more_capacity": False, "result": result}


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    result = build_context("生成整体学情报告", {"grades_api": [
        {"studentId": "001", "points": 91, "status": "正常"},
        {"studentId": "002", "points": 87, "status": "正常"},
    ]})["result"]
    print(result.context)
    print(result.stats)
