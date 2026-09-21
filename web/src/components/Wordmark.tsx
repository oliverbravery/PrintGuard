export function Wordmark({ size = "text-xl" }: { size?: string }) {
  return (
    <span className={`display font-bold ${size} leading-none select-none`}>
      PRINT<span className="text-accent">/</span>GUARD
    </span>
  );
}
