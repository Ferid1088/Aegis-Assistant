import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "./api";

describe("api client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("returns parsed JSON on success", async () => {
    (fetch as any).mockResolvedValue(new Response(JSON.stringify({ hello: "world" }), { status: 200 }));
    const result = await api.get<{ hello: string }>("/session");
    expect(result).toEqual({ hello: "world" });
    expect(fetch).toHaveBeenCalledWith("/api/v1/session", expect.objectContaining({ cache: "no-store" }));
  });

  it("throws an ApiError with status and body text on failure", async () => {
    (fetch as any).mockResolvedValue(new Response("nope", { status: 403, statusText: "Forbidden" }));
    await expect(api.get("/admin/users")).rejects.toBeInstanceOf(ApiError);
    (fetch as any).mockResolvedValue(new Response("nope", { status: 403, statusText: "Forbidden" }));
    await expect(api.get("/admin/users")).rejects.toMatchObject({ status: 403, message: "nope" });
  });

  it("returns undefined for 204 responses", async () => {
    (fetch as any).mockResolvedValue(new Response(null, { status: 204 }));
    const result = await api.delete("/admin/roles/x");
    expect(result).toBeUndefined();
  });

  it("post sends a JSON body", async () => {
    (fetch as any).mockResolvedValue(new Response("{}", { status: 200 }));
    await api.post("/chat", { question: "hi" });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/chat",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ question: "hi" }) })
    );
  });

  it("patch sends a JSON body", async () => {
    (fetch as any).mockResolvedValue(new Response("{}", { status: 200 }));
    await api.patch("/admin/users/1", { status: "inactive" });
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/admin/users/1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ status: "inactive" }) })
    );
  });
});
