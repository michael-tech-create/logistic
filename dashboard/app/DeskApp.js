"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Avatar, Box, Button, Chip, CircularProgress, Container, Dialog, DialogActions, DialogContent, DialogTitle, IconButton, LinearProgress, Paper, Skeleton, Stack, Typography } from "@mui/material";
import { Add, ArrowForward, DescriptionOutlined, DownloadOutlined, FactCheckOutlined, HubOutlined, Logout, SettingsOutlined } from "@mui/icons-material";
import Auth from "./Auth";
import Brand from "./Brand";
import IntakeDialog from "./IntakeDialog";
import QuoteDialog from "./QuoteDialog";
import QuoteInbox from "./QuoteInbox";
import { Approvals, Connections, panel, Settings } from "./WorkspacePanels";
import { filterRecords, mergeRecords, money, request, saveDownload, statusOf } from "./workflow.mjs";

const navigation = [
  { id: "quotes", label: "Quotes", icon: DescriptionOutlined },
  { id: "approvals", label: "Approvals", icon: FactCheckOutlined },
  { id: "connections", label: "Connections", icon: HubOutlined },
  { id: "settings", label: "Settings", icon: SettingsOutlined },
];
const headings = {
  quotes: ["Your quote desk", "Bring in a quote, check the details, and prepare a client file."],
  approvals: ["Approvals", "Review requests before authorizing payment or cargo clearance."],
  connections: ["Bring your channels together", "Send quotes from the places your team already works."],
  settings: ["Workspace settings", "Manage your rates, port risk, and parse allowance."],
};

