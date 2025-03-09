import glob
import hashlib
import logging
import mimetypes
import os
import re
import shutil
import sys
import time
from typing import List, Dict, Any
from urllib.parse import (
    urlparse,
    quote_plus as parse_quote_plus,
    urlsplit,
    parse_qs,
    unquote,
)
from pathlib import Path

from locowebflow.modules.conditions import PageLoaded

log = logging.getLogger(f"locowebflow.{__name__}")

try:
    import chromedriver_autoinstaller
    import cssutils
    import requests
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.support.ui import WebDriverWait

    cssutils.log.setLevel(logging.CRITICAL)  # removes warning logs from cssutils
except ModuleNotFoundError as error:
    log.critical(f"ModuleNotFoundError: {error}. have your installed the requirements?")
    sys.exit(1)


# noinspection PyMethodMayBeStatic
class Parser:
    processed_pages = {}

    @property
    def url_parts(self):
        return urlsplit(self.starting_url)

    @property
    def domain(self):
        return f"{self.url_parts.scheme}://{self.url_parts.netloc}"

    def __init__(self, args=None, config=None):
        self.config = config or {}
        self.args = args or {}
        try:
            self.starting_url = starting_url = self.config["page"]
        except KeyError as e:
            raise KeyError(
                "No initial page url specified. If passing a configuration file,"
                " make sure it contains a 'page' key with the url of the site"
                " page to parse"
            ) from e

        # get the site name from the config, or make it up by cleaning the target page's domain
        site_name = self.config.get("name", None)
        if not site_name:  # site name will be domain name
            site_name = urlparse(starting_url).netloc

        # set the output folder based on the site name
        self.dist_folder = Path(config.get("output", Path("dist") / site_name))
        log.info(f"Setting output path to '{self.dist_folder}'")

        # check if the argument to clean the dist folder was passed
        if self.args.get("clean", False):
            try:
                shutil.rmtree(self.dist_folder)
                log.info(f"Removing cached files in '{self.dist_folder}'")
            except OSError as e:
                log.error(f"Cannot remove '{self.dist_folder}': {e}")
        else:
            if self.args.get("clean_css", False):
                try:
                    log.info(f"Removing cached .css files in '{self.dist_folder}'")
                    for style_file in glob.glob(str(self.dist_folder / "*.css")):
                        os.remove(style_file)
                except OSError as e:
                    log.error(f"Cannot remove .css files in '{self.dist_folder}': {e}")
            if self.args.get("clean_js", False):
                try:
                    log.info(f"Removing cached .js files in '{self.dist_folder}'")
                    for style_file in glob.glob(str(self.dist_folder / "*.js")):
                        os.remove(style_file)
                except OSError as e:
                    log.error(f"Cannot remove .js files in '{self.dist_folder}': {e}")

        # create the output folder if necessary
        self.dist_folder.mkdir(parents=True, exist_ok=True)

        # initialize chromedriver
        self.driver = self.init_chromedriver()

    def get_page_config(self, token):
        # starts by grabbing the gobal site configuration table, if exists
        site_config = self.config.get("site", {})

        # check if there's anything wrong with the site config
        if site_config.get("path", None):
            log.error(
                "'path' parameter has no effect in the [site] table, "
                "and should only present in page tables."
            )
            del site_config["path"]

        # find a table in the configuration file whose key contains the passed token string
        site_pages_config = self.config.get("pages", {})
        matching_pages_config = [
            value for key, value in site_pages_config.items() if key.lower() in token
        ]
        if matching_pages_config:
            if len(matching_pages_config) > 1:
                log.error(
                    f"multiple matching page config tokens found for {token}"
                    " in configuration file. Make sure pages urls / paths are unique"
                )
                return site_config
            else:
                # if found, merge it on top of the global site configuration table
                # log.debug(f"Config table found for page with token {token}")
                matching_page_config = matching_pages_config[0]
                if type(matching_page_config) is dict:
                    return {**site_config, **matching_page_config}
                else:
                    log.error(
                        f"Matching page configuration for {token} was not a dict:"
                        f" {matching_page_config} - something went wrong"
                    )
                    return site_config
        else:
            # log.debug(f"No config table found for page token {token}, using global site config table")
            return site_config

    def get_page_path(self, input_url):
        # first check if the url has a custom path configured in the config file
        custom_path = self.get_page_config(input_url).get("path", None)
        if custom_path:
            log.debug(f"Custom path found for url '{input_url}': '{custom_path}'")
            return custom_path
        else:
            input_url = urlparse(input_url)
            if input_url.path.strip("/") == "":
                return "index.html"
            else:
                return input_url.path

    def cache_file(self, url, filename=None, extension=None):
        # stringify the url in case it's a Path object
        url = str(url)

        # if no filename specified, generate a hashed id based the query-less url,
        # so we avoid re-downloading / caching files we already have
        if not filename:
            parsed_url = urlparse(url)
            queryless_url = parsed_url.netloc + parsed_url.path
            query_params = parse_qs(parsed_url.query)
            # if any of the query params contains a size parameters store it in the has
            # so we can download other higher-resolution versions if needed
            if "width" in query_params.keys():
                queryless_url = queryless_url + f"?width={query_params['width']}"
            filename = hashlib.sha1(str.encode(queryless_url)).hexdigest()
            if extension:
                filename += f".{extension}"
        destination = self.dist_folder / filename

        # check if there are any files matching the filename, ignoring extension
        matching_file = glob.glob(str(destination.with_suffix(".*")))
        if not matching_file:
            # if url has a network scheme, download the file
            if "http" in urlparse(url).scheme:
                try:
                    # Disabling proxy speeds up requests time
                    # https://stackoverflow.com/questions/45783655/first-https-request-takes-much-more-time-than-the-rest
                    # https://stackoverflow.com/questions/28521535/requests-how-to-disable-bypass-proxy
                    session = requests.Session()
                    session.trust_env = False
                    log.info(f"Downloading '{url}'")
                    response = session.get(url)

                    # if the filename does not have an extension at this point,
                    # try to infer it from the url, and if not possible,
                    # from the content-type header mimetype
                    if not destination.suffix:
                        file_extension = Path(urlparse(url).path).suffix
                        if not file_extension:
                            content_type = response.headers.get("content-type")
                            if content_type:
                                file_extension = mimetypes.guess_extension(content_type)
                        elif "%3f" in file_extension.lower():
                            file_extension = re.split(
                                "%3f", file_extension, flags=re.IGNORECASE
                            )[0]
                        if file_extension:
                            destination = destination.with_suffix(file_extension)

                    Path(destination).parent.mkdir(parents=True, exist_ok=True)
                    with open(destination, "wb") as f:
                        f.write(response.content)

                    return destination.relative_to(self.dist_folder)
                except Exception as e:
                    log.error(f"Error downloading file '{url}': {e}")
                    return url
            # if not, check if it's a local file, and copy it to the dist folder
            else:
                if Path(url).is_file():
                    log.debug(f"Caching local file '{url}'")
                    destination = destination.with_suffix(Path(url).suffix)
                    shutil.copyfile(url, destination)
                    return destination.relative_to(self.dist_folder)
        # if we already have a matching cached file, just return its relative path
        else:
            cached_file = Path(matching_file[0]).relative_to(self.dist_folder)
            log.debug(f"'{url}' was already downloaded")
            return cached_file

    def init_chromedriver(self):
        chromedriver_path = self.args.get("chromedriver")
        if not chromedriver_path:
            try:
                chromedriver_path = chromedriver_autoinstaller.install()
            except Exception as e:
                log.critical(
                    f"Failed to install the built-in chromedriver: {e}\n"
                    "\nDownload the correct version for your system at"
                    " https://chromedriver.chromium.org/downloads and use the"
                    " --chromedriver argument to point to the chromedriver executable"
                )
                raise e from e

        log.info(f"Initialising chromedriver at {chromedriver_path}")
        logs_path = Path.cwd() / ".logs" / "webdrive.log"
        logs_path.parent.mkdir(parents=True, exist_ok=True)

        chrome_options = Options()
        if not self.args.get("non_headless", False):
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("window-size=1920,20000")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--silent")
        chrome_options.add_argument("--disable-logging")
        ## https://stackoverflow.com/questions/32970855/clear-cache-before-running-some-selenium-webdriver-tests-using-java
        chrome_options.add_argument("--incognito")
        #  removes the 'DevTools listening' log message
        chrome_options.add_experimental_option("excludeSwitches", ["enable-logging"])
        chrome_options.add_argument(f"--log-path={str(logs_path)}")

        service = Service(str(chromedriver_path))
        return webdriver.Chrome(options=chrome_options, service=service)

    def parse_page(self, url: str):
        """Parse page at url and write it to file, then recursively parse all subpages.

        Args:


        After the page at `url` has been parsed, calls itself recursively for every subpage
        it has discovered.
        """
        log.info(f"Parsing page '{url}'")
        log.debug(f"Using page config: {self.get_page_config(url)}")

        try:
            self.load(url)
        except TimeoutException as e:
            log.critical(
                "Timeout waiting for page content to load, or no content found."
                " Are you sure the page is set to public?"
            )
            raise e from e

        # creates soup from the page to start parsing
        soup = BeautifulSoup(self.driver.page_source, "html5lib")

        self.clean_up(url, soup)
        self.set_custom_meta_tags(url, soup)
        self.process_images(soup)
        self.process_stylesheets(soup)
        self.process_scripts(soup)
        self.embed_custom_fonts(url, soup)

        # inject any custom elements to the page
        custom_injects = self.get_page_config(url).get("inject", {})
        self.inject_custom_tags("head", soup, custom_injects)
        self.inject_custom_tags("body", soup, custom_injects)

        subpages = self.find_subpages(url, soup)
        self.export_parsed_page(url, soup)
        self.parse_subpages(subpages)

    def _clean_up_meta_tags(self, soup):
        for tag in [
            "description",
            "twitter:card",
            "twitter:site",
            "twitter:title",
            "twitter:description",
            "twitter:image",
            "twitter:url",
            "apple-itunes-app",
        ]:
            unwanted_tag = soup.find("meta", attrs={"name": tag})
            if unwanted_tag:
                unwanted_tag.decompose()
        for tag in [
            "og:site_name",
            "og:type",
            "og:url",
            "og:title",
            "og:description",
            "og:image",
        ]:
            unwanted_og_tag = soup.find("meta", attrs={"property": tag})
            if unwanted_og_tag:
                unwanted_og_tag.decompose()

    def clean_up(self, url, soup):
        config = self.get_page_config(url).get("cleanup", {})

        soup_scripts = soup.find_all("script")
        # remove scripts and other tags we don't want / need
        for target_script in config.get("scripts", []):  # type: Dict[str:Any]
            target_src = target_script["src"]
            for unwanted in soup_scripts:
                if unwanted.get("src") == target_src:
                    unwanted.decompose()

        # needed so we don't cache webflow assets later
        for unwanted in soup.find_all(class_="w-webflow-badge"):
            unwanted.decompose()

        # clean up the default meta tags
        # self._clean_up_meta_tags(soup)

    def set_custom_meta_tags(self, url, soup):
        # set custom meta tags
        custom_meta_tags = self.get_page_config(url).get("meta", [])
        for custom_meta_tag in custom_meta_tags:
            tag = soup.new_tag("meta")
            for attr, value in custom_meta_tag.items():
                tag.attrs[attr] = value
            log.debug(f"Adding meta tag {str(tag)}")
            soup.head.append(tag)

    def sanitize_a_domain_image(self, img):
        img_src = self.domain + img["src"]
        # region legacy code
        # notion's own default images urls are in a weird format, need to sanitize them
        # img_src = 'https://www.notion.so' + img['src'].split("notion.so")[-1].replace("notion.so", "").split("?")[0]
        # endregion
        if not ".amazonaws" in img_src:
            img_src = unquote(img_src)
        return img_src

    def get_elements_with_background_image(self, soup):
        # We go through all the elements that have a style attribute.
        for element in soup.find_all(style=True):
            style = cssutils.parseStyle(element["style"])
            background_image = style.getProperty("background-image")
            if background_image:
                if background_image.value.strip().lower().startswith("url"):
                    yield element

    def process_images(self, soup, cache_backgrounds=True, cache_images=True):
        for element in self.get_elements_with_background_image(soup):
            if not cache_backgrounds:
                break
            style = cssutils.parseStyle(element["style"])
            background_image = style["background-image"]
            image_url = background_image[
                background_image.find("(") + 1 : background_image.find(")")
            ]
            cached_image_url = self.cache_file(image_url)

            style["background-image"] = background_image.replace(
                image_url, str(cached_image_url)
            )
            element["style"] = style.cssText

        for img in soup.find_all("img"):
            if img.has_attr("src"):
                if cache_images and "data:image" not in img["src"]:
                    img_src = img["src"]
                    # if the path starts with /, it's one of notion's predefined images
                    if img["src"].startswith("/"):
                        img_src = self.sanitize_a_domain_image(img)

                    cached_image = self.cache_file(img_src)
                    img["src"] = cached_image
                elif img["src"].startswith("/"):
                    img["src"] = self.domain + img["src"]

    def process_scripts(self, soup):
        for script in soup.find_all("script"):
            if script.has_attr("src"):
                cached_script_file = self.cache_file(script["src"])
                script["src"] = str(cached_script_file)

    def process_stylesheets(self, soup):
        # process stylesheets
        for link in soup.find_all("link", rel="stylesheet"):
            if link.has_attr("href"):
                cached_css_file = self.cache_file(link["href"], extension="css")
                # files in the css file might be reference with a relative path,
                # so store the path of the current css file
                parent_css_path = os.path.split(urlparse(link["href"]).path)[0].strip()
                # open the locally saved file
                with open(self.dist_folder / cached_css_file, "rb+") as f:
                    stylesheet = cssutils.parseString(f.read())
                    # open the stylesheet and check for any font-face rule,
                    for rule in stylesheet.cssRules:
                        if rule.type == cssutils.css.CSSRule.FONT_FACE_RULE:
                            # if any are found, download the font file
                            # TODO: maths fonts have fallback font sources
                            font_file = (
                                rule.style["src"].split("url(")[-1].split(")")[0]
                            )
                            if "data:application" in font_file:
                                continue

                            font_url = font_file.strip()
                            if font_url.startswith("/"):
                                # assemble the url given the current css path
                                font_url = (
                                    self.domain + parent_css_path + "/" + font_file
                                )

                            # don't hash the font files filenames, rather get filename only
                            cached_font_file = self.cache_file(
                                font_url, Path(font_file).name
                            )
                            rule.style["src"] = f"url({cached_font_file})"

                    # commit stylesheet edits to file
                    f.seek(0)
                    f.truncate()
                    f.write(stylesheet.cssText)

                link["href"] = str(cached_css_file)

        return

    def embed_custom_fonts(self, url, soup):
        if not (custom_fonts := self.get_page_config(url).get("fonts", {})):
            return

        # append a stylesheet importing the google font for each unique font
        unique_custom_fonts = set(custom_fonts.values())
        for font in unique_custom_fonts:
            if font:
                google_fonts_embed_name = font.replace(" ", "+")
                font_href = f"https://fonts.googleapis.com/css2?family={google_fonts_embed_name}:wght@500;600;700&display=swap"
                custom_font_stylesheet = soup.new_tag(
                    "link", rel="stylesheet", href=font_href
                )
                soup.head.append(custom_font_stylesheet)

        # go through each custom font, and add a css rule overriding the font-family
        # to the font override stylesheet targeting the appropriate selector
        font_override_stylesheet = soup.new_tag("style", type="text/css")
        # embed custom google font(s)
        fonts_selectors = {
            "site": "div:not(.notion-code-block)",
            "navbar": ".notion-topbar div",
            "title": ".notion-page-block > div, .notion-collection_view_page-block > div[data-root]",
            "h1": ".notion-header-block div, notion-page-content > notion-collection_view-block > div:first-child div",
            "h2": ".notion-sub_header-block div",
            "h3": ".notion-sub_sub_header-block div",
            "body": ".notion-scroller",
            "code": ".notion-code-block *",
        }
        for target, custom_font in custom_fonts.items():
            if custom_font and target != "site":
                log.debug(f"Setting {target} font-family to {custom_font}")
                font_override_stylesheet.append(
                    fonts_selectors[target]
                    + " {font-family:"
                    + custom_font
                    + " !important} "
                )

        site_font = custom_fonts.get("site", None)
        if site_font:
            log.debug(f"Setting global site font-family to {site_font}"),
            font_override_stylesheet.append(
                fonts_selectors["site"] + " {font-family:" + str(site_font) + "} "
            )

        # finally append the font overrides stylesheets to the page
        soup.head.append(font_override_stylesheet)

    def inject_custom_tags(self, section: str, soup, custom_injects: dict):
        """Inject custom tags to the given section.

        Args:
            section (str): Section / tag name to insert into.
            soup (BeautifulSoup): a BeautifulSoup element holding the whole page.
            custom_injects (dict): description of custom tags to inject.
        """
        section_custom_injects = custom_injects.get(section, {})
        for tag, elements in section_custom_injects.items():
            for element in elements:
                injected_tag = soup.new_tag(tag)
                for attr, value in element.items():

                    # `inner_html` refers to the tag's inner content
                    # and will be added later
                    if attr == "inner_html":
                        continue

                    if attr.lower() in ["string", "str", "inline", "inline_script"]:
                        log.info(f"injecting inline script to '{section}'")
                        injected_tag.string = value
                    else:
                        injected_tag[attr] = None if value == "|NONE_VALUE|" else value

                    # if the value refers to a file, copy it to the dist folder
                    if attr.lower() in ["href", "src"]:
                        log.debug(f"Copying injected file '{value}'")
                        if urlparse(value).scheme:
                            path_to_file = value
                        else:
                            path_to_file = Path.cwd() / value.strip("/")
                        cached_custom_file = self.cache_file(path_to_file)
                        injected_tag[attr] = str(cached_custom_file)  # source.name
                log.debug(f"Injecting <{section}> tag: {injected_tag}")

                # adding `inner_html` as the tag's content
                if "inner_html" in element:
                    injected_tag.string = element["inner_html"]

                soup.find(section).append(injected_tag)

    def find_subpages(self, url, soup):
        log.info(f"Got the target domain as {self.domain}")

        # find sub-pages and clean paths / links
        subpages = []
        parse_links = not self.get_page_config(url).get("no-links", False)
        for a in soup.find_all("a", href=True):
            # region legacy code may need rework
            if not parse_links and len(a.find_parents("div", class_="notion-scroller")):
                # if the page is set not to follow any links, strip the href
                # do this only on children of .notion-scroller, we don't want
                # to strip the links from the top nav bar
                log.debug(f"Stripping link for {a['href']}")
                del a["href"]
                a.name = "span"
                # remove pointer cursor styling on the link and all children
                for child in [a] + a.find_all():
                    if child.has_attr("style"):
                        style = cssutils.parseStyle(child["style"])
                        style["cursor"] = "default"
                        child["style"] = style.cssText
                continue
            # endregion

            assert parse_links == True

            sub_page_href = a["href"]
            if sub_page_href.startswith("/"):
                sub_page_href = self.domain + parse_quote_plus(sub_page_href, safe="/")
                log.info(f"Got this as href {sub_page_href}")

            if not urlsplit(sub_page_href).netloc == self.url_parts.netloc:
                continue  # do nothing with external domain links

            # if the link is an anchor link,
            # check if the page hasn't already been parsed
            if "#" in sub_page_href:
                sub_page_href_tokens = sub_page_href.split("#")
                sub_page_href = sub_page_href_tokens[0]
                a["href"] = f"#{sub_page_href_tokens[-1]}"
                if (
                    sub_page_href in self.processed_pages.keys()
                    or sub_page_href in subpages
                ):
                    log.debug(
                        f"Original page for anchor link {sub_page_href}"
                        " already parsed / pending parsing, skipping"
                    )
                    continue
            else:
                extension_in_links = self.config.get("extension_in_links", True)
                a["href"] = (
                    self.get_page_path(sub_page_href)
                    if sub_page_href != self.starting_url
                    else ("index.html" if extension_in_links else "")
                )
            subpages.append(sub_page_href)
            log.debug(f"Found link to page {a['href']}")
        return subpages

    def export_parsed_page(self, url, soup):
        # exports the parsed page
        html_str = str(soup)
        html_file = (
            self.get_page_path(url) if url != self.starting_url else "index.html"
        )
        if html_file in self.processed_pages.values():
            log.error(
                f"Found duplicate pages with path '{html_file}' - previous one will be"
                " overwritten. Make sure that your notion pages names or custom paths"
                " in the configuration files are unique"
            )
        log.info(f"Exporting page '{url}' as '{html_file}'")
        with open(self.dist_folder / html_file, "wb") as f:
            f.write(html_str.encode("utf-8").strip())
        self.processed_pages[url] = html_file

    def parse_subpages(self, subpages):
        # parse sub-pages
        if subpages and not self.args.get("single_page", False):
            if self.processed_pages:
                log.debug(f"Pages processed so far: {len(self.processed_pages)}")
            for sub_page in subpages:
                if sub_page not in self.processed_pages.keys():
                    self.parse_page(sub_page)

    def load(self, url):
        self.driver.get(url)
        WebDriverWait(self.driver, 60).until(PageLoaded())

    def run(self):
        start_time = time.time()
        self.parse_page(self.starting_url)
        elapsed_time = time.time() - start_time
        formatted_time = "{:02d}:{:02d}:{:02d}".format(
            int(elapsed_time // 3600),
            int(elapsed_time % 3600 // 60),
            int(elapsed_time % 60),
        )
        log.info(
            f"Finished!\n\nProcessed {len(self.processed_pages)} pages in {formatted_time}"
        )
