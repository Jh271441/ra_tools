import json
import logging
import re
from enum import Enum
from typing import Optional, List, Dict, Any

import pandas as pd

from .issue_api import TrailInterface

logger = logging.getLogger(__name__)
trail_api = TrailInterface()


class ScenarioURL(Enum):
    add = 'http://100.69.238.11:8000/voyager/trail/simulation/scenario/add/'
    update = 'http://100.69.238.11:8000/voyager/trail/simulation/scenario/update/'
    review = 'http://100.69.238.11:8000/voyager/trail/simulation/scenario/review/'
    create = 'http://100.69.238.11:8000/voyager/trail/simulation/scenario/batch_add_by_disengage_info_ids/'
    query = 'http://100.69.238.11:8000/voyager/trail/simulation/scenario/query/'
    delete = 'http://100.69.238.11:8000/voyager/trail/simulation/scenario/delete/'


class TripSegment:
    def __init__(self, trip_id, start_timestamp, end_timestamp):
        self.tripId = trip_id
        self.startTimestamp = start_timestamp
        self.endTimestamp = end_timestamp

    def to_dict(self):
        return {
            "tripId": self.tripId,
            "startTimestamp": self.startTimestamp,
            "endTimestamp": self.endTimestamp
        }


class ScenarioProtoModel:
    def __init__(self, name: str, trip_segment: TripSegment, enabled_modules: List[str],
                 metrics: List[str], warmup_ms: int,
                 extra_attrs: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.trip_segment = trip_segment if (trip_segment is not None) else None
        self.enabled_modules = enabled_modules
        self.metrics = metrics
        self.warmup_ms = int(float(warmup_ms) * 1000)
        self.extra_attrs = extra_attrs if extra_attrs else {}

    def to_dict(self) -> Dict[str, Any]:
        proto_dict = {"name": self.name}
        if self.trip_segment:
            proto_dict["tripSegment"] = self.trip_segment.to_dict()
        proto_dict.update({
            "enabledModules": self.enabled_modules,
            "metrics": self.metrics,
            "warmupMs": self.warmup_ms,
            **self.extra_attrs
        })
        return proto_dict


class ScenarioInterface:

    @staticmethod
    def add_scenario(name, trip_segment, metrics_json, module, scenario_label, scenario_tags, username,
                     warmup_s=3, description='', extra_attrs=None, virtual_scene_content=None, scenario_proto=None):
        """
        创建scenario
        :param name:
        :param trip_segment:
        :param metrics_json:
        :param module:
        :param scenario_label:
        :param scenario_tags:
        :param username:
        :param warmup_s:
        :param description:
        :param extra_attrs:
        :param virtual_scene_content:
        :param scenario_proto:
        :return:
        """
        if not scenario_proto:
            scenario_proto = ScenarioProtoModel(name=name, trip_segment=trip_segment, metrics=metrics_json,
                                                enabled_modules=module, warmup_ms=warmup_s,
                                                extra_attrs=extra_attrs)
            # 创建ScenarioInfo字典，只包含非空字段
            scenario_info = {
                "name": name,
                "scenario": json.dumps(scenario_proto.to_dict()),
                "updater": username
            }
        else:
            # 创建ScenarioInfo字典，只包含非空字段
            scenario_proto['name'] = name
            scenario_info = {
                "name": name,
                "scenario": json.dumps(scenario_proto),
                "updater": username,
            }
        cleaned_labels = []
        for item in scenario_label:
            if item:
                cleaned_labels.append(str(item.strip()))
        scenario_label = ",".join(cleaned_labels)  # 拼接

        if scenario_label:
            scenario_info["labels"] = scenario_label
        if scenario_tags:
            scenario_info["scenario_tags"] = json.dumps(scenario_tags)
        if description:
            scenario_info["description"] = description
        if virtual_scene_content:
            scenario_info["virtual_scene_content"] = json.dumps(virtual_scene_content)
        res = trail_api.send_request(ScenarioURL.add.value, scenario_info)
        if res and res.get('msg', None) == 'success':
            return True, res['data']['id']
        else:
            if res:
                return False, res.get('msg', '接口超时！')
            else:
                return False, '接口超时！'

    @staticmethod
    def delete_scenario(scenario_id, updater):
        json_data = {
            "user_location": "cn",
            "id": scenario_id,
            "updater": updater
        }
        res = trail_api.send_request(ScenarioURL.delete.value, json_data)
        if res['msg'] == 'success':
            return True
        else:
            return res['msg']

    @staticmethod
    def update_scenario(scenario_id, scenario_name=None, scenario_labels=None, scenario_proto=None,
                        scenario_tags=None, updater=None, keep_review_status=None, description='',
                        virtual_scene_content=None):
        json_data = {k: v for k, v in {
            "id": scenario_id,
            "name": scenario_name,
            "labels": scenario_labels,
            "scenario": json.dumps(scenario_proto) if scenario_proto is not None else None,
            "scenario_tags": scenario_tags,
            "updater": updater,
            "description": description,
            "keep_review_status": keep_review_status,
            "user_location": "cn",
            "virtual_scene_content": virtual_scene_content
        }.items() if v is not None}
        if scenario_labels == '':
            json_data["labels"] = scenario_labels
        return trail_api.send_request(ScenarioURL.update.value, json_data)

    @staticmethod
    def query_scenario(query_labels=None, query_scenario_ids='', query_scenario_tags=None, query_scenario_set=None,
                       query_scenario_tag_or=False, review_status=None, size=500):
        query_dict = {
            "labels": query_labels,
            "id": ",".join(re.findall(r'\d+', query_scenario_ids)),
            "scenario_set": query_scenario_set,
            'size': size
        }
        # 移除值为 None 或空字符串的键值对
        query_dict = {key: value for key, value in query_dict.items() if value}
        # 处理 query_scenario_tags
        if query_scenario_tags:
            scenario_tags = [[foo] for foo in query_scenario_tags]
            query_dict['scenario_tags'] = str(scenario_tags)
            query_dict['scenario_tag_or'] = query_scenario_tag_or
        if review_status:
            string_status = [str(num) for num in review_status]
            query_dict['review_status'] = ",".join(string_status)
        df_scenario_info = trail_api.get_content_by_token(ScenarioURL.query.value, query_dict)
        if not df_scenario_info.empty:
            return df_scenario_info
        else:
            return pd.DataFrame()