function Workspace({ token, initialUser, onSignOut }) {
  const [me, setMe] = useState(initialUser);
  const [section, setSection] = useState("quotes");
  const [inbox, setInbox] = useState(null);
  const [reviews, setReviews] = useState(null);
  const [company, setCompany] = useState(null);
  const [rates, setRates] = useState(null);
  const [pack, setPack] = useState({ batch_id: "", records: [] });
  const [selected, setSelected] = useState(null);
  const [intake, setIntake] = useState(false);
  const [seed, setSeed] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [inboxError, setInboxError] = useState("");
  const [reviewsError, setReviewsError] = useState("");
  const [setupError, setSetupError] = useState("");
  const [updatedAt, setUpdatedAt] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmation, setConfirmation] = useState(null);

  function navigate(id) { setSection(id); window.location.hash = id; setError(""); setNotice(""); }
  const refresh = useCallback(async (isActive = () => true) => {
    const results = await Promise.allSettled([request(token, "/v1/inbox"), request(token, "/v1/reviews")]);
    if (!isActive()) return;
    if (results[0].status === "fulfilled") { setInbox(results[0].value.records || []); setInboxError(""); setUpdatedAt(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })); }
    else setInboxError(results[0].reason.message);
    if (results[1].status === "fulfilled") { setReviews(results[1].value.reviews || []); setReviewsError(""); }
    else setReviewsError(results[1].reason.message);
  }, [token]);
  const loadSetup = useCallback(async (isActive = () => true) => {
    const results = await Promise.allSettled([request(token, "/v1/company"), request(token, "/v1/rates")]);
    if (!isActive()) return;
    let problem = "";
    if (results[0].status === "fulfilled") setCompany(results[0].value); else problem = results[0].reason.message;
    if (results[1].status === "fulfilled") setRates(results[1].value); else problem = results[1].reason.message;
    setSetupError(problem);
  }, [token]);
  useEffect(() => {
    let active = true;
    let pulling = false;
    const poll = async () => { if (pulling) return; pulling = true; try { await refresh(() => active); } finally { pulling = false; } };
    poll(); loadSetup(() => active);
    const onHash = () => { const id = window.location.hash.slice(1); if (navigation.some((item) => item.id === id)) setSection(id); };
    onHash(); window.addEventListener("hashchange", onHash);
    const timer = setInterval(poll, 15000);
    const batchId = window.localStorage.getItem(`quote_pack_${initialUser.id}`);
    if (batchId) request(token, `/v1/quotes/batch/${encodeURIComponent(batchId)}`).then((payload) => { if (active) setPack(payload); }).catch((err) => { if (active) { setNotice(`Your last client pack could not be opened. ${err.message}`); if (err.status === 404) window.localStorage.removeItem(`quote_pack_${initialUser.id}`); } });
    return () => { active = false; clearInterval(timer); window.removeEventListener("hashchange", onHash); };
  }, [refresh, loadSetup, token, initialUser.id]);

  const shown = useMemo(() => mergeRecords(inbox || [], pack.records), [inbox, pack.records]);
  const visible = useMemo(() => filterRecords(shown, search, filter), [shown, search, filter]);
  const checked = shown.filter((record) => statusOf(record).key === "reviewed").length;
  const pending = (reviews || []).filter((row) => row.status === "pending");
  const packRecords = pack.records.map((record) => shown.find((item) => item.record_id === record.record_id) || record);
  const packUnchecked = packRecords.filter((record) => statusOf(record).key !== "reviewed");
  async function perform(action, callback) {
    setBusy(action); setError(""); setNotice("");
    try { await callback(); } catch (err) { setError(err.message); } finally { setBusy(""); }
  }
  function addQuote(text = "") { setSeed(text); setIntake(true); }
  function onCreated(payload) {
    const records = payload.records || [];
    setInbox((current) => mergeRecords(records, current || []));
    if (payload.batch_id) { setPack(payload); window.localStorage.setItem(`quote_pack_${me.id}`, payload.batch_id); }
    setIntake(false); setSelected(records[0] || null); setSection("quotes"); window.location.hash = "quotes";
    setNotice(`${records.length === 1 ? "Quote added" : `${records.length} quotes added`}. Check the details before exporting.`);
    request(token, "/v1/me").then(setMe).catch((err) => setError(err.message));
  }
  function updateRecord(record) {
    setInbox((current) => (current || []).map((item) => item.record_id === record.record_id ? record : item));
    setPack((current) => ({ ...current, records: current.records.map((item) => item.record_id === record.record_id ? record : item) }));
    setSelected(record);
  }
  function confirmDelete(record) {
    setConfirmation({ title: "Delete this quote?", description: `${record.commercial?.vendor_name || "This quote"} will be removed from your inbox. If it belongs to the current client pack, that pack will be closed. This cannot be undone.`, label: "Delete quote", danger: true, action: async () => {
      await request(token, `/v1/inbox/${record.record_id}`, { method: "DELETE" });
      setInbox((current) => (current || []).filter((item) => item.record_id !== record.record_id));
      if (pack.records.some((item) => item.record_id === record.record_id)) { setPack({ batch_id: "", records: [] }); window.localStorage.removeItem(`quote_pack_${me.id}`); }
      setSelected(null); setNotice("Quote deleted.");
    } });
  }
  function exportPack(kind) {
    perform(`export-${kind}`, async () => { const blob = await request(token, `/v1/quotes/batch/${pack.batch_id}.${kind}`, { download: true }); saveDownload(blob, `client-quotes.${kind}`); setNotice(`${kind.toUpperCase()} pack download started.`); });
  }
  const navButtons = () => navigation.map((item) => { const Icon = item.icon; return <Button key={item.id} onClick={() => navigate(item.id)} aria-current={section === item.id ? "page" : undefined} startIcon={<Icon fontSize="small" />} sx={{ justifyContent: "flex-start", px: 2, color: section === item.id ? "primary.main" : "text.secondary", bgcolor: section === item.id ? "action.selected" : "transparent", fontWeight: section === item.id ? 600 : 400, whiteSpace: "nowrap" }}>{item.label}{item.id === "approvals" && !!pending.length && <Chip label={pending.length} size="small" sx={{ ml: 1, height: 20, minWidth: 24, bgcolor: "surface.warning", color: "warning.main" }} />}</Button>; });

  return <Box sx={{ minHeight: "100vh" }}>
    <Box component="a" href="#main-content" sx={{ position: "fixed", top: -60, left: 16, zIndex: 2000, p: 1.5, bgcolor: "white", "&:focus": { top: 12 } }}>Skip to main content</Box>
    <Box component="aside" sx={{ display: { xs: "none", md: "flex" }, position: "fixed", inset: "0 auto 0 0", width: 232, bgcolor: "background.paper", borderRight: 1, borderColor: "divider", p: 2.5, flexDirection: "column", gap: 4 }}>
      <Box sx={{ mt: 1 }}><Brand subtitle="Quote workspace" /></Box>
      <Box><Typography variant="overline" color="text.secondary" sx={{ px: 2, fontSize: 10 }}>WORKSPACE</Typography><Stack component="nav" aria-label="Main navigation" spacing={.8} sx={{ mt: 1 }}>{navButtons()}</Stack></Box>
      <Box sx={{ mt: "auto", p: 2, bgcolor: "surface.soft", borderRadius: 2 }}><Typography variant="body2" fontWeight={650}>{me.quota_remaining} parses left</Typography><LinearProgress variant="determinate" value={Math.min(100, Math.max(0, me.quota_remaining / Math.max(me.plan_parses || 5, 1) * 100))} sx={{ my: 1.5, height: 5, borderRadius: 3, bgcolor: "surface.muted" }} /><Typography variant="caption" color="text.secondary">{me.plan === "trial" ? "Your trial allowance" : "Your current allowance"}</Typography><Button size="small" onClick={() => navigate("settings")} endIcon={<ArrowForward fontSize="small" />} sx={{ display: "flex", px: 0, mt: .5 }}>Manage usage</Button></Box>
      <Stack direction="row" alignItems="center" spacing={1}><Avatar sx={{ width: 32, height: 32, fontSize: 13, bgcolor: "surface.blue", color: "primary.main" }}>{me.business_name?.slice(0, 1).toUpperCase()}</Avatar><Typography variant="caption" sx={{ flex: 1, overflowWrap: "anywhere" }}>{me.business_name}</Typography><IconButton aria-label="Sign out" onClick={onSignOut}><Logout fontSize="small" /></IconButton></Stack>
    </Box>
    <Box sx={{ ml: { md: "232px" } }}>
      <Box component="header" sx={{ bgcolor: "background.paper", borderBottom: 1, borderColor: "divider", px: { xs: 2, md: 4 }, py: 1.7 }}><Stack direction="row" justifyContent="space-between" alignItems="center"><Stack direction="row" gap={1.5} alignItems="center"><Box sx={{ display: { md: "none" } }}><Brand compact /></Box><Typography variant="body2" color="text.secondary"><Box component="span" sx={{ display: { xs: "none", md: "inline" } }}>Workspace / </Box><Box component="span" sx={{ color: "text.primary", fontWeight: 600 }}>{navigation.find((item) => item.id === section)?.label}</Box></Typography></Stack><Stack direction="row" gap={1} alignItems="center"><Typography variant="caption" color="text.secondary" sx={{ maxWidth: { xs: 120, md: "none" }, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{me.business_name}</Typography><IconButton aria-label="Sign out" onClick={onSignOut} sx={{ display: { md: "none" } }}><Logout fontSize="small" /></IconButton></Stack></Stack><Stack component="nav" aria-label="Mobile navigation" direction="row" gap={.5} sx={{ display: { xs: "grid", md: "none" }, gridTemplateColumns: "repeat(2, minmax(0, 1fr))", pt: 1.5 }}>{navButtons()}</Stack></Box>
      <Container component="main" id="main-content" tabIndex={-1} maxWidth="xl" sx={{ px: { xs: 2, md: 4 }, py: { xs: 3, md: 4 } }}>
        <Stack direction={{ xs: "column", sm: "row" }} justifyContent="space-between" alignItems={{ sm: "center" }} gap={2} sx={{ mb: 3.5 }}><Box><Typography variant="overline" color="text.secondary" sx={{ fontSize: 10, letterSpacing: ".12em" }}>QUOTE OPERATIONS</Typography><Typography variant="h1" sx={{ fontSize: { xs: 29, md: 35 }, mt: .5 }}>{headings[section][0]}</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>{headings[section][1]}</Typography></Box>{section === "quotes" && <Button variant="contained" startIcon={<Add />} onClick={() => addQuote()}>Add a quote</Button>}</Stack>
        {error && <Alert severity="error" onClose={() => setError("")} sx={{ mb: 2 }}>{error}</Alert>}{notice && <Alert severity="info" role="status" onClose={() => setNotice("")} sx={{ mb: 2 }}>{notice}</Alert>}
        {section === "quotes" && <Stack spacing={3}>
          {me.quota_remaining <= 2 && <Alert severity={me.quota_remaining === 0 ? "warning" : "info"} action={<Button color="inherit" onClick={() => navigate("settings")}>Manage usage</Button>}>{me.quota_remaining === 0 ? "Your parse allowance is used up. You can still check and export saved quotes." : `${me.quota_remaining} parses left. Each uploaded file or pasted quote uses one parse.`}</Alert>}
          <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: { xs: 1, sm: 2 } }}>{[["Recent quotes", inbox === null ? null : shown.length, "Uploads, Telegram, and email"], ["To check", inbox === null ? null : shown.length - checked, "Your next step before export"], ["Checked", inbox === null ? null : checked, "Ready to prepare for your client"]].map(([label, count, hint]) => <Paper key={label} sx={{ ...panel, p: { xs: 1.5, md: 3 }, py: { md: 2.3 } }}><Typography variant="body2" color="text.secondary" sx={{ fontSize: { xs: 12, sm: 14 } }}>{label}</Typography>{count === null ? <Skeleton width={60} height={48} /> : <Typography sx={{ fontSize: { xs: 26, sm: 32 }, fontWeight: 650, letterSpacing: "-.04em", my: .5 }}>{count}</Typography>}<Typography variant="caption" color="text.secondary" sx={{ display: { xs: "none", sm: "block" } }}>{hint}</Typography></Paper>)}</Box>
          {!!pack.records.length && <Paper sx={{ ...panel, bgcolor: "surface.blue", borderColor: "surface.blueBorder" }}><Stack direction={{ xs: "column", lg: "row" }} justifyContent="space-between" gap={2} alignItems={{ lg: "center" }}><Box><Typography variant="h2">Your current client pack</Typography><Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{packRecords.length - packUnchecked.length} of {packRecords.length} quotes checked. {packUnchecked.length ? "Check each quote before exporting the pack." : "All quotes checked. Your pack is ready to export."}</Typography></Box><Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>{packUnchecked.length ? <Button variant="contained" onClick={() => setSelected(packUnchecked[0])}>Check next quote <ArrowForward sx={{ ml: 1, fontSize: 16 }} /></Button> : <><Button variant="outlined" disabled={!!busy} onClick={() => exportPack("xlsx")}>Excel pack</Button><Button variant="contained" disabled={!!busy} startIcon={<DownloadOutlined />} onClick={() => exportPack("pdf")}>PDF pack</Button></>}</Stack></Stack></Paper>}
          <QuoteInbox inbox={inbox} shown={shown} visible={visible} error={inboxError} updatedAt={updatedAt} busy={!!busy} refresh={() => perform("refresh", () => refresh())} filter={filter} onFilter={setFilter} search={search} onSearch={setSearch} onOpen={setSelected} onAdd={() => addQuote()} onConnect={() => navigate("connections")} />
          <Typography variant="caption" color="text.secondary">Quote totals stay in their original currencies. Open a quote for its NGN cash estimate.</Typography>
        </Stack>}
        {section === "approvals" && <Approvals reviews={reviews} error={reviewsError} refresh={() => refresh()} busy={busy} confirm={setConfirmation} token={token} notify={setNotice} />}
        {["settings", "connections"].includes(section) && setupError && <Alert severity="error" action={<Button color="inherit" onClick={() => loadSetup()}>Retry</Button>} sx={{ mb: 2 }}>{setupError}</Alert>}
        {section === "connections" && <Connections token={token} company={company} perform={perform} busy={busy} notify={setNotice} onQuotes={() => navigate("quotes")} onAdd={() => addQuote()} />}
        {section === "settings" && <Settings key={`${company?.code}-${rates?.parallel_usd_ngn}`} token={token} me={me} company={company} rates={rates} perform={perform} busy={busy} notify={setNotice} onRateSaved={setRates} onRiskSaved={(value) => setCompany((current) => ({ ...current, port_risk: value }))} />}
      </Container>
    </Box>
    {intake && <IntakeDialog token={token} quota={me.quota_remaining} seed={seed} onClose={() => setIntake(false)} onCreated={onCreated} onSettings={() => { setIntake(false); navigate("settings"); }} />}
    {selected && <QuoteDialog key={selected.record_id} token={token} record={selected} onClose={() => setSelected(null)} onUpdate={updateRecord} onCorrect={(record) => { setSelected(null); addQuote(record.source_text || ""); }} onDelete={confirmDelete} />}
    <Dialog open={!!confirmation} onClose={busy ? undefined : () => setConfirmation(null)} fullWidth maxWidth="xs" aria-labelledby="confirmation-title"><DialogTitle id="confirmation-title">{confirmation?.title}</DialogTitle><DialogContent><Typography variant="body2">{confirmation?.description}</Typography></DialogContent><DialogActions sx={{ p: 2.5 }}><Button disabled={!!busy} onClick={() => setConfirmation(null)}>Cancel</Button><Button variant="contained" color={confirmation?.danger ? "error" : "primary"} disabled={!!busy} onClick={() => perform("confirm", async () => { await confirmation.action(); setConfirmation(null); })}>{busy === "confirm" ? "Saving…" : confirmation?.label}</Button></DialogActions>{error && <Alert severity="error" sx={{ mx: 3, mb: 2 }}>{error}</Alert>}</Dialog>
  </Box>;
}

export default function HomePage() {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const checkSession = useCallback(async () => {
    setLoading(true); setError("");
    const token = window.localStorage.getItem("quote_token");
    if (!token) { setLoading(false); return; }
    try { const user = await request(token, "/v1/me"); setSession({ ...user, token }); }
    catch (err) { if (err.status === 401) window.localStorage.removeItem("quote_token"); else setError(err.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { checkSession(); }, [checkSession]);
  if (loading || error) return <Container maxWidth="sm" sx={{ py: 12, textAlign: "center" }}>{loading ? <><CircularProgress size={28} /><Typography role="status" sx={{ mt: 2 }}>Opening your workspace…</Typography></> : <Alert severity="error" action={<Button color="inherit" onClick={checkSession}>Retry</Button>}>{error}</Alert>}</Container>;
  if (!session) return <Auth onSession={setSession} />;
  return <Workspace key={session.id} token={session.token} initialUser={session} onSignOut={() => { window.localStorage.removeItem("quote_token"); setSession(null); window.location.hash = ""; }} />;
}
