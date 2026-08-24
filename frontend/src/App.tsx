import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import { useCartStore } from './store/cartStore';
import NavBar from './components/NavBar';
import ErrorBoundary from './components/ErrorBoundary';
import { Login } from './pages/Login';
import Register from './pages/Register';
import { Dashboard } from './pages/Dashboard';
import MapPage from './pages/MapPage';
import SchedulerPage from './pages/SchedulerPage';
import CartPage from './pages/CartPage';
import CheckoutPage from './pages/CheckoutPage';
import BenchmarkPage from './pages/BenchmarkPage';
import ResiliencePage from './pages/ResiliencePage';
import ModelCardPage from './pages/ModelCardPage';
import FrontierPage from './pages/FrontierPage';
import NotFoundPage from './pages/NotFoundPage';
import './index.css';

/** Shown while the stored session cookie is being validated against /auth/me. */
function AuthSplash() {
  return (
    <div className="h-screen w-screen bg-slate-900 flex items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="w-8 h-8 border-2 border-slate-700 border-t-blue-500 rounded-full animate-spin" />
        <span className="text-slate-500 text-sm">Restoring session…</span>
      </div>
    </div>
  );
}

function ProtectedLayout() {
  const { isAuthenticated, authResolved } = useAuthStore();
  const { fetchCart } = useCartStore();
  const location = useLocation();

  useEffect(() => {
    if (isAuthenticated) fetchCart();
  }, [isAuthenticated]);

  // Until initializeAuth() has resolved we know NOTHING about the session. Rendering
  // <Navigate to="/login"> here is what dumped logged-in users at the login screen on
  // every refresh and deep link — the redirect fired before the cookie was ever read.
  if (!authResolved) return <AuthSplash />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;

  return (
    <div className="flex flex-col h-screen">
      <NavBar />
      <div className="flex-1 overflow-hidden">
        {/* Per-page boundary: a crash in one page keeps the nav usable, and
            navigating elsewhere resets it via the pathname resetKey. */}
        <ErrorBoundary scope="This page" resetKey={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </div>
    </div>
  );
}

/** Login/Register shouldn't be reachable once a session is already restored. */
function PublicOnly({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, authResolved } = useAuthStore();
  if (!authResolved) return <AuthSplash />;
  if (isAuthenticated) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

function App() {
  const { initializeAuth } = useAuthStore();

  useEffect(() => {
    initializeAuth();
  }, []);

  return (
    // Root boundary: the last line of defence. Anything the per-page boundary
    // cannot catch (nav bar, router, layout) lands here instead of a white screen.
    <ErrorBoundary scope="The app">
      <Router>
        <Routes>
          <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
          <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
          <Route element={<ProtectedLayout />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/map" element={<MapPage />} />
            {/* Canonical paths now match the nav labels and the page content.
                The old paths stay mounted so existing links keep working. */}
            <Route path="/components" element={<SchedulerPage />} />
            <Route path="/scheduler" element={<SchedulerPage />} />
            <Route path="/cart" element={<CartPage />} />
            <Route path="/optimize" element={<CheckoutPage />} />
            <Route path="/checkout" element={<CheckoutPage />} />
            <Route path="/benchmark" element={<BenchmarkPage />} />
            <Route path="/resilience" element={<ResiliencePage />} />
            <Route path="/frontier" element={<FrontierPage />} />
            <Route path="/model-card" element={<ModelCardPage />} />
            {/* A real 404 rather than the old silent <Navigate to="/dashboard">.
                Redirecting an unknown URL to the dashboard makes a typo, a stale
                bookmark and a genuinely broken link all look identical — and all
                look like success. It lives INSIDE the protected layout so it keeps
                the nav bar; a logged-out visitor still lands on /login first, the
                same as every other route here. */}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
          {/* /digital-twin removed: the page called a legacy "simplified" endpoint,
              did no re-optimization, and rendered fields the API never returned.
              Resilience covers the same ground with real Monte Carlo + CVaR. */}
          <Route path="/digital-twin" element={<Navigate to="/resilience" replace />} />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Router>
    </ErrorBoundary>
  );
}

export default App;
