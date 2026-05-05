import { useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';
import { useCartStore } from '../store/cartStore';

const NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', icon: '⬡' },
  { path: '/map', label: 'Map', icon: '🗺' },
  { path: '/benchmark', label: 'Benchmark', icon: '📈' },
  { path: '/scheduler', label: 'Scheduler', icon: '📊' },
  { path: '/resilience', label: 'Resilience', icon: '🛡️' },
  { path: '/cart', label: 'Cart', icon: '🛒' },
  { path: '/checkout', label: 'Optimize', icon: '🚀' },
  { path: '/digital-twin', label: 'Digital Twin', icon: '🔬' },
];

export default function NavBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();
  const { items } = useCartStore();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <nav className="bg-slate-900 border-b border-slate-700 px-4 py-0 flex items-center h-12 shrink-0 z-20">
      {/* Brand */}
      <button
        onClick={() => navigate('/dashboard')}
        className="text-white font-bold text-sm mr-6 whitespace-nowrap hover:text-blue-400 transition-colors"
      >
        SupplyChain<span className="text-blue-400">IQ</span>
      </button>

      {/* Nav links */}
      <div className="flex items-center gap-1 flex-1">
        {NAV_ITEMS.map(({ path, label, icon }) => {
          const active = location.pathname === path;
          const isCart = path === '/cart';
          return (
            <button
              key={path}
              onClick={() => navigate(path)}
              className={`relative flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                active
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/60'
              }`}
            >
              <span>{icon}</span>
              {label}
              {isCart && items.length > 0 && (
                <span className="absolute -top-1 -right-1 bg-blue-500 text-white text-[10px] font-bold rounded-full w-4 h-4 flex items-center justify-center leading-none">
                  {items.length}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* User / logout */}
      {user && (
        <div className="flex items-center gap-3 ml-4">
          <span className="text-slate-400 text-xs truncate max-w-[140px]">{user.factory_name}</span>
          <button
            onClick={handleLogout}
            className="text-xs text-slate-500 hover:text-white transition-colors"
          >
            Logout
          </button>
        </div>
      )}
    </nav>
  );
}
