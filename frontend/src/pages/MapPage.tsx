import { useEffect, useState, useCallback, useMemo, useRef } from 'react';
import Map, {
  Marker,
  NavigationControl,
  Source,
  Layer,
  type MapLayerMouseEvent,
  type MapRef,
} from 'react-map-gl/maplibre';
import type { LineLayerSpecification } from 'maplibre-gl';
import { ArcLayer } from '@deck.gl/layers';
import { hubsAPI } from '../services/api';
import { useAuthStore } from '../store/authStore';
import { useOptimizeStore } from '../store/optimizeStore';
import RouteMetricsBar from '../components/map/RouteMetricsBar';
import MapLegendFilter, { HUB_TYPE_META } from '../components/map/MapLegendFilter';
import HubDetailSidebar from '../components/map/HubDetailSidebar';
import RouteLegPopup, { type RouteLegData } from '../components/map/RouteLegPopup';
import RouteTimeline from '../components/map/RouteTimeline';
import DeckGLOverlay from '../components/map/DeckGLOverlay';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Route, ChevronDown } from 'lucide-react';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const INITIAL_VIEW = {
  longitude: -88,
  latitude: 37,
  zoom: 4.5,
  pitch: 0,
  bearing: 0,
};

interface Hub {
  id: number;
  name: string;
  city: string;
  state: string;
  latitude: number;
  longitude: number;
  hub_type: string;
  specialization: string;
  active_suppliers: number;
  risk_index: number;
  suppliers?: Supplier[];
}

interface Supplier {
  id: number;
  name: string;
  lead_time_days: number;
  reliability_score: number;
  risk_score: number;
  is_domestic: boolean;
}

interface RoadPath {
  coordinates: [number, number][];
  stopIndex: number;
}

function riskTierId(r: number) {
  if (r < 0.25) return 'low';
  if (r < 0.5)  return 'moderate';
  if (r < 0.75) return 'high';
  return 'critical';
}

async function fetchRoadPath(
  from: [number, number],
  to: [number, number],
): Promise<[number, number][]> {
  try {
    const url =
      `https://router.project-osrm.org/route/v1/driving/` +
      `${from[0]},${from[1]};${to[0]},${to[1]}` +
      `?overview=full&geometries=geojson`;
    const res = await fetch(url, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) throw new Error('OSRM non-200');
    const data = await res.json();
    const coords: [number, number][] | undefined =
      data?.routes?.[0]?.geometry?.coordinates;
    if (coords && coords.length > 1) return coords;
  } catch {
    // fall through to straight line
  }
  return [from, to];
}

function buildRouteGeoJSON(paths: RoadPath[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: paths.map((p) => ({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: p.coordinates },
      properties: { stopIndex: p.stopIndex, isReturn: p.stopIndex < 0 },
    })),
  };
}

const routeForwardPaint = {
  'line-color': '#3b82f6',
  'line-width': ['interpolate', ['linear'], ['zoom'], 4, 2, 10, 5, 16, 9],
  'line-opacity': 0.9,
} as any;
const routeReturnPaint = {
  'line-color': '#64748b',
  'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1, 10, 3, 16, 5],
  'line-opacity': 0.5,
} as any;
const routeForwardLayout: LineLayerSpecification['layout'] = {
  'line-cap': 'round',
  'line-join': 'round',
};

const STRATEGY_COLORS: Record<string, string> = {
  cheapest: '#22c55e',
  fastest: '#3b82f6',
  greenest: '#10b981',
  balanced: '#a855f7',
};

const RISK_ARC_COLORS: Record<string, [number, number, number, number]> = {
  low: [34, 197, 94, 180],           // green-500
  moderate: [234, 179, 8, 180],      // yellow-500
  high: [249, 115, 22, 180],         // orange-500
  critical: [239, 68, 68, 180],      // red-500
};

