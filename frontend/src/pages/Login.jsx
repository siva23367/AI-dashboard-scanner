import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Satellite, ArrowRight } from "lucide-react";
import { useAuth } from "../AuthContext";
import { Button, inputClass } from "../components/ui";

export default function Login() {
  const { status, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  if (status === "in") return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message || "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-navy-700 via-navy-900 to-navy-950 px-4">
      <div className="w-full max-w-[380px]">
        <div className="flex flex-col items-center text-center mb-7">
          <div className="w-12 h-12 rounded-xl bg-signal-blue/20 border border-signal-blue/40 flex items-center justify-center mb-4">
            <Satellite size={22} className="text-signal-blue" />
          </div>
          <h1 className="font-display text-white text-[22px] font-semibold tracking-tight">Sriya Web Intelligence</h1>
          <p className="text-white/50 text-[13.5px] mt-1.5">Sign in to run scans, ingest dashboards &amp; research products</p>
        </div>

        <form onSubmit={submit} className="bg-white rounded-xl2 p-6 shadow-lift space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-[13px] rounded-lg px-3.5 py-2.5">
              {error}
            </div>
          )}
          <label className="block">
            <span className="block text-[13px] font-semibold text-ink mb-1.5">Username</span>
            <input
              className={inputClass}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              required
            />
          </label>
          <label className="block">
            <span className="block text-[13px] font-semibold text-ink mb-1.5">Password</span>
            <input
              type="password"
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"} <ArrowRight size={16} />
          </Button>
        </form>
      </div>
    </div>
  );
}
