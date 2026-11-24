import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { CASE_PAGE_SIZES, DEFAULT_CASE_PAGE_SIZE, Pagination } from "./Pagination";

describe("Pagination", () => {
  it("uses standard CASE_PAGE_SIZES and disables boundary controls cleanly", () => {
    expect(CASE_PAGE_SIZES).toEqual([10, 20, 50, 100]);
    expect(DEFAULT_CASE_PAGE_SIZE).toBe(20);

    const onPageChange = vi.fn();
    const onPageSizeChange = vi.fn();
    render(
      <Pagination
        page={1}
        pageSize={20}
        total={55}
        lang="zh"
        onPageChange={onPageChange}
        onPageSizeChange={onPageSizeChange}
      />,
    );

    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).not.toBeDisabled();
    expect(screen.getByText("1 / 3 · 55")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onPageChange).toHaveBeenCalledWith(2);
  });

  it("validates Enter jump, clamps out-of-range page numbers, and clears selection", () => {
    const onPageChange = vi.fn();
    const onClearSelection = vi.fn();
    render(
      <Pagination
        page={1}
        pageSize={20}
        total={60}
        lang="en"
        onPageChange={onPageChange}
        onPageSizeChange={vi.fn()}
        onClearSelection={onClearSelection}
      />,
    );

    const input = screen.getByLabelText("Enter page number");
    fireEvent.change(input, { target: { value: "99" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClearSelection).toHaveBeenCalledTimes(1);
    expect(onPageChange).toHaveBeenCalledWith(3);

    fireEvent.change(input, { target: { value: "1.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    expect(onPageChange).toHaveBeenCalledTimes(1);
  });

  it("changes page size via shared UiSelect and disables controls on empty total", () => {
    const onPageSizeChange = vi.fn();
    const onClearSelection = vi.fn();
    const { rerender } = render(
      <Pagination
        page={2}
        pageSize={20}
        total={100}
        lang="en"
        onPageChange={vi.fn()}
        onPageSizeChange={onPageSizeChange}
        onClearSelection={onClearSelection}
      />,
    );

    const sizePicker = screen.getByRole("combobox", { name: "Items per page" });
    fireEvent.click(sizePicker);
    fireEvent.click(screen.getByRole("option", { name: "50" }));
    expect(onClearSelection).toHaveBeenCalledTimes(1);
    expect(onPageSizeChange).toHaveBeenCalledWith(50);

    rerender(
      <Pagination
        page={1}
        pageSize={20}
        total={0}
        lang="zh"
        onPageChange={vi.fn()}
        onPageSizeChange={onPageSizeChange}
      />,
    );
    expect(screen.getByText("0 条结果")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "跳转" })).toBeDisabled();
  });
});
