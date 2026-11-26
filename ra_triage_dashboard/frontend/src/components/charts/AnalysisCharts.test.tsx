import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  ANALYSIS_PIE_BASE_DARK,
  ANALYSIS_PIE_BASE_LIGHT,
  AnalysisConfusionTable,
  AnalysisDonutGroup,
  AnalysisGtCard,
  AnalysisStatusBar,
  analysisDonutSlicePath,
  analysisPieArcs,
  analysisPiePalette,
  analysisPiePercent,
  labelBadgeClass,
} from "./AnalysisCharts";

describe("AnalysisCharts shared SVG donut and linked-hover engine", () => {
  it("computes rotating light/dark palettes, stable arcs, and full-circle donut path", () => {
    expect(analysisPiePalette("evidence", "dark")[0]).toBe(ANALYSIS_PIE_BASE_DARK[0]);
    expect(analysisPiePalette("scene", "light")[0]).toBe(ANALYSIS_PIE_BASE_LIGHT[5]);

    const { arcs, sum } = analysisPieArcs([
      { key: "a", label: "A", count: 3 },
      { key: "zero", label: "Z", count: 0 },
      { key: "b", label: "B", count: 1 },
    ]);
    expect(sum).toBe(4);
    expect(arcs.map((a) => [a.item.key, a.index])).toEqual([
      ["a", 0],
      ["b", 2],
    ]);
    expect(analysisPiePercent(3, 4)).toBe(75);
    const fullPath = analysisDonutSlicePath(60, 60, 55, 24, -Math.PI / 2, Math.PI * 1.5);
    expect(fullPath).toContain("A 55 55 0 1 1");
    expect(fullPath).toContain("Z");
  });

  it("links hover between SVG donut slice and legend row, and triggers GT rules modal", () => {
    const onShow = vi.fn();
    const onHide = vi.fn();
    const onOpenRules = vi.fn();

    const { container } = render(
      <div>
        <AnalysisDonutGroup
          group={{
            key: "env",
            label: "场景环境",
            annotated_count: 10,
            items: [
              { key: "rain", label: "雨天", count: 7 },
              { key: "night", label: "夜间", count: 3 },
            ],
          }}
          palette={analysisPiePalette("scene", "dark")}
          lang="zh"
          onShowTooltip={onShow}
          onHideTooltip={onHide}
        />
        <AnalysisGtCard
          counts={{ all: 10, ready: 4, blocked: 1 }}
          prefix="labelSummary"
          lang="zh"
          onOpenRules={onOpenRules}
          onShowTooltip={onShow}
          onHideTooltip={onHide}
        />
        <AnalysisStatusBar
          statuses={[
            { key: "resolved", cssKey: "completed", label: "已形成结论", count: 6, description: "done" },
            { key: "pending", cssKey: "pending", label: "待形成结论", count: 4, description: "wait" },
          ]}
          emptyText="暂无"
        />
        <AnalysisConfusionTable
          cornerHeader="GT ↓ / 标注 →"
          columnLabels={["误触发", "正确触发"]}
          rows={[
            {
              gtLabel: "误触发",
              cells: [
                { colLabel: "误触发", count: 5, tone: "match", title: "5" },
                { colLabel: "正确触发", count: 1, tone: "mismatch", title: "1" },
              ],
              total: 6,
            },
          ]}
          totalLabel="合计"
          columnTotals={[5, 1]}
          grandTotal={6}
        />
      </div>,
    );

    const rainSlice = container.querySelector('.analysis-pie-slice[data-pie-key="rain"]')!;
    fireEvent.pointerEnter(rainSlice);
    expect(onShow).toHaveBeenCalled();
    expect(
      container.querySelector('.analysis-pie-legend-row[data-pie-key="rain"]')?.classList.contains("is-hover"),
    ).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "GT 更新统计口径" }));
    expect(onOpenRules).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("40%").length).toBeGreaterThanOrEqual(2);
    expect(labelBadgeClass("误触发")).toBe("label-badge label-误触发");
    expect(labelBadgeClass("NONE")).toBe("label-badge label-empty");
  });
});
