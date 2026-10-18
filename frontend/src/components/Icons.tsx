// Drawn interface icons (Round 9): one 16-unit grid, 1.75 stroke, round caps, currentColor. Always next to a word.
type P = { size?: number };

function Svg({ size = 16, children }: P & { children: React.ReactNode }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export const SunIcon = (p: P) => (
  <Svg {...p}>
    <circle cx="8" cy="8" r="2.8" />
    <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" />
  </Svg>
);
export const MoonIcon = (p: P) => (
  <Svg {...p}>
    <path d="M13.2 9.6A5.6 5.6 0 0 1 6.4 2.8a5.6 5.6 0 1 0 6.8 6.8z" />
  </Svg>
);
export const PlayIcon = (p: P) => (
  <Svg {...p}>
    <path d="M5 3.2v9.6L12.6 8z" fill="currentColor" />
  </Svg>
);
export const PauseIcon = (p: P) => (
  <Svg {...p}>
    <path d="M5.2 3.2v9.6M10.8 3.2v9.6" strokeWidth="2.4" />
  </Svg>
);
export const SendIcon = (p: P) => (
  <Svg {...p}>
    <path d="M14.2 1.8 1.8 7.1l4.9 1.9 1.9 4.9z" />
    <path d="M6.7 9 14.2 1.8" />
  </Svg>
);
export const LogIcon = (p: P) => (
  <Svg {...p}>
    <rect x="3" y="2" width="10" height="12" rx="1.5" />
    <path d="M5.6 5.5h4.8M5.6 8h4.8M5.6 10.5h2.8" />
  </Svg>
);
export const WarnIcon = (p: P) => (
  <Svg {...p}>
    <path d="M8 1.8 14.6 13.6H1.4z" />
    <path d="M8 6.2v3.3M8 11.6v.2" />
  </Svg>
);
export const ArrowIcon = ({ dir = "right", ...p }: P & { dir?: "left" | "right" }) => (
  <Svg {...p}>
    <path d={dir === "left" ? "M13 8H3M7 4 3 8l4 4" : "M3 8h10M9 4l4 4-4 4"} />
  </Svg>
);
