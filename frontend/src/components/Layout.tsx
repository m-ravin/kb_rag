import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { LayoutDashboard, FileText, MessageSquare, LogOut } from "lucide-react";
import clsx from "clsx";

const navItems = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/documents", label: "Documents", icon: FileText },
  { to: "/qa-test", label: "Q&A Test", icon: MessageSquare },
];

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();

  const handleLogout = () => {
    localStorage.removeItem("access_token");
    navigate("/login");
  };

  return (
    <div className="flex h-screen bg-stone-50">
      {/* Sidebar */}
      <aside className="w-64 bg-stone-900 flex flex-col shrink-0">
        <div className="px-6 py-7 border-b border-white/10">
          <h1 className="font-display text-xl font-semibold text-white tracking-tight">
            kb-rag <span className="text-gold-400">CMS</span>
          </h1>
          <p className="text-xs text-stone-400 mt-1.5 tracking-wide">Knowledge Management</p>
        </div>
        <nav className="flex-1 px-3 py-6 space-y-1" data-testid="sidebar-nav">
          {navItems.map(({ to, label, icon: Icon }) => {
            const active = location.pathname.startsWith(to);
            return (
              <Link
                key={to}
                to={to}
                data-testid={`nav-${label.toLowerCase().replace(/[^a-z]/g, "-")}`}
                className={clsx(
                  "flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm font-medium transition-all border-l-2",
                  active
                    ? "bg-gold-400/10 text-gold-200 border-gold-400"
                    : "text-stone-400 border-transparent hover:bg-white/5 hover:text-stone-200"
                )}
              >
                <Icon size={17} strokeWidth={1.75} />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="p-3 border-t border-white/10">
          <button
            onClick={handleLogout}
            data-testid="logout-button"
            className="flex items-center gap-3 px-3.5 py-2.5 text-sm text-stone-400 hover:text-stone-100 w-full rounded-lg hover:bg-white/5 transition-colors"
          >
            <LogOut size={17} strokeWidth={1.75} />
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
