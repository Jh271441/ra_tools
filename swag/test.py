import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

# 1. Prepare the data (extracted from the image)
data = {
    'K': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20],
    'F2P_Improvement': [0, 7, 16, 21, 30, 30, 31, 29, 30, 30, 29, 29]
}
df = pd.DataFrame(data)

# 2. Set the plotting style
sns.set_theme(style="whitegrid") # Use seaborn's grid theme

# 3. Create the plot
plt.figure(figsize=(10, 6), dpi=120)

# Draw the line plot with circle markers
ax = sns.lineplot(
    x='K',
    y='F2P_Improvement',
    data=df,
    marker='o',
    markersize=8,
    linewidth=2.5,
    color='#1f77b4'
)

# 4. Add data labels above each point
for i in range(len(df)):
    plt.text(
        df['K'].iloc[i],
        df['F2P_Improvement'].iloc[i] + 0.8, # Offset y slightly to prevent overlap
        str(df['F2P_Improvement'].iloc[i]),
        ha='center',
        va='bottom',
        fontsize=11,
        fontweight='bold',
        color='#333333'
    )

# 5. Set axis labels and title
plt.xlabel('Top-K (Value of K)', fontsize=13, fontweight='bold')
plt.ylabel('Additional F2P Cases vs. Top-1 (Higher is Better)', fontsize=13, fontweight='bold')
plt.title('F2P Improvement Trend by Top-K', fontsize=16, pad=20, fontweight='bold')

# Set x-axis ticks to ensure only our specific K values are shown
plt.xticks(df['K'])

# Set y-axis limits to leave space at the top for labels
plt.ylim(0, 35)
plt.xlim(1, max(df['K']))

# Highlight the peak point (K=7, F2P=31)
# plt.scatter(7, 31, color='red', s=150, zorder=5, alpha=0.6)
# plt.annotate('Peak', xy=(7, 31), xytext=(8, 33),
#              arrowprops=dict(facecolor='red', shrink=0.05, width=1.5, headwidth=6),
#              color='red', fontsize=12, fontweight='bold')

# 6. Save and show the plot
plt.tight_layout()
plt.savefig('f2p_improvement_english.png')
plt.show()