export default function MapPage() {
  const { user } = useAuthStore();
  const { multiResult, selectedId, setSelectedId, getSelected } = useOptimizeStore();
  const selectedRoute = getSelected();
  const mapRef = useRef<MapRef>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);

  const [hubs, setHubs]               = useState<Hub[]>([]);
  const [selectedHub, setSelectedHub] = useState<Hub | null>(null);
  const [hubDetail, setHubDetail]     = useState<Hub | null>(null);
  const [loading, setLoading]         = useState(true);
  const [hubSidebarOpen, setHubSidebarOpen] = useState(false);
  const [timelineOpen, setTimelineOpen]     = useState(false);
  const [viewState, setViewState]     = useState(INITIAL_VIEW);
  const [showRoutes, setShowRoutes]   = useState(true);
  const [showArcs, setShowArcs]       = useState(false);

  const [roadPaths, setRoadPaths]       = useState<RoadPath[]>([]);
  const [routeLoading, setRouteLoading] = useState(false);

  const [legPopup, setLegPopup] = useState<{
    data: RouteLegData;
    position: { x: number; y: number };
  } | null>(null);

  const [hoveredHubId, setHoveredHubId] = useState<number | null>(null);
  const [routeDropdownOpen, setRouteDropdownOpen] = useState(false);

  const [activeHubTypes, setActiveHubTypes] = useState<Set<string>>(
    () => new Set(Object.keys(HUB_TYPE_META))
  );
  const [activeRiskTiers, setActiveRiskTiers] = useState<Set<string>>(
    () => new Set(['low', 'moderate', 'high', 'critical'])
  );

  useEffect(() => {
    hubsAPI.list().then((res) => {
      setHubs(res.data);
      setLoading(false);
    });
  }, []);

  // Fetch OSRM road geometry for selected route
  useEffect(() => {
    if (!selectedRoute?.route || !user) {
      setRoadPaths([]);
      return;
    }

    let cancelled = false;
    setRouteLoading(true);

    const legs: { from: [number, number]; to: [number, number]; stopIndex: number }[] = [];
    let prev: [number, number] = [user.longitude, user.latitude];
    for (let i = 0; i < selectedRoute.route.length; i++) {
      const stop = selectedRoute.route[i];
      legs.push({ from: prev, to: [stop.lng, stop.lat], stopIndex: i });
      prev = [stop.lng, stop.lat];
    }
    legs.push({ from: prev, to: [user.longitude, user.latitude], stopIndex: -1 });

    Promise.all(
      legs.map((leg) =>
        fetchRoadPath(leg.from, leg.to).then((coords) => ({
          coordinates: coords,
          stopIndex: leg.stopIndex,
        }))
      )
    ).then((results) => {
      if (!cancelled) {
        setRoadPaths(results);
        setRouteLoading(false);
      }
    });

    return () => { cancelled = true; };
  }, [selectedRoute, user]);

  const handleHubClick = useCallback(async (hub: Hub) => {
    setSelectedHub(hub);
    setHubDetail(null);
    setHubSidebarOpen(true);
    setTimelineOpen(false);
    const res = await hubsAPI.get(hub.id);
    setHubDetail(res.data);
  }, []);

  const handleHubTypeToggle = useCallback((id: string) => {
    setActiveHubTypes((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const handleRiskTierToggle = useCallback((id: string) => {
    setActiveRiskTiers((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }, []);

  const visibleHubs = useMemo(
    () =>
      hubs.filter(
        (h) =>
          activeHubTypes.has(h.hub_type) &&
          activeRiskTiers.has(riskTierId(h.risk_index))
      ),
    [hubs, activeHubTypes, activeRiskTiers]
  );

  const hubArcData = useMemo(() => {
    if (!user || !showArcs) return [];
    return visibleHubs.map((hub) => ({
      source: [user.longitude, user.latitude] as [number, number],
      target: [hub.longitude, hub.latitude] as [number, number],
      risk: riskTierId(hub.risk_index),
      width: Math.max(1, Math.min(8, hub.active_suppliers / 5)),
    }));
  }, [visibleHubs, user, showArcs]);

  const routeGeoJSON = useMemo(() => buildRouteGeoJSON(roadPaths), [roadPaths]);

  const forwardGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: 'FeatureCollection',
    features: routeGeoJSON.features.filter(
      (f) => (f.properties as { isReturn: boolean }).isReturn === false
    ),
  }), [routeGeoJSON]);

  const returnGeoJSON = useMemo<GeoJSON.FeatureCollection>(() => ({
    type: 'FeatureCollection',
    features: routeGeoJSON.features.filter(
      (f) => (f.properties as { isReturn: boolean }).isReturn === true
    ),
  }), [routeGeoJSON]);

  const handleMapClick = useCallback(
    (e: MapLayerMouseEvent) => {
      const features = e.features;
      if (!features || features.length === 0) {
        setLegPopup(null);
        return;
      }
      const feature = features[0];
      const stopIndex: number = feature.properties?.stopIndex ?? -1;
      if (stopIndex < 0 || !selectedRoute) return;
      const stop = selectedRoute.route[stopIndex];
      setLegPopup({
        data: {
          supplierName:  stop.supplier_name,
          city:          stop.city,
          state:         stop.state,
          legCostUsd:    stop.leg_cost_usd,
          legCo2eKg:     stop.leg_co2e_kg,
          distanceKm:    stop.distance_km,
          materialNames: stop.material_names,
          legIndex:      stopIndex + 1,
          totalLegs:     selectedRoute.route.length,
        },
        position: { x: e.point.x, y: e.point.y },
      });
    },
    [selectedRoute]
  );

  const handleFlyTo = useCallback((lat: number, lng: number) => {
    mapRef.current?.flyTo({ center: [lng, lat], zoom: 9, duration: 1000 });
  }, []);

  const alternatives = multiResult?.alternatives ?? [];

  return (
    <div ref={mapContainerRef} className="flex h-full bg-slate-900 text-slate-100 relative overflow-hidden">
      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/80">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
              <span className="text-blue-400 text-sm">Loading supply chain map...</span>
            </div>
          </div>
        )}

        {routeLoading && (
          <div className="absolute top-16 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 bg-slate-900/90 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-300 pointer-events-none">
            <div className="w-3 h-3 rounded-full border border-blue-500 border-t-transparent animate-spin" />
            Fetching road routes...
          </div>
        )}

        <Map
          ref={mapRef}
          {...viewState}
          onMove={(e) => setViewState(e.viewState)}
          mapStyle={MAP_STYLE}
          maxBounds={[[-130, 20], [-60, 55]]}
          attributionControl={false}
          style={{ width: '100%', height: '100%' }}
          interactiveLayerIds={showRoutes && roadPaths.length ? ['route-forward'] : []}
          onClick={handleMapClick}
          cursor="grab"
        >
          <NavigationControl position="top-right" />

          {showRoutes && roadPaths.length > 0 && (
            <>
              <Source id="route-return" type="geojson" data={returnGeoJSON}>
                <Layer
                  id="route-return"
                  type="line"
                  paint={routeReturnPaint}
                  layout={routeForwardLayout}
                />
              </Source>

              <Source id="route-forward" type="geojson" data={forwardGeoJSON}>
                <Layer
                  id="route-forward-hit"
                  type="line"
                  paint={{ 'line-color': 'transparent', 'line-width': 20 }}
                  layout={routeForwardLayout}
                />
                <Layer
                  id="route-forward"
                  type="line"
                  paint={{
                    ...routeForwardPaint,
                    'line-color': STRATEGY_COLORS[selectedId ?? 'balanced'] ?? '#3b82f6',
                  }}
                  layout={routeForwardLayout}
                />
              </Source>
            </>
          )}

          {visibleHubs.map((hub) => (
            <Marker
              key={hub.id}
              longitude={hub.longitude}
              latitude={hub.latitude}
              anchor="center"
              onClick={(e) => {
                e.originalEvent.stopPropagation();
                handleHubClick(hub);
              }}
            >
              <div
                className="relative group cursor-pointer"
                onMouseEnter={() => setHoveredHubId(hub.id)}
                onMouseLeave={() => setHoveredHubId(null)}
              >
                <div
                  className={`rounded-full border-2 border-white/20 transition-all duration-150 shadow-md ${
                    hoveredHubId === hub.id ? 'scale-[2.2] border-white/70' : ''
                  }`}
                  style={{
                    width: 12,
                    height: 12,
                    backgroundColor: HUB_TYPE_META[hub.hub_type]?.color ?? '#64748b',
                  }}
                />
                {hoveredHubId === hub.id && (
                  <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-slate-800/95 text-white text-xs px-2 py-0.5 rounded whitespace-nowrap pointer-events-none z-50 border border-slate-600 shadow-lg">
                    {hub.city}, {hub.state}
                  </div>
                )}
              </div>
            </Marker>
          ))}

          {user && (
            <Marker longitude={user.longitude} latitude={user.latitude} anchor="bottom">
              <div className="relative cursor-pointer group" title={user.factory_name}>
                <div className="w-5 h-5 rounded-full bg-white border-4 border-blue-500 shadow-lg shadow-blue-500/50 group-hover:scale-125 transition-transform" />
                <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-blue-600 text-white text-xs px-2 py-0.5 rounded whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
                  {user.factory_name}
                </div>
              </div>
            </Marker>
          )}

          {showArcs && hubArcData.length > 0 && (
            <DeckGLOverlay
              layers={[
                new ArcLayer({
                  id: 'hub-arcs',
                  data: hubArcData,
                  getSourcePosition: (d: typeof hubArcData[0]) => d.source,
                  getTargetPosition: (d: typeof hubArcData[0]) => d.target,
                  getSourceColor: (d: typeof hubArcData[0]) => RISK_ARC_COLORS[d.risk],
                  getTargetColor: (d: typeof hubArcData[0]) => RISK_ARC_COLORS[d.risk],
                  getWidth: (d: typeof hubArcData[0]) => d.width,
                  getTilt: 15,
                  pickable: false,
                }),
              ]}
            />
          )}
        </Map>

        {selectedRoute && (
          <RouteMetricsBar
            totalCostUsd={selectedRoute.total_cost_usd}
            totalCo2eKg={selectedRoute.total_co2e_kg}
            etaP50={selectedRoute.eta_p50}
            stopCount={selectedRoute.route.length}
          />
        )}

        {/* Route strategy switcher */}
        {alternatives.length > 0 && (
          <div className="absolute top-4 left-4 z-10 pointer-events-auto">
            <div className="relative">
              <button
                onClick={() => setRouteDropdownOpen((v) => !v)}
                className="flex items-center gap-2 bg-black/60 backdrop-blur-lg border border-white/10 rounded-lg px-3 py-2 text-xs font-medium text-white hover:bg-black/70 transition-colors"
              >
                <div
                  className="w-2.5 h-2.5 rounded-full"
                  style={{ backgroundColor: STRATEGY_COLORS[selectedId ?? 'balanced'] }}
                />
                {selectedRoute?.label ?? 'Select Route'}
                <ChevronDown className={`w-3 h-3 transition-transform ${routeDropdownOpen ? 'rotate-180' : ''}`} />
              </button>

              {routeDropdownOpen && (
                <div className="absolute top-full left-0 mt-1 w-72 bg-slate-900/95 backdrop-blur-lg border border-slate-700 rounded-lg shadow-2xl overflow-hidden">
                  {alternatives.map((alt) => {
                    const isActive = alt.id === selectedId;
                    return (
                      <button
                        key={alt.id}
                        onClick={() => { setSelectedId(alt.id); setRouteDropdownOpen(false); }}
                        className={`w-full flex items-start gap-3 px-3 py-2.5 text-left transition-colors ${
                          isActive ? 'bg-blue-500/10' : 'hover:bg-slate-800'
                        }`}
                      >
                        <div
                          className="w-2.5 h-2.5 rounded-full mt-1 shrink-0"
                          style={{ backgroundColor: STRATEGY_COLORS[alt.id] }}
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className={`text-xs font-semibold ${isActive ? 'text-white' : 'text-slate-300'}`}>
                              {alt.label}
                            </span>
                            {multiResult?.recommended_id === alt.id && (
                              <span className="text-[9px] text-purple-400 bg-purple-400/10 px-1.5 py-0.5 rounded font-medium">REC</span>
                            )}
                          </div>
                          <div className="flex items-center gap-3 mt-0.5 text-[10px] text-slate-500">
                            <span>${alt.total_cost_usd.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                            <span>{alt.eta_p50}d ETA</span>
                            <span>{alt.total_co2e_kg.toFixed(1)} kg CO2</span>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}

        {selectedRoute && (
          <button
            onClick={() => {
              setTimelineOpen((v) => !v);
              setHubSidebarOpen(false);
            }}
            className={`absolute top-4 right-14 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all pointer-events-auto border ${
              timelineOpen
                ? 'bg-blue-600 text-white border-blue-500'
                : 'bg-slate-800/90 text-slate-300 border-slate-700 hover:bg-slate-700'
            }`}
          >
            <Route className="w-3.5 h-3.5" />
            Route Stops
          </button>
        )}

        <MapLegendFilter
          activeHubTypes={activeHubTypes}
          activeRiskTiers={activeRiskTiers}
          onHubTypeToggle={handleHubTypeToggle}
          onRiskTierToggle={handleRiskTierToggle}
          showArcs={showRoutes}
          onToggleArcs={() => setShowRoutes((v) => !v)}
          showDeckArcs={showArcs}
          onToggleDeckArcs={() => setShowArcs((v) => !v)}
          hasRoute={!!selectedRoute}
          hasFactory={!!user}
        />

        <RouteLegPopup
          data={legPopup?.data ?? null}
          position={legPopup?.position ?? { x: 0, y: 0 }}
          onClose={() => setLegPopup(null)}
          containerRef={mapContainerRef}
        />
      </div>

      <HubDetailSidebar
        hub={selectedHub}
        hubDetail={hubDetail}
        open={hubSidebarOpen}
        onClose={() => setHubSidebarOpen(false)}
      />

      {selectedRoute && (
        <RouteTimeline
          route={selectedRoute.route}
          totalCost={selectedRoute.total_cost_usd}
          totalCo2={selectedRoute.total_co2e_kg}
          etaP50={selectedRoute.eta_p50}
          open={timelineOpen}
          onClose={() => setTimelineOpen(false)}
          onFlyTo={handleFlyTo}
        />
      )}
    </div>
  );
}
