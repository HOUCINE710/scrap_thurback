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
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 60000,
        "PLAYWRIGHT_LAUNCH_OPTIONS": {"headless": True},

        # تفعيل user-agents
        "DOWNLOADER_MIDDLEWARES": {
            "scrapy.downloadermiddlewares.useragent.UserAgentMiddleware": None,
            "scrapy_user_agents.middlewares.RandomUserAgentMiddleware": 400,
        },
    }

    def start_requests(self):
        url = "https://www.thumbtack.com/more-services"
        yield scrapy.Request(
            url=url,
            callback=self.parse,
            meta={
                "playwright": True,
                "playwright_include_page": True,
                "playwright_page_methods": [
                    PageMethod("wait_for_load_state", "domcontentloaded"),
                    PageMethod("wait_for_selector", "a.categories__container", timeout=20000),
                    PageMethod(
                        "route",
                        "**/*",
                        lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font", "media"] else route.continue_(),
                    ),
                ],
            },
        )

    async def parse(self, response):
        """جمع روابط التصنيفات"""
        relative_links = response.css("a.categories__container::attr(href)").getall()
        self.logger.info(f"Found {len(relative_links)} categories")

        seen = set()
        for link in relative_links:
            full_link = response.urljoin(link)
            if full_link in seen:
                continue
            seen.add(full_link)

            yield scrapy.Request(
                url=full_link,
                callback=self.parse_category,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "category_url": full_link,
                    "playwright_page_methods": [
                        PageMethod("wait_for_load_state", "domcontentloaded"),
                        PageMethod("wait_for_selector", "div.ButtonRow_item__AlEBm a", timeout=30000),
                    ],
                },
            )

        page = response.meta.get("playwright_page")
        if page:
            await page.close()

    async def parse_category(self, response):
        """استخراج final_link من صفحات التصنيفات"""
        category_url = response.meta.get("category_url", response.url)
        self.logger.info(f"Parsing category: {category_url}")

        button_links = response.css("div.ButtonRow_item__AlEBm a::attr(href)").getall()
        if not button_links:
            self.logger.warning(f"No buttons found in {category_url}")

        seen = set()
        for btn in button_links:
            final_link = response.urljoin(btn)
            if final_link in seen:
                continue
            seen.add(final_link)

            yield scrapy.Request(
                url=final_link,
                callback=self.parse_final,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "final_from_category": category_url,
                    "playwright_page_methods": [
                        PageMethod("wait_for_load_state", "domcontentloaded"),
                        PageMethod("wait_for_selector", "a[rel='noopener']", timeout=40000),
                    ],
                },
            )

        page = response.meta.get("playwright_page")
        if page:
            await page.close()

    async def parse_final(self, response):
        """التعامل مع final_link → إغلاق البوباب، الضغط على See More، استخراج روابط الخدمات"""
        final_url = response.url
        from_category = response.meta.get("final_from_category")
        self.logger.info(f"Visiting final link: {final_url}")

        page = response.meta.get("playwright_page")
        if not page:
            self.logger.error("No playwright_page in meta — skipping dynamic processing.")
            return

        # (1) إغلاق البوباب إذا وجد
        try:
            popup = await page.query_selector("div[role='dialog'] button, div.ml-auto.black button")
            if popup:
                await popup.click()
                await page.wait_for_timeout(800)
                self.logger.info("Popup closed")
        except Exception:
            self.logger.debug("No popup found")

        # (2) الضغط على See More إذا ظهر
        while True:
            try:
                btn = await page.query_selector("button:has-text('See More')")
                if not btn:
                    break
                await btn.scroll_into_view_if_needed()
                await btn.click()
                await page.wait_for_timeout(1500)
            except Exception:
                break

        # (3) استخراج الروابط
        try:
            hrefs = await page.eval_on_selector_all("a[rel='noopener']", "els => els.map(e => e.href)")
        except Exception:
            hrefs = []

        unique_hrefs = list(dict.fromkeys(hrefs))
        self.logger.info(f"Extracted {len(unique_hrefs)} service links")

        for link in unique_hrefs:
            yield {
                "category_url": from_category,
                "final_link": final_url,
                "service_link": link,
            }

        try:
            await page.close()
        except Exception:
            pass
