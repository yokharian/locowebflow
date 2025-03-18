from logging import Logger
from pathlib import Path
from types import MappingProxyType
from typing import Any
from urllib.parse import SplitResult

# noinspection PyProtectedMember
from bs4 import BeautifulSoup, PageElement, Tag, NavigableString
from selenium.webdriver.chrome.webdriver import WebDriver

log: Logger

class Parser:
    processed_pages: dict = {}
    config: dict[str, str] = {}
    args: MappingProxyType[str, Any] = {}
    url_parts: SplitResult
    domain: str
    starting_url: str
    dist_folder: Path
    driver: WebDriver
    def init_chromedriver(self): ...
    def __init__(
        self,
        args: MappingProxyType[str, Any] | None = None,
        config: dict[str, str] | None = None,
    ) -> None: ...
    def get_page_config(self, token) -> dict[str, str]: ...
    def get_page_path(self, input_url): ...
    def correct_local_references(self, soup: BeautifulSoup): ...
    def _clean_up_meta_tags(self, soup: BeautifulSoup): ...
    def clean_up(self, url: str, soup: BeautifulSoup): ...
    def set_custom_meta_tags(self, url: str, soup: BeautifulSoup) -> None: ...
    def sanitize_a_domain_image(
        self, img: PageElement | Tag | NavigableString
    ) -> str: ...
    def get_elements_with_background_image(self, soup: BeautifulSoup): ...
    def cache_file(
        self, url: str | Path, filename: str = None, extension: str | None = None
    ): ...
    def process_scripts(self, soup: BeautifulSoup) -> None: ...
    def process_stylesheets(self, soup: BeautifulSoup) -> None: ...
    def embed_custom_fonts(self, url: str, soup: BeautifulSoup) -> None: ...
    def inject_custom_tags(
        self, section: str, soup: BeautifulSoup, custom_injects: dict
    ): ...
    def export_parsed_page(self, url: str, soup: BeautifulSoup) -> None: ...
    def find_subpages(self, url: str, soup: BeautifulSoup): ...
    def process_images(
        self,
        soup: BeautifulSoup,
        cache_backgrounds: bool = True,
        cache_images: bool = True,
    ) -> None: ...
    def parse_page(self, url: str): ...
    def parse_subpages(self, subpages: list) -> None: ...
    def load(self, url: str) -> None: ...
    def run(self) -> None: ...
