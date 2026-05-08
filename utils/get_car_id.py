import pandas as pd

# 假设你的 DataFrame 名为 df
df = pd.read_excel("/Users/didi/workspace/python/data/issue_from_1122-1125.xlsx")
import pandas as pd
# 假设 DataFrame 名为 df
df = df.rename(columns={"create_date(天)": "create_date"})
df2 = df[df['ra_trigger'] == 'SCEN_DNN_2025Q4']

# 按天处理
for day, group in df.groupby("create_date"):
    print(f"Day {day}")

    # 唯一 car id 列表
    # unique_cars = sorted(group["car_id"].unique())
    # print(f"unique car ids: {unique_cars}")

    # 每个 car 的出现次数（转 dict）
    car_counts = group["car_id"].value_counts().to_dict()
    print(f"car counts: {car_counts}")
    print()  # 空行

print("+++++++++++++++")

# 每天的 car_id 集合
day_to_cars = {
    day: set(group["car_id"].unique())
    for day, group in df.groupby("create_date")
}

# 求所有天集合的交集
common_ids = set.intersection(*day_to_cars.values())
all_ids = set.union(*day_to_cars.values())

print(f"共同出现的 car_id（所有天都出现）: {len(common_ids)}")
print([int(x) for x in sorted(common_ids)])

print(f"所有的 car_id: {len(all_ids)}")
print([int(x) for x in sorted(all_ids)])

print("==================")
# 每天的 car_id 集合
day_to_cars_2 = {
    day: set(group["car_id"].unique())
    for day, group in df2.groupby("create_date")
}
common_ids_2 = set.intersection(*day_to_cars_2.values())
all_ids_2 = set.union(*day_to_cars_2.values())

print(f"共同出现的 car_id（所有天都出现）: {len(common_ids_2)}")
print([int(x) for x in sorted(common_ids_2)])

print(f"所有的 car_id: {len(all_ids_2)}")
print([int(x) for x in sorted(all_ids_2)])

print("==================")
print(len((all_ids - all_ids_2)))
print([int(x) for x in (all_ids - all_ids_2)])
