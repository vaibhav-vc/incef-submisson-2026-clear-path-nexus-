import { config } from '../config';
import { logger } from '../utils/logger';
import type { Station, TrackGeometry } from '../types';

// Haversine formula to compute distance in km
export function calculateDistance(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371; // km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export async function getNearbyStations(lat: number, lon: number, radiusKm: number): Promise<Station[]> {
  logger.gps(`Searching nearby stations around ${lat}, ${lon} with radius ${radiusKm}km`);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);

  const radiusMeters = radiusKm * 1000;
  const query = `[out:json];node["railway"="station"](around:${radiusMeters},${lat},${lon});out body;`;
  const url = `${config.overpassBaseUrl}?data=${encodeURIComponent(query)}`;

  try {
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`Overpass API returned status ${response.status}`);
    }

    const data = await response.json();
    const elements = data.elements || [];

    const stationMap: Record<string, Station> = {};

    elements.forEach((el: any) => {
      const name = el.tags?.name;
      if (!name) return;

      const code = el.tags?.ref || el.tags?.code || name.substring(0, 4).toUpperCase();
      const stLat = el.lat;
      const stLon = el.lon;
      const dist = calculateDistance(lat, lon, stLat, stLon);

      // Deduplicate by name, keeping the nearest one
      if (!stationMap[name] || (stationMap[name].distanceKm ?? Infinity) > dist) {
        stationMap[name] = {
          code,
          name,
          lat: stLat,
          lon: stLon,
          distanceKm: parseFloat(dist.toFixed(2)),
        };
      }
    });

    return Object.values(stationMap).sort((a, b) => (a.distanceKm ?? 0) - (b.distanceKm ?? 0));
  } catch (error) {
    clearTimeout(timeoutId);
    logger.error('Failed to get nearby stations from Overpass:', error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

export async function getRailwayTrackGeometry(
  minLat: number,
  minLon: number,
  maxLat: number,
  maxLon: number
): Promise<TrackGeometry[]> {
  logger.api(`Fetching railway track geometry inside BBOX [${minLat}, ${minLon}, ${maxLat}, ${maxLon}]`);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);

  const query = `[out:json];way["railway"="rail"](${minLat},${minLon},${maxLat},${maxLon});out geom;`;
  const url = `${config.overpassBaseUrl}?data=${encodeURIComponent(query)}`;

  try {
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`Overpass API returned status ${response.status}`);
    }

    const data = await response.json();
    const elements = data.elements || [];

    const tracks: TrackGeometry[] = [];

    elements.forEach((el: any) => {
      if (el.type === 'way' && el.geometry) {
        const coordinates = el.geometry.map((pt: any) => ({
          lat: pt.lat,
          lon: pt.lon,
        }));
        if (coordinates.length > 0) {
          tracks.push({ coordinates });
        }
      }
    });

    return tracks;
  } catch (error) {
    clearTimeout(timeoutId);
    logger.error('Failed to get track geometry from Overpass:', error instanceof Error ? error : new Error(String(error)));
    return [];
  }
}

export async function searchStations(queryStr: string): Promise<Station[]> {
  if (!queryStr || queryStr.trim().length < 2) return [];
  logger.api(`Searching stations with query: ${queryStr}`);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), config.requestTimeoutMs);

  const cleanQuery = queryStr.replace(/"/g, '\\"');
  const query = `[out:json];node["railway"="station"]["name"~"${cleanQuery}",i];out 10;`;
  const url = `${config.overpassBaseUrl}?data=${encodeURIComponent(query)}`;

  try {
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(timeoutId);

    if (!response.ok) {
      throw new Error(`Overpass API returned status ${response.status}`);
    }

    const data = await response.json();
    const elements = data.elements || [];
    const results: Station[] = [];

    elements.forEach((el: any) => {
      const name = el.tags?.name;
      if (!name) return;
      const code = el.tags?.ref || el.tags?.code || name.substring(0, 4).toUpperCase();
      results.push({
        code,
        name,
        lat: el.lat,
        lon: el.lon,
      });
    });

    return results;
  } catch (error) {
    clearTimeout(timeoutId);
    logger.error(`Failed to search stations with query ${queryStr}:`, error instanceof Error ? error : new Error(String(error)));
    return [];
  }
}
