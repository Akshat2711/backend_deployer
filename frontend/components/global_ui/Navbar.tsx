type NavbarProps = {
  userEmail: string;
  onNewDeployment: () => void;
  onSignOut: () => void;
};

export default function Navbar({
  userEmail,
  onNewDeployment,
  onSignOut,
}: NavbarProps) {
  return (
    <header className="border-b border-zinc-200 ">
      <div className="flex w-full flex-col gap-4 px-6 py-5 sm:flex-row sm:items-center sm:justify-between">

        <div className="flex items-center gap-3">
          <img
            src="/assets/logo.gif"
            alt="CloudTurtle Logo"
            className="h-14 w-14 object-contain"
          />

          <div>
            <p className="font-mono text-xs font-semibold uppercase tracking-widest text-zinc-400">
              CloudTurtle
            </p>

            <h1 className="mt-0.5 text-xl font-bold tracking-tight text-zinc-900">
              Deployment Console
            </h1>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="rounded-md bg-zinc-100 px-3 py-1.5 font-mono text-xs text-zinc-600">
            {userEmail}
          </span>

          <button
            onClick={onNewDeployment}
            className="h-9 rounded-md bg-cyan-700 px-4 text-xs font-semibold text-white shadow-sm transition hover:!bg-white hover:!text-black"
          >
            + New Deployment
          </button>

          <button
            onClick={onSignOut}
            className="h-9 rounded-md border border-zinc-200 bg-white px-4 text-xs font-semibold text-zinc-700 transition hover:!bg-red-500 hover:!text-white"
          >
            Sign Out
          </button>
        </div>
      </div>
    </header>
  );
}