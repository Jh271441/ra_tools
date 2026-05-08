import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd

# 1. Prepare the data extracted from the image
data = {
    'K': [2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20],
    'Latency_ms': [0.21, 0.19, 0.24, 0.28, 0.42, 0.45, 0.50, 0.61, 0.65, 0.83, 1.10]
}
df = pd.DataFrame(data)

# 2. Set the plotting style
sns.set_theme(style="whitegrid")

# 3. Create the plot
plt.figure(figsize=(10, 6), dpi=120)

# Draw the line plot with square markers
ax = sns.lineplot(
    x='K',
    y='Latency_ms',
    data=df,
    marker='s',
    markersize=8,
    linewidth=2.5,
    color='#d62728' # Red color to indicate latency/cost
)

# 4. Add data labels above each point
for i in range(len(df)):
    plt.text(
        df['K'].iloc[i],
        df['Latency_ms'].iloc[i] + 0.03, # Small offset for readability
        f"{df['Latency_ms'].iloc[i]:.2f}",
        ha='center',
        va='bottom',
        fontsize=11,
        fontweight='bold',
        color='#333333'
    )

# 5. Set axis labels and title
plt.xlabel('Top-K (Value of K)', fontsize=13, fontweight='bold')
plt.ylabel('Average Additional Latency (ms) (Lower is Better)', fontsize=13, fontweight='bold')
plt.title('Additional Latency Trend by Top-K', fontsize=16, pad=20, fontweight='bold')

plt.xticks(df['K'])
plt.ylim(0, 1.25)

# Highlight the K=7 point (the peak F2P improvement from the previous chart)
# plt.scatter(7, 0.45, color='blue', s=150, zorder=5, alpha=0.5)
# plt.annotate('Optimal point from\nprevious chart', xy=(7, 0.45), xytext=(8, 0.25),
#              arrowprops=dict(facecolor='blue', shrink=0.05, width=1.5, headwidth=6),
#              color='blue', fontsize=11, fontweight='bold')

# 6. Save and show the plot
plt.tight_layout()
plt.savefig('latency_trend_english.png')
plt.show()