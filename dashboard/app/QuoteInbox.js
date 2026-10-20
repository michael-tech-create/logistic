"use client";

import { Alert, Avatar, Box, Button, Chip, InputAdornment, Paper, Skeleton, Stack, Tab, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tabs, TextField, Typography } from "@mui/material";
import { ArrowForward, DescriptionOutlined, Refresh, Search } from "@mui/icons-material";
import { Heading } from "./WorkspacePanels";
import { money, statusOf } from "./workflow.mjs";

function Route({ record }) {
  return <Box>
    <Typography variant="body2" sx={{ minWidth: 130 }}>
      {record.movement?.origin?.location_name || "Missing origin"}
      <Box component="span" color="text.secondary"> → </Box>
      {record.movement?.destination?.location_name || "Missing destination"}
    </Typography>
    <Typography variant="caption" color="text.secondary">{record.movement?.mode || "Mode not provided"}</Typography>
  </Box>;
}

export default function QuoteInbox({ inbox, shown, visible, error, updatedAt, busy, refresh, filter, onFilter, search, onSearch, onOpen, onAdd, onConnect }) {
  function nextAction(record) {
    const checked = statusOf(record).key === "reviewed";
    return <Button size="small" sx={{ whiteSpace: "nowrap" }} onClick={() => onOpen(record)} aria-label={`${checked ? "Open" : "Check"} quote from ${record.commercial?.vendor_name || "unknown vendor"}`}>
      {checked ? "Open quote" : "Check quote"}<ArrowForward sx={{ ml: 1, fontSize: 15 }} />
    </Button>;
  }
  return <Paper sx={{ border: 1, borderColor: "divider", overflow: "hidden" }}>
    <Box sx={{ p: { xs: 2, md: 3 }, pb: 0 }}>
      <Heading title="Quote inbox" description="Open a quote to check its shipment details, charges, and currency estimates." action={<Button size="small" startIcon={<Refresh />} onClick={refresh} disabled={busy}>Refresh</Button>} />
      <Stack direction={{ xs: "column", lg: "row" }} justifyContent="space-between" gap={2} alignItems={{ lg: "center" }}>
        <Tabs value={filter} onChange={(_, value) => onFilter(value)} aria-label="Filter quotes" variant="fullWidth" sx={{ width: { xs: "100%", lg: 370 } }}>
          <Tab value="all" label={`All${inbox === null ? "" : ` (${shown.length})`}`} />
          <Tab value="unchecked" label="To check" />
          <Tab value="reviewed" label="Checked" />
        </Tabs>
        <TextField size="small" label="Search quotes" value={search} onChange={(event) => onSearch(event.target.value)} slotProps={{ input: { startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> } }} sx={{ minWidth: { lg: 250 }, mb: { xs: 2, lg: 1 } }} />
      </Stack>
    </Box>
    {error && <Alert severity="warning" action={<Button color="inherit" onClick={refresh}>Retry</Button>} sx={{ mx: 2, my: 2 }}>{error} {inbox !== null && "Showing the last quotes received."}</Alert>}
    {inbox === null ? <Box sx={{ p: 3 }}>
      {error ? <Typography variant="body2">Your inbox could not be loaded. Use Retry to reconnect.</Typography> : <Box role="status" aria-label="Loading quote inbox"><Skeleton height={60} /><Skeleton height={60} /><Skeleton height={60} /></Box>}
    </Box> : !shown.length ? <Box sx={{ px: 3, py: 7, textAlign: "center" }}>
      <Avatar variant="rounded" sx={{ mx: "auto", mb: 2, bgcolor: "surface.blue", color: "primary.main", width: 52, height: 52 }}><DescriptionOutlined /></Avatar>
      <Typography variant="h2">Your next shipment starts here</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 1, mb: 3, maxWidth: 370, mx: "auto" }}>Add a carrier quote to see its route, charges, and cash estimate in one place.</Typography>
      <Stack direction="row" justifyContent="center" spacing={1} useFlexGap flexWrap="wrap"><Button variant="contained" onClick={onAdd}>Add your first quote</Button><Button onClick={onConnect}>Connect Telegram</Button></Stack>
    </Box> : !visible.length ? <Box sx={{ p: 5, textAlign: "center" }}>
      <Typography variant="h3">No matching quotes</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ my: 1 }}>Try another vendor, reference, or route, or clear the filters.</Typography>
      <Button onClick={() => { onSearch(""); onFilter("all"); }}>Clear filters</Button>
    </Box> : <>
      <Stack sx={{ display: { xs: "flex", lg: "none" } }}>
        {visible.map((record, index) => {
          const status = statusOf(record);
          return <Box key={record.record_id || index} sx={{ p: 2, borderTop: 1, borderColor: "divider" }}>
            <Stack direction="row" justifyContent="space-between" gap={1} sx={{ mb: 1.5 }}>
              <Box sx={{ minWidth: 0 }}><Typography variant="body2" fontWeight={650}>{record.commercial?.vendor_name || "Vendor not provided"}</Typography><Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>{record.commercial?.quote_reference_id || record.source_file || "No reference"}</Typography></Box>
              <Chip size="small" variant="outlined" color={status.color} label={status.label} />
            </Stack>
            <Route record={record} />
            <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1} sx={{ mt: 1.5 }}>
              <Typography variant="body2" fontWeight={650}>{money(record.commercial?.currency, record.commercial?.total_amount)}</Typography>
              {nextAction(record)}
            </Stack>
          </Box>;
        })}
      </Stack>
      <TableContainer sx={{ display: { xs: "none", lg: "block" } }}>
        <Table aria-label="Freight quote inbox">
          <TableHead><TableRow><TableCell>Carrier / reference</TableCell><TableCell>Route</TableCell><TableCell>Status</TableCell><TableCell align="right">Quoted total</TableCell><TableCell align="right">Next step</TableCell></TableRow></TableHead>
          <TableBody>{visible.map((record, index) => {
            const status = statusOf(record);
            return <TableRow key={record.record_id || index} hover>
              <TableCell><Typography variant="body2" fontWeight={650}>{record.commercial?.vendor_name || "Vendor not provided"}</Typography><Typography variant="caption" color="text.secondary">{record.commercial?.quote_reference_id || record.source_file || "No reference"}</Typography></TableCell>
              <TableCell><Route record={record} /></TableCell>
              <TableCell><Chip size="small" variant="outlined" color={status.color} label={status.label} /></TableCell>
              <TableCell align="right" sx={{ whiteSpace: "nowrap", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>{money(record.commercial?.currency, record.commercial?.total_amount)}</TableCell>
              <TableCell align="right">{nextAction(record)}</TableCell>
            </TableRow>;
          })}</TableBody>
        </Table>
      </TableContainer>
    </>}
    <Stack direction="row" justifyContent="space-between" gap={1} sx={{ px: { xs: 2, md: 3 }, py: 1.5, borderTop: 1, borderColor: "divider" }}>
      <Typography variant="caption" color="text.secondary">{inbox === null ? "Connecting to your inbox" : `${visible.length} recent quote${visible.length === 1 ? "" : "s"} shown`}</Typography>
      <Typography variant="caption" color="text.secondary" role="status">{error ? "Updates paused" : updatedAt ? `Updated ${updatedAt}` : "Loading…"}</Typography>
    </Stack>
  </Paper>;
}
