import { useEffect, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

type HealthStatus = "loading" | "connected" | "disconnected";

function App() {
  const [status, setStatus] = useState<HealthStatus>("loading");
  const [dbStatus, setDbStatus] = useState<string>("");

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((res) => res.json())
      .then((data) => {
        setStatus(data.status === "ok" ? "connected" : "disconnected");
        setDbStatus(data.database);
      })
      .catch(() => {
        setStatus("disconnected");
        setDbStatus("unreachable");
      });
  }, []);

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 flex flex-col items-center justify-center gap-8">
      <h1 className="text-4xl font-bold tracking-tight">setflow</h1>

      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center gap-2">
          <span
            className={`h-3 w-3 rounded-full ${
              status === "loading"
                ? "bg-zinc-500 animate-pulse"
                : status === "connected"
                  ? "bg-emerald-500"
                  : "bg-red-500"
            }`}
          />
          <span className="text-sm text-zinc-400">
            {status === "loading"
              ? "Checking backend..."
              : status === "connected"
                ? "Backend connected"
                : "Backend disconnected"}
          </span>
        </div>

        {dbStatus && (
          <span className="text-xs text-zinc-500">database: {dbStatus}</span>
        )}
      </div>
    </div>
  );
}

export default App;
