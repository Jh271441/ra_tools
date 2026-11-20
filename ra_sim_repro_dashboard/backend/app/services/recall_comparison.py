"""Explain recall changes on paired, covered Issues without changing metrics."""
from app.services import metric_profiles as profiles


def transition(row, config):
    if row.get('result_status') != 'reused' or type(row.get('sim_triggered')) is not bool:
        return None
    source = profiles.membership(config, row['ra_type'], row['auto_label'])
    if not (source['precision_denominator'] or source['recall_denominator']):
        return None
    simulated = profiles.membership(config, 2 if row['sim_triggered'] else 3, row['auto_label'])
    delta = simulated['recall_numerator'] - source['recall_numerator']
    return 'recall_gain' if delta > 0 else 'recall_loss' if delta < 0 else None


def compare(rows, config):
    """Coverage proves availability, never behavioral reproduction validation."""
    source_n = source_d = sim_n = sim_d = gains = losses = covered = 0
    denominator_changed = 0
    for row in rows:
        if row.get('result_status') != 'reused' or type(row.get('sim_triggered')) is not bool:
            continue
        road = profiles.membership(config, row['ra_type'], row['auto_label'])
        sim = profiles.membership(config, 2 if row['sim_triggered'] else 3, row['auto_label'])
        # Match the existing evaluation population, including custom profiles.
        if not (road['precision_denominator'] or road['recall_denominator']):
            continue
        covered += 1
        source_n += road['recall_numerator']
        source_d += road['recall_denominator']
        sim_n += sim['recall_numerator']
        sim_d += sim['recall_denominator']
        delta = sim['recall_numerator'] - road['recall_numerator']
        gains += int(delta > 0)
        losses += int(delta < 0)
        denominator_changed += int(road['recall_denominator'] != sim['recall_denominator'])
    assert sim_n - source_n == gains - losses
    road_rate = source_n / source_d if source_d else None
    sim_rate = sim_n / sim_d if sim_d else None
    return {
        'basis': 'covered_issue_trigger_vs_scenario_window',
        'covered': covered, 'road_numerator': source_n, 'road_denominator': source_d,
        'sim_numerator': sim_n, 'sim_denominator': sim_d,
        'gains': gains, 'losses': losses, 'net': gains - losses,
        'denominator_changed': denominator_changed,
        'road_recall': road_rate, 'sim_recall': sim_rate,
        'gap': sim_rate - road_rate if sim_rate is not None and road_rate is not None else None,
        'behavior_validated': False,
    }
