export default function Mark({ size = 48 }) {
  return (
    <svg width={size} height={size * 0.66} viewBox="0 0 72 48" aria-hidden="true">
      <path
        d="M4 40 C 18 38, 22 12, 40 14 C 52 15, 58 28, 68 22"
        fill="none"
        stroke="#E8A317"
        strokeWidth="3"
        strokeLinecap="round"
      />
      <circle cx="68" cy="22" r="3.2" fill="#E8A317" />
    </svg>
  );
}
