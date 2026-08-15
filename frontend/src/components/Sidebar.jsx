import { NavLink } from "react-router-dom";
import { LayoutGrid, Link2, FileText, Search, Compass, Satellite, LogOut } from "lucide-react";
import { useAuth } from "../AuthContext";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/website", label: "Website Scan", icon: Link2 },
  { to: "/pdf", label: "Dashboard PDF", icon: FileText },
  { to: "/research", label: "Product Research", icon: Search },
  { to: "/ask", label: "Ask Your Dashboards", icon: Compass },
  { to: "/reports", label: "All Reports", icon: LayoutGrid },
];

export default function Sidebar() {
  const { username, logout } = useAuth();

  return (
    <aside className="hidden md:flex md:flex-col w-64 shrink-0 bg-navy-900 text-white min-h-screen sticky top-0">
      <div className="px-5 pt-6 pb-5 flex items-center gap-2.5 border-b border-white/10">
        <div className="w-9 h-9 rounded-lg bg-signal-blue/20 border border-signal-blue/40 flex items-center justify-center">
          <Satellite size={18} className="text-signal-blue" strokeWidth={2.2} />
        </div>
        <div>
          <div className="font-display font-semibold text-[15px] leading-tight">Sriya</div>
          <div className="text-[11px] text-white/50 leading-tight">Web Intelligence</div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] font-medium transition-colors ${
                isActive
                  ? "bg-signal-blue/15 text-white border border-signal-blue/30"
                  : "text-white/65 hover:text-white hover:bg-white/5 border border-transparent"
              }`
            }
          >
            <Icon size={17} strokeWidth={2} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-4 border-t border-white/10">
        <div className="flex items-center gap-2 mb-3 text-[12.5px] text-white/60">
          <span className="live-dot animate-pulseDot" />
          Signed in as <span className="text-white/90 font-medium">{username}</span>
        </div>
        <button
          onClick={logout}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-[13px] text-white/70 hover:text-white hover:bg-white/5 transition-colors"
        >
          <LogOut size={15} /> Log out
        </button>
      </div>
    </aside>
  );
}
