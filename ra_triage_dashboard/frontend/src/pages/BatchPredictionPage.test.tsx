import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BatchPredictionPage } from "./BatchPredictionPage";

const MOCK_CONFIG = {
  max_issues: 50,
  autotriage_push_enabled: true,
  prompt_version: "v3",
  model_gateway: { catalog_label: "ra-model · /v1/models" },
  providers: {
    active_provider_id: "kylin",
    providers: [
      { id: "kylin", display_name: "Kylin Gateway", enabled: true, supports_batch: true },
    ],
  },
};

const MOCK_MODELS = {
  status: "ready",
  catalog_label: "ra-model · /v1/models",
  default_model_id: "qwen-vl-max",
  models: [
    {
      id: "qwen-vl-max",
      display_name: "Qwen VL Max",
      resolved_model_id: "qwen2.5-vl-72b",
      validation_status: "validated",
    },
    {
      id: "exp-model-1",
      display_name: "Experimental VLM",
      resolved_model_id: "exp-vlm-1",
      validation_status: "experimental",
    },
  ],
};

const MOCK_PROMPTS = {
  default_prompt_id: "prompt-default",
  items: [
    {
      id: "prompt-default",
      display_name: "Default Stuck Prompt",
      template: "Classify whether the ego vehicle is stuck.",
      sha256: "abcdef1234567890abcdef",
      is_default: true,
    },
  ],
};

const MOCK_BATCHES = {
  items: [
    {
      id: "batch-001",
      name: "smoke-batch-1",
      status: "succeeded",
      publish_status: "not_published",
      provider_id: "kylin",
      requested_model_id: "qwen-vl-max",
      resolved_model_id: "qwen2.5-vl-72b",
      prompt_version: "prompt-default",
      prompt_mode: "catalog",
      prompt_template_sha256: "abcdef1234567890abcdef",
      input_profile: "camera_ra_event",
      model_run_id: "run-batch-001",
      total_count: 1,
      completed_count: 1,
      success_count: 1,
      failed_count: 0,
      requested_by: "jasperchen",
      requested_by_verified: true,
      created_at: "2026-11-25T10:00:00Z",
      items: [
        {
          issue_id: "cn37760285",
          status: "succeeded",
          result: { model_label: "误触发", model_confidence: 0.91, model_reason: "Cleared quickly" },
        },
      ],
    },
  ],
  total: 1,
  requesters: [{ name: "jasperchen", job_count: 1, verified: true }],
  facets: {
    models: [{ id: "qwen-vl-max", job_count: 1 }],
    prompts: [{ version: "prompt-default", mode: "catalog", sha256: "abcdef123456", job_count: 1 }],
    input_profiles: [{ id: "camera_ra_event", job_count: 1 }],
  },
};

function renderPage(lang: "zh" | "en" = "zh") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <BatchPredictionPage active lang={lang} username="jasperchen" />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("BatchPredictionPage", () => {
  it("renders gateway models, prompt editor, history filters with zero native selects and opens log detail + publish modal", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/api/prediction-batches/config")) {
        return new Response(JSON.stringify(MOCK_CONFIG), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/api/prediction-batches/models")) {
        return new Response(JSON.stringify(MOCK_MODELS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/api/prediction-batches/prompts")) {
        return new Response(JSON.stringify(MOCK_PROMPTS), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/api/prediction-batches/batch-001")) {
        return new Response(JSON.stringify(MOCK_BATCHES.items[0]), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      if (url.includes("/api/prediction-batches")) {
        return new Response(JSON.stringify(MOCK_BATCHES), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response("{}", { status: 200 });
    });

    const { container } = renderPage("zh");

    await waitFor(() => {
      expect(screen.getByText("smoke-batch-1")).toBeTruthy();
      expect(screen.getAllByText("Qwen VL Max").length).toBeGreaterThan(0);
    });

    expect(container.querySelectorAll("select").length).toBe(0);

    // Expand batch detail logs
    fireEvent.click(screen.getByRole("button", { name: "查看日志" }));
    await waitFor(() => {
      expect(screen.getByText("cn37760285")).toBeTruthy();
      expect(screen.getByText("Cleared quickly")).toBeTruthy();
    });

    // Open publish confirmation dialog
    fireEvent.click(screen.getByRole("button", { name: "推送 AutoTriage" }));
    await waitFor(() => {
      expect(screen.getByText("确认推送到 AutoTriage")).toBeTruthy();
    });
  });

  it("renders English UI cleanly", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url.includes("/config")) return new Response(JSON.stringify(MOCK_CONFIG), { status: 200 });
      if (url.includes("/models")) return new Response(JSON.stringify(MOCK_MODELS), { status: 200 });
      if (url.includes("/prompts")) return new Response(JSON.stringify(MOCK_PROMPTS), { status: 200 });
      return new Response(JSON.stringify(MOCK_BATCHES), { status: 200 });
    });

    renderPage("en");
    await waitFor(() => {
      expect(screen.getByText("Server model gateway")).toBeTruthy();
      expect(screen.getByText("smoke-batch-1")).toBeTruthy();
    });
  });
});
