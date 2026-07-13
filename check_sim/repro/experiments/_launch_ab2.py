import sys
import urllib3
import warnings
from pathlib import Path

urllib3.disable_warnings()
warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from check_sim.repro import ezsim as E

ISSUE = "cn32422765"
TRIP = {"tripId":"10498_20260527_194112","startTimestamp":1779882442644,"endTimestamp":1779882477644}
full = E._DEFAULT_EXTRA_ARGS
no_sa = full.split(" --sim_smart_agent")[0]
client = E.EzSimClient("https://172.16.145.60:10900")

def start(name, extra):
    body = {"issue_id": ISSUE,
            "scenario": {"tripSegment": TRIP, "name": name, "enabledModules": E._DEFAULT_MODULES,
                         "warmupMs": 5000, "extraArgs": extra, "topicInjections": [], "dpeMonitorNames": []},
            "options": {"skip_map_update": True, "skip_model_update": False, "run_dpe": False, "binary_id": 1665523}}
    r = client._post("/agent/simulation/", body)
    print(name, "->", r.get("id"), r.get("status")); return r.get("id")

a = start("ra_ab3_cn32422765_A_sa_bin1665523", full)
b = start("ra_ab3_cn32422765_B_nosa_bin1665523", no_sa)
print("A_id=", a); print("B_id=", b)
