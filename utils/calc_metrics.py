import pandas as pd
import pandas as pd
from typing import Union, List


def load_df(data: Union[str, pd.DataFrame, List[Union[str, pd.DataFrame]]]):
    """
    支持：
    - 单个 DataFrame
    - 单个 Excel 路径
    - 多个Excel路径 list[str]
    - 多个DataFrame list[df]
    - 混合类型的 list
    """

    # case 1: 不是 list，转成 list 统一处理
    if not isinstance(data, list):
        data = [data]

    dfs = []
    for item in data:
        if isinstance(item, str):
            dfs.append(pd.read_excel(item))
        elif isinstance(item, pd.DataFrame):
            dfs.append(item)
        else:
            raise TypeError(f"不支持的类型：{type(item)}")

    # 合并
    if len(dfs) == 1:
        return dfs[0]
    return pd.concat(dfs, ignore_index=True)




def compute_accuracy(df,
                     col_issue="issue_id",
                     col_ra_type="is_ra_auto_requested",  # Updated to reflect new column
                     col_ra_result="merged_ra_result"):  # Updated to reflect new column
    """
    准确率（仅计算，不做过滤）
    numerator: 自触发 & 结果 in 成功/失败/无需协助/限制使用
    denominator: 自触发 & 结果 not in out_of_scope/未接起
    """

    num = df.loc[
        (df[col_ra_type] == True) &  # Checking for True for self-triggered
        (df[col_ra_result].isin(["成功", "失败", "无需协助", "限制使用"]))
    ][col_issue].nunique()

    den = df.loc[
        (df[col_ra_type] == True) &  # Checking for True for self-triggered
        (~df[col_ra_result].isin(["out_of_scope", "未接起"]))
    ][col_issue].nunique()

    return num, den, num / den if den else 0


def compute_recall(df,
                   col_issue="issue_id",
                   col_ra_type="is_ra_auto_requested",  # Updated to reflect new column
                   col_ra_result="merged_ra_result"):  # Updated to reflect new column
    """
    召回率（仅计算，不做过滤）
    numerator: 自触发 & 结果 not in 误触发/out_of_scope/未接起
    denominator: 自触发 or 人工触发 & 结果 not in 误触发/out_of_scope/未接起
    """

    num = df.loc[
        (df[col_ra_type] == True) &  # Checking for True for self-triggered
        (~df[col_ra_result].isin(["误触发", "out_of_scope", "未接起"]))
    ][col_issue].nunique()

    den = df.loc[
        (df[col_ra_type].isin([True, False])) &  # True or False for self-triggered or manual triggered
        (~df[col_ra_result].isin(["误触发", "out_of_scope", "未接起"]))
    ][col_issue].nunique()

    return num, den, num / den if den else 0


data_dir = "/Users/didi/workspace/python/data"
# df = load_df("release1114_cloud_1125.xlsx")
df = load_df([
    # f"{data_dir}/release1114_cloud_1122-1123.xlsx",
    # f"{data_dir}/release1114_cloud_1124.xlsx",
    # f"{data_dir}/release1114_cloud_1125.xlsx",
    # f"{data_dir}/release1114_cloud_1126.xlsx",
    # f"{data_dir}/release1114_cloud_1127.xlsx",
    # f"{data_dir}/release1114_cloud_1128.xlsx",
    # f"{data_dir}/release1114_cloud_1129-1.xlsx",
    # f"{data_dir}/release1114_cloud_1129-2.xlsx",
    # f"{data_dir}/release1128-1206.xlsx",
    # f"{data_dir}/release1128-1205-1.xlsx",
    # f"{data_dir}/release1128-1205-2.xlsx",
    # f"{data_dir}/release1128-1204.xlsx",
    # f"{data_dir}/release1114_cloud_1130-2.xlsx",
])


acc = compute_accuracy(df)
rec = compute_recall(df)

print("整体准确率 =", acc)
print("整体召回率 =", rec)


df_scen = df[df["ra_trigger"] == "StuckModel"]

acc_scen = compute_accuracy(df_scen)
rec_scen = compute_recall(df_scen)

print("SCEN 准确率 =", acc_scen)
print("SCEN 召回率 =", rec_scen)