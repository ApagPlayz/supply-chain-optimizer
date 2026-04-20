import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import { useCartStore } from './store/cartStore';
import NavBar from './components/NavBar';
import { Login } from './pages/Login';
import Register from './pages/Register';
import { Dashboard } from './pages/Dashboard';
import MapPage from './pages/MapPage';
import SchedulerPage from './pages/SchedulerPage';
import CartPage from './pages/CartPage';
import CheckoutPage from './pages/CheckoutPage';
import DigitalTwinPage from './pages/DigitalTwinPage';
import BenchmarkPage from './pages/BenchmarkPage';
import './index.css';

function ProtectedLayout() {
  const { isAuthenticated } = useAuthStore();
  const { fetchCart } = useCartStore();

  useEffect(() => {
    if (isAuthenticated) fetchCart();
  }, [isAuthenticated]);

  if (!isAuthenticated) return <Navigate to="/login" replace />;

  return (
    <div className="flex flex-col h-screen">
      <NavBar />
      <div className="flex-1 overflow-hidden">
        <Outlet />
      </div>
    </div>
  );
}

function App() {
  const { initializeAuth } = useAuthStore();

  useEffect(() => {
    initializeAuth();
  }, []);

  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/map" element={<MapPage />} />
          <Route path="/scheduler" element={<SchedulerPage />} />
          <Route path="/cart" element={<CartPage />} />
          <Route path="/checkout" element={<CheckoutPage />} />
          <Route path="/benchmark" element={<BenchmarkPage />} />
          <Route path="/digital-twin" element={<DigitalTwinPage />} />
        </Route>
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
