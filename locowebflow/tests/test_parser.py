from modules.webflowparser import Parser


def test_parse_sample_page():
    config = {"page": "https://sofia-escobedo-portfolio.webflow.io/404"}
    args = {"timeout": 10, "single_page": True}
    parser = Parser(config, args)
    parser.processed_pages = {}

    parser.parse_page(parser.starting_url)

    assert parser.starting_url in parser.processed_pages
