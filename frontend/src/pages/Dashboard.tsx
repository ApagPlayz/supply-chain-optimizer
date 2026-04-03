import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export const Dashboard = () => {
  const navigate = useNavigate();
  const { isAuthenticated, user, logout } = useAuthStore();

  useEffect(() => {
    if (!isAuthenticated) {
      navigate('/login');
    }
  }, [isAuthenticated, navigate]);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-8">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-4xl font-bold text-white mb-2">Supply Chain Dashboard</h1>
            <p className="text-slate-400">Welcome back, {user?.factory_name}</p>
          </div>
          <button
            onClick={handleLogout}
            className="px-6 py-2 bg-red-600 hover:bg-red-700 text-white font-medium rounded-lg transition"
          >
            Logout
          </button>
        </div>

        {/* Navigation Tabs */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 hover:border-blue-500 cursor-pointer transition">
            <h3 className="text-white font-semibold mb-2">Map</h3>
            <p className="text-slate-400 text-sm">View production hubs and suppliers</p>
          </div>
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 hover:border-blue-500 cursor-pointer transition">
            <h3 className="text-white font-semibold mb-2">Scheduler</h3>
            <p className="text-slate-400 text-sm">Material insights & forecasts</p>
          </div>
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 hover:border-blue-500 cursor-pointer transition">
            <h3 className="text-white font-semibold mb-2">Cart</h3>
            <p className="text-slate-400 text-sm">Manage your orders</p>
          </div>
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700 hover:border-blue-500 cursor-pointer transition">
            <h3 className="text-white font-semibold mb-2">Checkout</h3>
            <p className="text-slate-400 text-sm">Route optimization</p>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 gap-6">
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
            <h3 className="text-slate-400 text-sm font-medium mb-2">Factory Location</h3>
            <p className="text-2xl font-bold text-white">
              {user?.latitude?.toFixed(2)}, {user?.longitude?.toFixed(2)}
            </p>
          </div>
          <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
            <h3 className="text-slate-400 text-sm font-medium mb-2">Active Orders</h3>
            <p className="text-2xl font-bold text-white">0</p>
          </div>
        </div>
      </div>
    </div>
  );
};
