import { useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Divider,
  Grid,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import {
  ArrowRightAlt,
  CheckCircleOutline,
  DescriptionOutlined,
  LocalShippingOutlined,
  Refresh,
  WarningAmberOutlined,
} from '@mui/icons-material'

const sampleQuoteText = `Maersk Line Freight Quote - Ref # MSK-88291
Date: Sept 12, 2026. Valid until Oct 12, 2026.
POL: Shanghai Port (CNSHA) -> POD: Hamburg (DEHAM)
Cargo: 1x 40ft High Cube Container, 18,500 kg.
Transit Time: ~22 days.

Charges:
- Ocean Freight: $2,400.00
- BAF Surcharge: $350.00
- Origin Terminal Handling Charge (THC): $180.00
- Destination THC: $210.00
- Export Customs Filing: $75.00
Total Amount Due: USD 3,215.00
Terms: FOB Shanghai, Payment within 30 days.`

const money = (amount) => amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

function Field({ label, value, wide = false }) {
  return (
    <Box sx={{ minWidth: 0, gridColumn: wide ? 'span 2' : undefined }}>
      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', textTransform: 'uppercase', fontWeight: 750, mb: 0.25 }}>
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 650, color: value ? 'text.primary' : 'text.secondary' }}>
        {value || 'Not provided'}
      </Typography>
    </Box>
  )
}

function SectionTitle({ children, icon }) {
  return (
    <Stack direction="row" alignItems="center" spacing={0.8} sx={{ mb: 1.4 }}>
      {icon}
      <Typography variant="h2">{children}</Typography>
    </Stack>
  )
}

