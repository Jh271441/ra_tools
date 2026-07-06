import pandas as pd
import json
import ast

# 1. Load metadata
df_meta = pd.read_csv('/volume/home/workspace/ra_auto_triage/vlm/scripts/output/issue_feature_analysis_0206_0508full/issue_meta.csv', low_memory=False)
df_meta = df_meta.set_index('issue_id')

# 2. Load 0508 dataset
df_0508 = pd.read_excel('/volume/home/workspace/ra_auto_triage/data/release_20260508_1071_eval.xlsx')
# Filter out 无需协助
df_0508 = df_0508[df_0508['期望输出'] != '无需协助']

# 3. Load 0206 dataset
rows_0206 = []
with open('/volume/home/workspace/stuck_auto_triage_vlm/data/raw/labeled_issues.jsonl') as f:
    for line in f:
        if line.strip():
            rows_0206.append(json.loads(line))
df_0206 = pd.DataFrame(rows_0206)
# Filter out 无需协助
df_0206 = df_0206[df_0206['gt_label'] != '无需协助']

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

# Correct intended labels based on visual verification and the slide image
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

def run_rules(df, label_col, limit_val):
    counts = {k: [0, 0] for k in INTENDED_LABELS.keys()}
    counts['Undecided'] = [0, 0]

    order_list = ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9']

    for idx, row in df.iterrows():
        issue_id = row['issue_id']
        gt = row[label_col]

        meta = df_meta.loc[issue_id] if issue_id in df_meta.index else None
        if meta is None:
            counts['Undecided'][0] += 1
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
            counts[matched_rule][0] += 1
            intended = INTENDED_LABELS[matched_rule]
            if gt == intended:
                counts[matched_rule][1] += 1
        else:
            counts['Undecided'][0] += 1

    return counts

# Run for 4.0s and 4.4s limits
for limit in [4.0, 4.4]:
    print(f"\n=================== Accuracy and Coverage stats (R7 limit < {limit}s) ===================")
    c0508 = run_rules(df_0508, '期望输出', limit)
    c0206 = run_rules(df_0206, 'gt_label', limit)

    total0508 = len(df_0508)
    total0206 = len(df_0206)

    print(f"| Rule Name | Intended Label | 0508 Matches | 0508 Accuracy | 0206 Matches | 0206 Accuracy |")
    print(f"|---|---|---|---|---|---|")

    for k in INTENDED_LABELS.keys():
        m_0508, c_0508 = c0508[k]
        acc_0508 = (c_0508 / m_0508 * 100.0) if m_0508 > 0 else 0.0
        acc_str_0508 = f"{acc_0508:.1f}%" if m_0508 > 0 else "-"

        m_0206, c_0206 = c0206[k]
        acc_0206 = (c_0206 / m_0206 * 100.0) if m_0206 > 0 else 0.0
        acc_str_0206 = f"{acc_0206:.1f}%" if m_0206 > 0 else "-"

        print(f"| {k} | {INTENDED_LABELS[k]} | {m_0508} ({m_0508/total0508*100.0:.1f}%) | {acc_str_0508} | {m_0206} ({m_0206/total0206*100.0:.1f}%) | {acc_str_0206} |")

    # Print Undecided summary
    m_0508 = c0508['Undecided'][0]
    m_0206 = c0206['Undecided'][0]
    print(f"| Undecided | - | {m_0508} ({m_0508/total0508*100.0:.1f}%) | - | {m_0206} ({m_0206/total0206*100.0:.1f}%) | - |")

    # Overall Accuracy of rules
    total_m_0508 = sum(c0508[k][0] for k in INTENDED_LABELS.keys())
    total_c_0508 = sum(c0508[k][1] for k in INTENDED_LABELS.keys())
    overall_acc_0508 = total_c_0508 / total_m_0508 * 100.0 if total_m_0508 > 0 else 0.0

    total_m_0206 = sum(c0206[k][0] for k in INTENDED_LABELS.keys())
    total_c_0206 = sum(c0206[k][1] for k in INTENDED_LABELS.keys())
    overall_acc_0206 = total_c_0206 / total_m_0206 * 100.0 if total_m_0206 > 0 else 0.0

    print(f"\nOverall Rule Match Coverage: 0508 = {total_m_0508/total0508*100.0:.1f}%, 0206 = {total_m_0206/total0206*100.0:.1f}%")
    print(f"Overall Rule Accuracy: 0508 = {overall_acc_0508:.1f}%, 0206 = {overall_acc_0206:.1f}%")
