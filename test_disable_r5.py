import pandas as pd
import json
import ast

df_meta = pd.read_csv('/volume/home/workspace/ra_auto_triage/vlm/scripts/output/issue_feature_analysis_0206_0508full/issue_meta.csv', low_memory=False)
df_meta = df_meta.set_index('issue_id')

df_0508 = pd.read_excel('/volume/home/workspace/ra_auto_triage/data/release_20260508_1071_eval.xlsx')
df_0508 = df_0508[df_0508['期望输出'].isin(['正确触发', '误触发', '无需协助'])]

rows_0206 = []
with open('/volume/home/workspace/stuck_auto_triage_vlm/data/raw/labeled_issues.jsonl') as f:
    for line in f:
        if line.strip():
            rows_0206.append(json.loads(line))
df_0206 = pd.DataFrame(rows_0206)

def parse_events(ev_str):
    if not ev_str or pd.isna(ev_str):
        return []
    try:
        return ast.literal_eval(ev_str)
    except Exception:
        try:
            return json.loads(ev_str)
        except Exception:
            return []

def get_durations(events):
    t_swag = None
    t_follow = None
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get('event') == 'swag':
            t_swag = e.get('timestamp')
        elif e.get('event') == 'waypoint' and e.get('value') == 'kFollowPath':
            t_follow = e.get('timestamp')
    return t_swag, t_follow

INTENDED_LABELS = {
    'R1: TidalFlowLane': '误触发',
    'R2: FN_FORCING_RECALL': '误触发',
    'R3: FN_SELECTION(无swag+Follow)': '误触发',
    'R3: FN_SELECTION(swag+FollowPath)': '正确触发',
    'R4: ra_result=5(ops关闭)': '误触发',
    'R5: ra_result=4(超时)': '误触发',
    'R6: ra_result=0(初始)': '正确触发',
    'R7: AE-swag+FollowPath<4s': '正确触发',
    'R8: AE-noSwag+FollowPath': '正确触发',
    'R9: ra_result=1+强操作': '正确触发'
}

