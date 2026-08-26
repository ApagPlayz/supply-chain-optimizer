import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { useCartStore } from '../store/cartStore';

// Labels describe what the page actually contains, and each path is the page's own
// canonical route. Previously "Scheduler" pointed at a component browser (nothing is
// scheduled) and "Optimize" pointed at /checkout.
interface NavItem {
  path: string;
  label: string;
  icon: string;
  /** Legacy paths that should still light this tab up. */
  aliases?: string[];
}

const NAV_ITEMS: NavItem[] = [
  { path: '/dashboard', label: 'Dashboard', icon: '⬡' },
  { path: '/map', label: 'Map', icon: '🗺' },
  { path: '/benchmark', label: 'Benchmark', icon: '📈' },
  { path: '/components', label: 'Components', icon: '📊', aliases: ['/scheduler'] },
  { path: '/resilience', label: 'Resilience', icon: '🛡️' },
  { path: '/frontier', label: 'Frontier', icon: '📉' },
  { path: '/cart', label: 'Cart', icon: '🛒' },
  { path: '/optimize', label: 'Optimize', icon: '🚀', aliases: ['/checkout'] },
  { path: '/model-card', label: 'Model Card', icon: '🧠' },
];

export default function NavBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { items } = useCartStore();
  // Below `xl` the 9-item link row plus brand, user and build stamp don't fit any
  // viewport down to phone width — they used to just overflow the nav (and drag the
  // whole page into horizontal scroll with them, since nothing shrinks a flex row
  // whose items default to min-width:auto). Collapse into a hamburger instead.
  const [menuOpen, setMenuOpen] = useState(false);
  // Close the mobile menu on any route change, including browser back/forward
  // (which skip the `go()` helper below). Adjusting state during render — rather
  // than in a useEffect — is the pattern React recommends for resetting state in
  // response to a prop/route change; it avoids an extra render pass.
  const [menuOpenForPath, setMenuOpenForPath] = useState(location.pathname);
  if (menuOpenForPath !== location.pathname) {
    setMenuOpenForPath(location.pathname);
    if (menuOpen) setMenuOpen(false);
  }

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const go = (path: string) => {
    navigate(path);
    setMenuOpen(false);
  };

  const renderNavButton = (
    { path, label, icon, aliases }: NavItem,
    variant: 'desktop' | 'mobile'
  ) => {
    const active = location.pathname === path || (aliases?.includes(location.pathname) ?? false);
    const isCart = path === '/cart';
    const badge = isCart && items.length > 0;
    return (
      <button
        key={path}
        onClick={() => go(path)}
        className={
          variant === 'desktop'
            ? `relative flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                active
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
              }`
            : `flex items-center gap-2 px-3 py-2.5 rounded text-sm font-medium transition-colors ${
                active
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
              }`
        }
      >
        <span>{icon}</span>
        {label}
        {badge && (
          <span
            className={
              variant === 'desktop'
                ? 'absolute -top-1 -right-1 bg-blue-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none'
                : 'ml-auto bg-blue-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none'
            }
          >
            {items.length}
          </span>
        )}
      </button>
    );
  };

  return (
    <nav className="relative bg-slate-900 border-b border-slate-700 px-4 py-0 flex items-center h-12 shrink-0 z-20">
      {/* Brand */}
      <button
        onClick={() => go('/dashboard')}
        className="text-white font-bold text-sm mr-6 whitespace-nowrap hover:text-blue-400 transition-colors"
      >
        SupplyChain<span className="text-blue-400">IQ</span>
      </button>

      {/* Nav links — full row, only once there's room for all of them */}
      <div className="hidden xl:flex items-center gap-1 flex-1">
        {NAV_ITEMS.map((item) => renderNavButton(item, 'desktop'))}
      </div>
      {/* Below xl, the links move into the hamburger menu; this spacer keeps the
          hamburger, build stamp pinned to the right the way flex-1 does above. */}
      <div className="flex-1 xl:hidden" />

      {/* User / logout */}
      {user && (
        <div className="hidden xl:flex items-center gap-3 ml-4">
          <span className="text-slate-400 text-xs truncate max-w-[140px]">
            {user.factory_name || user.email}
          </span>
          <button
            onClick={handleLogout}
            className="text-xs text-slate-500 hover:text-white transition-colors"
          >
            Logout
          </button>
        </div>
      )}

      {/* Build stamp — confirms which deploy you're looking at */}
      <span
        className="ml-3 text-[10px] text-slate-600 whitespace-nowrap font-mono hidden sm:inline"
        title={`Built ${new Date(__BUILD_TIME__).toLocaleString()}`}
      >
        build {__BUILD_COMMIT__.slice(0, 7)}
      </span>

      {/* Hamburger — shown below xl instead of the link row */}
      <button
        onClick={() => setMenuOpen((open) => !open)}
        className="xl:hidden ml-3 w-8 h-8 flex items-center justify-center rounded text-slate-400 hover:text-white hover:bg-slate-700/60 transition-colors shrink-0"
        aria-label={menuOpen ? 'Close navigation menu' : 'Open navigation menu'}
        aria-expanded={menuOpen}
      >
        {menuOpen ? '✕' : '☰'}
      </button>

      {/* Mobile/tablet menu */}
      {menuOpen && (
        <div className="xl:hidden absolute top-full left-0 right-0 bg-slate-900 border-b border-slate-700 shadow-2xl z-50 max-h-[calc(100vh-3rem)] overflow-y-auto">
          <div className="flex flex-col p-2 gap-1">
            {NAV_ITEMS.map((item) => renderNavButton(item, 'mobile'))}
          </div>
          {user && (
            <div className="border-t border-slate-700 px-3 py-2.5 flex items-center justify-between gap-3">
              <span className="text-slate-400 text-xs truncate">
                {user.factory_name || user.email}
              </span>
              <button
                onClick={handleLogout}
                className="text-xs text-slate-500 hover:text-white transition-colors shrink-0"
              >
                Logout
              </button>
            </div>
          )}
        </div>
      )}
    </nav>
  );
}
