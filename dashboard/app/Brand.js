import s from "./brand.module.css";

// One emblem and wordmark across the public site and every workspace entry.
export default function Brand({ subtitle, compact = false, large = false }) {
  return <a href="/" aria-label="Clearing Desk home" className={`${s.brand} ${compact ? s.compact : ""} ${large ? s.large : ""}`}>
    <img className={s.logo} src="/test-brand-log.png" width="60" height="60" alt="" decoding="async" />
    {!compact && <span className={s.text}><span className={s.wordmark}>clearing<span className={s.accent}>desk</span></span>{subtitle && <span className={s.subtitle}>{subtitle}</span>}</span>}
  </a>;
}
