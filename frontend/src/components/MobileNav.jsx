import { useState } from "react";
import { NavLink } from "react-router-dom";
import { LayoutGrid, Link2, FileText, Search, Compass, Satellite, Menu, X, LogOut } from "lucide-react";
import { useAuth } from "../AuthContext";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/website", label: "Website Scan", icon: Link2 },
  { to: "/pdf", label: "Dashboard PDF", icon: FileText },
  { to: "/research", label: "Product Research", icon: Search },
  { to: "/ask", label: "Ask Your Dashboards", icon: Compass },
  { to: "/reports", label: "All Reports", icon: LayoutGrid },
];

export default function MobileNav() {
  const [open, setOpen] = useState(false);
  const { logout } = useAuth();

  return (
    <div className="md:hidden sticky top-0 z-40 bg-navy-900 text-white">
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Satellite size={18} className="text-signal-blue" />
          <span className="font-display font-semibold text-[15px]">Sriya</span>
        </div>
        <button onClick={() => setOpen((v) => !v)} aria-label="Menu">
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>
      {open && (
        <nav className="px-3 pb-3 space-y-1 border-t border-white/10 pt-2">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] font-medium ${
                  isActive ? "bg-signal-blue/15 text-white" : "text-white/70"
                }`
              }
            >
              <Icon size={17} /> {label}
            </NavLink>
          ))}
          <button
            onClick={() => {
              setOpen(false);
              logout();
            }}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-[13.5px] text-white/70"
          >
            <LogOut size={16} /> Log out
          </button>
        </nav>
      )}
    </div>
  );
}
