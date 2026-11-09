// The Rootline mark: a request line that drops to its root cause.
export function Mark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path d="M1 7h13v10h9" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="11" y="14" width="6" height="6" fill="var(--signal)" />
    </svg>
  );
}
