from datetime import datetime
import random
import time
from concurrent.futures import ThreadPoolExecutor

from ra_api.issue_api import TrailInterface
from ra_api.scenario_api import TripSegment, ScenarioInterface
from ra_api.utils import get_first_event_time


def save_dataframe_to_csv(df, filename="ra_issues_data.csv"):
    """保存DataFrame为CSV文件"""
    try:
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        print(f"✅ 数据已保存为: {filename}")
        print(f"📊 数据形状: {df.shape} (行数: {df.shape[0]}, 列数: {df.shape[1]})")
    except Exception as e:
        print(f"❌ 保存CSV失败: {e}")


def get_ra_issue():
    #issue查询link中导出的查询参数
    # attrs =[
    #     {
    #     "attr_id": "issue_time",
    #     "operator": "range",
    #     "val": {
    #       "min": 1763740800996,
    #       "max": 1764086399996
    #     }
    #     },
    #     {
    #     "attr_id": "ra_type",
    #     "operator": "in",
    #     "val": [
    #       3,
    #       2
    #     ]
    #     },
    #     {
    #     "attr_id": "ra_result",
    #     "operator": "in",
    #     "val": [
    #       5
    #     ]
    #     },
    #     {
    #     "attr_id": "ra_config_tag",
    #     "operator": "like",
    #     "val": [
    #         "cloud:scen_dnn_2025Q4"
    #     ]
    #     }
    # ]
    attrs = [
      {
        "attr_id": "version",
        "operator": "like",
        "val": [
          "gen4"
        ]
      },
      {
        "attr_id": "ra_type",
        "operator": "in",
        "val": [
          2,
          3
        ]
      },
      {
        "attr_id": "ra_trigger",
        "operator": "in",
        "val": [
          "StuckModel",
          "FP_STARTUP"
        ]
      }
    ]
    # 注意view_id
    res = TrailInterface().query_issue_poll(view_id=2410, query_attrs=attrs)
    print(len(res))

    # count = 0
    # for index, row in res.iterrows():
    #     print(f"正在处理第{count}个issue")
    #     count += 1
    #     item = row.to_dict()
    #     create_dnn_test_scenario(item)

    items_list = [row.to_dict() for _, row in res.iterrows()]

    with ThreadPoolExecutor(max_workers=30) as executor:
        executor.map(create_dnn_test_scenario, items_list)

def create_dnn_test_scenario(item):
    time.sleep(random.uniform(1, 2))
    issue_id = item['issue_id']
    issue_time = item['issue_time']
    trip_id = item['trip_id']
    ra_event = item['ra_event']
    ra_trigger = item['ra_trigger']
    #获取 RA start时间
    start_timestamp = get_first_event_time(ra_event, 'start')
    if not start_timestamp:
        return
    end_timestamp = start_timestamp + 5 * 1000  # 结束时间为原始触发时间
    start_timestamp = start_timestamp - 20 * 1000  # 开始时间为原始触发时间
    date_time = datetime.utcfromtimestamp(issue_time / 1000)

    module = ['PREDICTION', 'PLANNING', 'ROUTING', 'MODEL_POSE', 'CONTROL']
    pre_name = "ra_auto_trigger_gen4_issue_test"
    trip_segment = TripSegment(trip_id, start_timestamp, end_timestamp)
    # correct_trigger
    tag_label = "mis_trigger"
    labels = [f'#{issue_id[2:]}', 'scenario_from_issue', "data_sim", pre_name,
              date_time.strftime('%Y_%m'), date_time.strftime('%Y_%m_%d'), tag_label, ra_trigger,
              'created_by_20251218']

    scenario_name = f"{pre_name}_{tag_label}_{issue_id}"
    scenario_interface = ScenarioInterface()
    scenario_flag, scenario_info = scenario_interface.add_scenario(name=scenario_name,
                                                                   trip_segment=trip_segment,
                                                                   extra_attrs=None,
                                                                   module=module,
                                                                   metrics_json=None,
                                                                   scenario_tags=None,
                                                                   scenario_label=labels,
                                                                   warmup_s=3,
                                                                   username='jasperchen')
    if scenario_flag:
        pass
        # trail_interface.update_issue_with_changes(
        #     [{'issue_id': issue_id, 'ra_scenario': str(scenario_info)}])
    else:
        print(scenario_info)



if __name__ == '__main__':
    get_ra_issue()