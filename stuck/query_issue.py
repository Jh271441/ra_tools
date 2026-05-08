from ra_api.scenario_api import ScenarioInterface


scenario_interface = ScenarioInterface()

# scenario_query_result = scenario_interface.query_scenario(query_scenario_tags=[2684])
# scenario_query_result.to_csv(
#     "data/sim_plan_scenario_not_triggered.csv",
#     index=False,
#     encoding="utf-8"
# )
# scenario_query_result = scenario_interface.query_scenario(query_scenario_tags=[5145,5147])
# scenario_query_result.to_csv(
#     "data/sim_plan_scenario_mis_triggering.csv",
#     index=False,
#     encoding="utf-8"
# )
# scenario_query_result = scenario_interface.query_scenario(query_scenario_tags=[2685])
# scenario_query_result.to_csv(
#     "data/sim_plan_scenario_correct_trigger.csv",
#     index=False,
#     encoding="utf-8"
# )

# scenario_query_result = scenario_interface.query_scenario(query_labels='lxh_ra_stuck_normal_stop_20260201')
# scenario_query_result.to_csv(
#     "data/sim_plan_scenario_stuck_normal_stop.csv",
#     index=False,
#     encoding="utf-8"
# )

scenario_query_result = scenario_interface.query_scenario(query_scenario_ids="21867337,21924216")
scenario_query_result.to_csv(
    "data/sim_plan_scenario_stuck_normal_stop.csv",
    index=False,
    encoding="utf-8"
)

print(scenario_query_result)