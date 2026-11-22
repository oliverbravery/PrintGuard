export function DrawFailure() {
  return (
    <main role="alert" className="grid min-h-dvh place-items-center p-6 text-center">
      <div className="space-y-3">
        <p className="text-text-0">PrintGuard hit an error drawing this page.</p>
        <button className="btn btn-primary" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    </main>
  );
}
