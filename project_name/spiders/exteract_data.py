import scrapy
from scrapy_playwright.page import PageMethod


class CategoriesSpider(scrapy.Spider):
    name = "categories"
    allowed_domains = ["thumbtack.com"]

    custom_settings = {
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
        "PLAYWRIGHT_BROWSER_TYPE": "chromium",
        "FEEDS": {
            "categories.json": {"format": "json", "overwrite": True},
        },
    }

    def start_requests(self):
        url = "https://www.thumbtack.com/more-services"
        yield scrapy.Request(
            url=url,
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_selector", "a.categories__container")
                ],
            },
        )

    async def parse(self, response):
        links = response.css("a.categories__container::attr(href)").getall()
        self.logger.info(f"Found {len(links)} categories")

        for link in links:
            full_link = response.urljoin(link)
            yield scrapy.Request(
                url=full_link,
                callback=self.parse_category,
                meta={
                    "playwright": True,
                    "category_url": full_link,
                    "playwright_page_methods": [
                        # ننتظر body بدل الأزرار عشان نضمن إن الصفحة محملة
                        PageMethod("wait_for_selector", "body")
                    ],
                },
            )

    async def parse_category(self, response):
        category_url = response.meta["category_url"]

        # نبحث مباشرة عن أي رابط يحتوي /instant-results/
        button_links = response.css("a[href*='/instant-results/']::attr(href)").getall()

        if not button_links:
            self.logger.warning(f"No instant-results links found in {category_url}")
        else:
            self.logger.info(f"Found {len(button_links)} instant-results links in {category_url}")

        for btn in button_links:
            yield {
                "category_url": category_url,
                "button_url": response.urljoin(btn),
            }
