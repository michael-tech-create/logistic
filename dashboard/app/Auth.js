"use client";

import { useEffect, useState } from "react";
import { Alert, Avatar, Box, Button, Stack, TextField, Typography } from "@mui/material";
import Brand from "./Brand";
import { ensureServiceReady, request } from "./workflow.mjs";

export default function Auth({ onSession }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", business_name: "", home_country: "Nigeria" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [resendAt, setResendAt] = useState(0);
  const [seconds, setSeconds] = useState(0);
  useEffect(() => { if (!resendAt) return; const update = () => setSeconds(Math.max(0, Math.ceil((resendAt - Date.now()) / 1000))); update(); const timer = setInterval(update, 1000); return () => clearInterval(timer); }, [resendAt]);
  function changeMode(next) { setMode(next); setError(""); setNotice(""); setForm((current) => ({ ...current, password: "" })); }
  useEffect(() => { const entry = new URLSearchParams(window.location.search).get("mode"); if (["register", "forgot-password"].includes(entry)) setMode(entry); }, []);
  async function submit(event) {
    event.preventDefault();
    if (mode === "forgot-password" && seconds > 0) return;
    setBusy(true); setError(""); setNotice("");
    try {
      setNotice("Connecting to your workspace… This may take a moment.");
      await ensureServiceReady();
      setNotice("");
      if (mode === "forgot-password") {
        const result = await request("", "/v1/auth/forgot-password", { method: "POST", body: JSON.stringify({ email: form.email }) });
        setNotice(result.message); setResendAt(Date.now() + 60000); return;
      }
      const session = await request("", `/v1/auth/${mode}`, { method: "POST", body: JSON.stringify(form) });
      window.localStorage.setItem("quote_token", session.token);
      // Signup is an entry hint, not a permanent mode. Remove it after success
      // so a later sign-out returns to the sign-in form.
      const location = new URL(window.location.href);
      location.searchParams.delete("mode");
      window.history.replaceState(null, "", `${location.pathname}${location.search}${location.hash}`);
      onSession(session);
    } catch (err) { setNotice(""); setError(err.message); } finally { setBusy(false); }
  }
  return <Box sx={{ minHeight: "100vh", display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gridTemplateRows: { xs: "auto 1fr", md: "1fr" } }}>
    <Box sx={{ background: "radial-gradient(ellipse at 10% 15%, #e7f1fc, transparent 65%), linear-gradient(145deg, #f8fbfd, #eff5fa)", color: "text.primary", borderRight: { md: "1px solid #dce3e8" }, borderBottom: { xs: "1px solid #dce3e8", md: 0 }, p: { xs: 3, md: 8 }, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 5 }}>
      <Brand large />
      <Box sx={{ maxWidth: 460, display: { xs: "none", md: "block" } }}><Typography component="h1" sx={{ fontSize: { xs: 32, md: 48 }, fontWeight: 450, letterSpacing: "-.05em", lineHeight: 1.15 }}>From a carrier quote<br />to a clear next step.</Typography><Typography sx={{ mt: 3, color: "text.secondary", lineHeight: 1.8 }}>One workspace to collect freight quotes, check costs and currencies, and prepare the file your client needs.</Typography><Stack spacing={2} sx={{ mt: 5 }}>{["Add a PDF, text, or Telegram quote", "Check the route and extracted charges", "Download a client PDF or spreadsheet"].map((text, index) => <Stack key={text} direction="row" spacing={2} alignItems="center"><Avatar sx={{ width: 30, height: 30, fontSize: 13, bgcolor: "surface.blue", color: "primary.main", border: 1, borderColor: "surface.blueBorder" }}>{index + 1}</Avatar><Typography variant="body2" color="text.secondary">{text}</Typography></Stack>)}</Stack></Box>
      <Typography variant="caption" color="text.secondary" sx={{ display: { xs: "none", md: "block" } }}>Built for the work behind every shipment.</Typography>
    </Box>
    <Box component="main" sx={{ display: "grid", placeItems: "center", p: { xs: 2, md: 6 } }}><Box sx={{ width: "100%", maxWidth: 440, bgcolor: "background.paper", p: { xs: 3, sm: 4 }, border: 1, borderColor: "divider", borderRadius: 3, boxShadow: "0 18px 55px #263e5310" }}>
      <Typography variant="overline" color="text.secondary">YOUR WORKSPACE</Typography><Typography component="h2" variant="h4" sx={{ mt: 1, mb: 1 }}>{mode === "forgot-password" ? "Reset your password" : mode === "login" ? "Welcome back" : "Open your clearing desk"}</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>{mode === "forgot-password" ? "Enter your work email and we’ll send you a link to choose a new password." : mode === "login" ? "Sign in to pick up where you left off." : "Start with 5 trial parses. Check your first quote before choosing a plan."}</Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {notice && <Alert severity={busy ? "info" : "success"} role="status" sx={{ mb: 2 }}>{notice}</Alert>}
      <Stack component="form" spacing={2.5} onSubmit={submit}>
        {mode === "register" && <><TextField label="Business name" required autoComplete="organization" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} disabled={busy} /><TextField label="Home country" required autoComplete="country-name" value={form.home_country} onChange={(e) => setForm({ ...form, home_country: e.target.value })} disabled={busy} /></>}
        <TextField label="Work email" type="email" required autoComplete="username" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} disabled={busy} />{mode !== "forgot-password" && <TextField label="Password" type="password" required autoComplete={mode === "login" ? "current-password" : "new-password"} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} disabled={busy} />}
        {mode === "login" && <Button type="button" sx={{ alignSelf: "flex-end", mt: "8px !important" }} disabled={busy} onClick={() => changeMode("forgot-password")}>Forgot password?</Button>}
        <Button type="submit" variant="contained" size="large" disabled={busy || (mode === "forgot-password" && seconds > 0)}>{busy ? (mode === "forgot-password" ? "Sending reset link…" : "Opening your desk…") : mode === "forgot-password" ? (seconds > 0 ? `Request again in ${seconds}s` : "Send reset link") : mode === "login" ? "Sign in" : "Create workspace"}</Button><Button type="button" disabled={busy} onClick={() => changeMode(mode === "login" ? "register" : "login")}>{mode === "forgot-password" ? "Back to sign in" : mode === "login" ? "New here? Create a workspace" : "Already have a workspace? Sign in"}</Button>
      </Stack>
    </Box></Box>
  </Box>;
}
