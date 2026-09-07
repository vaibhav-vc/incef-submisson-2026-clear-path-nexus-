interface AppConfig {
  weatherKey: string;
  weatherApiKey: string;
  openWeatherBaseUrl: string;
  overpassBaseUrl: string;
  requestTimeoutMs: number;
  apiUrl?: string;
}

const weatherKey = process.env.EXPO_PUBLIC_WEATHER_KEY || '';
const apiUrl = process.env.EXPO_PUBLIC_API_URL || '';

export const config: AppConfig = {
  weatherKey,
  weatherApiKey: weatherKey,
  openWeatherBaseUrl: 'https://api.openweathermap.org/data/2.5/weather',
  overpassBaseUrl: 'https://overpass-api.de/api/interpreter',
  requestTimeoutMs: 10000,
  apiUrl,
};

export function validateConfig(): void {
  if (!config.weatherKey) {
    throw new Error('EXPO_PUBLIC_WEATHER_KEY environment variable is missing.');
  }
}
