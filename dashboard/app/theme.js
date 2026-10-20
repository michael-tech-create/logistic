import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#2269d8", dark: "#1759bf", contrastText: "#ffffff" },
    secondary: { main: "#5c65b7" },
    background: { default: "#fcfcfa", paper: "#ffffff" },
    text: { primary: "#1d2836", secondary: "#596575" },
    divider: "#dce3e8",
    success: { main: "#247260" },
    warning: { main: "#8a5a12" },
    info: { main: "#1266ba" },
    action: { selected: "#eaf2fb", hover: "#f3f7fb" },
    // Neutral and blue surfaces match the public homepage without tinting
    // success/warning statuses, which retain their semantic colors.
    surface: { soft: "#f4f7f9", blue: "#eef5fc", blueBorder: "#cedeee", muted: "#e6edf4", warning: "#fff4df" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Segoe UI", Arial, sans-serif',
    h1: { fontSize: "2.2rem", fontWeight: 500, letterSpacing: "-.04em" },
    h2: { fontSize: "1.2rem", fontWeight: 500, letterSpacing: "-.02em" },
    h3: { fontSize: "1rem", fontWeight: 500 },
    h4: { fontWeight: 500, letterSpacing: "-.035em" },
    h6: { fontSize: "1.05rem", fontWeight: 500 },
    button: { textTransform: "none", fontWeight: 500 },
    body2: { lineHeight: 1.65 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { minHeight: 42, borderRadius: 8 } } },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { outlined: { borderColor: "#dce3e8" } } },
    MuiOutlinedInput: { styleOverrides: { root: { backgroundColor: "#ffffff" }, notchedOutline: { borderColor: "#c8d5e0" } } },
    MuiTableCell: { styleOverrides: { head: { backgroundColor: "#f4f7f9", color: "#596575", fontWeight: 600, fontSize: 12 }, root: { borderColor: "#e6edf1" } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 500, borderRadius: 6 } } },
    MuiCssBaseline: { styleOverrides: { "a, button, input, textarea, [tabindex]": { scrollMarginTop: 24 }, "*:focus-visible": { outline: "3px solid #2269d8", outlineOffset: 3 }, "@media (prefers-reduced-motion: reduce)": { "*, *::before, *::after": { animationDuration: "0.01ms !important", transitionDuration: "0.01ms !important" } } } },
  },
});

export default theme;
