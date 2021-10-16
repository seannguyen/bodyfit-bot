from requests import post, get
import logging
from bs4 import BeautifulSoup
from datetime import datetime
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
import os
from config import settings
import threading

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.getLevelName("INFO"),
)

logger = logging.getLogger(__name__)


SLOT_STATUS_PENDING = "SLOT_STATUS_PENDING"
SLOT_STATUS_BOOKED = "SLOT_STATUS_BOOKED"
SLOT_STATUS_WAITLISTED = "SLOT_STATUS_WAITLISTED"
SLOT_STATUS_FULL = "SLOT_STATUS_FULL"
SLOT_STATUS_FAILED = "SLOT_STATUS_FAILED"


class BodyfitBot:
    __cookie_domain = "onefitstop.com"
    __domain = "clients.onefitstop.com"
    __base_url = f"https://{__domain}"
    __email = settings.email
    __password = settings.password
    __trainer_id = settings.trainer_id
    __trid = settings.trid

    def bookSlot(self):
        logger.info("Start booking slots")
        try:
            cookies = self.__login()
            result = self.__getAndBookSlots(cookies)
            logger.info(f"Result {result}")
        except Exception as e:
            logger.error(e)

        logger.info("Finished booking slots")

    def __login(self):
        resp = post(
            f"{self.__base_url}/login",
            params={"loginAs": "trainer"},
            data={
                "login": "1",
                "email": self.__email,
                "password": self.__password,
                "redirect": self.__base_url,
                "loginchek": "businesspages",
                "trid": self.__trid,
            },
            allow_redirects=False,
        )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Fail to login, status {resp.status_code}, resp {resp.text}"
            )

        logger.info("Successfully logged-in")
        return resp.cookies

    def __getAndBookSlots(self, cookies):
        desired_slots = self.__get_desired_slot()
        threads = list()
        page = 1
        while True:
            slots_at_page = self.__getSlotsAtPage(cookies, page)
            if slots_at_page is None:
                break

            for desired_slot in desired_slots:
                if desired_slot["state"] != SLOT_STATUS_PENDING:
                    continue
                if desired_slot["day_of_week"] in slots_at_page:
                    slots_at_day = slots_at_page[desired_slot["day_of_week"]]
                    if desired_slot["time_of_day"] in slots_at_day:
                        attempted_slot = slots_at_day[desired_slot["time_of_day"]]
                        t = threading.Thread(
                            target=self.__attemptBook,
                            args=(cookies, desired_slot, attempted_slot),
                        )
                        threads.append(t)
                        t.start()
            page += 1

        for t in threads:
            t.join(60)
        return desired_slots

    def __getSlotsAtPage(self, cookies, page):
        logger.info(f"Start fetch slots information from html page {page}")
        resp = get(
            f"{self.__base_url}/index.php?route=widget/directory/businessclass&trid={self.__trid}&mytrainer_id={self.__trainer_id}",
            params={
                "trid": self.__trid,
                "mytrainer_id": self.__trainer_id,
                "page": page,
            },
            cookies=cookies,
        )

        if resp.status_code >= 400:
            raise RuntimeError(
                f"Fail to get html list of slots, status {resp.status_code}, resp {resp.text}"
            )

        soup = BeautifulSoup(resp.text, "lxml")

        if soup.find(text=re.compile(".*No Class scheduled.*")):
            return None

        day_schedules = soup.select(".schedule-list > ul > li:not(.schedule-list-head)")

        slots_by_weekday = {}
        for day_schedule in day_schedules:
            date_str = day_schedule.select_one(".schedule-list-day").text
            slot_date = datetime.strptime(date_str, "%A, %B %d, %Y")
            weekday_key = slot_date.weekday()
            if weekday_key not in slots_by_weekday:
                slots_by_weekday[weekday_key] = {}
            slots = day_schedule.select(".schedule")
            for slot in slots:
                slot_state = SLOT_STATUS_PENDING
                if slot.find("p", text=re.compile(".*Booked.*")):
                    slot_state = SLOT_STATUS_BOOKED
                elif slot.find("span", text="Class Full"):
                    slot_state = SLOT_STATUS_FULL
                elif slot.find("span", text="Already in waitlist"):
                    slot_state = SLOT_STATUS_WAITLISTED

                book_class_button = slot.select_one("button.bookClass")
                if book_class_button:
                    onclick_content = book_class_button["onclick"]
                    m = re.search("'(https.*)'", onclick_content)
                    book_class_url = m.group(1)
                join_waitlist_button = slot.select_one("button.join_wait_list")

                time_str = slot.select_one(":first-child").text.split("to")[0]
                time_str = time_str.strip()
                slot_time = datetime.strptime(time_str, "%I:%M %p")
                slots_by_weekday[weekday_key][slot_time.strftime("%H:%M")] = {
                    "state": slot_state,
                    "book_class_url": book_class_url if book_class_button else None,
                }
        logger.info(f"Success parse slots information from html page {page}")
        return slots_by_weekday

    def __attemptBook(self, cookies, desired_slot, attempted_slot):
        logger.info(
            f"Start booking slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}"
        )
        try:
            if attempted_slot["state"] != SLOT_STATUS_PENDING:
                desired_slot["state"] = attempted_slot["state"]
                logger.info(
                    f"Result booking slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}, state: {desired_slot['state']}"
                )
                return

            driver = self.__prepare_chrome_driver()
            wait = WebDriverWait(driver, 10)

            driver.get("https://clients.onefitstop.com")
            driver.add_cookie(
                {
                    "name": "PHPSESSID",
                    "value": cookies["PHPSESSID"],
                    "domain": self.__cookie_domain,
                }
            )

            driver.get(attempted_slot["book_class_url"])
            make_reservation_button = wait.until(
                EC.element_to_be_clickable((By.ID, "singleeventpayment"))
            )
            make_reservation_button.click()

            make_payment_button = wait.until(
                EC.element_to_be_clickable((By.ID, "btn_payment_bycredits"))
            )
            make_payment_button.click()
            driver.quit()
            desired_slot["state"] = SLOT_STATUS_BOOKED
            logger.info(
                f"Result booking slot day of week: {desired_slot['day_of_week']} time of day: {desired_slot['time_of_day']}, state: {desired_slot['state']}"
            )
        except Exception as e:
            desired_slot["state"] = SLOT_STATUS_FAILED
            raise e

    def __prepare_chrome_driver(self):
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-notifications")
        options.add_argument("--window-size=1280,800")
        options.add_argument("--disable-gpu")
        # Need to set user agent to look normal, otherwise Soxo will show a worning
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36"
        )

        service = Service(os.getcwd() + "/bin_lib/chromedriver")
        driver = webdriver.Chrome(options=options, service=service)
        driver.implicitly_wait(1)
        return driver

    def __get_desired_slot(self):
        return list(
            map(
                lambda i: {
                    "day_of_week": i.day_of_week,
                    "time_of_day": i.time_of_day,
                    "state": SLOT_STATUS_PENDING,
                },
                settings.desired_slots,
            )
        )


if __name__ == "__main__":
    bodyfitBot = BodyfitBot()
    bodyfitBot.bookSlot()
