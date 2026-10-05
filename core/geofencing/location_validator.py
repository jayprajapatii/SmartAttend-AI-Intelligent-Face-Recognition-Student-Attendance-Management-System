"""
core/geofencing/location_validator.py

Optional geofencing: restricts attendance marking to within the
institution's campus boundary. Marked optional in the spec since most
deployments run a fixed classroom camera (whose location never
changes and can just be configured once), rather than needing live
GPS from a mobile device.

Three ways to validate location, in order of how this app is likely
to actually be used:

    1. Camera-based (primary, recommended for this desktop app):
       each camera/classroom has a known fixed lat/lng configured
       once via register_camera_location(). validate_camera(camera_id)
       then just checks that fixed point against the campus boundary -
       effectively "is this classroom on campus", decided once at
       setup time rather than every attendance mark.

    2. Direct coordinates: validate_coordinates(lat, lng) for any
       caller that already has a lat/lng (e.g. a future mobile
       companion app submitting GPS with each check-in).

    3. IP-based (coarse fallback): validate_ip_geolocation() gives a
       rough estimate when no GPS/camera coordinate is available at
       all. IP geolocation is frequently inaccurate (ISP routing,
       VPNs, campus-wide NAT) - this is explicitly a low-confidence
       fallback, not a primary mechanism, and is flagged as such in
       its result.

Usage:
    from core.geofencing.location_validator import location_validator

    location_validator.set_campus_boundary(
        center_lat=23.0225, center_lng=72.5714, radius_meters=500
    )
    location_validator.register_camera_location("cam_room_204", 23.0227, 72.5716)

    result = location_validator.validate_camera("cam_room_204")
    if not result.is_within_campus:
        block_attendance()
"""

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger("SmartAttendAI.core.geofencing.location_validator")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.info("requests package not installed - IP-based geolocation fallback unavailable.")

EARTH_RADIUS_METERS = 6371000
IP_GEOLOCATION_API_URL = "http://ip-api.com/json/"  # free tier, no key required - swap for a paid provider in production


@dataclass
class LocationCheckResult:
    is_within_campus: bool
    distance_meters: float = None
    method: str = ""          # "camera" | "coordinates" | "ip" | "unconfigured"
    confidence: str = "high"   # "high" | "low" (low for IP-based fallback)
    reason: str = ""


class LocationValidator:
    """
    Optional geofencing check. If no campus boundary has been
    configured, all validation calls report is_within_campus=True by
    default (fail-open) so this feature never blocks attendance for
    deployments that haven't set it up - geofencing is opt-in, not a
    silent hard requirement.
    """

    def __init__(self):
        self._center_lat = None
        self._center_lng = None
        self._radius_meters = None
        self._camera_locations = {}  # camera_id -> (lat, lng)

    # ------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------
    def set_campus_boundary(self, center_lat: float, center_lng: float, radius_meters: float):
        self._center_lat = center_lat
        self._center_lng = center_lng
        self._radius_meters = radius_meters
        logger.info(
            "Campus boundary set: center=(%.6f, %.6f), radius=%.0fm.",
            center_lat, center_lng, radius_meters,
        )

    def is_configured(self) -> bool:
        return self._center_lat is not None and self._center_lng is not None and self._radius_meters is not None

    def clear_boundary(self):
        self._center_lat = None
        self._center_lng = None
        self._radius_meters = None
        logger.info("Campus boundary cleared - geofencing disabled (fail-open).")

    def register_camera_location(self, camera_id: str, lat: float, lng: float):
        """
        Registers a fixed lat/lng for a given camera/classroom. Since
        cameras in this app are stationary, this only needs to be set
        once per camera (e.g. from the Settings page), not per frame.
        """
        self._camera_locations[camera_id] = (lat, lng)
        logger.info("Camera '%s' location registered: (%.6f, %.6f).", camera_id, lat, lng)

    def unregister_camera_location(self, camera_id: str):
        self._camera_locations.pop(camera_id, None)

    def get_registered_cameras(self) -> dict:
        return dict(self._camera_locations)

    # ------------------------------------------------------------
    # Distance calculation (Haversine formula)
    # ------------------------------------------------------------
    @staticmethod
    def haversine_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)

        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_METERS * c

    # ------------------------------------------------------------
    # Validation entry points
    # ------------------------------------------------------------
    def validate_coordinates(self, lat: float, lng: float) -> LocationCheckResult:
        if not self.is_configured():
            return LocationCheckResult(
                is_within_campus=True, method="unconfigured",
                reason="No campus boundary configured - geofencing not enforced.",
            )

        distance = self.haversine_distance_meters(lat, lng, self._center_lat, self._center_lng)
        within = distance <= self._radius_meters

        return LocationCheckResult(
            is_within_campus=within,
            distance_meters=round(distance, 1),
            method="coordinates",
            confidence="high",
            reason="" if within else f"{distance:.0f}m from campus center, outside the {self._radius_meters:.0f}m boundary.",
        )

    def validate_camera(self, camera_id: str) -> LocationCheckResult:
        if not self.is_configured():
            return LocationCheckResult(
                is_within_campus=True, method="unconfigured",
                reason="No campus boundary configured - geofencing not enforced.",
            )

        location = self._camera_locations.get(camera_id)
        if location is None:
            logger.warning(
                "Camera '%s' has no registered location - cannot geofence-check; failing open.", camera_id
            )
            return LocationCheckResult(
                is_within_campus=True, method="camera",
                reason=f"Camera '{camera_id}' has no registered location.",
            )

        lat, lng = location
        result = self.validate_coordinates(lat, lng)
        result.method = "camera"
        return result

    def validate_ip_geolocation(self, ip_address: str = None) -> LocationCheckResult:
        """
        Coarse fallback when no GPS/camera coordinate is available.
        IP geolocation accuracy varies widely (can be off by entire
        cities on mobile/VPN connections) - always reports
        confidence="low" so callers can choose to warn rather than
        hard-block based on this alone.
        """
        if not REQUESTS_AVAILABLE:
            return LocationCheckResult(
                is_within_campus=True, method="ip", confidence="low",
                reason="requests package not installed - cannot perform IP geolocation.",
            )

        if not self.is_configured():
            return LocationCheckResult(
                is_within_campus=True, method="unconfigured",
                reason="No campus boundary configured - geofencing not enforced.",
            )

        try:
            url = f"{IP_GEOLOCATION_API_URL}{ip_address}" if ip_address else IP_GEOLOCATION_API_URL
            response = requests.get(url, timeout=5)
            data = response.json()

            if data.get("status") != "success":
                return LocationCheckResult(
                    is_within_campus=True, method="ip", confidence="low",
                    reason=f"IP geolocation lookup failed: {data.get('message', 'unknown error')}.",
                )

            lat, lng = data["lat"], data["lon"]
            result = self.validate_coordinates(lat, lng)
            result.method = "ip"
            result.confidence = "low"
            return result

        except Exception as exc:
            logger.error("IP geolocation request failed: %s", exc)
            return LocationCheckResult(
                is_within_campus=True, method="ip", confidence="low",
                reason=f"IP geolocation request failed: {exc}",
            )


# Singleton instance - import this everywhere instead of instantiating directly
location_validator = LocationValidator()