export function Progress({ value, total, className = "" }: { value: number; total: number; className?: string }) {
  return (
    <div
      className={`flex items-center gap-3 ${className}`}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={total}
    >
      <div aria-hidden className="h-1.5 flex-1 overflow-hidden rounded-full bg-accent/25">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-500"
          style={{ width: `${(value / total) * 100}%` }}
        />
      </div>
      <span className="label whitespace-nowrap">
        {value} of {total}
      </span>
    </div>
  );
}
