import * as SQLite from 'expo-sqlite';
import { logger } from '../utils/logger';
import type { WeatherData, RouteEvaluation, LoadProfile } from '../types';

let dbInstance: SQLite.SQLiteDatabase | null = null;

export async function initDatabase(): Promise<SQLite.SQLiteDatabase> {
  if (dbInstance) return dbInstance;
  try {
    const db = await SQLite.openDatabaseAsync('clearpath.db');
    await db.execAsync(`
      PRAGMA journal_mode = WAL;
      CREATE TABLE IF NOT EXISTS weather_cache (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_code TEXT NOT NULL,
        weather_condition TEXT,
        temperature REAL,
        wind_speed REAL,
        visibility REAL,
        weather_score REAL,
        fetched_at TEXT
      );
      CREATE TABLE IF NOT EXISTS route_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_station TEXT,
        to_station TEXT,
        waypoints TEXT,
        final_score REAL,
        status TEXT,
        approved_at TEXT,
        created_at TEXT
      );
      CREATE TABLE IF NOT EXISTS load_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        cargo_height REAL,
        cargo_width REAL,
        cargo_weight REAL,
        created_at TEXT
      );
    `);
    logger.db('Database schema initialized.');
    dbInstance = db;
    return db;
  } catch (error) {
    logger.error('Database initialization failed:', error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

export async function saveWeatherCache(data: WeatherData): Promise<void> {
  const db = await initDatabase();
  try {
    await db.runAsync(
      `INSERT OR REPLACE INTO weather_cache (station_code, weather_condition, temperature, wind_speed, visibility, weather_score, fetched_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        data.stationCode,
        data.condition,
        data.temperature,
        data.windSpeed,
        data.visibility,
        data.score,
        data.fetchedAt,
      ]
    );
    logger.db(`Weather cached for ${data.stationCode}`);
  } catch (error) {
    logger.error(`Failed to save weather cache for ${data.stationCode}:`, error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

export async function getWeatherCache(stationCode: string): Promise<WeatherData | null> {
  const db = await initDatabase();
  try {
    const row = await db.getFirstAsync<{
      station_code: string;
      weather_condition: string;
      temperature: number;
      wind_speed: number;
      visibility: number;
      weather_score: number;
      fetched_at: string;
    }>(
      `SELECT * FROM weather_cache WHERE station_code = ? ORDER BY fetched_at DESC LIMIT 1`,
      [stationCode]
    );
    if (!row) return null;
    return {
      stationCode: row.station_code,
      condition: row.weather_condition as any,
      temperature: row.temperature,
      windSpeed: row.wind_speed,
      visibility: row.visibility,
      score: row.weather_score,
      fetchedAt: row.fetched_at,
    };
  } catch (error) {
    logger.error(`Failed to get weather cache for ${stationCode}:`, error instanceof Error ? error : new Error(String(error)));
    return null;
  }
}

export async function saveRouteHistory(route: RouteEvaluation): Promise<void> {
  const db = await initDatabase();
  try {
    const fromStation = route.stations[0]?.code || '';
    const toStation = route.stations[route.stations.length - 1]?.code || '';
    const waypoints = JSON.stringify(route.stations.slice(1, -1));
    await db.runAsync(
      `INSERT INTO route_history (from_station, to_station, waypoints, final_score, status, approved_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
      [
        fromStation,
        toStation,
        waypoints,
        route.finalScore,
        route.status,
        route.approvedAt || null,
        route.createdAt,
      ]
    );
    logger.db('Route evaluation saved to history.');
  } catch (error) {
    logger.error('Failed to save route history:', error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

export async function getRouteHistoryList(): Promise<RouteEvaluation[]> {
  const db = await initDatabase();
  try {
    const rows = await db.getAllAsync<{
      id: number;
      from_station: string;
      to_station: string;
      waypoints: string;
      final_score: number;
      status: string;
      approved_at: string | null;
      created_at: string;
    }>(`SELECT * FROM route_history ORDER BY created_at DESC`);
    
    return rows.map((row) => {
      const fromSt: any = { code: row.from_station, name: row.from_station, lat: 0, lon: 0 };
      const toSt: any = { code: row.to_station, name: row.to_station, lat: 0, lon: 0 };
      let middle: any[] = [];
      try {
        middle = JSON.parse(row.waypoints || '[]');
      } catch (e) {}

      return {
        id: row.id,
        stations: [fromSt, ...middle, toSt],
        breakdown: {
          weather: { score: 0.8, weight: 0.40 },
          port: { score: 0.65, weight: 0.30 },
          congestion: { score: 0.80, weight: 0.15 },
          historical: { score: 0.70, weight: 0.15 },
        },
        finalScore: row.final_score,
        status: row.status as any,
        approvedAt: row.approved_at || undefined,
        createdAt: row.created_at,
      };
    });
  } catch (error) {
    logger.error('Failed to query route history:', error instanceof Error ? error : new Error(String(error)));
    return [];
  }
}

export async function saveLoadProfile(profile: Omit<LoadProfile, 'id' | 'createdAt'>): Promise<LoadProfile> {
  const db = await initDatabase();
  try {
    const createdAt = new Date().toISOString();
    const result = await db.runAsync(
      `INSERT INTO load_profiles (name, cargo_height, cargo_width, cargo_weight, created_at)
       VALUES (?, ?, ?, ?, ?)`,
      [profile.name, profile.cargoHeight, profile.cargoWidth, profile.cargoWeight, createdAt]
    );
    return {
      id: result.lastInsertRowId,
      name: profile.name,
      cargoHeight: profile.cargoHeight,
      cargoWidth: profile.cargoWidth,
      cargoWeight: profile.cargoWeight,
      createdAt,
    };
  } catch (error) {
    logger.error('Failed to save load profile:', error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

export async function getLoadProfilesList(): Promise<LoadProfile[]> {
  const db = await initDatabase();
  try {
    const rows = await db.getAllAsync<{
      id: number;
      name: string;
      cargo_height: number;
      cargo_width: number;
      cargo_weight: number;
      created_at: string;
    }>(`SELECT * FROM load_profiles ORDER BY id DESC`);
    return rows.map((row) => ({
      id: row.id,
      name: row.name,
      cargoHeight: row.cargo_height,
      cargoWidth: row.cargo_width,
      cargoWeight: row.cargo_weight,
      createdAt: row.created_at,
    }));
  } catch (error) {
    logger.error('Failed to get load profiles:', error instanceof Error ? error : new Error(String(error)));
    return [];
  }
}

export async function deleteLoadProfile(id: number): Promise<void> {
  const db = await initDatabase();
  try {
    await db.runAsync(`DELETE FROM load_profiles WHERE id = ?`, [id]);
    logger.db(`Deleted load profile ID: ${id}`);
  } catch (error) {
    logger.error(`Failed to delete load profile ID ${id}:`, error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}

export async function clearRouteHistory(): Promise<void> {
  const db = await initDatabase();
  try {
    await db.runAsync(`DELETE FROM route_history`);
    logger.db('Cleared route history.');
  } catch (error) {
    logger.error('Failed to clear route history:', error instanceof Error ? error : new Error(String(error)));
    throw error;
  }
}
