import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UsersPage } from "./UsersPage";

function renderWithQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UsersPage", () => {
  it("blocks non-admin sessions cleanly in ZH and EN", () => {
    const { rerender } = renderWithQuery(<UsersPage active lang="zh" isAdmin={false} />);
    expect(screen.getByText("该页面仅限 Dashboard 管理员访问。")).toBeInTheDocument();

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    rerender(
      <QueryClientProvider client={client}>
        <UsersPage active lang="en" isAdmin={false} />
      </QueryClientProvider>,
    );
    expect(
      screen.getByText("This page is restricted to Dashboard administrators."),
    ).toBeInTheDocument();
  });

  it("renders paginated users with UiSelect, filters by role/search, and sends X-RA-Triage-Request header on save", async () => {
    const users = Array.from({ length: 25 }, (_, i) => ({
      username: i === 0 ? "jasperchen" : `reviewer_${String(i).padStart(2, "0")}`,
      role: i === 0 ? "admin" : "writer",
      intent_permission: "manage",
      annotation_role: "rd",
      updated_at: "2026-11-24T10:00:00Z",
    }));
    const fetchMock = vi.fn().mockImplementation(async (url: string) => {
      if (url.startsWith("/api/access-users/")) {
        return { ok: true, status: 200, text: async () => JSON.stringify({ user: users[0] }) };
      }
      if (url === "/api/access-users") {
        return { ok: true, status: 200, text: async () => JSON.stringify({ items: users }) };
      }
      if (url === "/api/mention-users") {
        return {
          ok: true,
          status: 200,
          text: async () =>
            JSON.stringify({
              items: [{ username: "jasperchen", display_name: "Jasper", enabled: true }],
            }),
        };
      }
      return { ok: true, status: 200, text: async () => "{}" };
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithQuery(<UsersPage active lang="en" isAdmin />);

    await waitFor(() => expect(screen.getByText("jasperchen")).toBeInTheDocument());
    expect(container.querySelector("select")).toBeNull();
    expect(screen.getByText("1 / 2 · 25")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("combobox", { name: "Filter by role" }));
    fireEvent.click(screen.getByRole("option", { name: "Admin" }));
    const accessNav = screen.getByRole("navigation", { name: "User access pagination" });
    expect(within(accessNav).getByText("1 / 1 · 1")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("e.g. xuhaoxuan_i"), {
      target: { value: "new_reviewer" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add user" }));
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/access-users/new_reviewer",
        expect.objectContaining({
          method: "PUT",
          headers: expect.objectContaining({
            "X-RA-Triage-Request": "browser-v1",
          }),
        }),
      );
    });
  });
});
