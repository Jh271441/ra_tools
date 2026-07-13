"""EzSim client and CLI for Scenario DNN reproduction.

通过 EzSim dev-server 的 REST API 发起开环规划仿真。
支持直接传 Trail scenario_id，自动查询 tripSegment 数据。

Usage:
    python3 check_sim/ezsim.py <scenario_id>
    python3 check_sim/ezsim.py <scenario_id> --wait
    python3 check_sim/ezsim.py --list
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DEFAULT_SERVER = "https://172.16.145.60:10900"
_AGENT_PORT_FILE = Path.home() / ".voyager/ezsim/agent.port"

_DEFAULT_EXTRA_ARGS = (
    "--sim_disable_loading_assist_topic"
    " --sim_aligned_mode"
    " --planning_use_old_stuck_feature_extractor_length_only_in_sim"
    " --planning_enable_warmup_frame_state"
    " --planning_enable_warmup_frame_seed"
    " --planning_enable_sim_planner_init_state_recovery_mode"
    " --sim_smart_agent"
    " --sim_smart_agent_config_file SIM_dl_agent_second_order_model.conf"
    " --sim_override_smart_agent_config"
    " {ego_pose_divergence_threshold:1.5,ego_heading_divergence_threshold:8}"
)
_DEFAULT_MODULES = ["PLANNING", "PERFECT_POSE"]


def _resolve_build_dir_hash(client_session: requests.Session, base_url: str, build: str) -> str:
    """将 alias / 路径 / hash 解析为 build_dir_hash。

    - 8位十六进制字符串 → 直接当 hash
    - 字母别名（如 "Voyager2"）→ 查 /agent/env/build_dirs/alias/{alias}
    - 绝对路径 → 遍历 /agent/env/build_dirs 按 devel_location 匹配
    """
    # 已经是 hash 格式（8位hex）
    if len(build) == 8 and all(c in "0123456789abcdefABCDEF" for c in build):
        return build

    resp = client_session.get(f"{base_url}/agent/env/build_dirs", verify=False, timeout=10)
    resp.raise_for_status()
    build_dirs: dict = resp.json()

    # 按 alias 匹配
    for hash_val, info in build_dirs.items():
        if info.get("alias") == build:
            return hash_val

    # 按路径匹配（devel_location）
    if build.startswith("/"):
        for hash_val, info in build_dirs.items():
            if info.get("devel_location", "").rstrip("/") == build.rstrip("/"):
                return hash_val

    available = {v.get("alias") or k: k for k, v in build_dirs.items()}
    raise ValueError(
        f"找不到 build '{build}'，已注册的 build：\n" +
        "\n".join(f"  {alias} → {k}  ({build_dirs[k].get('devel_location','')})"
                  for alias, k in available.items())
    )


def _resolve_server(server: Optional[str]) -> str:
    if server:
        return server.rstrip("/")
    if _AGENT_PORT_FILE.exists():
        port = _AGENT_PORT_FILE.read_text().strip()
        return f"https://localhost:{port}"
    return _DEFAULT_SERVER


def get_trail_trip_segment(scenario_id: str) -> dict:
    """从 Trail 查 scenario 的 tripSegment（tripId、startTimestamp、endTimestamp）。"""
    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from ra_api.scenario_api import ScenarioInterface

    df = ScenarioInterface.query_scenario(query_scenario_ids=str(scenario_id), size=1)
    if df.empty:
        raise RuntimeError(f"Trail 中未找到 scenario_id={scenario_id}")
    row = df.iloc[0]
    trip_id = row["trip_id"]
    start_ts = int(row["start_timestamp"])
    end_ts = int(row["end_timestamp"])
    issue_uid = row.get("issue_uid", "")
    if not trip_id or not start_ts or not end_ts:
        raise RuntimeError(f"scenario {scenario_id} 缺少 tripSegment 数据：{row.to_dict()}")
    return {
        "trip_segment": {"tripId": trip_id, "startTimestamp": start_ts, "endTimestamp": end_ts},
        "issue_id": issue_uid,
        "name": row.get("name", str(scenario_id)),
    }


# Keep the legacy private name for scripts importing the old module directly.
_get_trail_trip_segment = get_trail_trip_segment


class EzSimClient:
    def __init__(self, server: Optional[str] = None):
        self.base_url = _resolve_server(server)
        self._s = requests.Session()
        self._s.verify = False

    def _post(self, path: str, body: dict) -> dict:
        resp = self._s.post(f"{self.base_url}{path}", json=body, timeout=30)
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _get(self, path: str):
        resp = self._s.get(f"{self.base_url}{path}", timeout=15)
        resp.raise_for_status()
        return resp.json()

    def list_builds(self) -> dict:
        """列出 server 上已注册的所有 build_dir。"""
        return self._get("/agent/env/build_dirs")

    def start_by_scenario_id(
        self,
        scenario_id: str,
        extra_args: Optional[str] = None,
        modules: Optional[list] = None,
        warmup_ms: int = 5000,
        skip_map_update: bool = False,
        skip_model_update: bool = False,
        binary_id: Optional[int] = None,
        build: Optional[str] = None,
    ) -> dict:
        """从 Trail 查 scenario 的 tripSegment，然后发起仿真。

        binary 优先级（与 ezsim server 逻辑一致）：
          1. binary_id  → 从 Orion 下载对应 CI binary（如 1665523）
          2. build      → 本地 build_dir，支持 alias/hash/绝对路径
          3. 两者都不传 → server 当前环境的 build
        """
        info = get_trail_trip_segment(scenario_id)

        options: dict = {
            "skip_map_update": skip_map_update,
            "skip_model_update": skip_model_update,
            "run_dpe": False,
        }
        if binary_id is not None:
            options["binary_id"] = binary_id

        body: dict = {
            "issue_id": info["issue_id"],
            "scenario": {
                "tripSegment": info["trip_segment"],
                "name": f"ra_repro_{scenario_id}",
                "enabledModules": modules or _DEFAULT_MODULES,
                "warmupMs": warmup_ms,
                "extraArgs": extra_args if extra_args is not None else _DEFAULT_EXTRA_ARGS,
                "topicInjections": [],
                "dpeMonitorNames": [],
            },
            "options": options,
        }
        if build is not None:
            body["build_dir_hash"] = _resolve_build_dir_hash(self._s, self.base_url, build)

        return self._post("/agent/simulation/", body)

    def get(self, sim_id: str) -> dict:
        return self._get(f"/agent/simulation/{sim_id}")

    def list(self) -> list:
        return self._get("/agent/simulation/")

    def wait(self, sim_id: str, poll: int = 10, timeout: int = 3600) -> dict:
        terminal = {"Success", "Failed to complete simulation", "Cancelled"}
        deadline = time.time() + timeout
        while time.time() < deadline:
            sim = self.get(sim_id)
            status = sim.get("status", "?")
            print(f"  [{time.strftime('%H:%M:%S')}] {status}", flush=True)
            if status in terminal:
                return sim
            time.sleep(poll)
        raise TimeoutError(f"仿真 {sim_id} 超时（{timeout}s）")


def main():
    parser = argparse.ArgumentParser(description="EzSim RA 复现仿真触发工具")
    parser.add_argument("scenario_id", nargs="?", help="Trail scenario_id")
    parser.add_argument("--server", default=None, help=f"EzSim server（默认 {_DEFAULT_SERVER}）")
    parser.add_argument("--wait", action="store_true", help="等待仿真完成")
    parser.add_argument("--poll", type=int, default=15, help="轮询间隔秒数（默认 15）")
    parser.add_argument("--extra-args", default=None, help="覆盖 extra_args")
    parser.add_argument("--modules", default=None, help="模块列表，如 PLANNING,PERFECT_POSE")
    parser.add_argument("--warmup", type=int, default=5000, help="warmup ms（默认 5000）")
    parser.add_argument(
        "--skip-map-update",
        action="store_true",
        help="跳过路测地图更新（RA 复现通常不要开启）",
    )
    parser.add_argument(
        "--skip-model-update",
        action="store_true",
        help="跳过模型包更新（指定旧 binary 时通常不要开启）",
    )
    parser.add_argument("--binary", type=int, default=None,
                        help="Orion binary_id，从 Trail 下载对应 CI binary（如 1665523）")
    parser.add_argument("--build", default=None,
                        help="本地 build_dir，支持 alias（Voyager2）/ hash（c7603ed0）/ 绝对路径")
    parser.add_argument("--list-builds", action="store_true", help="列出 server 上已注册的 build_dir")
    parser.add_argument("--list", action="store_true", dest="do_list", help="列出所有仿真")
    args = parser.parse_args()

    client = EzSimClient(server=args.server)
    print(f"EzSim server: {client.base_url}")

    if args.list_builds:
        builds = client.list_builds()
        print(f"已注册的 build_dir（共 {len(builds)} 个）：")
        for hash_val, info in builds.items():
            alias = info.get("alias") or "（无alias）"
            print(f"  {hash_val}  [{alias}]  {info.get('devel_location','?')}")
        return

    if args.do_list:
        sims = client.list()
        print(f"共 {len(sims)} 条仿真记录：")
        for s in sims:
            bd = s.get("durations", {}).get("binary_id", "local")
            print(f"  {s.get('id','?')[:8]}...  status={s.get('status')}  "
                  f"binary={bd}  issue={s.get('issue_id','?')}  "
                  f"name={s.get('scenario',{}).get('name','?')}")
        return

    if not args.scenario_id:
        parser.error("请提供 scenario_id，或 --list 查看已有仿真")

    modules = args.modules.split(",") if args.modules else None
    if args.binary and args.build:
        parser.error("--binary 和 --build 互斥，只能选一个")

    print(f"查询 Trail scenario {args.scenario_id} 的 tripSegment...")
    sim = client.start_by_scenario_id(
        scenario_id=args.scenario_id,
        extra_args=args.extra_args,
        modules=modules,
        warmup_ms=args.warmup,
        skip_map_update=args.skip_map_update,
        skip_model_update=args.skip_model_update,
        binary_id=args.binary,
        build=args.build,
    )

    sim_id = sim.get("id", "?")
    print(f"仿真已创建: id={sim_id}  status={sim.get('status')}")

    if args.wait:
        print(f"\n等待完成（每 {args.poll}s 轮询）...")
        final = client.wait(sim_id, poll=args.poll)
        status = final.get("status")
        print(f"\n完成: {status}")
        if final.get("failure"):
            print(f"失败原因: {final['failure']}")
        durations = final.get("durations", {})
        if durations:
            print("耗时:", json.dumps(durations, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
