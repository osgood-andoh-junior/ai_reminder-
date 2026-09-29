export function XenonMark({
  size = 28,
  state = "idle",
}: {
  size?: number;
  state?: "idle" | "listening" | "thinking" | "speaking";
}) {
  return (
    <svg
      className={`xenon-mark ${state}`}
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M10 9C10 19 30 21 30 31M30 9C30 19 10 21 10 31"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <circle cx="20" cy="20" r="3" fill="currentColor" />
    </svg>
  );
}
