// Distributor Failure scenario
interface DistributorSelectorProps {
  distributors: Array<{ id: number; name: string }>;
  selectedDistributorId: number | null;
  onSelect: (id: number) => void;
  onSimulate: () => void;
  loading: boolean;
}

export function DistributorSelector({
  distributors,
  selectedDistributorId,
  onSelect,
  onSimulate,
  loading,
}: DistributorSelectorProps) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <label className="text-slate-300 text-sm font-semibold">Select Distributor to Fail</label>
        <select
          value={selectedDistributorId ?? ""}
          onChange={(e) => onSelect(Number(e.target.value))}
          className="w-full mt-2 bg-slate-700 border border-slate-600 rounded px-4 py-2 text-white"
        >
          <option value="">Choose a distributor...</option>
          {distributors.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </div>
      <button
        onClick={onSimulate}
        disabled={!selectedDistributorId || loading}
        className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-2 rounded font-semibold text-white transition"
      >
        {loading ? "Simulating..." : "Simulate Failure"}
      </button>
    </div>
  );
}

// Geopolitical Risk scenario (slider)
interface GeopoliticalRiskSelectorProps {
  riskMultiplier: number;
  onRiskChange: (multiplier: number) => void;
  onSimulate: () => void;
  loading: boolean;
}

export function GeopoliticalRiskSelector({
  riskMultiplier,
  onRiskChange,
  onSimulate,
  loading,
}: GeopoliticalRiskSelectorProps) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <label className="text-slate-300 text-sm font-semibold">GPR Risk Multiplier: {riskMultiplier.toFixed(1)}x</label>
        <input
          type="range"
          min="0.5"
          max="5"
          step="0.5"
          value={riskMultiplier}
          onChange={(e) => onRiskChange(parseFloat(e.target.value))}
          className="w-full mt-2 cursor-pointer"
        />
        <div className="flex justify-between text-slate-500 text-xs mt-1">
          <span>0.5x (Low Risk)</span>
          <span>5.0x (Severe Crisis)</span>
        </div>
      </div>
      <button
        onClick={onSimulate}
        disabled={loading}
        className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-2 rounded font-semibold text-white transition"
      >
        {loading ? "Recalculating..." : "Update Risk Scenario"}
      </button>
    </div>
  );
}

// Delivery Target scenario (slider)
interface DeliveryTargetSelectorProps {
  targetDeliveryDays: number;
  onTargetChange: (days: number) => void;
  onSimulate: () => void;
  loading: boolean;
}

export function DeliveryTargetSelector({
  targetDeliveryDays,
  onTargetChange,
  onSimulate,
  loading,
}: DeliveryTargetSelectorProps) {
  return (
    <div className="flex flex-col gap-4">
      <div>
        <label className="text-slate-300 text-sm font-semibold">Target Delivery: {targetDeliveryDays} days</label>
        <input
          type="range"
          min="1"
          max="90"
          step="1"
          value={targetDeliveryDays}
          onChange={(e) => onTargetChange(Number(e.target.value))}
          className="w-full mt-2 cursor-pointer"
        />
        <div className="flex justify-between text-slate-500 text-xs mt-1">
          <span>1 day (Express)</span>
          <span>90 days (Standard)</span>
        </div>
      </div>
      <button
        onClick={onSimulate}
        disabled={loading}
        className="bg-blue-600 hover:bg-blue-700 disabled:bg-slate-700 disabled:text-slate-500 px-4 py-2 rounded font-semibold text-white transition"
      >
        {loading ? "Optimizing..." : "Simulate Delivery Target"}
      </button>
    </div>
  );
}
