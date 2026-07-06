import pandas as pd
import json
import ast

df_meta = pd.read_csv('/volume/home/workspace/ra_auto_triage/vlm/scripts/output/issue_feature_analysis_0206_0508full/issue_meta.csv', low_memory=False)
df_meta = df_meta.set_index('issue_id')

df_0508 = pd.read_excel('/volume/home/workspace/ra_auto_triage/data/release_20260508_1071_eval.xlsx')
df_0508 = df_0508[df_0508['期望输出'] != '无需协助']

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
    t_exit = None
    t_exit_wp = None
    for e in events:
        if not isinstance(e, dict):
            continue
        if e.get('event') == 'swag':
            t_swag = e.get('timestamp')
        elif e.get('event') == 'waypoint' and e.get('value') == 'kFollowPath':
            t_follow = e.get('timestamp')
        elif e.get('event') == 'waypoint' and e.get('value') == 'kExitWayPoint':
            t_exit_wp = e.get('timestamp')
        elif e.get('event') == 'exit':
            t_exit = e.get('timestamp')
    return t_swag, t_follow, t_exit_wp, t_exit

# Targets
target = {
    'R1': 8,
    'R2': 83,
    'R3_no_swag': 13,
    'R3_swag': 3,
    'R4': 228,
    'R5': 203,
    'R6': 6,
    'R7': 149,
    'R8': 71,
    'R9': 151
}

# Priority orders to test:
# Since R1, R2, R3, R4, R5, R6 matches exactly, we keep their order relative to each other:
# R1 -> R2 -> R3 -> R4 -> R5 -> R6
# And we need to find where R7, R8 fit.
# In the target image, R7 and R8 are listed after R6.
# So let's test orders where R7 and R8 are placed at different positions.
# Let's test all possible positions of R7 and R8 relative to R4, R5, R6:
# 1. R1 -> R2 -> R3 -> R4 -> R5 -> R6 -> R7 -> R8 -> R9
# 2. R1 -> R2 -> R3 -> R7 -> R8 -> R4 -> R5 -> R6 -> R9

orders = [
    ('Numeric', ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9']),
    ('Task770', ['R1', 'R2', 'R3', 'R7', 'R8', 'R4', 'R5', 'R6', 'R9'])
]

found_any = False
for order_name, order_list in orders:
    for limit_type in ['swag_to_follow', 'follow_to_exit_wp', 'follow_to_exit']:
        # Let's sweep limit from 1 to 25 seconds, step 0.1
        for limit_val in [x * 0.1 for x in range(10, 250)]:
            counts = {k: 0 for k in target.keys()}

            for idx, row in df_0508.iterrows():
                issue_id = row['issue_id']
                meta = df_meta.loc[issue_id]

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

                t_swag, t_follow, t_exit_wp, t_exit = get_durations(events)

                dur = None
                if limit_type == 'swag_to_follow' and t_swag and t_follow:
                    dur = (t_follow - t_swag) / 1000.0
                elif limit_type == 'follow_to_exit_wp' and t_follow and t_exit_wp:
                    dur = (t_exit_wp - t_follow) / 1000.0
                elif limit_type == 'follow_to_exit' and t_follow and t_exit:
                    dur = (t_exit - t_follow) / 1000.0

                matched = False
                for r in order_list:
                    if r == 'R1':
                        if ra_trigger == 'TidalFlowLane' or ra_type == 'TidalFlowLane':
                            counts['R1'] += 1
                            matched = True
                            break
                    elif r == 'R2':
                        if ra_trigger == 'FN_FORCING_RECALL' or ra_type == 'FN_FORCING_RECALL':
                            counts['R2'] += 1
                            matched = True
                            break
                    elif r == 'R3':
                        if (ra_trigger == 'FN_SELECTION' or ra_type == 'FN_SELECTION'):
                            if has_swag and has_follow:
                                counts['R3_swag'] += 1
                            else:
                                counts['R3_no_swag'] += 1
                            matched = True
                            break
                    elif r == 'R4':
                        if ra_result == 5:
                            counts['R4'] += 1
                            matched = True
                            break
                    elif r == 'R5':
                        if ra_result == 4:
                            counts['R5'] += 1
                            matched = True
                            break
                    elif r == 'R6':
                        if ra_result == 0:
                            counts['R6'] += 1
                            matched = True
                            break
                    elif r == 'R7':
                        if has_swag and has_follow and dur is not None and dur < limit_val:
                            counts['R7'] += 1
                            matched = True
                            break
                    elif r == 'R8':
                        if not has_swag and has_follow:
                            counts['R8'] += 1
                            matched = True
                            break
                    elif r == 'R9':
                        if ra_result == 1 and (has_follow or has_swag or has_manual):
                            counts['R9'] += 1
                            matched = True
                            break

            # Print if very close or matching
            diffs = sum(abs(counts[k] - target[k]) for k in target.keys())
            if diffs <= 5:
                print(f"Close Match! Diff: {diffs}, Order: {order_name}, Limit Type: {limit_type}, Limit Val: {limit_val:.1f}s")
                print("Counts:", counts)

            matched_all = True
            for k in target.keys():
                if counts[k] != target[k]:
                    matched_all = False
                    break
            if matched_all:
                print(f"FOUND EXACT MATCH! Order: {order_name}, Limit Type: {limit_type}, Limit Val: {limit_val:.2f}s")
                print(counts)
                found_any = True
                break
        if found_any:
            break
    if found_any:
        break

if not found_any:
    print("Done sweeping, no exact match found.")
