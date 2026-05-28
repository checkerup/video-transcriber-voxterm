"""PyWebView entry point — opens the desktop GUI."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import AppConfig
from .api import JsApi


logger = logging.getLogger(__name__)


def launch(config: AppConfig, config_path: Path, project_root: Path,
           *, debug: bool = False, title: str = "Video Transcriber") -> None:
    import webview

    static_dir = Path(__file__).parent / "static"
    index_html = static_dir / "index.html"
    if not index_html.exists():
        raise FileNotFoundError(f"GUI HTML missing: {index_html}")

    url = index_html.resolve().as_uri()
    logger.info("GUI loading URL: %s", url)

    api = JsApi(config=config, config_path=config_path, project_root=project_root)

    window = webview.create_window(
        title=title,
        url=url,
        js_api=api,
        width=1180,
        height=780,
        min_size=(960, 620),
        text_select=True,
        confirm_close=False,
    )
    api.attach_window(window)

    def _on_loaded():
        logger.info("GUI window loaded — JS api is reachable")

    window.events.loaded += _on_loaded

    # Try debug first if asked; fall back if WebView2 DevTools is missing.
    try:
        webview.start(debug=debug)
    except Exception as e:
        if debug:
            logger.warning("webview.start(debug=True) failed (%s); retrying without debug", e)
            webview.start(debug=False)
        else:
            raise
