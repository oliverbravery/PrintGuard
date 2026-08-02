export function BugIcon({ className = "h-[1.15em] w-[1.15em]" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path d="M9.5 3.5 11 5.5M14.5 3.5 13 5.5" />
      <rect x="7" y="5.5" width="10" height="15" rx="5" />
      <path d="M12 9v11" />
      <path d="M7 9.5 3 7.5M7 13H3M7 16.5 3 18.5" />
      <path d="m17 9.5 4-2M17 13h4M17 16.5l4 2" />
    </svg>
  );
}