def simulate(df, label_col, disable_r5, limit_val=4.4):
    counts = {
        '误触发_by_rules': 0,
        '正确触发_by_rules': 0,
        'Undecided_to_VLM': 0,
    }

    no_assist_dest = {
        'classified_as_误触发': 0,
        'classified_as_正确触发': 0,
        'flowed_to_VLM': 0
    }

    order_list = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9']
    if disable_r5:
        order_list.remove('R5')

    for idx, row in df.iterrows():
        issue_id = row['issue_id']
        gt = row[label_col]

        meta = df_meta.loc[issue_id] if issue_id in df_meta.index else None
        if meta is None:
            counts['Undecided_to_VLM'] += 1
            if gt == '无需协助':
                no_assist_dest['flowed_to_VLM'] += 1
            continue

        ra_trigger = str(meta.get('ra_trigger', ''))
        ra_type = str(meta.get('ra_type', ''))
        ra_result = meta.get('ra_result')
        try:
            ra_result = int(float(ra_result)) if not pd.isna(ra_result) else -1
        except:
            ra_result = -1

        ra_event_str = str(meta.get('ra_event', ''))
        events = parse_events(ra_event_str)

        has_swag = 'swag' in ra_event_str.lower()
        has_follow = 'kFollowPath' in ra_event_str
        has_manual = any(cmd in ra_event_str for cmd in ['kDirectControl', 'kForward', 'kBackward', 'kLeft', 'kRight', '方向键', '倒车'])

        t_swag, t_follow = get_durations(events)
        dur = None
        if t_swag and t_follow:
            dur = (t_follow - t_swag) / 1000.0

        matched = False
        matched_rule = None

        for r in order_list:
            if r == 'R1':
                if ra_trigger == 'TidalFlowLane' or ra_type == 'TidalFlowLane':
                    matched_rule = 'R1: TidalFlowLane'
                    matched = True
                    break
            elif r == 'R2':
                if ra_trigger == 'FN_FORCING_RECALL' or ra_type == 'FN_FORCING_RECALL':
                    matched_rule = 'R2: FN_FORCING_RECALL'
                    matched = True
                    break
            elif r == 'R3':
                if (ra_trigger == 'FN_SELECTION' or ra_type == 'FN_SELECTION'):
                    if has_swag and has_follow:
                        matched_rule = 'R3: FN_SELECTION(swag+FollowPath)'
                    else:
                        matched_rule = 'R3: FN_SELECTION(无swag+Follow)'
                    matched = True
                    break
            elif r == 'R4':
                if ra_result == 5:
                    matched_rule = 'R4: ra_result=5(ops关闭)'
                    matched = True
                    break
            elif r == 'R5':
                if ra_result == 4:
                    matched_rule = 'R5: ra_result=4(超时)'
                    matched = True
                    break
            elif r == 'R6':
                if ra_result == 0:
                    matched_rule = 'R6: ra_result=0(初始)'
                    matched = True
                    break
            elif r == 'R7':
                if has_swag and has_follow and dur is not None and dur < limit_val:
                    matched_rule = 'R7: AE-swag+FollowPath<4s'
                    matched = True
                    break
            elif r == 'R8':
                if not has_swag and has_follow:
                    matched_rule = 'R8: AE-noSwag+FollowPath'
                    matched = True
                    break
            elif r == 'R9':
                if ra_result == 1 and (has_follow or has_swag or has_manual):
                    matched_rule = 'R9: ra_result=1+强操作'
                    matched = True
                    break

        if matched:
            pred = INTENDED_LABELS[matched_rule]
            if pred == '误触发':
                counts['误触发_by_rules'] += 1
                if gt == '无需协助':
                    no_assist_dest['classified_as_误触发'] += 1
            else:
                counts['正确触发_by_rules'] += 1
                if gt == '无需协助':
                    no_assist_dest['classified_as_正确触发'] += 1
        else:
            counts['Undecided_to_VLM'] += 1
            if gt == '无需协助':
                no_assist_dest['flowed_to_VLM'] += 1

    return counts, no_assist_dest

for df, name, col in [(df_0508, 'Release 0508', '期望输出'), (df_0206, 'Release 0206', 'gt_label')]:
    print(f"\n--- {name} (Total: {len(df)}) ---")
    c_with, na_with = simulate(df, col, disable_r5=False)
    c_without, na_without = simulate(df, col, disable_r5=True)

    print("WITH R5 (Default):")
    print(f"  Decided by Rules: {c_with['误触发_by_rules'] + c_with['正确触发_by_rules']} ({(c_with['误触发_by_rules'] + c_with['正确触发_by_rules'])/len(df)*100.0:.1f}%)")
    print(f"  Sent to VLM (Undecided): {c_with['Undecided_to_VLM']} ({c_with['Undecided_to_VLM']/len(df)*100.0:.1f}%)")
    print("  NoAssist Destinations:")
    print(f"    -> Classified as Misfire: {na_with['classified_as_误触发']}")
    print(f"    -> Classified as Correct: {na_with['classified_as_正确触发']}")
    print(f"    -> Flowed to VLM: {na_with['flowed_to_VLM']}")

    print("WITHOUT R5 (Disabled):")
    print(f"  Decided by Rules: {c_without['误触发_by_rules'] + c_without['正确触发_by_rules']} ({(c_without['误触发_by_rules'] + c_without['正确触发_by_rules'])/len(df)*100.0:.1f}%)")
    print(f"  Sent to VLM (Undecided): {c_without['Undecided_to_VLM']} ({c_without['Undecided_to_VLM']/len(df)*100.0:.1f}%)")
    print("  NoAssist Destinations:")
    print(f"    -> Classified as Misfire: {na_without['classified_as_误触发']}")
    print(f"    -> Classified as Correct: {na_without['classified_as_正确触发']}")
    print(f"    -> Flowed to VLM: {na_without['flowed_to_VLM']}")
