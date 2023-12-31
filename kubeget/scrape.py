from bs4 import BeautifulSoup
from tqdm import tqdm

import requests
import time
from dataset import Dataset, Entry
import re
from utils import cached, get_unique_id


@cached
def fetch(url: str) -> str:
    """Fetch HTML content from a URL and cache it."""

    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(
            f"Failed to fetch HTML from {url}. Status code: {response.status_code}"
        )

    return response.text


def parse_kubectl():
    KUBCTL_DOCS_URL = (
        "https://kubernetes.io/docs/reference/generated/kubectl/kubectl-commands"
    )
    UNIQUE_MARKER = get_unique_id()  # A unique enough marker

    def scrape_page_kubectl(url: str) -> BeautifulSoup:
        """Scrape and process the HTML content of a page."""

        html_content: str = fetch(url)
        html_content = html_content.replace("<h2", "<h1").replace("</h2", "</h1")
        soup: BeautifulSoup = BeautifulSoup(html_content, "html.parser")

        return soup

    def group_elements_by_h1(soup, bs):
        def group_header(header_tag):
            div = bs.new_tag("div", attrs={"class": UNIQUE_MARKER})
            current_tag = header_tag
            current_tag.insert_before(div)

            prev_sibling = current_tag
            next_sibling = current_tag.find_next_sibling()
            div.append(prev_sibling.extract())

            while (
                next_sibling
                and next_sibling.name
                and not next_sibling.name.startswith("h1")
            ):
                prev_sibling = next_sibling
                next_sibling = next_sibling.find_next_sibling()
                div.append(prev_sibling.extract())

        headers = soup.select("h1")
        for header in headers:
            group_header(header)

        return soup

    bs = scrape_page_kubectl(KUBCTL_DOCS_URL)
    soup = bs.select_one("#page-content-wrapper")

    for prev in list(soup.select_one("hr").find_previous_siblings()):
        prev.extract()
    soup.select_one("hr").extract()

    for header_element in list(soup.select('h1[id^="-strong"][id$="-"]')):
        header_element.extract()

    soup = group_elements_by_h1(soup, bs)

    dataset = Dataset()
    blocks = soup.select(f"div.{UNIQUE_MARKER}")


    desc_links = re.compile(r'\[http.*\]')
    for block in tqdm(blocks, leave=True, desc="kubectl scrape"):
        example_context = block.select("blockquote.example")
        example_code = block.select("blockquote.example+pre>code")
        examples = [
            {"description": desc.text.strip(), "code": code.text.strip()}
            for desc, code in zip(example_context, example_code)
        ]

        description_p = []
        description_next = block.select_one("h1 ~ p")
        while description_next and description_next.get("id", "") != "usage":
            if description_next.name == "p":
                description_p.append(description_next.text.strip())
            description_next = description_next.find_next_sibling()

        description = "\n".join(description_p)
        syntax = block.select_one("#usage + p code").text[2:]
        flags_table = block.select_one("#flags + table tbody")
        if flags_table:
            flags = []
            for row in flags_table.select("tr"):
                flag_name, flag_short, flag_default, flag_usage = [
                    r.text for r in row.select("td")
                ]

                # strip out links

                flag_usage = desc_links.sub('', flag_usage)

                flag = {
                    "option": flag_name.strip(),
                    "short": flag_short or None,
                    "default": flag_default or None,
                    "description": flag_usage.strip()
                }

                flags.append(flag)
        else:
            flags = []

        command_name = block.select_one("h1").text.strip()

        if examples:
            dataset.add_entries([
              Entry(
                  objective=example["description"],
                  command=example["code"],
                  command_name=command_name,
                  description=description,
                  syntax=syntax,
                  flags=flags
              )
              for example in examples
            ])

    return dataset
