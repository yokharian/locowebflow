import argparse
import copy
import json
import logging
import sys
import urllib.parse
from pathlib import Path

from .webflowparser import Parser

log = logging.getLogger("locowebflow")

try:
    import colorama
    import requests
    import toml

except ModuleNotFoundError as error:
    log.critical(f"ModuleNotFoundError: {error}. Have you installed the requirements?")
    sys.exit(1)


def get_args():
    # set up argument parser and return parsed args
    argparser = argparse.ArgumentParser(
        description="Generate static websites from webflow.io pages"
    )
    argparser.add_argument(
        "target",
        help="The config file containing the site properties, or the url"
        " of the webflow.io page to generate the site from",
    )
    argparser.add_argument(
        "--chromedriver",
        help="Use a specific chromedriver executable instead of the auto-installing one",
    )
    argparser.add_argument(
        "--single-page",
        action="store_true",
        help="Only parse the first page, then stop",
    )
    argparser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Time in seconds to wait for the loading of lazy-loaded dynamic elements (default 5)."
        " If content from the page seems to be missing, try increasing this value",
    )
    argparser.add_argument(
        "--clean",
        action="store_true",
        help="Delete all previously cached files for the site before generating it",
    )
    argparser.add_argument(
        "--clean-css",
        action="store_true",
        help="Delete previously cached .css files for the site before generating it",
    )
    argparser.add_argument(
        "--clean-js",
        action="store_true",
        help="Delete previously cached .js files for the site before generating it",
    )
    argparser.add_argument(
        "--non-headless",
        action="store_true",
        help="Run chromedriver in non-headless mode",
    )
    argparser.add_argument(
        "-v", "--verbose", action="store_true", help="Increase output log verbosity"
    )
    return argparser.parse_args()


def setup_logging(args):
    # set up some pretty logs
    log = logging.getLogger("locowebflow")
    log.setLevel(logging.INFO if not args.verbose else logging.DEBUG)
    log_screen_handler = logging.StreamHandler(stream=sys.stdout)
    log.addHandler(log_screen_handler)
    log.propagate = False
    try:
        LOG_COLORS = {
            logging.DEBUG: colorama.Fore.GREEN,
            logging.INFO: colorama.Fore.BLUE,
            logging.WARNING: colorama.Fore.YELLOW,
            logging.ERROR: colorama.Fore.RED,
            logging.CRITICAL: colorama.Back.RED,
        }

        class ColorFormatter(logging.Formatter):
            def format(self, record, *args, **kwargs):
                # if the corresponding logger has children, they may receive modified
                # record, so we want to keep it intact
                new_record = copy.copy(record)
                if new_record.levelno in LOG_COLORS:
                    new_record.levelname = "{color_begin}{level}{color_end}".format(
                        level=new_record.levelname,
                        color_begin=LOG_COLORS[new_record.levelno],
                        color_end=colorama.Style.RESET_ALL,
                    )
                return super(ColorFormatter, self).format(new_record, *args, **kwargs)

        log_screen_handler.setFormatter(
            ColorFormatter(
                fmt="%(asctime)s %(levelname)-8s %(message)s",
                datefmt="{color_begin}[%H:%M:%S]{color_end}".format(
                    color_begin=colorama.Style.DIM, color_end=colorama.Style.RESET_ALL
                ),
            )
        )
    except ModuleNotFoundError as identifier:
        pass

    return log


def init_parser(args, log):
    # initialise the website parser
    if urllib.parse.urlparse(args.target).scheme:
        try:
            requests.get(args.target)
        except requests.ConnectionError as exception:
            log.critical("Connection error")
            raise exception

        if "webflow.io" not in args.target:
            log.critical(f"{args.target} is not a webflow.io page")

        log.info(f"Initialising parser for {args.target}")
        config = {"page": args.target}
        parser = Parser(args=vars(args), config=config)

    elif Path(args.target).is_file():
        with open(args.target, encoding="utf-8") as f:
            if f.name.endswith(".toml"):
                parsed_config = toml.loads(f.read())
            elif f.name.endswith(".json"):
                parsed_config = json.loads(f.read())
            else:
                raise NotImplementedError(f.name)
            log.info("Initialising parser with configuration file")
            log.debug(parsed_config)
            parser = Parser(args=vars(args), config=parsed_config)

    else:
        log.critical(f"Config file {args.target} does not exist")
        raise FileNotFoundError(args.target)

    return parser
