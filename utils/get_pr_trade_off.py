import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# Data definitions
models = [
    "Q4 FP16",
    "Exp 1.1 (Rm Sig, Rec-Ep27)",
    "Exp 1.2 (Rm Sig, Acc-Ep23)",
    "Exp 2 (a75-Ep12)",
    "Exp 3 (a75+randn4-Ep6)",
    "Exp 4 (a75+randn4+lr5-Ep09)",
    "Exp 5 (a95+frz)",
    "Exp 6 (a60+lr5e-5+frz)",
    "Exp 7.1 (a60+frz+Rec-Ep26)",
    "Exp 7.2 (a60+frz+Acc-Ep53)",
    "Exp 8 (a95+frz+topk1-Ep30)",
    "Exp 9 (a95+frz+randn4-Ep23)",
    "Exp 10 (a95+frz+lvl1+randn4-Ep18)"
]

# Raw counts
raw_counts = [
    {"mis": [729, 771], "not": [369, 927], "cor": [551, 1297]},  # Q4 FP16
    {"mis": [630, 872], "not": [325, 973], "cor": [558, 1292]},  # Exp 1.1
    {"mis": [818, 684], "not": [445, 853], "cor": [640, 1210]},  # Exp 1.2
    {"mis": [737, 763], "not": [379, 917], "cor": [585, 1263]},  # Exp 2
    {"mis": [859, 641], "not": [411, 885], "cor": [595, 1253]},  # Exp 3
    {"mis": [439, 1061], "not": [234, 1062], "cor": [526, 1322]},  # Exp 4
    {"mis": [332, 1168], "not": [202, 1094], "cor": [644, 1204]},  # Exp 5
    {"mis": [901, 599], "not": [640, 656], "cor": [960, 888]},  # Exp 6
    {"mis": [674, 826], "not": [376, 920], "cor": [808, 1040]},  # Exp 7.1
    {"mis": [877, 623], "not": [474, 822], "cor": [857, 991]},  # Exp 7.2
    {"mis": [222, 1278], "not": [148, 1148], "cor": [604, 1244]},  # Exp 8
    {"mis": [402, 1098], "not": [234, 1062], "cor": [679, 1169]},  # Exp 9
    {"mis": [495, 1005], "not": [247, 1049], "cor": [657, 1191]}  # Exp 10
]

# Totals
total_mis = 1502  # Negatives
total_not = 1298
total_cor = 1851
total_pos = total_not + total_cor  # 3149 (Positives)
total_all = total_mis + total_pos  # 4651

data = []
for i, counts in enumerate(raw_counts):
    tn_mis = counts["mis"][0]  # TN
    tp_not = counts["not"][1]  # TP part 1
    tp_cor = counts["cor"][1]  # TP part 2

    # Specificity (TN Rate) -> Now Y-axis
    specificity = tn_mis / total_mis

    # Sensitivity (Weighted Recall / TP Rate) -> Now X-axis
    sensitivity = (tp_not + tp_cor) / total_pos

    # Overall Accuracy
    overall_acc = (tn_mis + tp_not + tp_cor) / total_all

    data.append({
        "Model": models[i],
        "Specificity (TN Rate)": specificity,
        "Weighted Recall (TP Rate)": sensitivity,
        "Overall Accuracy": overall_acc
    })

df = pd.DataFrame(data)

# --- Plotting ---
plt.figure(figsize=(14, 9))

# 1. Define X and Y data (Swapped: X=Recall, Y=Specificity)
x_data = df['Weighted Recall (TP Rate)']
y_data = df['Specificity (TN Rate)']

# 2. Draw Iso-Accuracy Contours (The "Lines")
# Formula derivation:
# Accuracy = (Recall * Pos_Total + Specificity * Neg_Total) / All_Total
# Specificity * Neg_Total = Accuracy * All_Total - Recall * Pos_Total
# Specificity = (Accuracy * All_Total / Neg_Total) - Recall * (Pos_Total / Neg_Total)
# y = C - m * x

x_range = np.linspace(x_data.min() - 0.05, x_data.max() + 0.05, 100)
acc_levels = np.arange(0.60, 0.80, 0.01)  # Lines every 1% accuracy

for acc in acc_levels:
    # Calculate Y (Specificity) for this Accuracy level
    y_line = (acc * total_all - x_range * total_pos) / total_mis

    # Only draw lines that are roughly within the plot area to reduce clutter
    if np.mean(y_line) > 0 and np.mean(y_line) < 1.0:
        # Determine style: thick line for every 5%, thin for others
        if round(acc * 100) % 5 == 0:
            linewidth = 1.0
            alpha = 0.4
            linestyle = '--'
            color = 'gray'
            # Add text label for 5% increments
            mid_x = x_range[-20]  # Position text near the right side
            mid_y = (acc * total_all - mid_x * total_pos) / total_mis
            if 0.1 < mid_y < 0.9:  # Check if text is visible
                plt.text(mid_x, mid_y, f'Acc={acc:.2f}', color='gray', fontsize=8, rotation=-20, va='bottom')
        else:
            linewidth = 0.5
            alpha = 0.15
            linestyle = ':'
            color = 'gray'

        plt.plot(x_range, y_line, linestyle=linestyle, linewidth=linewidth, color=color, alpha=alpha, zorder=0)

# 3. Scatter Plot
plt.scatter(x_data, y_data, color='teal', s=120, zorder=2, edgecolors='white', linewidth=1.5)

