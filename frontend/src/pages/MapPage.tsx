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
import { distributorsAPI, getCrossDockHubs, type HubOut, graphAPI, benchmarkAPI } from '../services/api';
import { useAuthStore } from '../store/authStore';
import { useOptimizeStore } from '../store/optimizeStore';
import RouteMetricsBar from '../components/map/RouteMetricsBar';
import RouteLegPopup, { type RouteLegData } from '../components/map/RouteLegPopup';
import RouteTimeline from '../components/map/RouteTimeline';
import DistributorSearchBar from '../components/map/DistributorSearchBar';
import { RISK_COLORS, riskLabel } from '../lib/risk';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Route, ChevronDown, Globe, MapPin, X, Search, Package, Tag } from 'lucide-react';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

const INITIAL_VIEW = {
  longitude: -40,
  latitude: 30,
  zoom: 2.5,
  pitch: 0,
  bearing: 0,
};

interface DistributorPin {
  id: number;
  name: string;
  city: string | null;
  state: string | null;
  country: string;
  latitude: number;
  longitude: number;
  is_domestic: boolean;
  total_offers: number;
  total_stock: number;
}

interface RoadPath {
  coordinates: [number, number][];
  stopIndex: number;
}

// Network Risk view interfaces
interface GraphMetricsResponse {
  n_distributors: number;
  n_components: number;
  n_edges: number;
  fiedler: number;
  single_source_count: number;
  betweenness: Record<string, number>;
  pagerank: Record<string, number>;
  k_core_summary: Record<string, number>;
  hhi_by_category: Record<string, number>;
}

interface SingleSourceComponent {
  component_id: number;
  mpn: string;
  manufacturer: string;
  distributor_id: number;
  distributor_name: string;
}

