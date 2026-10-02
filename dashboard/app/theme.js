import { createTheme } from "@mui/material/styles";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#0b3954" },
    secondary: { main: "#e07a2f" },
    background: { default: "#eef3f6", paper: "#ffffff" },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: "Inter, Segoe UI, sans-serif",
    h4: { fontWeight: 750 },
    h6: { fontWeight: 700 },
  },
});

export default theme;
