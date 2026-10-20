"""Runnable offline example. Passing a client alone never enables network calls."""
from edu_context import Policy, compress_planned, profile_data
from edu_context.planning import conservative_plan


def main():
    data = {"records": [
        {"person": "S1", "points": 81.5, "grade": 2, "note": "只有复核后才能确认。"},
        {"person": "S2", "points": 79, "grade": 1, "note": "任务已提交。"},
    ]}
    policy = Policy(
        definitions={"/records": {
            "/person": {"role": "entity"},
            "/points": {"role": "metric", "unit": "points", "scale": "0-100"},
            "/grade": {"role": "status"},
            "/note": {"role": "text"},
        }},
        protected_entities={"/records": [{"field": "/person", "value": "S1"}]},
        required_fields={"/records": ["/note"]},
        max_tokens=8000,
    )
    plan = conservative_plan(profile_data(data), policy)
    plan["tables"][0]["aggregates"] = [
        {"field": "/points", "op": "stats", "unit": "points", "scale": "0-100", "group_by": []}
    ]
    result = compress_planned("统计成绩，保留评语", data, policy=policy, plan=plan, source_complete=True)
    assert result["status"] == "ready" and result["within_budget"]
    print(result["context"])

    # Model planning is an explicit alternate call:
    # client = JSONModelClient(api_key=caller_key, base_url=caller_url,
    #                          model=caller_model, max_calls=10, timeout=120)
    # result = compress_planned(task, data, policy=policy, model_call=client,
    #                           allow_model=True, token_counter=actual_counter)
    # Handle needs_clarification / unsupported / fallback / over_budget before
    # forwarding result["context"] to the answering model.


if __name__ == "__main__":
    main()
