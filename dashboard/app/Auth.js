"use client";

import { useState } from "react";
import { Alert, Avatar, Box, Button, Stack, TextField, Typography } from "@mui/material";
import { LocalShippingOutlined } from "@mui/icons-material";
import { request } from "./workflow.mjs";

export default function Auth({ onSession }) {
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", business_name: "", home_country: "Nigeria" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const session = await request("", `/v1/auth/${mode}`, { method: "POST", body: JSON.stringify(form) });
      window.localStorage.setItem("quote_token", session.token);
      onSession(session);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  }
  return <Box sx={{ minHeight: "100vh", display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" } }}>
    <Box sx={{ bgcolor: "primary.dark", color: "white", p: { xs: 3, md: 8 }, display: "flex", flexDirection: "column", justifyContent: "space-between", gap: 5 }}>
      <Stack direction="row" gap={1.5} alignItems="center"><LocalShippingOutlined /><Typography fontWeight={700} letterSpacing=".04em">CLEARING DESK</Typography></Stack>
      <Box sx={{ maxWidth: 460, display: { xs: "none", md: "block" } }}><Typography component="h1" sx={{ fontSize: { xs: 32, md: 48 }, fontWeight: 650, letterSpacing: "-.04em", lineHeight: 1.15 }}>From a carrier quote<br />to a clear next step.</Typography><Typography sx={{ mt: 3, color: "#c8dcd2", lineHeight: 1.8 }}>One workspace to collect freight quotes, check costs and currencies, and prepare the file your client needs.</Typography><Stack spacing={2} sx={{ mt: 5 }}>{["Add a PDF, text, or Telegram quote", "Check the route and extracted charges", "Download a client PDF or spreadsheet"].map((text, index) => <Stack key={text} direction="row" spacing={2} alignItems="center"><Avatar sx={{ width: 30, height: 30, fontSize: 13, bgcolor: "#285548", color: "white" }}>{index + 1}</Avatar><Typography variant="body2" color="#e0ece3">{text}</Typography></Stack>)}</Stack></Box>
      <Typography variant="caption" color="#b4ccc0" sx={{ display: { xs: "none", md: "block" } }}>Built for the work behind every shipment.</Typography>
    </Box>
    <Box component="main" sx={{ display: "grid", placeItems: "center", p: { xs: 3, md: 6 } }}><Box sx={{ width: "100%", maxWidth: 400 }}>
      <Typography variant="overline" color="text.secondary">YOUR WORKSPACE</Typography><Typography component="h2" variant="h4" sx={{ mt: 1, mb: 1 }}>{mode === "login" ? "Welcome back" : "Open your clearing desk"}</Typography><Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>{mode === "login" ? "Sign in to pick up where you left off." : "Start with 5 trial parses. Check your first quote before choosing a plan."}</Typography>
      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      <Stack component="form" spacing={2.5} onSubmit={submit}>
        {mode === "register" && <><TextField label="Business name" required autoComplete="organization" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} disabled={busy} /><TextField label="Home country" required autoComplete="country-name" value={form.home_country} onChange={(e) => setForm({ ...form, home_country: e.target.value })} disabled={busy} /></>}
        <TextField label="Work email" type="email" required autoComplete="username" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} disabled={busy} /><TextField label="Password" type="password" required autoComplete={mode === "login" ? "current-password" : "new-password"} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} disabled={busy} />
        <Button type="submit" variant="contained" size="large" disabled={busy}>{busy ? "Opening your desk…" : mode === "login" ? "Sign in" : "Create workspace"}</Button><Button disabled={busy} onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>{mode === "login" ? "New here? Create a workspace" : "Already have a workspace? Sign in"}</Button>
      </Stack>
    </Box></Box>
  </Box>;
}
