export function CairnMark({ size = 28 }: { size?: number }) {
  return (
    <svg className="mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <ellipse cx="16" cy="26" rx="12" ry="4.5" />
      <ellipse cx="16" cy="17.5" rx="8.5" ry="3.8" />
      <ellipse cx="16" cy="10" rx="5.5" ry="3.2" />
      <ellipse cx="16" cy="4.5" rx="3" ry="2.2" />
    </svg>
  );
}
