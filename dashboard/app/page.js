"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Toolbar,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/Grid";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import PaymentsIcon from "@mui/icons-material/Payments";
import { BarChart } from "@mui/x-charts/BarChart";
import { PieChart } from "@mui/x-charts/PieChart";

const API = process.env.NEXT_PUBLIC_API_URL || "";

const money = (currency, amount) => `${currency || ""} ${Number(amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

export default function HomePage() {
  const [token, setToken] = useState("");
  const [me, setMe] = useState(null);
  const [mode, setMode] = useState("login");
  const [form, setForm] = useState({ email: "", password: "", business_name: "", home_country: "Nigeria" });
  const [error, setError] = useState("");
  const [records, setRecords] = useState([]);
  const [live, setLive] = useState([]);
  const [batchId, setBatchId] = useState("");
  const [busy, setBusy] = useState(false);
  const [chosen, setChosen] = useState([]);
  const [parallelRate, setParallelRate] = useState("");
  const [cbnRate, setCbnRate] = useState("");
  const [fallbackOfficial, setFallbackOfficial] = useState("1550");
  const [fallbackParallel, setFallbackParallel] = useState("1650");
  const [company, setCompany] = useState(null);
  const [deskNote, setDeskNote] = useState("");
  const [reviews, setReviews] = useState([]);

  useEffect(() => {
    const saved = window.localStorage.getItem("quote_token");
    if (saved) setToken(saved);
  }, []);

  useEffect(() => {
    if (!token) return;
    fetch(`${API}/v1/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        if (!response.ok) throw new Error("Session expired");
        setMe(await response.json());
      })
      .catch(() => {
        setToken("");
        window.localStorage.removeItem("quote_token");
      });
  }, [token]);

  useEffect(() => {
    if (!token || !me) return undefined;
    let stop = false;
    const pull = () => {
      fetch(`${API}/v1/inbox`, { headers: { Authorization: `Bearer ${token}` } })
        .then((response) => (response.ok ? response.json() : { records: [] }))
        .then((payload) => {
          if (!stop) setLive(payload.records || []);
        })
        .catch(() => {});
    };
    pull();
    fetch(`${API}/v1/company`, { headers: { Authorization: `Bearer ${token}` } })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => { if (!stop && payload) setCompany(payload); })
      .catch(() => {});
    const timer = setInterval(pull, 8000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [token, me]);

  const shown = useMemo(() => {
    const seen = new Set();
    const rows = [];
    [...live, ...records].forEach((record, index) => {
      const reference = record.commercial?.quote_reference_id || record.source_file || `row-${index}`;
      if (seen.has(reference)) return;
      seen.add(reference);
      rows.push(record);
    });
    return rows;
  }, [live, records]);

  const charts = useMemo(() => {
    const categories = {};
    const lanes = {};
    let customs = 0;
    let quoted = 0;
    for (const record of shown) {
      const lane = record.lane || "unknown";
      lanes[lane] = (lanes[lane] || 0) + 1;
      quoted += Number(record.commercial?.total_amount || 0);
      customs += Number(record.commercial?.customs_and_tax || 0);
      for (const item of record.line_items || []) {
        categories[item.category] = (categories[item.category] || 0) + Number(item.amount || 0);
      }
    }
    return {
      categories: Object.keys(categories),
      amounts: Object.values(categories),
      lanes: Object.entries(lanes).map(([label, value], id) => ({ id, label, value })),
      customs,
      quoted,
    };
  }, [shown]);

  async function submitAuth(event) {
    event.preventDefault();
    setError("");
    const path = mode === "login" ? "/v1/auth/login" : "/v1/auth/register";
    const response = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const payload = await response.json();
    if (!response.ok) {
      setError(typeof payload.detail === "string" ? payload.detail : "Could not sign in");
      return;
    }
    window.localStorage.setItem("quote_token", payload.token);
    setToken(payload.token);
    setMe(payload);
  }

  async function upload(event) {
    event.preventDefault();
    const files = event.target.elements.quotes.files;
    if (!files?.length) return;
    setBusy(true);
    setError("");
    const body = new FormData();
    for (const file of files) body.append("files", file);
    const response = await fetch(`${API}/v1/quotes/batch`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body,
    });
    const payload = await response.json();
    setBusy(false);
    if (!response.ok) {
      setError(typeof payload.detail === "string" ? payload.detail : "Upload failed");
      return;
    }
    setRecords(payload.records);
    setBatchId(payload.batch_id);
    const profile = await fetch(`${API}/v1/me`, { headers: { Authorization: `Bearer ${token}` } });
    setMe(await profile.json());
  }

  async function postDesk(path, body) {
    setDeskNote("");
    const response = await fetch(`${API}${path}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    setDeskNote(payload.note || payload.detail || payload.level || (response.ok ? "Saved" : "Request failed"));
  }

  async function loadReviews() {
    const response = await fetch(`${API}/v1/reviews`, { headers: { Authorization: `Bearer ${token}` } });
    const payload = await response.json();
    const rows = payload.reviews || [];
    setReviews(rows);
    const pending = rows.filter((row) => row.status === "pending");
    setDeskNote(pending.length ? pending.map((row) => `#${row.id} ${row.kind}: ${row.summary}`).join(" · ") : "No human reviews are waiting.");
  }

  async function decideReview(id, status) {
    const response = await fetch(`${API}/v1/reviews/${id}`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    });
    const payload = await response.json();
    setDeskNote(payload.execution?.note || payload.execution_note || payload.detail || payload.status || "Review updated");
    await loadReviews();
  }

  async function removeQuote(recordId) {
    setError("");
    const response = await fetch(`${API}/v1/inbox/${recordId}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` },
    });
    const payload = await response.json();
    if (!response.ok) {
      setError(typeof payload.detail === "string" ? payload.detail : "Could not delete the quote");
      return;
    }
    setLive((current) => current.filter((record) => record.record_id !== recordId));
  }

  async function saveRates() {
    setError("");
    const body = {};
    if (parallelRate) body.parallel_usd_ngn = Number(parallelRate);
    if (cbnRate) body.cbn_usd_ngn = Number(cbnRate);
    if (fallbackOfficial) body.fallback_official_usd_ngn = Number(fallbackOfficial);
    if (fallbackParallel) body.fallback_parallel_usd_ngn = Number(fallbackParallel);
    const response = await fetch(`${API}/v1/rates`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) {
      setError(typeof payload.detail === "string" ? payload.detail : "Could not save rates");
    }
  }

  async function pay(plan) {
    setError("");
    const response = await fetch(`${API}/v1/billing/checkout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ callback_url: `${window.location.origin}/billing`, plan }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setError(typeof payload.detail === "string" ? payload.detail : "Paystack is not configured");
      return;
    }
    window.location.href = payload.authorization_url;
  }

  async function download(kind) {
    const response = await fetch(`${API}/v1/quotes/batch/${batchId}.${kind}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      setError("Download failed");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = kind === "xlsx" ? "client-quotes.xlsx" : "client-quotes.pdf";
    link.click();
    URL.revokeObjectURL(url);
  }

  const quotaMax = Math.max(me?.plan_parses || 1000, me?.quota_remaining || 0, 1);

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="static" elevation={0}>
        <Toolbar>
          <Typography sx={{ flexGrow: 1, letterSpacing: "0.08em", fontWeight: 700 }}>CLEARING DESK</Typography>
          {me ? <Chip label={me.business_name} sx={{ bgcolor: "rgba(255,255,255,0.16)", color: "white" }} /> : null}
        </Toolbar>
      </AppBar>
      <Container maxWidth="lg" sx={{ py: 4 }}>
        {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
        {!me ? (
          <Paper sx={{ p: 4, maxWidth: 480, mx: "auto" }}>
            <Typography variant="h4" gutterBottom>{mode === "login" ? "Agent sign in" : "Open a desk"}</Typography>
            <Stack component="form" spacing={2} onSubmit={submitAuth}>
              {mode === "register" ? (
                <>
                  <TextField label="Business name" required value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} />
                  <TextField label="Home country" value={form.home_country} onChange={(e) => setForm({ ...form, home_country: e.target.value })} />
                </>
              ) : null}
              <TextField label="Email" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
              <TextField label="Password" type="password" required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
              <Button type="submit" variant="contained">{mode === "login" ? "Sign in" : "Create desk"}</Button>
              <Button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
                {mode === "login" ? "Need an account" : "I already have an account"}
              </Button>
            </Stack>
          </Paper>
        ) : (
          <Stack spacing={3}>
            {company ? (
              <Paper sx={{ p: 2 }}>
                <Typography variant="h6">Company tools</Typography>
                <Typography variant="body2">Telegram link code: {company.link_command}</Typography>
                <Typography variant="body2" sx={{ mb: 1 }}>Port risk is {company.port_risk}. Pay and clear wait for a person. Approve sends the stored quote to the payout or customs rail. If that rail is not configured, nothing is marked paid or cleared.</Typography>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mb: 1 }}>
                  <TextField size="small" label="Fallback official USD/NGN" value={fallbackOfficial} onChange={(e) => setFallbackOfficial(e.target.value)} />
                  <TextField size="small" label="Fallback parallel USD/NGN" value={fallbackParallel} onChange={(e) => setFallbackParallel(e.target.value)} />
                  <Button size="small" variant="outlined" onClick={saveRates}>Save fallback rates</Button>
                </Stack>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  {["normal", "elevated", "severe"].map((level) => (
                    <Button key={level} size="small" variant="outlined" onClick={async () => { await postDesk("/v1/port-risk", { level }); setCompany({ ...company, port_risk: level }); }}>{level}</Button>
                  ))}
                  <Button size="small" variant="outlined" onClick={() => postDesk("/v1/finance/apply", { record_id: shown[0]?.record_id || "manual", principal_ngn: shown[0]?.financing?.principal_ngn || shown[0]?.commercial?.customs_and_tax || 0 })}>Request duty finance</Button>
                  <Button size="small" variant="outlined" onClick={() => postDesk("/v1/escrow", { record_id: shown[0]?.record_id || "manual", amount_ngn: shown[0]?.commercial?.total_amount || 0, action: "hold" })}>Hold on escrow ledger</Button>
                  <Button size="small" variant="outlined" onClick={() => postDesk("/v1/escrow", { record_id: shown[0]?.record_id || "manual", amount_ngn: shown[0]?.commercial?.total_amount || 0, action: "release" })}>Release ledger</Button>
                  <Button size="small" variant="outlined" onClick={() => postDesk("/v1/payouts", { record_id: shown[0]?.record_id || "manual", trucker_account: "trucker", agent_account: "agent", customs_account: "customs" })}>Save payout plan</Button>
                  <Button size="small" variant="outlined" onClick={loadReviews}>Human reviews</Button>
                </Stack>
                {deskNote ? <Typography variant="body2" sx={{ mt: 1 }}>{deskNote}</Typography> : null}
                {reviews.filter((row) => row.status === "pending" && (row.kind === "pay" || row.kind === "clear")).map((row) => (
                  <Stack key={row.id} direction="row" spacing={1} sx={{ mt: 1 }} alignItems="center">
                    <Typography variant="body2">#{row.id} {row.kind}: {row.summary}</Typography>
                    <Button size="small" variant="contained" onClick={() => decideReview(row.id, "approved")}>Approve</Button>
                    <Button size="small" onClick={() => decideReview(row.id, "rejected")}>Reject</Button>
                  </Stack>
                ))}
              </Paper>
            ) : null}
            <Grid container spacing={2}>
              {[
                ["Parses left", me.quota_remaining, `of ${me.plan_parses} on the paid plan`],
                ["Quotes in this pack", shown.length, "Telegram, email, and uploads"],
                ["Quoted total", shown.length ? charts.quoted.toLocaleString() : "—", "sum of quote totals"],
                ["Customs and tax", shown.length ? charts.customs.toLocaleString() : "—", "classified customs lines"],
              ].map(([label, value, hint]) => (
                <Grid key={label} size={{ xs: 12, sm: 6, md: 3 }}>
                  <Card>
                    <CardContent>
                      <Typography variant="body2" color="text.secondary">{label}</Typography>
                      <Typography variant="h4">{value}</Typography>
                      <Typography variant="caption" color="text.secondary">{hint}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              ))}
            </Grid>

            <Paper sx={{ p: 2 }}>
              <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }} component="form" onSubmit={upload}>
                <Button component="label" variant="contained" startIcon={<UploadFileIcon />}>
                  Choose quote files
                  <input name="quotes" hidden type="file" accept=".pdf,.txt,application/pdf,text/plain" multiple required onChange={(e) => setChosen(Array.from(e.target.files || []).map((file) => file.name))} />
                </Button>
                <Typography sx={{ flexGrow: 1 }} color="text.secondary">{chosen.length ? chosen.join(", ") : "No file chosen yet"}</Typography>
                <Button type="submit" variant="contained" color="secondary" disabled={busy}>{busy ? "Reading quotes…" : "Build client pack"}</Button>
                <Button variant="outlined" startIcon={<PaymentsIcon />} onClick={() => pay("quote-200")}>₦15,000 / 200</Button>
                <Button variant="outlined" startIcon={<PaymentsIcon />} onClick={() => pay("quote-1000")}>₦50,000 / 1,000</Button>
                <Button variant="outlined" disabled={!batchId} onClick={() => download("xlsx")}>Excel</Button>
                <Button variant="outlined" disabled={!batchId} onClick={() => download("pdf")}>PDF</Button>
              </Stack>
              <Typography variant="body2" sx={{ mt: 1 }}>Live intake checks Telegram and email every 8 seconds. {live.length} quote{live.length === 1 ? "" : "s"} arrived without an upload.</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
                API key {me.api_key.slice(0, 6)}…{me.api_key.slice(-4)} · ₦{Number(me.plan_price_ngn).toLocaleString()} for {me.plan_parses} parses
              </Typography>
            </Paper>

            {shown[0]?.fx ? (
              <Paper sx={{ p: 2 }}>
                <Typography variant="h6">Cash needed</Typography>
                <Typography variant="body2" color="text.secondary">{shown[0].fx.note}</Typography>
                <Grid container spacing={2} sx={{ mt: 0.5 }}>
                  {["cbn", "parallel"].map((tier) => (
                    <Grid key={tier} size={{ xs: 12, md: 6 }}>
                      <Card variant="outlined">
                        <CardContent>
                          <Typography variant="overline">{tier === "cbn" ? "Official figures" : "Parallel cash rate"}</Typography>
                          {shown[0].fx[tier]?.anomaly ? (
                            <Typography>FX calculation anomaly. This rate was withheld.</Typography>
                          ) : (
                            <>
                              <Typography>USD {shown[0].fx[tier].USD?.toLocaleString() ?? "—"}</Typography>
                              <Typography>CNY {shown[0].fx[tier].CNY?.toLocaleString() ?? "—"}</Typography>
                              <Typography>NGN {shown[0].fx[tier].NGN?.toLocaleString() ?? "Set a parallel rate"}</Typography>
                            </>
                          )}
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2 }}>
                  <TextField size="small" label="Parallel USD/NGN" value={parallelRate} onChange={(e) => setParallelRate(e.target.value)} />
                  <TextField size="small" label="CBN USD/NGN override" value={cbnRate} onChange={(e) => setCbnRate(e.target.value)} />
                  <Button variant="outlined" onClick={saveRates}>Save rates</Button>
                </Stack>
                <Typography variant="body2" sx={{ mt: 1 }}>
                  {shown[0].financing?.offered
                    ? `Duty finance estimate NGN ${shown[0].financing.principal_ngn?.toLocaleString()} plus fee NGN ${shown[0].financing.origination_fee_ngn?.toLocaleString()}. ${shown[0].financing.reason}`
                    : shown[0].financing?.reason}
                </Typography>
                <Typography variant="body2">{shown[0].demurrage?.reason}{shown[0].demurrage?.buffer_hours ? "" : ` Buffer NGN ${Number(shown[0].demurrage?.buffer_ngn || 0).toLocaleString()}.`}</Typography>
                <Typography variant="body2">{shown[0].split?.execution}</Typography>
              </Paper>
            ) : null}

            <Grid container spacing={2}>
              <Grid size={{ xs: 12, md: 7 }}>
                <Paper sx={{ p: 2, height: 360 }}>
                  <Typography variant="h6">Charges by category</Typography>
                  {charts.categories.length ? (
                    <BarChart
                      height={290}
                      xAxis={[{ scaleType: "band", data: charts.categories }]}
                      series={[{ data: charts.amounts, label: "Amount", color: "#0b3954" }]}
                    />
                  ) : (
                    <Typography color="text.secondary" sx={{ mt: 8, textAlign: "center" }}>Upload a quote to chart the charges.</Typography>
                  )}
                </Paper>
              </Grid>
              <Grid size={{ xs: 12, md: 5 }}>
                <Paper sx={{ p: 2, height: 360 }}>
                  <Typography variant="h6">Quota and lanes</Typography>
                  <BarChart
                    height={140}
                    layout="horizontal"
                    yAxis={[{ scaleType: "band", data: ["Parses left"] }]}
                    xAxis={[{ max: quotaMax }]}
                    series={[{ data: [me.quota_remaining], color: "#e07a2f", label: "Remaining" }]}
                  />
                  {charts.lanes.length ? (
                    <PieChart height={160} series={[{ data: charts.lanes, innerRadius: 28 }]} />
                  ) : (
                    <Typography color="text.secondary">Lane mix appears after a pack is built.</Typography>
                  )}
                </Paper>
              </Grid>
            </Grid>

            <Paper>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Vendor</TableCell>
                    <TableCell>Reference</TableCell>
                    <TableCell>Lane</TableCell>
                    <TableCell>Route</TableCell>
                    <TableCell align="right">Total</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {shown.length ? shown.map((record, index) => (
                    <TableRow key={`${record.record_id || record.commercial?.quote_reference_id || record.source_file || "quote"}-${index}`}>
                      <TableCell>{record.commercial.vendor_name}</TableCell>
                      <TableCell>{record.commercial.quote_reference_id}</TableCell>
                      <TableCell><Chip size="small" label={record.lane} /></TableCell>
                      <TableCell>{record.movement.origin?.location_name} → {record.movement.destination?.location_name}</TableCell>
                      <TableCell align="right">{money(record.commercial.currency, record.commercial.total_amount)}</TableCell>
                      <TableCell align="right">
                        {record.record_id ? <Button size="small" color="error" onClick={() => removeQuote(record.record_id)}>Delete</Button> : null}
                      </TableCell>
                    </TableRow>
                  )) : (
                    <TableRow>
                      <TableCell colSpan={6}>No quotes in this pack yet.</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </Paper>
          </Stack>
        )}
      </Container>
    </Box>
  );
}
