import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { UiSelect } from "./UiSelect";

const OPTIONS = [
  { value: "all", label: "全部角色" },
  { value: "writer", label: "可写" },
  { value: "disabled_opt", label: "不可用", disabled: true },
  { value: "admin", label: "管理员" },
];

describe("UiSelect", () => {
  it("renders selected option and opens/selects via click without native select", () => {
    const onChange = vi.fn();
    const { container } = render(
      <UiSelect value="writer" options={OPTIONS} ariaLabel="Role" onChange={onChange} />,
    );
    expect(container.querySelector("select")).toBeNull();
    const trigger = screen.getByRole("combobox", { name: "Role" });
    expect(trigger).toHaveTextContent("可写");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const listbox = screen.getByRole("listbox", { name: "Role" });
    expect(listbox).toHaveClass("ui-select-panel", "is-positioned");

    fireEvent.click(screen.getByRole("option", { name: "管理员" }));
    expect(onChange).toHaveBeenCalledWith("admin");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("supports keyboard navigation skipping disabled options and closes on Escape", () => {
    const onChange = vi.fn();
    render(<UiSelect value="writer" options={OPTIONS} ariaLabel="Role" onChange={onChange} />);
    const trigger = screen.getByRole("combobox", { name: "Role" });

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("admin");

    fireEvent.keyDown(trigger, { key: "ArrowUp" });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("dismisses when clicking outside and preserves selection across label/language updates", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <div>
        <UiSelect value="admin" options={OPTIONS} ariaLabel="Role" onChange={onChange} />
        <button type="button">Outside</button>
      </div>,
    );
    const trigger = screen.getByRole("combobox", { name: "Role" });
    fireEvent.click(trigger);
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByText("Outside"));
    expect(screen.queryByRole("listbox")).toBeNull();

    rerender(
      <div>
        <UiSelect
          value="admin"
          options={[
            { value: "all", label: "All roles" },
            { value: "writer", label: "Writer" },
            { value: "admin", label: "Admin" },
          ]}
          ariaLabel="Role"
          onChange={onChange}
        />
        <button type="button">Outside</button>
      </div>,
    );
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveTextContent("Admin");
  });
});
