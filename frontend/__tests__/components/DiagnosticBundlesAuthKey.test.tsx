/**
 * The Charger Auth Key affordance on the Diagnostic Bundles panel.
 *
 * Rotation is irreversible and has no grace overlap, and the fleet is behind
 * carrier NAT — so the guard these tests cover is the difference between a slip
 * and a site visit. They deliberately assert the *negative* cases: that the
 * destructive call is not reachable by one click, and that a revealed key
 * cannot be dismissed by accident.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

// fireEvent rather than user-event: the latter is not a dependency of this repo,
// and adding one for a handful of clicks is not a trade worth making.
import DiagnosticBundles from "@/components/DiagnosticBundles";

const list = vi.fn();
const provisionAuthKey = vi.fn();
const rotateAuthKey = vi.fn();

vi.mock("@/lib/api-services", () => ({
  diagnosticBundleService: {
    list: (...a: unknown[]) => list(...a),
    provisionAuthKey: (...a: unknown[]) => provisionAuthKey(...a),
    rotateAuthKey: (...a: unknown[]) => rotateAuthKey(...a),
    downloadUrl: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const KEY = "brand-new-secret-key";

// jsdom ships no clipboard API; without this the Copy button throws.
Object.assign(navigator, { clipboard: { writeText: vi.fn() } });

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue({ items: [], next_cursor: null });
});

const renderPanel = (hasAuthKey: boolean) =>
  render(
    <DiagnosticBundles chargerId={7} chargerName="VOW0007" hasAuthKey={hasAuthKey} />
  );

describe("auth key affordance", () => {
  it("offers to generate when the charger has no key, and does not confirm", async () => {
    provisionAuthKey.mockResolvedValue({ auth_key: KEY, rotated: false });
    renderPanel(false);

    fireEvent.click(screen.getByRole("button", { name: /generate auth key/i }));

    expect(provisionAuthKey).toHaveBeenCalledWith(7);
    expect(rotateAuthKey).not.toHaveBeenCalled();
    expect(await screen.findByText(KEY)).toBeInTheDocument();
  });

  it("says Rotate — not Generate — once a key exists", () => {
    renderPanel(true);
    expect(screen.getByRole("button", { name: /rotate auth key/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate auth key/i })).toBeNull();
  });

  it("never rotates on a single click — it opens a confirmation instead", async () => {
    renderPanel(true);

    fireEvent.click(screen.getByRole("button", { name: /rotate auth key/i }));

    expect(rotateAuthKey).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("keeps the rotate button disabled until the charger name is typed", async () => {
    renderPanel(true);
    fireEvent.click(screen.getByRole("button", { name: /rotate auth key/i }));

    const confirmBtn = await screen.findByRole("button", { name: /^rotate key$/i });
    expect(confirmBtn).toBeDisabled();

    const input = screen.getByPlaceholderText("VOW0007");
    fireEvent.change(input, { target: { value: "VOW000" } });
    expect(confirmBtn).toBeDisabled();

    fireEvent.change(input, { target: { value: "VOW0007" } });
    await waitFor(() => expect(confirmBtn).toBeEnabled());
  });

  it("accepts the name in any case, with surrounding whitespace", async () => {
    renderPanel(true);
    fireEvent.click(screen.getByRole("button", { name: /rotate auth key/i }));

    fireEvent.change(screen.getByPlaceholderText("VOW0007"), {
      target: { value: "  vow0007  " },
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^rotate key$/i })).toBeEnabled()
    );
  });

  it("sends the typed confirmation through to the API", async () => {
    rotateAuthKey.mockResolvedValue({ auth_key: KEY, rotated: true });
    renderPanel(true);
    fireEvent.click(screen.getByRole("button", { name: /rotate auth key/i }));
    fireEvent.change(screen.getByPlaceholderText("VOW0007"), {
      target: { value: "VOW0007" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^rotate key$/i }));

    await waitFor(() => expect(rotateAuthKey).toHaveBeenCalledWith(7, "VOW0007"));
    expect(await screen.findByText(KEY)).toBeInTheDocument();
  });

  it("holds the revealed key until it is explicitly acknowledged", async () => {
    provisionAuthKey.mockResolvedValue({ auth_key: KEY, rotated: false });
    renderPanel(false);
    fireEvent.click(screen.getByRole("button", { name: /generate auth key/i }));
    expect(await screen.findByText(KEY)).toBeInTheDocument();

    // The key exists nowhere else — copying alone must not dismiss it.
    fireEvent.click(screen.getByRole("button", { name: /^copy$/i }));
    expect(screen.getByText(KEY)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /i have saved this key/i }));
    await waitFor(() => expect(screen.queryByText(KEY)).toBeNull());
  });

  it("flips to Rotate after a first provision, without waiting for a refetch", async () => {
    provisionAuthKey.mockResolvedValue({ auth_key: KEY, rotated: false });
    renderPanel(false);

    fireEvent.click(screen.getByRole("button", { name: /generate auth key/i }));

    expect(
      await screen.findByRole("button", { name: /rotate auth key/i })
    ).toBeInTheDocument();
  });
});