# 4. Annotations
for i, txt in enumerate(df['Model']):
    short_name = txt
    if "Exp" in txt:
        parts = txt.split(' ')
        short_name = parts[0] + " " + parts[1]

    # Offset adjustments to avoid overlapping (simple manual tweak logic)
    xytext = (5, 5)
    if "Exp 1.1" in short_name: xytext = (5, -10)
    if "Exp 8" in short_name: xytext = (-30, 5)

    plt.annotate(short_name, (x_data.iloc[i], y_data.iloc[i]),
                 xytext=xytext, textcoords='offset points', fontsize=9, fontweight='bold', alpha=0.9)

# 5. Styling
plt.title('Performance Trade-off with Iso-Accuracy Contours', fontsize=16)
plt.xlabel('Weighted Recall (Positive Datasets TP Rate)\n(Better at Detecting Positives ->)', fontsize=12)
plt.ylabel('Specificity (Mis Triggering Dataset TN Rate)\n(Better at Rejecting Negatives ->)', fontsize=12)

# Set limits to make it look nice
plt.xlim(x_data.min() - 0.02, x_data.max() + 0.05)
plt.ylim(y_data.min() - 0.02, y_data.max() + 0.05)

plt.grid(True, linestyle='-', alpha=0.2)
plt.tight_layout()
plt.savefig('tradeoff_swapped_contours.png')
plt.show()

# Display sorted table
print(df[['Model', 'Overall Accuracy', 'Specificity (TN Rate)', 'Weighted Recall (TP Rate)']].sort_values(
    by='Overall Accuracy', ascending=False).to_markdown())

# import matplotlib.pyplot as plt
# import pandas as pd
# import numpy as np
#
# # Data Extraction
# models = [
#     "Q4 FP16",
#     "Exp 1.1 (Rm Sig, Rec-Ep27)",
#     "Exp 1.2 (Rm Sig, Acc-Ep23)",
#     "Exp 2 (a75-Ep12)",
#     "Exp 3 (a75+randn4-Ep6)",
#     "Exp 4 (a75+randn4+lr5-Ep09)",
#     "Exp 5 (a95+frz)",
#     "Exp 6 (a60+lr5e-5+frz)",
#     "Exp 7.1 (a60+frz+Rec-Ep26)",
#     "Exp 7.2 (a60+frz+Acc-Ep53)",
#     "Exp 8 (a95+frz+topk1-Ep30)",
#     "Exp 9 (a95+frz+randn4-Ep23)",
#     "Exp 10 (a95+frz+lvl1+randn4-Ep18)"
# ]
#
# # Precision and Recall values from the "Val-0824-1012" dataset (6731 scenarios)
# # Based on the user's first provided text
# data = {
#     "Model": models,
#     "Precision": [0.60426, 0.58927, 0.6231, 0.53453, 0.63872, 0.57733, 0.54337, 0.66543, 0.60279, 0.65188, 0.43081,
#                   0.47406, 0.51429],
#     "Recall": [0.79499, 0.79351, 0.72419, 0.87906, 0.76401, 0.80383, 0.84071, 0.53097, 0.76549, 0.71534, 0.89086,
#                0.87611, 0.82301],
#     "F1": [0.68662, 0.6763, 0.66985, 0.66481, 0.69577, 0.67201, 0.6601, 0.59065, 0.67446, 0.68214, 0.58077, 0.61523,
#            0.63301]
# }
#
# df = pd.DataFrame(data)
#
# # Create the plot
# plt.figure(figsize=(12, 10))
#
# # Plot points
# plt.scatter(df['Recall'], df['Precision'], color='purple', s=100, label='Models')
#
# # Annotate points
# for i, txt in enumerate(df['Model']):
#     # Simplify names for the plot to avoid clutter
#     short_name = txt
#     if "Exp" in txt:
#         short_name = txt.split(' ')[0] + " " + txt.split(' ')[1]
#
#     plt.annotate(short_name, (df['Recall'][i], df['Precision'][i]),
#                  xytext=(5, 5), textcoords='offset points', fontsize=9)
#
# # Add F1 score contour lines (Iso-F1 curves)
# f_scores = np.linspace(0.4, 0.8, num=9)
# x = np.linspace(0.01, 1, 100)
# for f in f_scores:
#     y = (f * x) / (2 * x - f)
#     # Filter valid y values (precision must be between 0 and 1)
#     mask = (y >= 0) & (y <= 1)
#     plt.plot(x[mask], y[mask], color='gray', alpha=0.2, linestyle='--')
#     # Label the contour
#     if mask.any():
#         plt.text(x[mask][-1], y[mask][-1], f'F1={f:.2f}', color='gray', fontsize=8, alpha=0.6)
#
# plt.title('Precision-Recall Scatter Plot (Val Set: 6731 Scenarios)', fontsize=16)
# plt.xlabel('Recall (Higher is better ->)', fontsize=12)
# plt.ylabel('Precision (Higher is better ->)', fontsize=12)
# plt.xlim(0.4, 1.0)  # Adjust limits to focus on the data cluster if needed, or keep 0-1
# plt.ylim(0.4, 0.8)  # Adjust based on data range
# plt.grid(True, linestyle='--', alpha=0.6)
#
# # Save the plot
# plt.savefig('pr_scatter_val_6731.png')
#
# # Print the data for verification
# print(df[['Model', 'Precision', 'Recall', 'F1']].sort_values(by='F1', ascending=False).to_markdown())