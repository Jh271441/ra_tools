import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MultiSelect } from "./MultiSelect";

describe("MultiSelect", () => {
  const options = [
    { value: "20261113", label: "1113" },
    { value: "20261106", label: "1106" },
    { value: "20261030", label: "1030" },
  ];

  it("renders summary, toggles values, supports Select all / Clear / Only and Escape close", () => {
    const onChange = vi.fn();
    render(
      <MultiSelect
        values={["20261113"]}
        options={options}
        onChange={onChange}
        ariaLabel="Versions"
        lang="en"
      />,
    );

    const trigger = screen.getByRole("button", { name: "Versions" });
    expect(trigger).toHaveTextContent("1113");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("1106"));
    expect(onChange).toHaveBeenCalledWith(["20261113", "20261106"]);

    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(onChange).toHaveBeenCalledWith(["20261113", "20261106", "20261030"]);

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(onChange).toHaveBeenCalledWith([]);

    const onlyButtons = screen.getAllByRole("button", { name: "Only" });
    fireEvent.click(onlyButtons[2]);
    expect(onChange).toHaveBeenCalledWith(["20261030"]);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
