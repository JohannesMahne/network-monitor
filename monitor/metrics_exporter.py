"""Metrics exporter for InfluxDB and Prometheus.

Exports network monitoring metrics to time-series databases
for long-term storage and Grafana dashboards.
"""

from typing import Dict

from config import get_logger

logger = get_logger(__name__)


class MetricsExporter:
    """Exports metrics to InfluxDB or Prometheus."""

    def __init__(self):
        """Initialize the metrics exporter."""
        self._influx_client = None
        self._prometheus_enabled = False
        logger.debug("MetricsExporter initialized")

    def export_to_influxdb(
        self, data: Dict, endpoint: str, token: str, org: str, bucket: str
    ) -> bool:
        """Export metrics to InfluxDB.

        Args:
            data: Dictionary with metrics (upload_speed, download_speed, latency, etc.)
            endpoint: InfluxDB endpoint URL
            token: InfluxDB authentication token
            org: InfluxDB organization
            bucket: InfluxDB bucket name

        Returns:
            True if export succeeded, False otherwise
        """
        try:
            # Try to import influxdb-client (optional dependency)
            try:
                from influxdb_client import InfluxDBClient, Point
                from influxdb_client.client.write_api import SYNCHRONOUS
            except ImportError:
                logger.warning(
                    "influxdb-client not installed. Install with: pip install influxdb-client"
                )
                return False

            # Create client
            client = InfluxDBClient(url=endpoint, token=token, org=org)
            write_api = client.write_api(write_options=SYNCHRONOUS)

            # Create data point
            point = (
                Point("network_metrics")
                .field("upload_speed", data.get("upload_speed", 0))
                .field("download_speed", data.get("download_speed", 0))
                .field("latency_ms", data.get("latency_ms", 0))
                .field("quality_score", data.get("quality_score", 0))
                .field("device_count", data.get("device_count", 0))
            )

            # Write to InfluxDB
            write_api.write(bucket=bucket, org=org, record=point)
            client.close()

            logger.debug("Metrics exported to InfluxDB")
            return True
        except Exception as e:
            logger.error(f"InfluxDB export error: {e}", exc_info=True)
            return False

    def export_to_prometheus(
        self, data: Dict, gateway_url: str, job: str = "network_monitor"
    ) -> bool:
        """Export metrics to Prometheus Pushgateway.

        Args:
            data: Dictionary with metrics
            gateway_url: Prometheus Pushgateway URL
            job: Job name for Prometheus

        Returns:
            True if export succeeded, False otherwise
        """
        try:
            # Try to import prometheus_client (optional dependency)
            try:
                from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
            except ImportError:
                logger.warning(
                    "prometheus-client not installed. Install with: pip install prometheus-client"
                )
                return False

            # Create registry and metrics
            registry = CollectorRegistry()

            upload_gauge = Gauge(
                "network_upload_speed_bytes", "Upload speed in bytes/sec", registry=registry
            )
            download_gauge = Gauge(
                "network_download_speed_bytes", "Download speed in bytes/sec", registry=registry
            )
            latency_gauge = Gauge(
                "network_latency_ms", "Network latency in milliseconds", registry=registry
            )
            quality_gauge = Gauge(
                "network_quality_score", "Network quality score (0-100)", registry=registry
            )
            device_gauge = Gauge(
                "network_device_count", "Number of network devices", registry=registry
            )

            # Set metric values
            upload_gauge.set(data.get("upload_speed", 0))
            download_gauge.set(data.get("download_speed", 0))
            latency_gauge.set(data.get("latency_ms", 0))
            quality_gauge.set(data.get("quality_score", 0))
            device_gauge.set(data.get("device_count", 0))

            # Push to gateway
            push_to_gateway(gateway_url, job=job, registry=registry)

            logger.debug("Metrics exported to Prometheus Pushgateway")
            return True
        except Exception as e:
            logger.error(f"Prometheus export error: {e}", exc_info=True)
            return False

    def start_continuous_export(self, interval: int, export_type: str, **kwargs) -> None:
        """Start continuous background export.

        Args:
            interval: Export interval in seconds
            export_type: 'influxdb' or 'prometheus'
            **kwargs: Export-specific parameters
        """
        # This would be implemented to run in a background thread
        # For now, just log that it's not fully implemented
        logger.info(f"Continuous {export_type} export requested (interval: {interval}s)")
        # TODO: Implement background thread for continuous export
