import { createTheme } from '@mui/material/styles'

const theme = createTheme({
  palette: {
    primary: {
      main: '#0b3954',
      dark: '#082b40',
      light: '#1c5878',
      contrastText: '#ffffff',
    },
    secondary: {
      main: '#e07a2d',
      contrastText: '#ffffff',
    },
    background: {
      default: '#f3f6f8',
      paper: '#ffffff',
    },
    text: {
      primary: '#17232d',
      secondary: '#61717d',
    },
    divider: '#dce4e9',
    warning: { main: '#b86b11' },
    info: { main: '#1976a8' },
    success: { main: '#2f7d5a' },
  },
  typography: {
    fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    h1: { fontSize: '1.35rem', fontWeight: 750, letterSpacing: '-0.02em' },
    h2: { fontSize: '0.98rem', fontWeight: 750 },
    body1: { fontSize: '0.84rem' },
    body2: { fontSize: '0.76rem' },
    caption: { fontSize: '0.68rem', letterSpacing: '0.04em' },
    button: { fontWeight: 700, textTransform: 'none' },
  },
  shape: { borderRadius: 5 },
  components: {
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { borderRadius: 4, minHeight: 36 } },
    },
    MuiCard: {
      styleOverrides: { root: { border: '1px solid #dce4e9', boxShadow: '0 1px 2px rgba(23,35,45,0.04)' } },
    },
    MuiOutlinedInput: {
      styleOverrides: { root: { borderRadius: 4 } },
    },
  },
})

export default theme
export { theme }
