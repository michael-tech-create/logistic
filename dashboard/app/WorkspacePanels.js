"use client";

import { useState } from "react";
import { Alert, Box, Button, Chip, Divider, IconButton, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import { ArrowForward, CheckCircleOutline, ContentCopy, Refresh } from "@mui/icons-material";
import { money, request, reviewStatusOf } from "./workflow.mjs";

import WhatsAppConnection from "./WhatsAppConnection";

export const panel = { p: { xs: 2, md: 3 }, border: 1, borderColor: "divider" };
export function Heading({ title, description, action }) {
  return <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" gap={2} sx={{ mb: 2.5 }}><Box><Typography variant="h2">{title}</Typography>{description && <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{description}</Typography>}</Box>{action}</Stack>;
}

export function Approvals({ reviews, error, refresh, busy, confirm, token, notify }) {
  const pending = (reviews || []).filter((row) => row.status === "pending");
  const decided = (reviews || []).filter((row) => row.status !== "pending");
  function decide(row, status, send = false) {
    const approval = status === "approved";
    confirm({
      title: send ? "Send this approved request?" : approval ? "Approve this request?" : "Reject this request?",
      description: `${row.summary}. ${send ? "This sends the stored quote to your connected provider. Confirm the quote and recipient details before continuing." : approval && ["pay", "clear"].includes(row.kind) ? "Your approval is saved even if no provider is connected. If a provider is connected, this also submits the request. Check the quote and recipient details first." : "This records your decision on the request."}`,
      label: send ? "Send to provider" : approval ? "Confirm approval" : "Reject request", danger: !approval,
      action: async () => {
        const result = await request(token, `/v1/reviews/${row.id}${send ? "/execute" : ""}`, { method: "POST", ...(send ? {} : { body: JSON.stringify({ status }) }) });
        await refresh(); notify(result.execution?.note || result.execution_note || `Request ${result.status}.`);
      },
    });
  }
  function payloadOf(row) { try { return typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload; } catch { return null; } }
  return <Stack spacing={3}>
    <Alert severity="info">Human approval and provider submission are separate statuses. If no payment or customs provider is connected, your approval is saved and nothing is sent.</Alert>
    <Paper sx={panel}><Heading title="Requests awaiting a decision" description="Check the stored details before you approve or reject a request." action={<Button startIcon={<Refresh />} onClick={refresh} disabled={!!busy}>Refresh</Button>} />
      {error && <Alert severity="error" sx={{ mb: 2 }} action={<Button color="inherit" onClick={refresh}>Retry</Button>}>{error}</Alert>}
      {reviews === null ? <Typography role="status">{error ? "Requests could not be loaded." : "Loading requests…"}</Typography> : !pending.length ? <Box sx={{ py: 5, textAlign: "center" }}><CheckCircleOutline sx={{ fontSize: 36, color: "success.main", mb: 1.5 }} /><Typography variant="h2">No decisions waiting</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>Check request history below for approved requests that still need a provider or verification.</Typography></Box> : <Stack spacing={2}>{pending.map((row) => { const payload = payloadOf(row); return <Paper key={row.id} variant="outlined" sx={{ p: 2.5 }}>
        <Stack direction="row" gap={1} alignItems="center" sx={{ mb: 1 }}><Chip size="small" label={row.kind === "pay" ? "Payment" : row.kind === "clear" ? "Cargo clearance" : row.kind} variant="outlined" /><Typography variant="caption" color="text.secondary">Request #{row.id}</Typography></Stack>
        <Typography variant="h3">{row.summary}</Typography><Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>{row.detail}</Typography>
        {payload && <Box sx={{ p: 2, mb: 2, bgcolor: "surface.soft", borderRadius: 1 }}><Typography variant="body2">{payload.commercial?.vendor_name || "Vendor not provided"} · {money(payload.commercial?.currency, payload.commercial?.total_amount)}</Typography><Typography variant="body2" color="text.secondary">{payload.movement?.origin?.location_name || "Origin not provided"} → {payload.movement?.destination?.location_name || "Destination not provided"}</Typography><Typography variant="caption" color="text.secondary">Reference: {payload.commercial?.quote_reference_id || "Not provided"}</Typography></Box>}
        {row.execution_note && <Alert severity="warning" sx={{ mb: 2 }}>{row.execution_note}</Alert>}
        <Stack direction="row" gap={1}><Button variant="contained" disabled={!!busy} onClick={() => decide(row, "approved")}>Review approval</Button><Button color="error" disabled={!!busy} onClick={() => decide(row, "rejected")}>Reject</Button></Stack>
      </Paper>; })}</Stack>}
    </Paper>
    {!!decided.length && <Paper sx={panel}><Heading title="Request history" description="Approval records your decision. Submitted means the provider accepted the request; check there for the final outcome." /><Stack divider={<Divider />} spacing={2}>{decided.map((row) => { const state = reviewStatusOf(row); return <Stack key={row.id} direction={{ xs: "column", sm: "row" }} gap={2} justifyContent="space-between"><Box sx={{ flex: 1 }}><Typography variant="body2" sx={{ mb: 1 }}>#{row.id} · {row.summary}</Typography><Chip size="small" label={state.label} variant="outlined" color={state.color} />{row.execution_note && <Typography variant="body2" color="text.secondary" sx={{ mt: 1, overflowWrap: "anywhere" }}>{row.execution_note}</Typography>}</Box>{state.canSend && <Button variant="outlined" sx={{ alignSelf: "flex-start", whiteSpace: "nowrap" }} disabled={!!busy} onClick={() => decide(row, "approved", true)}>Send to provider</Button>}</Stack>; })}</Stack></Paper>}
  </Stack>;
}

export function Connections({ token, company, perform, busy, notify, onQuotes, onAdd }) {
  const [emailStatus, setEmailStatus] = useState(null);
  return <Stack spacing={3}>
    <Paper sx={panel}><Heading title="Telegram intake" description="Link your chat so quotes are filed under your company." /><Stack spacing={2.5}>
      <Typography variant="body2">1. Open your company’s freight quote bot in Telegram.</Typography>
      <Box><Typography variant="body2" sx={{ mb: 1 }}>2. Copy this command and send it in the bot chat.</Typography><Stack direction="row" gap={1} alignItems="center"><Box component="code" sx={{ p: 1.5, bgcolor: "surface.soft", borderRadius: 1, overflowWrap: "anywhere", flex: 1 }}>{company?.link_command || "Loading your link command…"}</Box><IconButton aria-label="Copy Telegram link command" disabled={!company?.link_command || !!busy} onClick={() => perform("copy-link", async () => { await navigator.clipboard.writeText(company.link_command); notify("Link command copied. Paste it into your Telegram bot chat."); })}><ContentCopy fontSize="small" /></IconButton></Stack></Box>
      <Typography variant="body2">3. Wait for the bot’s link confirmation, then send text, a voice note, a photo, or a PDF.</Typography>
      <Typography variant="body2" color="text.secondary">Quotes appear in your inbox after processing. A copied command alone does not confirm a connection.</Typography><Button sx={{ alignSelf: "flex-start" }} onClick={onQuotes} endIcon={<ArrowForward />}>Go to quote inbox</Button>
    </Stack></Paper>
    <WhatsAppConnection token={token} />
    <Paper sx={panel}><Heading title="Email intake" description="Check whether the desk can reach its configured mailbox." action={<Button variant="outlined" disabled={!!busy} onClick={() => perform("email", async () => setEmailStatus(await request(token, "/v1/channels/email")))}>{busy === "email" ? "Checking…" : "Check email connection"}</Button>} /><Typography variant="body2" color="text.secondary">Email routing uses the inbound addresses assigned to your company. Ask your desk administrator to configure those addresses before forwarding quotes.</Typography>{emailStatus && <Alert severity={emailStatus.ok ? "success" : "warning"} sx={{ mt: 2 }}>{emailStatus.detail}</Alert>}</Paper>
    <Paper sx={panel}><Heading title="Upload directly" description="Add PDFs, text, images, voice notes, or pasted quotes without linking a channel." /><Button variant="outlined" onClick={onAdd}>Add a quote</Button></Paper>
  </Stack>;
}

export function Settings({ token, me, rates, company, perform, busy, notify, onRateSaved, onRiskSaved }) {
  const [rate, setRate] = useState(rates?.parallel_usd_ngn ?? "");
  const [risk, setRisk] = useState(company?.port_risk || "normal");
  return <Stack spacing={3}>
    <Paper sx={panel}><Heading title="Company preferences" description={company?.legal_name || me.business_name} />
      <Box component="form" onSubmit={(event) => { event.preventDefault(); perform("rates", async () => { const value = Number(rate); if (!Number.isFinite(value) || value <= 0) throw new Error("Enter a parallel USD/NGN rate greater than zero."); const saved = await request(token, "/v1/rates", { method: "POST", body: JSON.stringify({ parallel_usd_ngn: value }) }); onRateSaved(saved); notify("Your company’s parallel rate was saved. New quotes use it; existing estimates keep their original rate."); }); }} sx={{ maxWidth: 550 }}>
        <TextField label="Parallel USD/NGN rate" type="number" fullWidth value={rate} onChange={(event) => setRate(event.target.value)} helperText="Your company’s cash planning rate. Used for new quotes." slotProps={{ htmlInput: { min: 1, step: "any" } }} disabled={!rates || !!busy} /><Button type="submit" variant="outlined" disabled={!rates || !!busy} sx={{ mt: 2 }}>{busy === "rates" ? "Saving…" : "Save company rate"}</Button>
      </Box><Divider sx={{ my: 3 }} />
      <Box component="form" onSubmit={(event) => { event.preventDefault(); perform("risk", async () => { await request(token, "/v1/port-risk", { method: "POST", body: JSON.stringify({ level: risk }) }); onRiskSaved(risk); notify(`Port risk saved as ${risk}. New quotes use this planning setting.`); }); }} sx={{ maxWidth: 550 }}><TextField select label="Port risk planning level" fullWidth value={risk} onChange={(event) => setRisk(event.target.value)} helperText="A desk planning setting, not a live congestion report." disabled={!company || !!busy}>{["normal", "elevated", "severe"].map((value) => <MenuItem key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</MenuItem>)}</TextField><Button type="submit" variant="outlined" disabled={!company || !!busy} sx={{ mt: 2 }}>Save port risk</Button></Box>
    </Paper>
    <Paper sx={panel}><Heading title="Usage and subscription" description={`${me.quota_remaining} parses remaining · ${me.plan === "trial" ? "Trial" : me.plan_parses + '-parse plan'}`} /><Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>One pasted quote or uploaded file uses one parse. Checking saved quotes and downloading exports do not use parses.</Typography>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}>{(me.plans || []).map((plan) => <Box key={plan.code} sx={{ p: 3, border: 1, borderColor: "divider", borderRadius: 2 }}><Typography variant="h2">{plan.parses} parses</Typography><Typography sx={{ fontSize: 26, fontWeight: 650, my: 1 }}>{money("NGN", plan.price_ngn)}<Typography component="span" variant="body2" color="text.secondary"> / 30 days</Typography></Typography><Button variant="outlined" fullWidth disabled={!!busy} onClick={() => perform(plan.code, async () => { const payload = await request(token, "/v1/billing/checkout", { method: "POST", body: JSON.stringify({ plan: plan.code, callback_url: `${window.location.origin}/billing` }) }); if (!payload.authorization_url) throw new Error("Checkout could not be opened. Please try again."); window.location.assign(payload.authorization_url); })}>{busy === plan.code ? "Opening checkout…" : "Continue to Paystack"}</Button></Box>)}</Box>
    </Paper>
    <Paper sx={panel}><Heading title="Developer access" description="Use your account’s API key when connecting another tool. Keep it private." /><Typography component="code" variant="body2">{me.api_key ? `${me.api_key.slice(0, 6)}…${me.api_key.slice(-4)}` : "Not available"}</Typography><Button sx={{ ml: 2 }} disabled={!me.api_key || !!busy} onClick={() => perform("copy-key", async () => { await navigator.clipboard.writeText(me.api_key); notify("API key copied. Keep it private."); })}>Copy API key</Button></Paper>
  </Stack>;
}
