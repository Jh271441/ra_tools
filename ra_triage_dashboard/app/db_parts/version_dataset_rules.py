import json


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def current_version_prediction_sql(alias, run_alias=None):
    ordinary = (
        f"{run_alias}.kind <> 'version_live'"
        if run_alias
        else f"NOT EXISTS (SELECT 1 FROM model_runs v_run WHERE v_run.id={alias}.model_run_id AND v_run.kind='version_live')"
    )
    return f"({ordinary} OR EXISTS (SELECT 1 FROM version_dataset_items v_item JOIN version_datasets v_dataset ON v_dataset.id=v_item.dataset_id WHERE v_dataset.run_id={alias}.model_run_id AND v_item.issue_id={alias}.issue_id AND v_item.is_target=1))"
