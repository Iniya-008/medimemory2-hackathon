import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/api", async (orig) => {
  const actual = await orig();
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn(), interceptors: actual.api.interceptors } };
});

import { api } from "../services/api";
import { AuthProvider, useAuth } from "../context/AuthContext";
import { ToastProvider } from "../context/ToastContext";
import ChatHome from "../pages/ChatHome";

const USER = { id: 7, email: "demo@medimemory.app", full_name: "Lakshmi Raman", profile: { ai_data_consent: false, preferred_language: "ta" } };
const VISIT = {
  id: 3, doctor_name: "Dr. Kavitha Rao", visit_date: "2026-11-20", status: "confirmed", source: "recording", instructions: [
    { id: 11, category: "medicine", simple_text: "Take Metformin 500 mg after breakfast.", source_sentence: "Take Metformin 500 mg after breakfast.",
      translations: { ta: { text: "காலை உணவுக்குப் பிறகு Metformin 500 mg.", verified: false, method: "machine" } } },
  ],
};

function Gate() { const { user } = useAuth(); return user ? <ChatHome /> : null; }

function mount() {
  sessionStorage.setItem("medimemory_token", "tok");
  api.get.mockImplementation((url) => Promise.resolve({ data: url === "/api/auth/me" ? USER : url === "/api/visits" ? [VISIT] : [] }));
  return render(<MemoryRouter initialEntries={["/app"]}><ToastProvider><AuthProvider><Routes>
    <Route path="/app" element={<Gate />} /></Routes></AuthProvider></ToastProvider></MemoryRouter>);
}

beforeEach(() => { vi.clearAllMocks(); sessionStorage.clear(); localStorage.clear(); window.HTMLElement.prototype.scrollIntoView = vi.fn(); });

describe("chat home", () => {
  it("puts record, upload and ask on one page, defaults to Tamil and flags unverified translation", async () => {
    mount();
    expect(await screen.findByText("Record my doctor visit")).toBeInTheDocument();
    expect(screen.getByText("Upload a prescription")).toBeInTheDocument();
    expect(screen.getByLabelText("Dictate a question")).toBeInTheDocument();
    expect(screen.getByLabelText("Talk with MediMemory (voice conversation)")).toBeInTheDocument();
    expect(screen.getByLabelText("Answer language")).toHaveValue("ta");
    expect(await screen.findByText(/Metformin 500 mg\./)).toBeInTheDocument();
    expect(screen.getByText(/not yet checked by a native speaker/)).toBeInTheDocument();
  });

  it("asks for AI consent before opening the voice conversation", async () => {
    mount();
    await userEvent.click(await screen.findByLabelText("Talk with MediMemory (voice conversation)"));
    expect(screen.getByText("One permission first")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Voice conversation" })).toBeNull();
  });

  it("offers many languages, Indian languages first", async () => {
    sessionStorage.setItem("medimemory_token", "tok");
    const LANGS = [{ code: "en", name: "English", native: "English", group: "india" }, { code: "ta", name: "Tamil", native: "தமிழ்", group: "india" },
      { code: "te", name: "Telugu", native: "తెలుగు", group: "india" }, { code: "ar", name: "Arabic", native: "العربية", group: "world" }];
    api.get.mockImplementation((url) => Promise.resolve({ data: url === "/api/auth/me" ? USER : url === "/api/visits" ? [] : url === "/api/visits/languages" ? { languages: LANGS } : [] }));
    render(<MemoryRouter initialEntries={["/app"]}><ToastProvider><AuthProvider><Routes>
      <Route path="/app" element={<Gate />} /></Routes></AuthProvider></ToastProvider></MemoryRouter>);
    expect(await screen.findByRole("option", { name: /తెలుగు/ })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /العربية/ })).toBeInTheDocument();
  });

  it("asks for AI consent before recording", async () => {
    mount();
    await userEvent.click(await screen.findByText("Record my doctor visit"));
    expect(screen.getByText("One permission first")).toBeInTheDocument();
  });

  it("shows the emergency card with a call button", async () => {
    mount();
    await screen.findByText("Record my doctor visit");
    api.post.mockResolvedValueOnce({ data: { type: "emergency", reason: "emergency", lang: "en", matches: [], phrase: "emergency",
      message: "This could be an emergency. Please call 108 or go to the nearest hospital now." } });
    await userEvent.selectOptions(screen.getByLabelText("Answer language"), "en");
    await userEvent.type(screen.getByLabelText("Your question"), "I have chest pain{enter}");
    expect(await screen.findByText(/call 108/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Call 108/ })).toHaveAttribute("href", "tel:108");
    expect(api.post).toHaveBeenCalledWith("/api/visits/ask", { question: "I have chest pain", lang: "en" });
  });

  it("shows grounded answers with the doctor's source sentence", async () => {
    mount();
    await screen.findByText("Record my doctor visit");
    api.post.mockResolvedValueOnce({ data: { type: "grounded", lang: "en", timing_ms: 40, matches: [{
      instruction_id: 11, visit_id: 3, doctor_name: "Dr. Kavitha Rao", visit_date: "2026-11-20", text: "Take Metformin 500 mg after breakfast.",
      text_lang: "en", translation_verified: true, english: "Take Metformin 500 mg after breakfast.", source_sentence: "Metformin 500 after breakfast, amma." }] } });
    await userEvent.type(screen.getByLabelText("Your question"), "When do I take Metformin?{enter}");
    expect(await screen.findByText(/Metformin 500 after breakfast, amma/)).toBeInTheDocument();
    expect(screen.getByText(/Answered only from instructions you confirmed/)).toBeInTheDocument();
  });
});
