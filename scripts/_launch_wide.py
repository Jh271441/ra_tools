import sys, urllib3, warnings
urllib3.disable_warnings(); warnings.filterwarnings("ignore")
sys.path.insert(0,"/home/didi/workspace/ra_tools"); sys.path.insert(0,"/home/didi/workspace/ra_tools/scripts")
import ezsim_run as E
client = E.EzSimClient("https://172.16.145.60:10900")
# 事件 ~1779882467；起点拉到 1779882410000（事件前 ~57s），end 477644
TRIP = {"tripId":"10498_20260527_194112","startTimestamp":1779882410000,"endTimestamp":1779882477644}
body = {"issue_id":"cn32422765",
        "scenario":{"tripSegment":TRIP,"name":"ra_wide_cn32422765_bin1665523",
                    "enabledModules":E._DEFAULT_MODULES,"warmupMs":5000,
                    "extraArgs":E._DEFAULT_EXTRA_ARGS,"topicInjections":[],"dpeMonitorNames":[]},
        "options":{"skip_map_update":True,"skip_model_update":False,"run_dpe":False,"binary_id":1665523}}
r=client._post("/agent/simulation/", body)
print("WIDE_id=", r.get("id"), r.get("status"))
