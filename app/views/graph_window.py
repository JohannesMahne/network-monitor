"""Historical graphs window for Network Monitor.

Displays full-size matplotlib graphs of historical network data
in a popup window with tabs for different time periods.
"""

import threading
from datetime import datetime

from config import get_logger

logger = get_logger(__name__)


class GraphWindow:
    """Window with matplotlib graphs for historical data.

    Opens a non-blocking window with tabs for daily/weekly/monthly views.
    """

    def __init__(self, store):
        """Initialize the graph window.

        Args:
            store: SQLiteStore instance for data access
        """
        self.store = store
        self._window_open = False
        logger.debug("GraphWindow initialized")

    def show(self) -> None:
        """Open the graph window in a separate thread (non-blocking)."""
        if self._window_open:
            logger.debug("Graph window already open")
            return

        self._window_open = True
        # Run in background thread to avoid blocking menu
        threading.Thread(target=self._show_window, daemon=True).start()

    def _show_window(self) -> None:
        """Show the window with graphs (runs in background thread)."""
        try:
            import matplotlib

            # Use Agg backend and save to file (more reliable for menu bar apps)
            matplotlib.use("Agg")
            import subprocess
            import tempfile

            from matplotlib import pyplot as plt

            # Create figure with subplots for different views
            fig = plt.figure(figsize=(12, 8))
            fig.suptitle("Network Monitor - Historical Data", fontsize=14, fontweight="bold")

            # Get data
            try:
                daily_data = self.store.get_daily_totals(days=30)
                weekly_data = self.store.get_weekly_totals()
                monthly_data = self.store.get_monthly_totals()
            except Exception as e:
                logger.error(f"Error fetching data: {e}", exc_info=True)
                daily_data = []
                weekly_data = {}
                monthly_data = {}

            # Create subplots
            ax1 = fig.add_subplot(2, 2, 1)
            ax2 = fig.add_subplot(2, 2, 2)
            ax3 = fig.add_subplot(2, 2, 3)
            ax4 = fig.add_subplot(2, 2, 4)

            # Plot 1: Daily upload/download (last 30 days)
            if daily_data:
                dates = [datetime.fromisoformat(d["date"]) for d in daily_data]
                uploads = [d["sent"] / (1024 * 1024) for d in daily_data]  # Convert to MB
                downloads = [d["recv"] / (1024 * 1024) for d in daily_data]

                ax1.plot(dates, uploads, label="Upload", color="#34C759", linewidth=2)
                ax1.plot(dates, downloads, label="Download", color="#007AFF", linewidth=2)
                ax1.fill_between(dates, uploads, alpha=0.3, color="#34C759")
                ax1.fill_between(dates, downloads, alpha=0.3, color="#007AFF")
                ax1.set_title("Daily Traffic (Last 30 Days)")
                ax1.set_xlabel("Date")
                ax1.set_ylabel("MB")
                ax1.legend()
                ax1.grid(True, alpha=0.3)
                ax1.tick_params(axis="x", rotation=45)

            # Plot 2: Weekly totals
            if weekly_data:
                weeks = ["Week"]
                week_upload = [weekly_data["sent"] / (1024 * 1024 * 1024)]  # GB
                week_download = [weekly_data["recv"] / (1024 * 1024 * 1024)]

                x = range(len(weeks))
                width = 0.35
                ax2.bar(
                    [i - width / 2 for i in x], week_upload, width, label="Upload", color="#34C759"
                )
                ax2.bar(
                    [i + width / 2 for i in x],
                    week_download,
                    width,
                    label="Download",
                    color="#007AFF",
                )
                ax2.set_title("Weekly Totals")
                ax2.set_ylabel("GB")
                ax2.set_xticks(x)
                ax2.set_xticklabels(weeks)
                ax2.legend()
                ax2.grid(True, alpha=0.3, axis="y")

            # Plot 3: Monthly totals
            if monthly_data:
                months = ["Month"]
                month_upload = [monthly_data["sent"] / (1024 * 1024 * 1024)]  # GB
                month_download = [monthly_data["recv"] / (1024 * 1024 * 1024)]

                x = range(len(months))
                width = 0.35
                ax3.bar(
                    [i - width / 2 for i in x], month_upload, width, label="Upload", color="#34C759"
                )
                ax3.bar(
                    [i + width / 2 for i in x],
                    month_download,
                    width,
                    label="Download",
                    color="#007AFF",
                )
                ax3.set_title("Monthly Totals")
                ax3.set_ylabel("GB")
                ax3.set_xticks(x)
                ax3.set_xticklabels(months)
                ax3.legend()
                ax3.grid(True, alpha=0.3, axis="y")

            # Plot 4: Per-connection breakdown (top 5)
            if monthly_data.get("by_connection"):
                connections = list(monthly_data["by_connection"].items())[:5]
                conn_names = [name[:15] for name, _ in connections]
                conn_totals = [
                    (stats["sent"] + stats["recv"]) / (1024 * 1024 * 1024)
                    for _, stats in connections
                ]

                ax4.barh(conn_names, conn_totals, color="#AF52DE")
                ax4.set_title("Top Connections (This Month)")
                ax4.set_xlabel("GB")
                ax4.grid(True, alpha=0.3, axis="x")

            plt.tight_layout()

            # Save to file and open (more reliable for menu bar apps)
            graph_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            graph_file.close()  # Close the file handle so we can write to it

            try:
                plt.savefig(graph_file.name, dpi=100, bbox_inches="tight")
                plt.close(fig)

                # Open in default image viewer (Preview on macOS)
                subprocess.run(["open", graph_file.name], check=True)
                logger.info(f"Graph saved and opened: {graph_file.name}")
            except Exception as e:
                logger.error(f"Error saving/opening graph: {e}", exc_info=True)
                # Try to clean up
                try:
                    import os

                    os.unlink(graph_file.name)
                except:
                    pass
                raise

        except Exception as e:
            logger.error(f"Error showing graph window: {e}", exc_info=True)
            # Show error notification on main thread
            import rumps

            # Use notification instead of alert (less intrusive)
            rumps.notification(
                title="Graph Window Error",
                subtitle="Could not open graphs",
                message=f"Error: {str(e)[:100]}",
                sound=False,
            )
        finally:
            self._window_open = False
