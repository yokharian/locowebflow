from _typeshed import Incomplete
from types import MappingProxyType
from typing import Any

from selenium.common.exceptions import TimeoutException as TimeoutException
from selenium.webdriver.support.ui import WebDriverWait as WebDriverWait

log: Incomplete

class Parser:
    processed_pages: dict = {}
    config: dict[str, str]
    args: Incomplete
    index_url: Incomplete
    dist_folder: Incomplete
    driver: Incomplete
    starting_url: Incomplete
    def __init__(
        self,
        args: MappingProxyType[str, Any] | None = None,
        config: dict[str, str] | None = None,
    ) -> None: ...
    def sanitize_domain_image(self, img: dict) -> str: ...
    def get_page_config(self, token) -> dict[str, str]: ...
    def get_page_path(self, input_url): ...
    def cache_file(self, url, filename: Incomplete | None = None): ...
    def init_chromedriver(self): ...
    def parse_page(self, url: str): ...
    def clean_up(self, soup): ...
    def set_custom_meta_tags(self, url, soup) -> None: ...
    def process_images_and_emojis(self, soup) -> None: ...
    def process_stylesheets(self, soup) -> None: ...
    def embed_custom_fonts(self, url, soup) -> None: ...
    def inject_custom_tags(self, section: str, soup, custom_injects: dict): ...
    def inject_loconotion_script_and_css(self, soup) -> None: ...
    def find_subpages(self, url, soup, hrefDomain): ...
    def export_parsed_page(self, url, soup) -> None: ...
    def parse_subpages(self, subpages) -> None: ...
    def load(self, url) -> None: ...
    processed_pages: Incomplete
    def run(self) -> None: ...
