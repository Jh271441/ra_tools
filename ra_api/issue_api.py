import concurrent.futures
import hashlib
import json
import logging
import math
import os
import random
import time
import traceback
from enum import Enum

import pandas as pd
import requests

logger = logging.getLogger(__name__)


class IssueURL(Enum):
    query_by_issue_id_list = 'http://10.85.128.137/paladin/issue/pool/query_by_issue_id_list/'
    query = 'http://10.85.128.137/paladin/issue/pool/query/'
    query_issue_pool_url = 'http://voyager.intra.xiaojukeji.com/paladin/issue/pool/query/'


class TrailInterface:
    def __init__(self) -> None:
        self.orion_token = 'Bearer 8ba193ea-123f-44c4-a98a-3f2cb21aa1fa'
        self.token = 'd2570c086ea9c64219c81ab95dd1e31f'
        self.default_timeout = 60

    def _sign_for_json_string(self, json_data):
        """
        根据token和data生成签名字符串
        """
        text = "{data}&token={token}".format(data=json_data, token=self.token)
        return hashlib.md5(text.encode('utf8')).hexdigest()

    @staticmethod
    def _sign(data):
        """Sign data."""
        data['appid'] = 6
        data['time'] = int(time.time())

        payload = data.copy()
        payload['token'] = '17475d2cbc65f4772125542ef93e90ed'

        values = ["%s=%s" % (k, payload[k]) for k in sorted(payload)]
        text = '&'.join(values)
        md5_hash = hashlib.md5(text.encode('utf8')).hexdigest()
        data['sign'] = md5_hash
        return data

    def _get_page_content(self, url, query_json, page):
        """
        用于获取单页的内容
        """
        time.sleep(random.uniform(0, 2))
        query_json['page'] = page
        response = self.send_request(url, query_json)
        res = response['data'].get('res', [])
        if res:
            return res
        data = response['data'].get('data', [])
        if data:
            return data

    def get_content_by_token(self, url, data, return_type='df'):
        first_page = self.send_request(url=url, json_data=data, timeout=60)
        if not first_page:
            if return_type == 'df':
                return pd.DataFrame()
            return None
        first_page_data = first_page['data']
        total = first_page_data.get('total', None)
        count = first_page_data.get('count', None)
        size = data.get('size', 500)
        if total:
            total_count = total
        else:
            total_count = count
        if total_count == 0:
            if return_type == 'df':
                return pd.DataFrame()
            return None
        # 得到总页数
        page_count = math.ceil(total_count / size)
        result = []
        # 多线程并发查询
        with concurrent.futures.ThreadPoolExecutor(os.cpu_count() // 2) as executor:
            future_to_page = {executor.submit(self._get_page_content, url, data, page): page
                              for page in
                              range(1, page_count + 1)}
            for future in concurrent.futures.as_completed(future_to_page):
                page = future_to_page[future]
                try:
                    json_data = future.result()
                    result.extend(json_data)
                except Exception as exc:
                    print(f'page {page} generated an exception: {exc}')
        if len(result) > 0:
            if return_type == 'df':
                return pd.DataFrame(result)
            return result

    def update_content_by_token(self, url, data):
        sign = self._sign_for_json_string(json.dumps(data))
        headers = {
            'content-type': 'application/json',
            'sign': sign,
            'appid': "21",
            'time': str(int(time.time()))
        }
        failed_cnt = 3
        response = None
        while failed_cnt:
            response = requests.post(
                url=url, json=data, timeout=90, headers=headers)
            try:
                if response.json()["msg"] == 'success':
                    return response.json()
                failed_cnt -= 1
            except Exception as e:
                logger.exception(traceback.print_exc())
                failed_cnt -= 1
                time.sleep(1)
            time.sleep(1)
        return response.json()

    def query_by_issue_id_list(self, issue_id_list, select_field_list):
        """
       查询问题信息
       :param issue_id_list: 包含多个 issue_id 的列表
       :param select_field_list： 要查询的字段
       :return: requests.Response or None: 请求响应对象或者失败返回 None
       """
        # 构建请求体
        if len(issue_id_list) <= 200:
            request_data = {
                "source_id": 1,
                "issue_id_list": issue_id_list,
                "select_field_list": select_field_list
            }
            return self.send_request(IssueURL.query_by_issue_id_list.value, request_data).get('data', {})
        else:
            count = math.ceil(len(issue_id_list) / 200)
            res_all = {}
            for i in range(count):
                request_data = {
                    "source_id": 1,
                    "issue_id_list": issue_id_list[i * 200:(i + 1) * 200],
                    "select_field_list": select_field_list
                }
                res = self.send_request(IssueURL.query_by_issue_id_list.value, request_data).get('data', {})
                res_all.update(res)
            # 发送请求
            return res_all

    def query_issue_poll(self, view_id, query_attrs, size=None):
        """
        查询 issue 数据，自动补全缺失字段
        :param view_id: 视图ID
        :param query_attrs: 查询条件
        :param size: 每页数据数量
        :return: pd.DataFrame
        """
        page_size = size or 200
        query_json = {
            "view_id": view_id,
            "user_location": "cn",
            "page": 1,
            "query_attrs": query_attrs,
            "size": page_size
        }

        # 请求第一页,获得问题总数，方便得到分页数
        try:
            response = self.send_request(IssueURL.query_issue_pool_url.value, query_json)
        except Exception as e:
            print(f"Request or JSON parsing failed: {e}")
            return pd.DataFrame()

        total_count = response.get('data', {}).get('total', 0)
        if total_count == 0:
            return pd.DataFrame()

        page_count = math.ceil(total_count / page_size)

        results = []
        # 多线程抓取所有页
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                executor.submit(self._get_page_content, IssueURL.query_issue_pool_url.value, query_json, page): page
                for page in range(1, page_count + 1)
            }
            for future in concurrent.futures.as_completed(futures):
                page = futures[future]
                try:
                    data = future.result()
                    if isinstance(data, list):
                        results.extend(data)
                except Exception as exc:
                    print(f"Page {page} error: {exc}")

        if not results:
            return pd.DataFrame()

        # 收集所有字段
        all_keys = set()
        for item in results:
            all_keys.update(item.keys())
        required_fields = {'issue_topic', 'poi'}
        all_keys.update(required_fields)

        # 补全缺失字段
        for item in results:
            for key in all_keys:
                item.setdefault(key, None)

        df = pd.DataFrame(results, columns=sorted(all_keys))

        if 'ares_bag_animation' in df.columns:
            df['new_url'] = df['ares_bag_animation'].str.extract(r'/(ares_animation_videos/[^:]+)', expand=False)
            df['bag_animation_url'] = 'https://voyager.intra.xiaojukeji.com/static/ares-animation/?ares_url=' + df[
                'new_url'].fillna('')
        else:
            df['new_url'] = None
            df['bag_animation_url'] = None

        return df

    def send_request(self, url, json_data, timeout=None):
        """
        发送请求，并在发送请求时进行异常处理和状态码检查
        :param url: 请求的URL
        :param json_data: 要发送的JSON数据
        :param timeout : 请求超时时间，秒为单位
        :return: requests.Response or None: 请求响应对象或者失败返回None
        """
        if timeout is None:
            timeout = self.default_timeout
        try:
            sign = self._sign_for_json_string(json.dumps(json_data))
            headers = {
                'content-type': 'application/json',
                'sign': sign,
                'appid': '21',
                'time': str(int(time.time())),
            }
            response = requests.post(url=url, json=json_data, timeout=timeout, headers=headers)

            if response.status_code == 200:
                response_data = response.json()
                code = response_data.get('code')
                msg = response_data.get('msg')
                if msg != 'success':
                    logger.error("Request failed - Code: %s,\n Msg: %s\n Request: %s", code, msg, json_data)
                return response_data
            else:
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)
            return None


if __name__ == '__main__':
    query_attrs = [
        {
            "attr_id": "issue_id",
            "val": [
                "cn25454325"
            ],
            "operator": "like"
        },
        {
            "attr_id": "issue_time",
            "val": {
                "min": 1764086400000,
                "max": 1764172799999
            },
            "operator": "range"
        }
    ]
    res = TrailInterface().query_issue_poll(view_id=2410, query_attrs=query_attrs)
    print(res)

