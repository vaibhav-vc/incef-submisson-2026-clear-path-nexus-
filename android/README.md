# ClearPath Nexus Android client

The Kotlin/Jetpack Compose client uses Supabase for authentication and sends the resulting bearer token to the FastAPI `/api/v1` operational backend. Backend authorization remains authoritative.

## Requirements

- JDK 17
- Android Studio and Android SDK 35
- A reachable FastAPI deployment
- Your public Supabase URL and anon key

Do not place a Supabase service-role key in this app.

## Configuration

Pass local Gradle properties or set them in the user-level Gradle properties file:

```properties
backendBaseUrl=http://10.0.2.2:8000/api/v1
supabaseUrl=https://your-project.supabase.co
supabaseAnonKey=your-public-anon-key
```

The committed defaults are placeholders. A physical device needs a backend address reachable from the device. Production releases require HTTPS and all three release properties: `releaseBackendBaseUrl`, `releaseSupabaseUrl`, and `releaseSupabaseAnonKey`. The build rejects local/placeholder endpoints and non-public Supabase keys. A distributable APK also requires an external signing configuration in `key.properties`.

## Verification

```powershell
.\gradlew.bat testDebugUnitTest assembleDebug
```

## Data-source behavior

Operational route decisions come only from the authenticated FastAPI backend.
Backend/provider failures surface as unavailable errors; the Android client does
not substitute bundled routes, reliability values, weather scores, geometry, or
alternate journeys. Operator berth windows require a manifest reference and
SHA-256 digest. Multi-leg decisions preserve every backend route ID and use
`HARD_BLOCKED > UNAVAILABLE > HOLD > READY` precedence.

Android v6 parses the compact SourceLine traceability summary. Full incident-kit
inspection, deterministic journey export, and ComplianceGuard review remain
available in the web console.