export default function App() {
  const [quoteText, setQuoteText] = useState(sampleQuoteText)
  const [result, setResult] = useState(null)
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)

  const normalize = async () => {
    setBusy(true)
    setError("")
    try {
      const response = await fetch("/api/normalize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: quoteText }),
      })
      const payload = await response.json()
      if (!response.ok) throw new Error(payload.error || "Normalize failed")
      setResult(payload)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Normalize failed")
    } finally {
      setBusy(false)
    }
  }


  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', color: 'text.primary' }}>
      <Box component="header" sx={{ height: 64, bgcolor: 'primary.dark', color: '#fff', px: { xs: 2, md: 4 }, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Box sx={{ width: 30, height: 30, borderRadius: 1, bgcolor: 'secondary.main', display: 'grid', placeItems: 'center' }}>
            <LocalShippingOutlined sx={{ fontSize: 19 }} />
          </Box>
          <Box>
            <Typography sx={{ fontSize: '0.94rem', fontWeight: 800, lineHeight: 1.1 }}>FreightOps</Typography>
            <Typography sx={{ fontSize: '0.65rem', color: 'rgba(255,255,255,.62)', letterSpacing: '.08em', textTransform: 'uppercase' }}>Quote normalizer</Typography>
          </Box>
        </Stack>
        <Chip label="REVIEW QUEUE  /  01" size="small" sx={{ color: '#dcecf5', bgcolor: 'rgba(255,255,255,.1)', fontWeight: 700, fontSize: '0.66rem' }} />
      </Box>

      <Box sx={{ px: { xs: 2, md: 4 }, py: 3, maxWidth: 1600, mx: 'auto' }}>
        <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'center' }} sx={{ mb: 2.5 }}>
          <Box>
            <Typography variant="h1">Freight quote review</Typography>
            <Typography variant="body2" sx={{ color: 'text.secondary', mt: 0.4 }}>Normalize an unstructured carrier quote into a reviewable shipment record.</Typography>
          </Box>
          <Stack direction="row" alignItems="center" spacing={0.8} sx={{ mt: { xs: 1.5, md: 0 } }}>
            <CheckCircleOutline sx={{ color: 'success.main', fontSize: 18 }} />
            <Typography variant="body2" sx={{ color: 'success.main', fontWeight: 700 }}>{result ? "Extraction ready for review" : "Paste a quote and normalize"}</Typography>
          </Stack>
        </Stack>

        <Grid container spacing={2.5} alignItems="flex-start">
          <Grid size={{ xs: 12, lg: 4 }}>
            <Paper sx={{ bgcolor: 'primary.main', color: '#fff', p: { xs: 2, md: 2.5 }, borderRadius: 1, position: { lg: 'sticky' }, top: { lg: 20 } }}>
              <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 0.5 }}>
                <DescriptionOutlined sx={{ color: '#f2a15e', fontSize: 20 }} />
                <Typography variant="h2" sx={{ color: '#fff' }}>Source quote</Typography>
              </Stack>
              <Typography variant="body2" sx={{ color: 'rgba(255,255,255,.65)', mb: 2 }}>Paste a carrier quote to normalize its commercial terms.</Typography>
              <TextField
                fullWidth
                multiline
                minRows={18}
                value={quoteText}
                onChange={(event) => setQuoteText(event.target.value)}
                aria-label="Source freight quote"
                sx={{ '& .MuiOutlinedInput-root': { alignItems: 'flex-start', bgcolor: '#082f46', color: '#e7f0f5', fontFamily: 'ui-monospace, SFMono-Regular, Consolas, monospace', fontSize: '0.78rem', lineHeight: 1.65 }, '& textarea': { padding: 0 }, '& fieldset': { borderColor: 'rgba(255,255,255,.18)' }, '& .MuiOutlinedInput-root:hover fieldset': { borderColor: 'rgba(255,255,255,.4)' } }}
              />
              <Button fullWidth disabled={busy} variant="contained" onClick={normalize} startIcon={<Refresh />} sx={{ mt: 1.5, bgcolor: 'secondary.main', '&:hover': { bgcolor: '#c96821' } }}>
                {busy ? "Normalizing…" : "Normalize quote"}
              </Button>
              <Typography variant="caption" sx={{ display: 'block', mt: 1.2, color: 'rgba(255,255,255,.5)', textAlign: 'center' }}>Runs the local quote parser</Typography>
            </Paper>
          </Grid>

          <Grid size={{ xs: 12, lg: 8 }}>
            {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}
            {!result ? <Paper sx={{ p: 3 }}><Typography>Normalized charges appear here after you run Normalize quote.</Typography></Paper> : (
            <Stack spacing={2}>
              <Card>
                <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                  <SectionTitle icon={<DescriptionOutlined sx={{ color: 'primary.main', fontSize: 19 }} />}>Quote metadata</SectionTitle>
                  <Grid container spacing={2}>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Vendor" value={result.quote_metadata.vendor_name} /></Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Reference" value={result.quote_metadata.quote_reference_id} /></Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Quote date" value={result.quote_metadata.quote_date} /></Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Valid until" value={result.quote_metadata.valid_until} /></Grid>
                  </Grid>
                </CardContent>
              </Card>

              <Card>
                <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                  <SectionTitle icon={<ArrowRightAlt sx={{ color: 'primary.main', fontSize: 22 }} />}>Shipment details</SectionTitle>
                  <Grid container spacing={2}>
                    <Grid size={{ xs: 12, md: 6 }}>
                      <Typography variant="caption" sx={{ textTransform: 'uppercase', color: 'text.secondary', fontWeight: 750 }}>Origin</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 750, mt: .25 }}>{result.shipment_details.origin.location_name} <Chip label={result.shipment_details.origin.port_code} size="small" sx={{ ml: .5, height: 20, fontSize: '.65rem', fontWeight: 800, bgcolor: '#e7f0f5', color: 'primary.main' }} /></Typography>
                      <Typography variant="caption" color="text.secondary">{result.shipment_details.origin.country}</Typography>
                    </Grid>
                    <Grid size={{ xs: 12, md: 6 }}>
                      <Typography variant="caption" sx={{ textTransform: 'uppercase', color: 'text.secondary', fontWeight: 750 }}>Destination</Typography>
                      <Typography variant="body2" sx={{ fontWeight: 750, mt: .25 }}>{result.shipment_details.destination.location_name} <Chip label={result.shipment_details.destination.port_code} size="small" sx={{ ml: .5, height: 20, fontSize: '.65rem', fontWeight: 800, bgcolor: '#e7f0f5', color: 'primary.main' }} /></Typography>
                      <Typography variant="caption" color="text.secondary">{result.shipment_details.destination.country}</Typography>
                    </Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Mode" value={result.shipment_details.transport_mode} /></Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Weight" value={`${(result.shipment_details.weight_kg ?? 0).toLocaleString()} kg`} /></Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Container" value={result.shipment_details.container_or_package_type} /></Grid>
                    <Grid size={{ xs: 6, sm: 3 }}><Field label="Transit" value={`${result.shipment_details.est_transit_days ?? "—"} days`} /></Grid>
                  </Grid>
                </CardContent>
              </Card>

              <Card>
                <CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}>
                  <SectionTitle icon={<LocalShippingOutlined sx={{ color: 'primary.main', fontSize: 19 }} />}>Charge breakdown</SectionTitle>
                  <TableContainer>
                    <Table size="small" aria-label="Freight quote line items">
                      <TableHead><TableRow sx={{ bgcolor: '#f5f8fa' }}><TableCell sx={{ fontWeight: 800, color: 'text.secondary', fontSize: '.67rem', textTransform: 'uppercase' }}>Description</TableCell><TableCell sx={{ fontWeight: 800, color: 'text.secondary', fontSize: '.67rem', textTransform: 'uppercase' }}>Category</TableCell><TableCell align="right" sx={{ fontWeight: 800, color: 'text.secondary', fontSize: '.67rem', textTransform: 'uppercase' }}>Amount (USD)</TableCell></TableRow></TableHead>
                      <TableBody>{result.financials.line_items.map((item) => <TableRow key={item.description}><TableCell sx={{ fontWeight: 650 }}>{item.description}</TableCell><TableCell><Chip label={item.category} size="small" variant="outlined" sx={{ height: 22, fontSize: '.67rem', borderColor: '#cbd8df' }} /></TableCell><TableCell align="right" sx={{ fontFamily: 'ui-monospace, monospace', fontWeight: 650 }}>{money(item.amount)}</TableCell></TableRow>)}</TableBody>
                    </Table>
                  </TableContainer>
                  <Divider sx={{ my: 1.5 }} />
                  <Stack direction="row" justifyContent="flex-end" alignItems="baseline" spacing={1.5}>
                    <Typography variant="body2" sx={{ color: 'text.secondary', fontWeight: 700 }}>RECONCILED TOTAL</Typography>
                    <Typography sx={{ color: 'primary.main', fontSize: '1.45rem', fontWeight: 800, fontFamily: 'ui-monospace, monospace' }}>{result.financials.currency} {money(result.financials.total_amount)}</Typography>
                  </Stack>
                </CardContent>
              </Card>

              <Grid container spacing={2}>
                <Grid size={{ xs: 12, md: 5 }}><Card sx={{ height: '100%' }}><CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}><SectionTitle>Terms</SectionTitle><Stack spacing={1.25}><Field label="Incoterms" value={result.terms_and_notes.incoterms} /><Field label="Payment terms" value={result.terms_and_notes.payment_terms} /></Stack></CardContent></Card></Grid>
                <Grid size={{ xs: 12, md: 7 }}><Card sx={{ height: '100%' }}><CardContent sx={{ p: 2.25, '&:last-child': { pb: 2.25 } }}><SectionTitle icon={<WarningAmberOutlined sx={{ color: 'warning.main', fontSize: 19 }} />}>Extraction flags</SectionTitle><Stack spacing={1}>{result.extraction_flags.map((flag) => <Alert key={flag} severity="info" variant="standard" sx={{ py: 0, px: 1, '& .MuiAlert-message': { fontSize: '.73rem', py: .65 } }}>{flag}</Alert>)}</Stack></CardContent></Card></Grid>
              </Grid>
            </Stack>
            )}
          </Grid>
        </Grid>
      </Box>
    </Box>
  )
}

