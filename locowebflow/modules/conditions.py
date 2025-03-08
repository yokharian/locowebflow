import logging

log = logging.getLogger(f"locowebflow.{__name__}")


class PageLoaded:
    """An expectation for checking that a notion page has loaded."""

    def __init__(self):
        self.previous_page_source = ""

    def __call__(self, driver):
        source_changed = self.previous_page_source != driver.page_source
        log.debug(f"Waiting for page content to load source changed: {source_changed})")
        if not source_changed:
            return True
        else:
            self.previous_page_source = driver.page_source
            return False
