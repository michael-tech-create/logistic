import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#174f46", dark: "#103a33", contrastText: "#fff" },
    secondary: { main: "#c66d2e" },
    background: { default: "#f5f6f3", paper: "#ffffff" },
    text: { primary: "#203731", secondary: "#61716b" },
    divider: "#e2e7e1",
    success: { main: "#276547" },
    warning: { main: "#945716" },
  },
  shape: { borderRadius: 10 },
  typography: {
    fontFamily: '"Segoe UI", Arial, sans-serif',
    h1: { fontSize: "2.2rem", fontWeight: 700, letterSpacing: "-.04em" },
    h2: { fontSize: "1.2rem", fontWeight: 700, letterSpacing: "-.02em" },
    h3: { fontSize: "1rem", fontWeight: 700 },
    h4: { fontWeight: 700 },
    h6: { fontSize: "1.05rem", fontWeight: 700 },
    button: { textTransform: "none", fontWeight: 650 },
    body2: { lineHeight: 1.65 },
  },
  components: {
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { minHeight: 42, borderRadius: 8 } } },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { outlined: { borderColor: "#e2e7e1" } } },
    MuiTableCell: { styleOverrides: { head: { backgroundColor: "#f7f8f5", color: "#61716b", fontWeight: 650, fontSize: 12 }, root: { borderColor: "#e9ece7" } } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600, borderRadius: 6 } } },
    MuiCssBaseline: { styleOverrides: { "a, button, input, textarea, [tabindex]": { scrollMarginTop: 24 }, "*:focus-visible": { outline: "3px solid #c66d2e", outlineOffset: 3 }, "@media (prefers-reduced-motion: reduce)": { "*, *::before, *::after": { animationDuration: "0.01ms !important", transitionDuration: "0.01ms !important" } } } },
  },
});

export default theme;
