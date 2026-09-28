export function LoadingState({ label = "Loading your workspace…" }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <span>{label}</span>
      <div aria-hidden="true">
        <i />
        <i />
        <i />
      </div>
    </div>
  );
}