interface HeatmapPoint {
  lat: number;
  lng: number;
  weight: number;
  distributor_id: number;
  distributor_name: string;
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
  'line-width': ['interpolate', ['linear'], ['zoom'], 2, 1.5, 6, 3, 10, 5],
  'line-opacity': 0.9,
} as any;
const routeReturnPaint = {
  'line-color': '#64748b',
  'line-width': ['interpolate', ['linear'], ['zoom'], 2, 1, 6, 2, 10, 3],
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

export default function MapPage() {
  const { user } = useAuthStore();
  const { multiResult, selectedId, setSelectedId, getSelected } = useOptimizeStore();
  const selectedRoute = getSelected();
  const mapRef = useRef<MapRef>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);

  const [distributors, setDistributors] = useState<DistributorPin[]>([]);
  const [hubs, setHubs] = useState<HubOut[]>([]);
  const [selectedDist, setSelectedDist] = useState<DistributorPin | null>(null);
  const [loading, setLoading] = useState(true);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [viewState, setViewState] = useState(INITIAL_VIEW);
  const [showRoutes, setShowRoutes] = useState(true);
  const [showDomesticOnly, setShowDomesticOnly] = useState(false);

  const [roadPaths, setRoadPaths] = useState<RoadPath[]>([]);
  const [routeLoading, setRouteLoading] = useState(false);

  const [legPopup, setLegPopup] = useState<{
    data: RouteLegData;
    position: { x: number; y: number };
  } | null>(null);

  const [hoveredDistId, setHoveredDistId] = useState<number | null>(null);
  const [routeDropdownOpen, setRouteDropdownOpen] = useState(false);

  const [distDetail, setDistDetail] = useState<{
    top_components: {
      component_id: number;
      mpn: string;
      manufacturer: string;
      category: string;
      price: number;
      stock: number;
      sku: string;
    }[];
  } | null>(null);
  const [distDetailLoading, setDistDetailLoading] = useState(false);
  const [componentSearch, setComponentSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState<string>('');

  // Network Risk view state
  const [mapView, setMapView] = useState<'routes' | 'network-risk'>('routes');
  const [graphMetrics, setGraphMetrics] = useState<GraphMetricsResponse | null>(null);
  const [singleSourceComponents, setSingleSourceComponents] = useState<SingleSourceComponent[]>([]);
  const [singleSourceDistributorIds, setSingleSourceDistributorIds] = useState<Set<number>>(new Set());
  const [showNetworkRiskPanel, setShowNetworkRiskPanel] = useState(false);
  const [cascadeActive, setCascadeActive] = useState(false);
  const [cascadeHeatmapData, setCascadeHeatmapData] = useState<HeatmapPoint[]>([]);

  useEffect(() => {
    distributorsAPI.list().then((res) => {
      setDistributors(res.data);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    getCrossDockHubs().then(setHubs).catch(() => setHubs([]));
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

  // Fetch distributor detail (with component offerings) when sidebar opens
  useEffect(() => {
    if (!selectedDist) {
      setDistDetail(null);
      setComponentSearch('');
      setCategoryFilter('');
      return;
    }
    setDistDetailLoading(true);
    distributorsAPI.get(selectedDist.id).then((res) => {
      setDistDetail(res.data);
      setDistDetailLoading(false);
    }).catch(() => setDistDetailLoading(false));
  }, [selectedDist]);

  // Fetch graph metrics AND single-source components when switching to Network Risk view
  useEffect(() => {
    if (mapView !== 'network-risk') return;

    // Fetch betweenness/pagerank metrics for marker sizing
    if (!graphMetrics) {
      graphAPI.metrics()
        .then((res) => setGraphMetrics(res.data))
        .catch(() => {
          // Silent fail — Network Risk view shows unsized markers on API error
        });
    }

    // Fetch real single-source component list from /benchmark/single-source-components
    // This is the authoritative source — never use betweenness threshold as a proxy.
    if (singleSourceComponents.length === 0) {
      benchmarkAPI.singleSourceComponents()
        .then((res) => {
          const components: SingleSourceComponent[] = res.data.components ?? [];
          setSingleSourceComponents(components);
          // Build the set of distributor IDs that are sole sources
          // Used to determine which markers get the red halo
          setSingleSourceDistributorIds(
            new Set(components.map((c) => c.distributor_id))
          );
        })
        .catch(() => {
          // Silent fail — side panel shows empty state; no halos shown
        });
    }
  }, [mapView]); // eslint-disable-line react-hooks/exhaustive-deps

  // Cascade heatmap fetch
  useEffect(() => {
    if (!cascadeActive) return;
    if (cascadeHeatmapData.length > 0) return; // already loaded
    benchmarkAPI.cascadeHeatmap()
      .then((res) => setCascadeHeatmapData(res.data.points))
      .catch(() => {
        // Silent fail — show nothing when cascade data unavailable
      });
  }, [cascadeActive]); // eslint-disable-line react-hooks/exhaustive-deps

  const visibleDistributors = useMemo(
    () => showDomesticOnly ? distributors.filter((d) => d.is_domestic) : distributors,
    [distributors, showDomesticOnly]
  );

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
          distributorName: stop.distributor_name,
          city:            stop.city,
          state:           stop.state,
          country:         stop.country,
          legCostUsd:      stop.leg_cost_usd,
          legCo2eKg:       stop.leg_co2e_kg,
          distanceKm:      stop.distance_km,
          components:      stop.components,
          legIndex:        stopIndex + 1,
          totalLegs:       selectedRoute.route.length,
        },
        position: { x: e.point.x, y: e.point.y },
      });
    },
    [selectedRoute]
  );

  const handleFlyTo = useCallback((lat: number, lng: number) => {
    mapRef.current?.flyTo({ center: [lng, lat], zoom: 9, duration: 1000 });
  }, []);

  const handleSearchSelect = useCallback((dist: DistributorPin) => {
    mapRef.current?.flyTo({ center: [dist.longitude, dist.latitude], zoom: 9, duration: 1000 });
    setSelectedDist(dist);
  }, []);

  const alternatives = multiResult?.alternatives ?? [];

  const domesticCount = distributors.filter((d) => d.is_domestic).length;
  const internationalCount = distributors.length - domesticCount;

  return (
    <div ref={mapContainerRef} className="flex h-full bg-slate-900 text-slate-100 relative overflow-hidden">
      <div className="flex-1 relative">
        {loading && (
          <div className="absolute inset-0 z-30 flex items-center justify-center bg-slate-900/80">
            <div className="flex flex-col items-center gap-3">
              <div className="w-8 h-8 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
              <span className="text-blue-400 text-sm">Loading distributor network...</span>
            </div>
          </div>
        )}

        {/* Distributor search bar — top center */}
        {!loading && (
          <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 w-full max-w-sm px-4 pointer-events-auto">
            <DistributorSearchBar distributors={visibleDistributors} onSelect={handleSearchSelect} />
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

          {/* Cascade heatmap layer — only in Network Risk view when cascade toggle is active */}
          {cascadeActive && cascadeHeatmapData.length > 0 && (
            <Source
              id="cascade-heatmap-source"
              type="geojson"
              data={{
                type: 'FeatureCollection',
                features: cascadeHeatmapData.map((pt) => ({
                  type: 'Feature',
                  geometry: { type: 'Point', coordinates: [pt.lng, pt.lat] },
                  properties: { weight: pt.weight },
                })),
              }}
            >
              <Layer
                id="cascade-heatmap"
                type="heatmap"
                paint={{
                  'heatmap-weight': ['interpolate', ['linear'], ['get', 'weight'], 0, 0, 1, 1],
                  'heatmap-intensity': 1.5,
                  'heatmap-radius': 40,
                  'heatmap-opacity': 0.7,
                  'heatmap-color': [
                    'interpolate', ['linear'], ['heatmap-density'],
                    0,    '#440154',
                    0.25, '#3b528b',
                    0.5,  '#21918c',
                    0.75, '#5ec962',
                    1,    '#fde725',
                  ],
                } as any}
              />
            </Source>
          )}

          {visibleDistributors.map((dist) => {
            if (mapView === 'network-risk') {
              // Network Risk view — betweenness sizing + risk-tier color
              const btw = graphMetrics ? (graphMetrics.betweenness[String(dist.id)] ?? 0) : 0;
              const pxSize = Math.max(6, Math.min(22, 6 + btw * 16));
              const riskTier = riskLabel(btw); // betweenness as risk proxy
              const markerColor = RISK_COLORS[riskTier];
              // Sole-source halo: derived from real API data — distributor appears in
              // /benchmark/single-source-components response. NOT a betweenness threshold.
              const isSingleSource = singleSourceDistributorIds.has(dist.id);
              const singleSourceCount = singleSourceComponents.filter(
                (c) => c.distributor_id === dist.id
              ).length;
              return (
                <Marker key={`nr-${dist.id}`} longitude={dist.longitude} latitude={dist.latitude} anchor="center">
                  <div className="relative" style={{ width: pxSize, height: pxSize }}>
                    <div
                      onClick={() => setShowNetworkRiskPanel(true)}
                      title={`${dist.name} — betweenness: ${(btw * 100).toFixed(1)}%${isSingleSource ? ` · sole source of ${singleSourceCount} component${singleSourceCount !== 1 ? 's' : ''}` : ''}`}
                      aria-label={`${dist.name}${isSingleSource ? `, sole source of ${singleSourceCount} single-source component${singleSourceCount !== 1 ? 's' : ''}, highest risk` : ''}`}
                      role="button"
                      tabIndex={0}
                      style={{
                        width: pxSize,
                        height: pxSize,
                        backgroundColor: markerColor,
                        borderRadius: '50%',
                        border: '2px solid rgba(255,255,255,0.2)',
                        cursor: 'pointer',
                      }}
                      className="hover:scale-110 transition-transform"
                    />
                    {isSingleSource && (
                      <div
                        className="absolute inset-0 rounded-full bg-red-500/60 animate-ping"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                </Marker>
              );
            }
            // Routes view — existing marker JSX unchanged
            return (
              <Marker
                key={dist.id}
                longitude={dist.longitude}
                latitude={dist.latitude}
                anchor="center"
                onClick={(e) => {
                  e.originalEvent.stopPropagation();
                  setSelectedDist(dist);
                }}
              >
                <div
                  className="relative group cursor-pointer"
                  onMouseEnter={() => setHoveredDistId(dist.id)}
                  onMouseLeave={() => setHoveredDistId(null)}
                >
                  <div
                    className={`rounded-full border-2 border-white/20 transition-all duration-150 shadow-md pointer-events-none ${
                      hoveredDistId === dist.id ? 'scale-[2.2] border-white/70' : ''
                    }`}
                    style={{
                      width: Math.max(6, Math.min(14, 6 + dist.total_offers / 100)),
                      height: Math.max(6, Math.min(14, 6 + dist.total_offers / 100)),
                      backgroundColor: dist.is_domestic ? '#3b82f6' : '#f59e0b',
                    }}
                  />
                  {hoveredDistId === dist.id && (
                    <div className="absolute -top-8 left-1/2 -translate-x-1/2 bg-slate-800/95 text-white text-xs px-2 py-0.5 rounded whitespace-nowrap pointer-events-none z-50 border border-slate-600 shadow-lg select-none">
                      {dist.name}
                    </div>
                  )}
                </div>
              </Marker>
            );
          })}

          {hubs.map((hub) => {
            const isActiveHub =
              !!selectedRoute?.cross_dock?.enabled &&
              selectedRoute?.cross_dock?.hub_id === hub.id;
            return (
              <Marker
                key={`hub-${hub.id}`}
                longitude={hub.longitude}
                latitude={hub.latitude}
                anchor="center"
              >
                <div
                  data-testid="hub-marker"
                  title={`${hub.name} (${hub.city}, ${hub.state})${isActiveHub ? ' — consolidation hub for selected strategy' : ''}`}
                  className={`relative cursor-pointer hover:scale-150 transition-transform ${
                    isActiveHub ? 'hub-marker-pulse' : ''
                  }`}
                  style={{
                    width: isActiveHub ? '16px' : '12px',
                    height: isActiveHub ? '16px' : '12px',
                    backgroundColor: '#fbbf24',
                    border: '1.5px solid rgba(254, 243, 199, 0.9)',
                    transform: 'rotate(45deg)',
                    boxShadow: isActiveHub
                      ? undefined // controlled by hub-marker-pulse animation
                      : '0 0 8px 2px rgba(251, 191, 36, 0.45), 0 0 2px 0 rgba(0,0,0,0.6)',
                  }}
                />
              </Marker>
            );
          })}

          {user && (
            <Marker longitude={user.longitude} latitude={user.latitude} anchor="bottom">
              <div className="relative cursor-pointer group" title={user.factory_name}>
                <div className="w-5 h-5 rounded-full bg-white border-4 border-green-500 shadow-lg shadow-green-500/50 group-hover:scale-125 transition-transform" />
                <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-green-600 text-white text-xs px-2 py-0.5 rounded whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-50">
                  {user.factory_name}
                </div>
              </div>
            </Marker>
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

        {/* Network Risk view toggle — UI-SPEC section 8 */}
        <div
          className="absolute top-4 right-14 z-10 flex bg-slate-900/90 border border-slate-700 rounded-lg overflow-hidden text-xs font-semibold"
          role="tablist"
          aria-label="Map view"
        >
          <button
            role="tab"
            aria-selected={mapView === 'routes'}
            onClick={() => { setMapView('routes'); setShowNetworkRiskPanel(false); }}
            className={`px-3 py-2 transition-colors ${mapView === 'routes' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            Routes
          </button>
          <button
            role="tab"
            aria-selected={mapView === 'network-risk'}
            onClick={() => { setMapView('network-risk'); setShowNetworkRiskPanel(true); }}
            className={`px-3 py-2 transition-colors ${mapView === 'network-risk' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:text-white'}`}
          >
            Network Risk
          </button>
        </div>

        {/* Cascade Risk sub-toggle — only visible in Network Risk view */}
        {mapView === 'network-risk' && (
          <button
            onClick={() => setCascadeActive((v) => !v)}
            className={`absolute top-14 right-14 z-10 px-3 py-2 text-xs font-semibold rounded-lg border transition-colors ${
              cascadeActive
                ? 'bg-slate-700 text-white border-slate-500'
                : 'bg-slate-900/90 text-slate-300 border-slate-700 hover:bg-slate-800'
            }`}
          >
            Cascade Risk{cascadeActive ? ' \u2713' : ''}
          </button>
        )}

        {selectedRoute && mapView === 'routes' && (
          <button
            onClick={() => {
              setTimelineOpen((v) => !v);
              setSelectedDist(null);
            }}
            className={`absolute top-16 right-14 z-10 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all pointer-events-auto border ${
              timelineOpen
                ? 'bg-blue-600 text-white border-blue-500'
                : 'bg-slate-800/90 text-slate-300 border-slate-700 hover:bg-slate-700'
            }`}
          >
            <Route className="w-3.5 h-3.5" />
            Route Stops
          </button>
        )}

        {/* Map legend / filter panel */}
        <div className="absolute bottom-4 left-4 z-10 pointer-events-auto">
          <div className="bg-slate-900/95 backdrop-blur-md border border-slate-700/60 rounded-xl shadow-2xl overflow-hidden w-64 p-4 space-y-3">
            <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
              Distributor Network
            </div>

            <div className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                <span className="text-slate-300">Domestic ({domesticCount})</span>
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-amber-500" />
                <span className="text-slate-300">Int'l ({internationalCount})</span>
              </span>
            </div>

            <button
              onClick={() => setShowDomesticOnly((v) => !v)}
              className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                showDomesticOnly ? 'text-blue-400' : 'text-slate-500'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              {showDomesticOnly ? 'Show all distributors' : 'Domestic only'}
            </button>

            {selectedRoute && (
              <button
                onClick={() => setShowRoutes((v) => !v)}
                className={`flex items-center gap-2 text-xs font-medium transition-colors ${
                  showRoutes ? 'text-blue-400' : 'text-slate-500'
                }`}
              >
                <div className={`w-6 h-0.5 rounded-full transition-colors ${showRoutes ? 'bg-blue-500' : 'bg-slate-600'}`} />
                {showRoutes ? 'Hide' : 'Show'} route paths
              </button>
            )}

            {hubs.length > 0 && (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <div
                  className="w-2.5 h-2.5 bg-amber-400 border border-amber-200/80 flex-shrink-0"
                  style={{ transform: 'rotate(45deg)' }}
                />
                Cross-Dock Hubs ({hubs.length})
              </div>
            )}

            {user && (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <div className="w-3 h-3 rounded-full bg-white border-2 border-green-500 flex-shrink-0" />
                Your Factory
              </div>
            )}

            {/* Cascade heatmap legend (shown when cascade is active in Network Risk view) */}
            {mapView === 'network-risk' && cascadeActive && (
              <div>
                <p className="text-xs font-semibold text-slate-400 mb-2">Cascade risk</p>
                <div className="flex items-center gap-1">
                  <div
                    className="flex-1 h-3 rounded"
                    style={{ background: 'linear-gradient(to right, #440154, #3b528b, #21918c, #5ec962, #fde725)' }}
                  />
                </div>
                <div className="flex justify-between text-xs text-slate-500 mt-1">
                  <span>0% BOM collapse</span>
                  <span>100%</span>
                </div>
              </div>
            )}
          </div>
        </div>

        <RouteLegPopup
          data={legPopup?.data ?? null}
          position={legPopup?.position ?? { x: 0, y: 0 }}
          onClose={() => setLegPopup(null)}
          containerRef={mapContainerRef}
        />
      </div>

      {/* Network Risk side panel — right-docked, auto-opens in Network Risk view */}
      {mapView === 'network-risk' && showNetworkRiskPanel && (
        <div className="absolute top-0 right-0 h-full w-96 bg-slate-900/98 backdrop-blur-md border-l border-slate-700/60 z-20 flex flex-col">
          {/* Header */}
          <div className="p-4 border-b border-slate-700 flex items-start justify-between">
            <div>
              <h2 className="text-3xl font-semibold text-white">Single-source components</h2>
              <p className="text-sm text-slate-400 mt-1">
                k-core components with exactly one distributor. These fail the BOM if that distributor goes offline.
              </p>
            </div>
            <button
              aria-label="Close network risk panel"
              onClick={() => setShowNetworkRiskPanel(false)}
              className="text-slate-400 hover:text-white ml-2 p-1 rounded hover:bg-slate-700 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
          {/* Body */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {singleSourceComponents.length === 0 ? (
              <p className="text-slate-600 text-xs text-center mt-8">
                No single-source components detected in the current graph.
              </p>
            ) : (
              singleSourceComponents.map((comp, i) => {
                // Find the distributor's coordinates from the existing distributors list
                // for flyTo on click
                const dist = distributors.find((d) => d.id === comp.distributor_id);
                return (
                  <button
                    key={i}
                    onClick={() => {
                      if (dist && mapRef.current) {
                        mapRef.current.flyTo({ center: [dist.longitude, dist.latitude], zoom: 5, duration: 800 });
                      }
                    }}
                    className="w-full text-left bg-slate-800/40 hover:bg-slate-800/70 rounded-lg px-3 py-2 border-l-2 border-red-500 transition-colors"
                  >
                    {/* UI-SPEC § 8: {MPN} · {manufacturer} · only source: {distributor_name} */}
                    <p className="text-xs font-mono text-white">{comp.mpn}</p>
                    <p className="text-xs text-slate-500">{comp.manufacturer}</p>
                    <p className="text-sm text-slate-300">only source: {comp.distributor_name}</p>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* Distributor detail sidebar */}
      {selectedDist && (() => {
        const allComponents = distDetail?.top_components ?? [];
        const categories = [...new Set(allComponents.map((c) => c.category))].sort();
        const filtered = allComponents.filter((c) => {
          const q = componentSearch.toLowerCase();
          const matchesSearch = !q || c.mpn.toLowerCase().includes(q) || c.manufacturer.toLowerCase().includes(q) || c.category.toLowerCase().includes(q);
          const matchesCategory = !categoryFilter || c.category === categoryFilter;
          return matchesSearch && matchesCategory;
        });

        return (
          <div className="absolute top-0 right-0 h-full w-96 bg-slate-900/98 backdrop-blur-md border-l border-slate-700/60 shadow-2xl z-20 flex flex-col pointer-events-auto">
            {/* Header */}
            <div className="flex items-start justify-between p-5 border-b border-slate-700/50 flex-shrink-0">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                    style={{ backgroundColor: selectedDist.is_domestic ? '#3b82f6' : '#f59e0b' }}
                  />
                  <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
                    {selectedDist.is_domestic ? 'Domestic' : 'International'} Distributor
                  </span>
                </div>
                <h2 className="text-sm font-semibold text-white leading-tight truncate">{selectedDist.name}</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  {[selectedDist.city, selectedDist.state, selectedDist.country].filter(Boolean).join(', ')}
                </p>
              </div>
              <button
                onClick={() => setSelectedDist(null)}
                className="ml-3 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-700 transition-colors flex-shrink-0"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-2 p-4 border-b border-slate-700/50 flex-shrink-0">
              <div className="bg-slate-800/60 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-white">{selectedDist.total_offers}</div>
                <div className="text-[10px] text-slate-400 mt-0.5">Offers</div>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-white">{selectedDist.total_stock.toLocaleString()}</div>
                <div className="text-[10px] text-slate-400 mt-0.5">Total Stock</div>
              </div>
              <div className="bg-slate-800/60 rounded-lg p-3 text-center">
                <div className="text-lg font-bold text-white flex items-center justify-center gap-1">
                  <MapPin className="w-3.5 h-3.5 text-slate-500" />
                  <span className="text-xs">{selectedDist.latitude.toFixed(1)}°</span>
                </div>
                <div className="text-[10px] text-slate-400 mt-0.5">{selectedDist.longitude.toFixed(1)}° Lng</div>
              </div>
            </div>

            {/* Component offerings section */}
            <div className="flex flex-col flex-1 min-h-0">
              {/* Section header */}
              <div className="px-4 pt-3 pb-2 flex-shrink-0">
                <div className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                  <Package className="w-3 h-3" />
                  Component Offerings
                  {distDetailLoading && (
                    <div className="w-3 h-3 rounded-full border border-blue-500 border-t-transparent animate-spin ml-1" />
                  )}
                </div>

                {/* Search */}
                <div className="relative mb-2">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none" />
                  <input
                    type="text"
                    placeholder="Search MPN, manufacturer..."
                    value={componentSearch}
                    onChange={(e) => setComponentSearch(e.target.value)}
                    className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg bg-slate-800/80 border border-slate-700/60 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/60 transition-colors"
                  />
                  {componentSearch && (
                    <button
                      onClick={() => setComponentSearch('')}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  )}
                </div>

                {/* Category filter */}
                {categories.length > 0 && (
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <Tag className="w-3 h-3 text-slate-500 flex-shrink-0" />
                    <button
                      onClick={() => setCategoryFilter('')}
                      className={`text-[10px] px-2 py-0.5 rounded-full transition-colors ${!categoryFilter ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'text-slate-500 hover:text-slate-300'}`}
                    >
                      All
                    </button>
                    {categories.slice(0, 5).map((cat) => (
                      <button
                        key={cat}
                        onClick={() => setCategoryFilter(cat === categoryFilter ? '' : cat)}
                        className={`text-[10px] px-2 py-0.5 rounded-full transition-colors truncate max-w-[90px] ${cat === categoryFilter ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'text-slate-500 hover:text-slate-300'}`}
                        title={cat}
                      >
                        {cat}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Component list */}
              <div className="flex-1 overflow-y-auto px-2 pb-4 space-y-1 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
                {distDetailLoading ? (
                  <div className="flex flex-col items-center justify-center h-32 gap-2">
                    <div className="w-6 h-6 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
                    <span className="text-xs text-slate-500">Loading offerings...</span>
                  </div>
                ) : filtered.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-32 text-slate-600 text-xs">
                    {allComponents.length === 0 ? 'No offerings found' : 'No matches for your search'}
                  </div>
                ) : (
                  filtered.map((comp) => (
                    <div
                      key={comp.component_id}
                      className="flex items-center justify-between px-3 py-2.5 rounded-lg bg-slate-800/40 hover:bg-slate-800/70 transition-colors border border-transparent hover:border-slate-700/50 group"
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="text-xs font-mono font-semibold text-white truncate">{comp.mpn}</span>
                        </div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className="text-[10px] text-slate-500 truncate">{comp.manufacturer}</span>
                          <span className="text-[10px] text-slate-600">·</span>
                          <span className="text-[10px] text-blue-500/70 truncate">{comp.category}</span>
                        </div>
                        {comp.sku && (
                          <div className="text-[9px] text-slate-600 font-mono mt-0.5 truncate">SKU: {comp.sku}</div>
                        )}
                      </div>
                      <div className="flex-shrink-0 text-right ml-3">
                        <div className="text-xs font-semibold text-green-400">
                          ${comp.price.toFixed(2)}
                        </div>
                        <div className="text-[10px] text-slate-500 mt-0.5">
                          {comp.stock.toLocaleString()} in stock
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>

              {/* Footer count */}
              {!distDetailLoading && allComponents.length > 0 && (
                <div className="px-4 py-2 border-t border-slate-700/40 flex-shrink-0">
                  <span className="text-[10px] text-slate-600">
                    Showing {filtered.length} of {allComponents.length} offerings
                    {allComponents.length === 20 ? ' (top 20 by stock)' : ''}
                  </span>
                </div>
              )}
            </div>
          </div>
        );
      })()}

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
